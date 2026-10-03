"""X2 browser bridge: ONE model-facing browser runtime over the Hermes stack.

The pinned ``hermes-agent`` package owns the real browser runtime (per-task
agent-browser sessions, a11y snapshots with ``@eN`` refs, real-profile copy
browser, CDP attach, extension routing, vault backends, dialogs, vision).  This
module wires it into the Atlas seams instead of forking it:

- One tool surface: the familiar ``browser_*`` tool names (navigate, snapshot,
  click, type, scroll, back, press, vision, console) plus Atlas-only actions
  ``browser_handoff`` (human handoff), ``browser_vault_list`` /
  ``browser_vault_fill`` (credential vault) and ``browser_replay`` (run a
  learned recording).  The legacy ``atlas.capabilities.browser.browser_use``
  agent stays available ONLY as the hand-the-whole-task-to-an-agent mode, not
  as a second tool surface here.
- Four takeover modes behind settings (设置 → 浏览器): ``standalone`` /
  ``copied real profile`` / ``cdp attach`` / ``extension``.  The mode is
  persisted in user-settings.json and pushed into the Hermes engine config's
  ``[browser]`` section via :mod:`atlas.tools.x2.hermes_config_sync`.
- Human handoff: ``browser_handoff`` emits ``browser.handoff_required`` and
  blocks on ``X2Context.wait_input`` (options open_panel / done / give_up),
  then resumes in place.  The frontend resolves the card through
  ``POST /api/browser/handoff`` which feeds :class:`HandoffBroker`.
- Panel sync: every navigation emits ``browser.panel.sync {url, title}``; every
  action appends a ``browser.step`` replay-trail event.
- Vault safety: tool results are scrubbed of secret-shaped keys; fills run on
  the backend only, and bank-card (payment) fills require explicit human
  confirmation first.
- Recording: while a recording is active (user starts it from the browser
  panel), every successful mutating action is captured by
  :mod:`atlas.tools.x2.recording`.

Test seam: the Hermes browser stack is injected (``backend=...`` factory or
instance), so tests drive a fake browser with no network and no agent-browser
process.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any, Awaitable, Callable

from atlas.config import load_user_settings, save_user_settings
from atlas.tools.x2.context import (
    EVENT_BROWSER_STEP,
    EVENT_PANEL_SYNC,
    HANDOFF_DONE,
    HANDOFF_GIVE_UP,
    HANDOFF_OPEN_PANEL,
    X2Context,
    current_context,
)
from atlas.tools.x2.hermes_config_sync import (
    _invalidate_hermes_config_cache,
    _load_yaml,
    _write_yaml,
    config_file,
    sync_x2_config,
)
from atlas.tools.x2.recording import (
    Recorder,
    RecordingStore,
    ReplayEngine,
    origin_of,
)

log = logging.getLogger(__name__)

# ``register(schema, handler)`` contract used by the engine integrator (same as
# the X2 computer bridge).
Register = Callable[[dict[str, Any], Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]], None]

# ---------------------------------------------------------------------------
# Takeover modes
# ---------------------------------------------------------------------------
# Frontend (设置 → 浏览器) spellings -> internal Atlas browser.mode values.
FRONTEND_MODES = ("standalone", "copied-profile", "cdp", "extension")
_MODE_ALIASES = {
    "standalone": "standalone",
    "builtin": "standalone",
    "local": "standalone",
    "copied-profile": "real_profile",
    "copied_profile": "real_profile",
    "real_profile": "real_profile",
    "real-profile": "real_profile",
    "cdp": "cdp",
    "extension": "extension",
}
# Internal mode -> (Hermes backend that must serve the session, config keys).
_MODE_BACKENDS = {
    "standalone": "local",
    "real_profile": "real_profile",
    "cdp": "cdp",
    "extension": "extension",
}


def normalize_mode(mode: str) -> str:
    internal = _MODE_ALIASES.get(str(mode or "").strip().lower())
    if internal is None:
        raise ValueError(
            f"未知的浏览器接管方式：{mode!r}（可选 standalone / copied-profile / cdp / extension）"
        )
    return internal


def to_frontend_mode(mode: str) -> str:
    return {"standalone": "standalone", "real_profile": "copied-profile",
            "cdp": "cdp", "extension": "extension"}.get(mode, "standalone")


def get_browser_settings() -> dict[str, Any]:
    """Browser takeover settings (设置 → 浏览器), frontend field spellings."""
    stored = load_user_settings().get("browser") or {}
    mode = _MODE_ALIASES.get(str(stored.get("mode") or "standalone").lower(), "standalone")
    return {
        "mode": to_frontend_mode(mode),
        "cdp_url": str(stored.get("cdp_url") or ""),
        "proxy": str(stored.get("proxy") or ""),
    }


def apply_browser_settings(
    mode: str = "", cdp_url: str = "", proxy: str = "", *, persist: bool = True,
) -> dict[str, Any]:
    """Validate + persist takeover settings; returns the normalized settings."""
    internal = normalize_mode(mode) if mode else _MODE_ALIASES.get(
        str(get_browser_settings()["mode"]).lower(), "standalone")
    if internal == "cdp" and not (cdp_url or get_browser_settings().get("cdp_url")):
        raise ValueError("CDP 接管方式需要提供 cdp_url（Chrome 调试地址）")
    if persist:
        settings = load_user_settings()
        browser = dict(settings.get("browser") or {})
        if mode:
            browser["mode"] = internal
        if cdp_url:
            browser["cdp_url"] = str(cdp_url).strip()
        if proxy:
            browser["proxy"] = str(proxy).strip()
        settings["browser"] = browser
        save_user_settings(settings)
    return get_browser_settings()


def backend_request(mode: str, cdp_url: str = "") -> dict[str, Any]:
    """Which Hermes backend must serve the session for a takeover mode."""
    internal = normalize_mode(mode)
    return {
        "mode": internal,
        "backend": _MODE_BACKENDS[internal],
        "cdp_url": str(cdp_url or "").strip() if internal == "cdp" else "",
    }


_BROWSER_CONFIG_KEYS = {
    "standalone": {"use_real_profile": False, "cdp_url": ""},
    "real_profile": {"use_real_profile": True, "cdp_url": ""},
    "cdp": {"use_real_profile": False},
    "extension": {"use_real_profile": False, "cdp_url": ""},
}


def _apply_browser_mode_to_hermes(mode: str, cdp_url: str, proxy: str) -> None:
    """Push the takeover mode into the Hermes engine config ``[browser]`` section
    (sync_x2_config owns the section's shape; only the mode keys are adjusted)."""
    internal = normalize_mode(mode)
    path = config_file()
    data = _load_yaml(path)
    section = data.get("browser") if isinstance(data.get("browser"), dict) else {}
    section.update({
        "mode": internal,
        "use_real_profile": bool(_BROWSER_CONFIG_KEYS[internal].get("use_real_profile")),
        "cdp_url": str(cdp_url or "").strip() if internal == "cdp" else "",
    })
    if proxy:
        section["proxy"] = proxy
    section.setdefault("extension_control", {})
    if isinstance(section["extension_control"], dict):
        section["extension_control"]["enabled"] = internal == "extension"
    data["browser"] = section
    _write_yaml(path, data)
    _invalidate_hermes_config_cache()


# ---------------------------------------------------------------------------
# Handoff broker (frontend card -> blocked tool call)
# ---------------------------------------------------------------------------
class HandoffBroker:
    """Routes ``POST /api/browser/handoff`` resolutions into blocked
    ``browser_handoff`` tool calls (one waiter per run)."""

    def __init__(self) -> None:
        self._waiters: dict[str, asyncio.Future[str]] = {}

    async def wait_input(self, prompt: str, options: list[str]) -> str:
        """Drop-in ``X2Context.wait_input`` keyed by the current run."""
        ctx = current_context()
        run_id = ctx.run_id or "default"
        fut: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._waiters[run_id] = fut
        try:
            return await fut
        finally:
            self._waiters.pop(run_id, None)

    def resolve(self, run_id: str, resolution: str) -> bool:
        fut = self._waiters.get(run_id or "default")
        if fut is None or fut.done():
            return False
        fut.set_result(resolution)
        return True

    def pending(self) -> list[str]:
        return [run_id for run_id, fut in self._waiters.items() if not fut.done()]


_broker = HandoffBroker()


async def handoff_wait_input(prompt: str, options: list[str]) -> str:
    """Module-level wait_input for the integration owner:
    ``X2Context(..., wait_input=x2browser.handoff_wait_input)``."""
    return await _broker.wait_input(prompt, options)


def resolve_handoff(run_id: str, resolution: str) -> bool:
    """Resolve a pending handoff (router surface). Returns False when nothing waits."""
    return _broker.resolve(run_id, resolution)


def pending_handoffs() -> list[str]:
    return _broker.pending()


# ---------------------------------------------------------------------------
# Result shaping
# ---------------------------------------------------------------------------
_SUMMARY_LIMIT = 400

_SECRET_KEY_MARKERS = (
    "password", "passwd", "secret", "cvc", "cvv", "card_number", "cardnumber",
    "otp_seed", "private_key", "api_key", "credential",
)


def scrub_secrets(value: Any) -> Any:
    """Recursively drop secret-shaped keys from a backend payload — vault handles
    and metadata may pass, secret values must never reach a tool result."""
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            folded = str(key).casefold()
            if any(marker in folded for marker in _SECRET_KEY_MARKERS):
                continue
            clean[key] = scrub_secrets(item)
        return clean
    if isinstance(value, list):
        return [scrub_secrets(item) for item in value]
    return value


def _error(message: str, **extra: Any) -> dict[str, Any]:
    return {
        "data": {"error": message, **extra},
        "content": [{"type": "text", "text": message}],
        "is_error": True,
    }


def _ok(data: dict[str, Any], text: str | None = None) -> dict[str, Any]:
    text = text or json.dumps(data, ensure_ascii=False)
    return {"data": data, "content": [{"type": "text", "text": text}], "is_error": False}


def _normalize_payload(payload: Any) -> dict[str, Any]:
    """Hermes browser tools return JSON strings; normalize to the Atlas
    tool-result contract ``{data, content, is_error}``."""
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, default=str)
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        data = {"result": text}
    if not isinstance(data, dict):
        data = {"result": data}
    data = scrub_secrets(data)
    # The text boundary is rebuilt from the SCRUBBED payload: a backend that
    # echoed a secret-shaped key must not leak it through content either.
    text = json.dumps(data, ensure_ascii=False, default=str)
    is_error = bool(data.get("error")) or data.get("success") is False
    return {"data": data, "content": [{"type": "text", "text": text}], "is_error": is_error}


def _summary_from(result: dict[str, Any]) -> str:
    data = result.get("data") or {}
    for key in ("message", "summary", "title", "clicked", "element", "error"):
        value = data.get(key)
        if value:
            return str(value)[:_SUMMARY_LIMIT]
    for block in result.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            return str(block.get("text") or "")[:_SUMMARY_LIMIT]
    return ""


# ---------------------------------------------------------------------------
# Default backend: lazy Hermes browser stack
# ---------------------------------------------------------------------------
class BackendUnavailable(RuntimeError):
    """The Hermes browser stack could not be loaded (offline / not installed)."""


class HermesBrowserBackend:
    """Calls the Hermes ``browser_*`` functions (JSON-string returns) in a thread.

    The import is lazy: importing this module must never load the Hermes stack.
    """

    _FUNCTIONS = {
        "navigate": ("tools.browser_tool", "browser_navigate"),
        "snapshot": ("tools.browser_tool", "browser_snapshot"),
        "click": ("tools.browser_tool", "browser_click"),
        "type": ("tools.browser_tool", "browser_type"),
        "scroll": ("tools.browser_tool", "browser_scroll"),
        "back": ("tools.browser_tool", "browser_back"),
        "press": ("tools.browser_tool", "browser_press"),
        "vision": ("tools.browser_tool", "browser_vision"),
        "console": ("tools.browser_tool", "browser_console"),
        "get_images": ("tools.browser_tool", "browser_get_images"),
        "vault_list": ("tools.browser_vault_tool", "browser_vault_list"),
        "vault_fill": ("tools.browser_vault_tool", "browser_vault_fill"),
    }

    async def call(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        target = self._FUNCTIONS.get(action)
        if target is None:
            raise BackendUnavailable(f"浏览器后端不支持动作 {action!r}")
        module_name, func_name = target
        return await asyncio.to_thread(self._invoke, module_name, func_name, params)

    def _invoke(self, module_name: str, func_name: str, params: dict[str, Any]) -> dict[str, Any]:
        import importlib

        try:
            module = importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001 - offline / stack missing
            raise BackendUnavailable(f"Hermes 浏览器模块 {module_name} 加载失败：{exc}") from exc
        fn = getattr(module, func_name, None)
        if fn is None:
            raise BackendUnavailable(f"Hermes 浏览器模块缺少 {func_name}")
        raw = fn(**params)
        if isinstance(raw, dict):
            return raw
        try:
            return json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise BackendUnavailable(f"浏览器后端返回了无法解析的结果：{exc}") from exc


# Sentinel: distinguishes "no backend injected" (lazy Hermes acquisition) from
# an explicit ``backend=False`` ("Hermes unavailable" — offline Chinese error).
_UNSET = object()


# ---------------------------------------------------------------------------
# Tool schemas — the single model-facing browser surface
# ---------------------------------------------------------------------------
def _schema(name: str, description: str, properties: dict[str, Any],
            required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
            },
        },
    }


_TASK_ID_PROP = {"type": "string", "description": "浏览器会话 id；缺省用当前 Atlas 会话隔离。"}

BROWSER_TOOL_SCHEMAS: list[dict[str, Any]] = [
    _schema("browser_navigate", "打开网页；返回页面标题与紧凑可访问性快照（元素带 @eN 引用）。",
            {"url": {"type": "string", "description": "要打开的完整 URL"}, "task_id": _TASK_ID_PROP}, ["url"]),
    _schema("browser_snapshot", "获取当前页面的可访问性树快照（含 @eN 元素引用），用于后续 click/type。",
            {"full": {"type": "boolean", "description": "true 时返回完整快照（默认紧凑）"}, "task_id": _TASK_ID_PROP}),
    _schema("browser_click", "点击快照中的元素，ref 形如 \"@e5\"。",
            {"ref": {"type": "string", "description": "元素引用，如 @e5"}, "task_id": _TASK_ID_PROP}, ["ref"]),
    _schema("browser_type", "向元素填入文本（先清空再输入）。绝不用于密码/卡号——用 browser_vault_fill。",
            {"ref": {"type": "string"}, "text": {"type": "string"}, "task_id": _TASK_ID_PROP},
            ["ref", "text"]),
    _schema("browser_scroll", "滚动页面（up/down 约半屏）。",
            {"direction": {"type": "string", "enum": ["up", "down"]}, "task_id": _TASK_ID_PROP}, ["direction"]),
    _schema("browser_back", "浏览器历史后退。", {"task_id": _TASK_ID_PROP}),
    _schema("browser_press", "发送按键（如 Enter）。",
            {"key": {"type": "string", "description": "如 Enter、Tab"}, "task_id": _TASK_ID_PROP}, ["key"]),
    _schema("browser_vision", "对页面截图提问（截图分析走视觉通道）。",
            {"question": {"type": "string"}, "annotate": {"type": "boolean"}}, ["question"]),
    _schema("browser_console", "读取/执行页面 console（受评估策略约束）。",
            {"expression": {"type": "string"}, "clear": {"type": "boolean"}}),
    _schema("browser_vault_list",
            "页面要求密码/银行卡/地址时先调用：列出已存凭据句柄与元数据（绝不返回明文密码）。",
            {}),
    _schema("browser_vault_fill",
            "把句柄对应的密码/卡号直接注入页面（值不经过对话）。银行卡需用户确认。",
            {"handle": {"type": "string", "description": "browser_vault_list 返回的句柄"}}, ["handle"]),
    _schema("browser_handoff",
            "遇到登录验证、支付确认、验证码等需要人工处理的页面时，把控制权交给用户并等待处理完成。",
            {"reason": {"type": "string", "description": "为什么需要人工处理"},
             "url": {"type": "string", "description": "相关页面 URL（缺省为当前页）"}},
            ["reason"]),
    _schema("browser_replay", "逐步回放一个已学习的浏览器录制（不经过模型，失败步骤自动单步自愈）。",
            {"recording_id": {"type": "string"}}, ["recording_id"]),
]

BROWSER_TOOL_NAMES = [s["function"]["name"] for s in BROWSER_TOOL_SCHEMAS]

# Actions captured into an active recording (mutating actions only).
_RECORDABLE = {
    "browser_navigate": "navigate",
    "browser_click": "click",
    "browser_type": "type",
    "browser_scroll": "scroll",
    "browser_back": "back",
    "browser_press": "press",
}

# Schema name -> Hermes action key (identity for most).
_ACTION_BY_TOOL = {
    "browser_navigate": "navigate", "browser_snapshot": "snapshot", "browser_click": "click",
    "browser_type": "type", "browser_scroll": "scroll", "browser_back": "back",
    "browser_press": "press", "browser_vision": "vision", "browser_console": "console",
    "browser_vault_list": "vault_list", "browser_vault_fill": "vault_fill",
}

# Hermes functions that accept task_id for session isolation.
_TAKES_TASK_ID = {"navigate", "snapshot", "click", "type", "scroll", "back", "press",
                  "vision", "console", "get_images", "vault_fill"}


# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------
class X2BrowserRuntime:
    """Bridges the single Atlas browser tool surface onto the Hermes stack."""

    def __init__(
        self,
        backend: Any = _UNSET,
        backend_factory: Callable[[dict[str, Any]], Any] | None = None,
        replanner: Any = None,
        store: RecordingStore | None = None,
    ) -> None:
        self._injected_backend = backend
        self._backend_injected = backend is not _UNSET
        self._backend_factory = backend_factory
        self._backend: Any = None
        self._backend_failed = backend is False
        self.replanner = replanner  # single-step self-heal for browser_replay
        self.recordings = store or RecordingStore()
        self.recorder: Recorder | None = None
        self._config_lock = threading.Lock()
        self._configured = False
        # Page context for recording / handoff defaults.
        self.last_url: str = ""
        self.last_title: str = ""
        self.last_snapshot: str = ""
        self.backend_request: dict[str, Any] = {}

    # -- setup -------------------------------------------------------------
    def ensure_configured(self) -> None:
        """Sync the takeover mode into the Hermes engine config and resolve the backend."""
        with self._config_lock:
            if self._configured:
                return
            self._configured = True
        try:
            sync_x2_config()
        except Exception as exc:  # noqa: BLE001 - config sync must not break tool calls
            log.warning("x2.browser_config_sync_failed", extra={"error": str(exc)})
        stored = load_user_settings().get("browser") or {}
        mode = _MODE_ALIASES.get(str(stored.get("mode") or "standalone").lower(), "standalone")
        cdp_url = str(stored.get("cdp_url") or "")
        proxy = str(stored.get("proxy") or "")
        self.backend_request = backend_request(mode, cdp_url)
        try:
            _apply_browser_mode_to_hermes(mode, cdp_url, proxy)
        except Exception as exc:  # noqa: BLE001
            log.warning("x2.browser_mode_push_failed", extra={"error": str(exc)})
        if self._backend_factory is not None and self._backend is None:
            # Mode config → correct backend requested (tests assert on this seam).
            self._backend = self._backend_factory(dict(self.backend_request))

    # -- backend -----------------------------------------------------------
    def acquire_backend(self) -> Any:
        """The injected backend, the factory product, or the lazy Hermes stack."""
        if self._backend is not None:
            return self._backend
        if self._backend_injected:
            if self._injected_backend is False:
                # Explicit backend=False means "unavailable" → offline Chinese error.
                self._backend_failed = True
                return None
            self._backend = self._injected_backend
            return self._backend
        self._backend = HermesBrowserBackend()
        return self._backend

    async def call_backend(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        backend = self.acquire_backend()
        if backend is None:
            raise BackendUnavailable(
                "浏览器后端不可用：Hermes 浏览器栈未加载（离线或未安装 agent-browser）。")
        return await backend.call(action, params)

    # -- recording ---------------------------------------------------------
    def start_recording(self) -> dict[str, Any]:
        """Arm capture; returns the recording document."""
        if self.recorder is not None and self.recorder.active:
            return self.recorder.doc
        try:
            self.recordings.prune()  # bound the replays: keep the newest 50
        except Exception as exc:  # noqa: BLE001 - pruning is best-effort
            log.debug("x2.recordings_prune_failed", extra={"error": str(exc)})
        site = origin_of(self.last_url)
        doc = self.recordings.create(site=site)
        self.recorder = Recorder(doc, self.recordings)
        if self.last_snapshot:
            self.recorder.observe(self.last_snapshot, self.last_url)
        return doc

    def stop_recording(self) -> dict[str, Any] | None:
        if self.recorder is None:
            return None
        doc = self.recorder.stop()
        self.recorder = None
        return doc

    # -- shutdown ----------------------------------------------------------
    async def shutdown(self) -> None:
        """Close Hermes browser sessions at process exit; best-effort, never raises."""
        if self._backend_injected or self._backend_factory is not None:
            return  # injected test / direct-mode runtime owns no Hermes sessions
        try:
            from tools.browser_tool_lifecycle import cleanup_all_browsers
        except Exception as exc:  # noqa: BLE001 - stack absent offline
            log.debug("x2.browser_cleanup_import_failed", extra={"error": str(exc)})
            return
        try:
            await asyncio.to_thread(cleanup_all_browsers)
        except Exception as exc:  # noqa: BLE001 - shutdown must never raise
            log.debug("x2.browser_cleanup_failed", extra={"error": str(exc)})

    # -- dispatch ----------------------------------------------------------
    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Entry point for the engine tool registry (all browser_* names)."""
        args = dict(arguments or {})
        try:
            self.ensure_configured()
            ctx = current_context()
            if name == "browser_handoff":
                return await self._handle_handoff(ctx, args)
            if name == "browser_replay":
                return await self._handle_replay(ctx, args)
            if name == "browser_vault_fill":
                return await self._handle_vault_fill(ctx, args)
            action = _ACTION_BY_TOOL.get(name)
            if action is None:
                return _error(f"未知的浏览器工具：{name}")
            if action in _TAKES_TASK_ID and not args.get("task_id"):
                args["task_id"] = ctx.session_id or "default"
            return await self._perform(ctx, name, action, args)
        except BackendUnavailable as exc:
            message = str(exc)
            if not message.startswith("浏览器后端不可用"):
                message = f"浏览器后端不可用：{message}"
            return _error(message, code="backend_unavailable")
        except Exception as exc:  # noqa: BLE001 - mirror the browser tool contract
            log.exception("x2.browser_call_failed", extra={"tool": name})
            return _error(f"浏览器工具 {name} 执行失败：{exc}")

    async def _perform(
        self, ctx: X2Context, name: str, action: str, args: dict[str, Any],
        *, replayed: bool = False,
    ) -> dict[str, Any]:
        payload = await self.call_backend(action, args)
        result = _normalize_payload(payload)
        await self._after_action(ctx, name, action, args, result, replayed=replayed)
        return result

    async def _after_action(
        self, ctx: X2Context, name: str, action: str, args: dict[str, Any],
        result: dict[str, Any], *, replayed: bool = False,
    ) -> None:
        """Bookkeeping after one action: page context, panel sync, recording, step event."""
        data = result.get("data") or {}
        if result.get("is_error"):
            return  # failed actions change nothing observable
        url = str(data.get("url") or (args.get("url") if name == "browser_navigate" else "") or "")
        if url:
            self.last_url = url
        if data.get("title"):
            self.last_title = str(data["title"])
        snapshot = data.get("snapshot")
        if isinstance(snapshot, str) and snapshot:
            self.last_snapshot = snapshot

        if name == "browser_navigate":
            # Browser panel sync: the frontend panel follows the model's navigation.
            await ctx.emit_event(EVENT_PANEL_SYNC, {
                "url": self.last_url, "title": self.last_title, "run_id": ctx.run_id,
            })

        recorder = self.recorder
        if recorder is not None and recorder.active:
            if action in ("navigate", "snapshot") and isinstance(snapshot, str) and snapshot:
                recorder.observe(snapshot, self.last_url)
            recordable = _RECORDABLE.get(name)
            if recordable is not None:
                recorder.record(recordable, args, ref=str(args.get("ref") or ""))

        await ctx.emit_event(EVENT_BROWSER_STEP, {
            "tool": name,
            "action": action,
            "ok": True,
            "replay": replayed,
            "ref": str(args.get("ref") or ""),
            "summary": _summary_from(result),
            "url": self.last_url,
            "run_id": ctx.run_id,
            "session_id": ctx.session_id,
        })

    # -- handoff -----------------------------------------------------------
    async def _handle_handoff(self, ctx: X2Context, args: dict[str, Any]) -> dict[str, Any]:
        reason = str(args.get("reason") or "页面需要人工处理")
        url = str(args.get("url") or self.last_url or "")
        choice = await ctx.request_handoff(reason, url)
        if choice == HANDOFF_GIVE_UP:
            return _error("用户选择放弃（give_up），停止当前浏览器任务。请总结已有进展后结束。")
        if choice == HANDOFF_OPEN_PANEL:
            return _ok(
                {"choice": choice, "url": url},
                "用户已在浏览器面板中接手该页面（open_panel）。请稍后重新获取快照，根据页面变化继续任务。",
            )
        return _ok(
            {"choice": HANDOFF_DONE, "url": url},
            "用户已在页面上完成所需处理（done）。请重新获取快照并继续当前任务。",
        )

    # -- vault -------------------------------------------------------------
    async def _handle_vault_fill(self, ctx: X2Context, args: dict[str, Any]) -> dict[str, Any]:
        handle = str(args.get("handle") or "")
        if not handle:
            return _error("browser_vault_fill 需要 handle 参数（来自 browser_vault_list）。")
        listing = await self.call_backend("vault_list", {})
        listing = scrub_secrets(listing if isinstance(listing, dict) else {})
        item = self._find_vault_item(listing, handle)
        if item is None:
            return _error(f"没有句柄为 {handle!r} 的凭据，请先调用 browser_vault_list。")
        if str(item.get("kind") or "") == "payment":
            label = str(item.get("label") or handle)
            origin = str(item.get("origin") or self.last_url or "当前页面")
            if ctx.wait_input is None:
                return _error("银行卡填写需要用户确认，但当前会话没有可用的确认通道，已取消。")
            choice = await ctx.wait_input(
                f"是否允许在 {origin} 的页面中填写银行卡「{label}」？卡号与 CVC 不会进入对话。",
                ["allow", "deny"],
            )
            if str(choice).strip().lower() not in {"allow", "allow_card", "yes"}:
                await ctx.emit_event("browser.vault_fill_denied", {"handle": handle})
                return _error("用户未确认银行卡填写，已取消。请不要重试，改为询问用户。")
        fill_args = {"handle": handle}
        fill_args["task_id"] = args.get("task_id") or ctx.session_id or "default"
        payload = await self.call_backend("vault_fill", fill_args)
        result = _normalize_payload(payload)
        await ctx.emit_event(EVENT_BROWSER_STEP, {
            "tool": "browser_vault_fill", "action": "vault_fill",
            "ok": not result["is_error"], "handle": handle,
            "summary": "凭据已由后端注入页面（值未经过对话）" if not result["is_error"] else _summary_from(result),
            "run_id": ctx.run_id, "session_id": ctx.session_id,
        })
        return result

    @staticmethod
    def _find_vault_item(listing: dict[str, Any], handle: str) -> dict[str, Any] | None:
        items = listing.get("items") if isinstance(listing, dict) else None
        for item in items or []:
            if isinstance(item, dict) and str(item.get("handle") or "") == handle:
                return item
        return None

    # -- replay ------------------------------------------------------------
    def _replay_browser(self) -> Any:
        """Adapter exposing the runtime as a ReplayEngine browser."""
        runtime = self

        class _StepExecutor:
            async def execute(self, step: dict[str, Any]) -> dict[str, Any]:
                ctx = current_context()
                action = str(step.get("action") or "")
                args = dict(step.get("params") or {})
                if action in _TAKES_TASK_ID and not args.get("task_id"):
                    args["task_id"] = ctx.session_id or "default"
                try:
                    payload = await runtime.call_backend(action, args)
                except BackendUnavailable as exc:
                    return {"ok": False, "error": str(exc)}
                result = _normalize_payload(payload)
                if result["is_error"]:
                    return {"ok": False, "error": _summary_from(result)}
                await runtime._after_action(ctx, f"browser_{action}", action, args, result, replayed=True)
                return {
                    "ok": True,
                    "url": runtime.last_url,
                    "snapshot": runtime.last_snapshot,
                }

        return _StepExecutor()

    async def _handle_replay(self, ctx: X2Context, args: dict[str, Any]) -> dict[str, Any]:
        recording_id = str(args.get("recording_id") or "")
        doc = self.recordings.load(recording_id) if recording_id else None
        if doc is None:
            return _error(f"没有 id 为 {recording_id!r} 的浏览器录制。")
        engine = ReplayEngine(self._replay_browser(), self.recordings, self.replanner)
        outcome = await engine.replay(doc)
        if outcome.get("ok"):
            return _ok(outcome)
        extra = {k: v for k, v in outcome.items() if k != "ok"}
        return _error(
            f"回放在第 {outcome.get('failed_index')} 步失败：{outcome.get('error')}", **extra)


# ---------------------------------------------------------------------------
# Module-level surface for the engine integrator
# ---------------------------------------------------------------------------
_runtime: X2BrowserRuntime | None = None
_runtime_lock = threading.Lock()


def get_runtime() -> X2BrowserRuntime:
    """Process-wide runtime (lazy; tests may replace it via :func:`set_runtime`)."""
    global _runtime
    with _runtime_lock:
        if _runtime is None:
            _runtime = X2BrowserRuntime()
        return _runtime


def set_runtime(runtime: X2BrowserRuntime | None) -> None:
    global _runtime
    with _runtime_lock:
        _runtime = runtime


async def call_tool(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Dispatch through the shared runtime (the handler for every browser_* tool)."""
    return await get_runtime().call_tool(name, arguments)


async def shutdown() -> None:
    """Process-wide shutdown hook (server lifespan): close Hermes browser sessions."""
    global _runtime
    with _runtime_lock:
        runtime, _runtime = _runtime, None
    if runtime is not None:
        await runtime.shutdown()


def get_browser_tool_schemas() -> list[dict[str, Any]]:
    """The single model-facing browser surface."""
    return [json.loads(json.dumps(schema)) for schema in BROWSER_TOOL_SCHEMAS]


def register_browser_tools(register: Register) -> list[str]:
    """Register every browser tool name onto the ONE X2 handler.

    ``register(schema, handler)`` is invoked once per tool with the SAME async
    handler.  The engine should also bind the handoff channel when building the
    run's X2Context: ``X2Context(..., wait_input=x2browser.handoff_wait_input)``
    so ``POST /api/browser/handoff`` resolutions reach blocked tool calls.
    """
    handler = call_tool
    for schema in BROWSER_TOOL_SCHEMAS:
        register(schema, handler)
    return list(BROWSER_TOOL_NAMES)


def start_recording() -> dict[str, Any]:
    return get_runtime().start_recording()


def stop_recording() -> dict[str, Any] | None:
    return get_runtime().stop_recording()


__all__ = [
    "BackendUnavailable",
    "BROWSER_TOOL_SCHEMAS",
    "BROWSER_TOOL_NAMES",
    "HandoffBroker",
    "X2BrowserRuntime",
    "apply_browser_settings",
    "backend_request",
    "call_tool",
    "get_browser_settings",
    "get_browser_tool_schemas",
    "get_runtime",
    "handoff_wait_input",
    "normalize_mode",
    "pending_handoffs",
    "register_browser_tools",
    "resolve_handoff",
    "scrub_secrets",
    "set_runtime",
    "shutdown",
    "start_recording",
    "stop_recording",
    "to_frontend_mode",
]

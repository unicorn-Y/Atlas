"""X2 computer bridge: one background-first desktop runtime over Hermes ``computer_use``.

The pinned ``hermes-agent`` package owns the real runtime (cua-driver over MCP:
background input delivery, verify/escalate verdicts, auxiliary-vision routing,
doctor diagnostics).  This module wires it into the Atlas seams instead of
forking it:

- Legacy Atlas tool names (``computer_observe/mouse/keyboard/window/clipboard``,
  see ``atlas.tools.computer_use``) stay as thin aliases translated onto Hermes
  `computer` actions, so the model never sees two desktop tool surfaces.
  Actions Hermes does not implement (window move/resize, clipboard, raw
  mouse move/down/up) fall through to the legacy Windows runtime, which is
  kept ONLY as this fallback/alias layer.
- Foreground escalation: when a background action reports it could not land,
  the bridge asks the human through :meth:`X2Context.confirm_foreground`
  (emits ``computer.foreground_required``, blocks on ``wait_input``, emits
  ``computer.foreground_resumed``) and retries with ``delivery_mode="foreground"``.
- Every dispatched action appends a ``computer.step`` event (action + thumbnail)
  for the frontend operation replay trail.
- Screenshots are returned by Hermes' own capture pipeline, which routes them
  through ``vision_routing`` / auxiliary vision when the main model cannot see
  images.

Test seam: Hermes' ``tools.computer_use.tool`` accepts injected backends; this
bridge accepts one too (``X2ComputerRuntime(backend=...)``), so tests run
without any real UI automation.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import sys
import threading
from io import BytesIO
from typing import Any, Awaitable, Callable

from atlas.config import get_config
from atlas.tools.computer_use import COMPUTER_TOOLS
from atlas.tools.x2.context import EVENT_COMPUTER_STEP, X2Context, current_context
from atlas.tools.x2.hermes_config_sync import sync_x2_config

log = logging.getLogger(__name__)

# Legacy name -> handler registration contract used by the engine integrator:
# ``register(schema, handler)`` with an OpenAI-style function schema dict and an
# ``async def handler(name, args) -> dict`` coroutine.
Register = Callable[[dict[str, Any], Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]], None]

# Backend codes meaning "the target window is gone / the sticky target is stale":
# the bridge re-resolves by stored PID / title once before failing.
_STALE_WINDOW_CODES = frozenset({
    "window_gone", "stale_target", "element_token_stale", "window_not_found",
})
# Backend codes meaning "background delivery cannot reach this target": the
# bridge escalates to a foreground confirmation instead.
_BACKGROUND_UNAVAILABLE_CODES = frozenset({"background_unavailable"})

_SUMMARY_LIMIT = 400

# Replay-trail thumbnails are event-payload, not model input: cap them so a
# churning desktop loop cannot flood the runtime-events queue.
_THUMBNAIL_MAX_SIDE = 256
_THUMBNAIL_JPEG_QUALITY = 50
_THUMBNAIL_FALLBACK_BYTES = 8192

# Sentinel: distinguishes "no backend injected" (lazy Hermes acquisition) from
# an explicit ``backend=None`` ("Hermes unavailable" — straight to legacy).
_UNSET = object()


# ---------------------------------------------------------------------------
# Legacy alias translation
# ---------------------------------------------------------------------------
def _delivery(args: dict[str, Any]) -> dict[str, Any]:
    mode = args.get("delivery_mode")
    return {"delivery_mode": str(mode)} if mode in {"background", "foreground"} else {}


def translate_legacy_tool(
    name: str, args: dict[str, Any],
) -> tuple[str, dict[str, Any]] | None:
    """Translate a legacy Atlas computer tool call onto a Hermes action.

    Returns ``(hermes_action, hermes_args)``, or ``None`` when the call has no
    Hermes equivalent and must run on the legacy Windows runtime (window
    management, clipboard, raw mouse move/down/up, element-token targeting).
    """
    if name == "computer_observe":
        target = str(args.get("target", "desktop"))
        hargs: dict[str, Any] = {"mode": "som"}
        if target == "desktop":
            hargs["app"] = "desktop"
        elif target == "monitor":
            # Composited full-screen grab (image only) is the closest Hermes lane.
            hargs["app"] = "screen"
        elif target == "window":
            if args.get("window_id"):
                hargs["window_id"] = int(args["window_id"])
            if args.get("pid"):
                hargs["pid"] = int(args["pid"])
        # active_window: no target keys -> Hermes frontmost window.
        return "capture", hargs

    if name == "computer_mouse":
        action = str(args.get("action", ""))
        if action in {"click", "double_click"} and args.get("x") is not None and args.get("y") is not None:
            if args.get("element_token") or args.get("element_index") is not None:
                return None  # element-token targeting stays on the legacy UIA path
            hargs = {
                "coordinate": [int(args["x"]), int(args["y"])],
                "button": str(args.get("button", "left")),
                **_delivery(args),
            }
            return "double_click" if action == "double_click" else "click", hargs
        if action == "drag" and None not in (args.get("from_x"), args.get("from_y"), args.get("x"), args.get("y")):
            return "drag", {
                "from_coordinate": [int(args["from_x"]), int(args["from_y"])],
                "to_coordinate": [int(args["x"]), int(args["y"])],
                "button": str(args.get("button", "left")),
                **_delivery(args),
            }
        if action == "scroll":
            amount = int(args.get("amount") or 0)
            if bool(args.get("horizontal")):
                direction = "right" if amount >= 0 else "left"
            else:
                # Windows wheel semantics: a positive delta scrolls up.
                direction = "up" if amount >= 0 else "down"
            return "scroll", {"direction": direction, "amount": abs(amount) or 3}
        return None  # move / move_relative / mouse_down / mouse_up

    if name == "computer_keyboard":
        action = str(args.get("action", ""))
        if action == "type":
            text = str(args.get("text", ""))
            if args.get("element_token") or args.get("element_index") is not None:
                # Direct value set instead of typing, mirroring the legacy path.
                index = args.get("element_index")
                hargs = {"value": text}
                if index is not None:
                    # Legacy element indexes are 0-based; Hermes SOM indexes are 1-based.
                    hargs["element"] = int(index) + 1
                return "set_value", hargs
            return "type", {"text": text, **_delivery(args)}
        if action == "press" and args.get("key"):
            return "key", {"keys": str(args["key"]).lower(), **_delivery(args)}
        if action == "hotkey" and args.get("keys"):
            return "key", {"keys": "+".join(str(k).lower() for k in args["keys"]), **_delivery(args)}
        return None  # down / up and empty inputs

    if name == "computer_window":
        if str(args.get("action")) == "list":
            return "list_windows", {}
        return None  # focus/move/resize/close need HWND semantics -> legacy

    return None  # computer_clipboard and unknown names


# ---------------------------------------------------------------------------
# Result shaping (Hermes dispatch result -> legacy Atlas tool-result contract)
# ---------------------------------------------------------------------------
def _error(message: str) -> dict[str, Any]:
    return {
        "data": {"error": message},
        "content": [{"type": "text", "text": message}],
        "is_error": True,
    }


def _normalize_dispatch(result: Any) -> dict[str, Any]:
    """Normalize a Hermes ``_dispatch`` result (JSON str or ``_multimodal`` dict)."""
    if isinstance(result, dict) and result.get("_multimodal"):
        meta = result.get("meta") or {}
        data = {"_multimodal": True, "summary": str(result.get("text_summary") or ""), **meta}
        if isinstance(result.get("action_result"), dict):
            data["action_result"] = result["action_result"]
        return {
            "data": data,
            "content": [dict(b) for b in (result.get("content") or [])],
            "is_error": False,
        }
    text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        payload = {"result": text}
    if not isinstance(payload, dict):
        payload = {"result": payload}
    is_error = bool(payload.get("error")) or payload.get("ok") is False
    return {"data": payload, "content": [{"type": "text", "text": text}], "is_error": is_error}


def _verdict_recommends_foreground(payload: dict[str, Any]) -> bool:
    verdict = payload.get("verdict") if isinstance(payload.get("verdict"), dict) else {}
    if verdict.get("decision") == "escalate":
        recommended = verdict.get("recommended") or (payload.get("escalation") or {}).get("recommended")
        if recommended == "foreground":
            return True
    return str(payload.get("code") or "") in _BACKGROUND_UNAVAILABLE_CODES or (
        "background_unavailable" in str(payload.get("error") or "")
    )


def _is_stale_window_error(payload: dict[str, Any]) -> bool:
    if str(payload.get("code") or "") in _STALE_WINDOW_CODES:
        return True
    text = json.dumps(payload, ensure_ascii=False, default=str).casefold()
    return any(marker in text for marker in ("window_gone", "stale window", "window no longer exists"))


def _thumbnail_from(result: dict[str, Any]) -> str | None:
    data = result.get("data") or {}
    if isinstance(data.get("_image_data_url"), str):
        return data["_image_data_url"]
    for block in result.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "image_url":
            url = (block.get("image_url") or {}).get("url")
            if isinstance(url, str):
                return url
    return None


def _truncate_thumbnail(data_url: str) -> str:
    if len(data_url) <= _THUMBNAIL_FALLBACK_BYTES:
        return data_url
    return f"{data_url[:_THUMBNAIL_FALLBACK_BYTES]}…[缩略图已截断]"


def _cap_thumbnail(data_url: str) -> str:
    """Downscale a step thumbnail to a small replay-trail preview.

    ≤256px longest side at JPEG q50 keeps every ``computer.step`` event light.
    If Pillow or the payload is unusable, fall back to truncating the data-URL
    with an explicit marker so the event stream stays bounded either way.
    """
    _, sep, payload = str(data_url).partition(",")
    if not sep:
        return data_url
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001 - Pillow absent: truncate instead
        return _truncate_thumbnail(data_url)
    try:
        image = Image.open(BytesIO(base64.b64decode(payload)))
        image.thumbnail((_THUMBNAIL_MAX_SIDE, _THUMBNAIL_MAX_SIDE))
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        out = BytesIO()
        image.save(out, format="JPEG", quality=_THUMBNAIL_JPEG_QUALITY)
        return f"data:image/jpeg;base64,{base64.b64encode(out.getvalue()).decode('ascii')}"
    except Exception:  # noqa: BLE001 - undecodable payload: truncate instead
        return _truncate_thumbnail(data_url)


def _summary_from(result: dict[str, Any]) -> str:
    data = result.get("data") or {}
    text = str(data.get("message") or data.get("summary") or data.get("error") or "")
    if not text:
        for block in result.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "text":
                text = str(block.get("text") or "")
                break
    return text[:_SUMMARY_LIMIT]


# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------
class X2ComputerRuntime:
    """Bridges legacy Atlas computer tool calls onto the Hermes computer_use stack."""

    def __init__(
        self,
        backend: Any = _UNSET,
        legacy: Any = None,
        hermes_tool: Any = None,
    ) -> None:
        self._injected_backend = backend
        self._backend_injected = backend is not _UNSET
        self._injected_legacy = legacy
        self._injected_hermes_tool = hermes_tool
        self._hermes_tool_failed = hermes_tool is not None and hermes_tool is False
        self._legacy_runtime: Any = None
        self._action_lock = asyncio.Lock()
        self._config_lock = threading.Lock()
        self._configured = False
        self.backend_name = "cua"
        self.driver_binary: str | None = None
        # Last known capture target for stale-window recovery.
        self._last_target: dict[str, Any] = {}

    # -- setup -------------------------------------------------------------
    def ensure_configured(self) -> None:
        """Sync Atlas [computer_use]/[browser] settings into the Hermes engine config."""
        with self._config_lock:
            if self._configured:
                return
            self._configured = True
        try:
            sync_x2_config()
        except Exception as exc:  # noqa: BLE001 - config sync must not break tool calls
            log.warning("x2.computer_config_sync_failed", extra={"error": str(exc)})
        try:
            from tools.computer_use.cua_backend_driver import resolve_cua_driver_cmd

            self.driver_binary = resolve_cua_driver_cmd(None)
            if self.driver_binary:
                # Backend = cua driver when available; Hermes defaults to it anyway.
                os.environ.setdefault("HERMES_COMPUTER_USE_BACKEND", "cua")
            else:
                self.backend_name = "cua(unavailable)"
        except Exception as exc:  # noqa: BLE001
            log.debug("x2.cua_driver_probe_failed", extra={"error": str(exc)})

    def _hermes_tool(self) -> Any:
        if self._injected_hermes_tool is not None:
            return self._injected_hermes_tool or None
        if self._hermes_tool_failed:
            return None
        try:
            from tools.computer_use import tool as hermes_tool

            return hermes_tool
        except Exception as exc:  # noqa: BLE001 - pinned dependency may be absent
            log.warning("x2.hermes_computer_tool_missing", extra={"error": str(exc)})
            self._hermes_tool_failed = True
            return None

    def _acquire_backend(self, hermes_tool: Any) -> Any:
        if self._backend_injected:
            return self._injected_backend  # may be None: caller falls back to legacy
        if not self.driver_binary and not os.environ.get("HERMES_COMPUTER_USE_BACKEND"):
            # No resolvable cua-driver: never let Hermes lazily bootstrap/install
            # (it would download a toolchain mid tool-call). Legacy stays in charge.
            return None
        try:
            return hermes_tool._get_backend("")
        except Exception as exc:  # noqa: BLE001 - fallback to legacy below
            log.warning("x2.hermes_backend_unavailable", extra={"error": str(exc)})
            return None

    def _ensure_legacy(self) -> Any:
        if self._injected_legacy is not None:
            return self._injected_legacy
        if self._legacy_runtime is not None:
            return self._legacy_runtime
        if os.name != "nt":
            return None
        try:
            from atlas.tools.computer_use import ComputerUseRuntime

            self._legacy_runtime = ComputerUseRuntime()
            return self._legacy_runtime
        except Exception as exc:  # noqa: BLE001
            log.warning("x2.legacy_computer_runtime_failed", extra={"error": str(exc)})
            return None

    # -- dispatch ----------------------------------------------------------
    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Entry point matching the legacy runtime ``call_tool(name, args)`` contract."""
        args = dict(arguments or {})
        try:
            permission_mode = get_config().computer_use_permission_mode
            if permission_mode != "full_access":
                return _error(f"Computer Use 已被 permission_mode={permission_mode!r} 禁用。")
            self.ensure_configured()
            ctx = current_context()
            await _wait_if_paused(_run_key(ctx.run_id, ctx.session_id))
            translated = translate_legacy_tool(name, args)
            if translated is not None:
                result = await self._call_hermes(translated[0], translated[1], legacy_name=name, ctx=ctx)
                if result is not None:
                    await self._emit_step(ctx, name, result)
                    return result
            return await self._call_legacy(name, args, ctx=ctx)
        except Exception as exc:  # noqa: BLE001 - mirror the legacy tool contract
            log.exception("x2.computer_call_failed", extra={"tool": name})
            return _error(f"{name} 执行失败：{exc}")

    async def _call_hermes(
        self, action: str, args: dict[str, Any], *, legacy_name: str, ctx: X2Context,
    ) -> dict[str, Any] | None:
        """Run one Hermes action; ``None`` = no Hermes backend, fall back to legacy."""
        hermes_tool = self._hermes_tool()
        if hermes_tool is None:
            return None
        backend = await asyncio.to_thread(self._acquire_backend, hermes_tool)
        if backend is None:
            return None
        async with self._action_lock:
            try:
                result = await asyncio.to_thread(
                    hermes_tool._dispatch, backend, action, args,
                    session_id=ctx.session_id or None,
                )
            except Exception as exc:  # noqa: BLE001 - a raise after input may have landed
                log.exception("x2.hermes_dispatch_failed", extra={"action": action})
                return _error(f"桌面控制后端执行 {action} 失败：{exc}")
            normalized = _normalize_dispatch(result)
            self._remember_target(action, args, normalized)
            if normalized["is_error"] and _is_stale_window_error(normalized["data"]):
                recovered = await self._recover_target(backend, hermes_tool)
                if recovered is not None:
                    retry_args = {**args, **recovered}
                    result = await asyncio.to_thread(
                        hermes_tool._dispatch, backend, action, retry_args,
                        session_id=ctx.session_id or None,
                    )
                    normalized = _normalize_dispatch(result)
            if (
                _verdict_recommends_foreground(normalized["data"])
                and str(args.get("delivery_mode") or "background") != "foreground"
            ):
                payload = normalized["data"]
                reason = str(payload.get("message") or "后台投递未能生效，需要短暂接管前台焦点")
                target = str(self._last_target.get("title") or payload.get("app") or "")
                approved = await ctx.confirm_foreground(reason=reason, target=target)
                if not approved:
                    return _error(f"用户拒绝了前台接管，已取消 {legacy_name or action} 操作。")
                result = await asyncio.to_thread(
                    hermes_tool._dispatch, backend, action, {**args, "delivery_mode": "foreground"},
                    session_id=ctx.session_id or None,
                )
                normalized = _normalize_dispatch(result)
            return normalized

    def _remember_target(self, action: str, args: dict[str, Any], normalized: dict[str, Any]) -> None:
        if action != "capture":
            return
        payload = normalized.get("data") or {}
        target = {
            "pid": args.get("pid") or self._last_target.get("pid"),
            "window_id": args.get("window_id") or self._last_target.get("window_id"),
            "title": str(payload.get("window_title") or self._last_target.get("title") or ""),
        }
        self._last_target = {k: v for k, v in target.items() if v}

    async def _recover_target(self, backend: Any, hermes_tool: Any) -> dict[str, Any] | None:
        """Re-resolve a dead window handle by stored PID / title and restick the target."""
        target = self._last_target
        if not target:
            return None
        try:
            windows = await asyncio.to_thread(backend.list_windows)
        except Exception as exc:  # noqa: BLE001
            log.debug("x2.window_recovery_list_failed", extra={"error": str(exc)})
            return None
        match: dict[str, Any] | None = None
        for window in windows or []:
            if target.get("pid") and window.get("pid") == target["pid"]:
                match = window
                break
        if match is None and target.get("title"):
            for window in windows or []:
                if target["title"] in str(window.get("title") or ""):
                    match = window
                    break
        if match is None:
            return None
        try:
            await asyncio.to_thread(
                backend.capture, "ax", None, match.get("pid"), match.get("window_id"),
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("x2.window_recovery_capture_failed", extra={"error": str(exc)})
            return None
        recovered = {"pid": match.get("pid"), "window_id": match.get("window_id")}
        self._last_target.update({k: v for k, v in recovered.items() if v})
        log.info("x2.window_recovered", extra={"pid": recovered["pid"], "window_id": recovered["window_id"]})
        return recovered

    async def _call_legacy(self, name: str, args: dict[str, Any], *, ctx: X2Context) -> dict[str, Any]:
        """Legacy Windows runtime as the fallback/alias layer for non-Hermes actions."""
        runtime = self._ensure_legacy()
        if runtime is None:
            return _error(
                "当前没有可用的桌面控制后端：cua-driver 不可用，且本机没有 Windows 桌面回退运行时。"
                "可运行 `hermes computer-use install` 安装 cua-driver。"
            )
        result = await runtime.call_tool(name, args)
        await self._emit_step(ctx, name, result)
        return result

    async def _emit_step(self, ctx: X2Context, name: str, result: dict[str, Any]) -> None:
        """Append one replay-trail event (action + capped thumbnail) for the frontend."""
        thumbnail = _thumbnail_from(result)
        if thumbnail:
            thumbnail = _cap_thumbnail(thumbnail)
        step = {
            "tool": name,
            "ok": not bool(result.get("is_error")),
            "summary": _summary_from(result),
            "thumbnail": thumbnail,
            "run_id": ctx.run_id,
            "session_id": ctx.session_id,
        }
        _record_step(ctx.run_id or ctx.session_id or "", step)
        await ctx.emit_event(EVENT_COMPUTER_STEP, step)

    async def shutdown(self) -> None:
        """Release the Hermes session backend and stop the legacy runtime, best-effort."""
        hermes_tool = self._hermes_tool()
        if hermes_tool is not None and not self._backend_injected:
            try:
                hermes_tool.release_computer_use_session("")
            except Exception as exc:  # noqa: BLE001
                log.debug("x2.hermes_backend_release_failed", extra={"error": str(exc)})
        legacy = self._legacy_runtime
        if legacy is not None:
            stop = getattr(legacy, "shutdown", None)
            if callable(stop):
                try:
                    await stop()
                except Exception as exc:  # noqa: BLE001
                    log.debug("x2.legacy_shutdown_failed", extra={"error": str(exc)})


# ---------------------------------------------------------------------------
# Module-level surface for the engine integrator
# ---------------------------------------------------------------------------
_runtime: X2ComputerRuntime | None = None
_runtime_lock = threading.Lock()

# Replay trail (run key → last N steps) and pause gates (run key → Event that
# is SET while running, CLEARed while paused). Bounded: 40 steps per run,
# 20 runs FIFO.
_STEP_LOCK = threading.Lock()
_RUN_STEPS: dict[str, list[dict[str, Any]]] = {}
_RUN_ORDER: list[str] = []
_PAUSE_EVENTS: dict[str, threading.Event] = {}
_STEP_LIMIT = 40
_RUN_LIMIT = 20


def _run_key(run_id: str | None, session_id: str | None) -> str:
    return str(run_id or session_id or "")


def _record_step(key: str, step: dict[str, Any]) -> None:
    if not key:
        return
    with _STEP_LOCK:
        trail = _RUN_STEPS.setdefault(key, [])
        trail.append(dict(step))
        del trail[:-_STEP_LIMIT]
        if key not in _RUN_ORDER:
            _RUN_ORDER.append(key)
            del _RUN_ORDER[:-_RUN_LIMIT]
            for stale in list(_RUN_STEPS):
                if stale not in _RUN_ORDER:
                    _RUN_STEPS.pop(stale, None)
                    _PAUSE_EVENTS.pop(stale, None)


def run_steps(run_id: str) -> list[dict[str, Any]]:
    """Replay trail for one run (newest last); empty when unknown."""
    with _STEP_LOCK:
        return [dict(item) for item in _RUN_STEPS.get(str(run_id or ""), [])]


def set_paused(run_id: str, paused: bool) -> bool:
    """Pause/resume the next action of a run's computer sequence. True when known."""
    key = str(run_id or "")
    with _STEP_LOCK:
        if key not in _RUN_STEPS:
            return False
        gate = _PAUSE_EVENTS.setdefault(key, threading.Event())
    if paused:
        gate.clear()
    else:
        gate.set()
    return True


async def _wait_if_paused(key: str, timeout: float = 120.0) -> None:
    with _STEP_LOCK:
        gate = _PAUSE_EVENTS.get(key)
    if gate is not None and not gate.is_set():
        # The edge bar flips this when the user touches the mouse; wait bounded.
        def _wait() -> None:
            gate.wait(timeout)

        await asyncio.to_thread(_wait)


def get_runtime() -> X2ComputerRuntime:
    """Process-wide runtime (lazy; tests may replace it via :func:`set_runtime`)."""
    global _runtime
    with _runtime_lock:
        if _runtime is None:
            _runtime = X2ComputerRuntime()
        return _runtime


def set_runtime(runtime: X2ComputerRuntime | None) -> None:
    global _runtime
    with _runtime_lock:
        _runtime = runtime


async def call_tool(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Dispatch through the shared runtime (the alias handler for every legacy name)."""
    return await get_runtime().call_tool(name, arguments)


def get_computer_tool_schemas() -> list[dict[str, Any]]:
    """The legacy Atlas schemas — the exact alias surface exposed to the model."""
    return [dict(schema) for schema in COMPUTER_TOOLS]


def register_computer_tools(register: Register) -> list[str]:
    """Register every legacy computer tool name onto the single X2 handler.

    ``register(schema, handler)`` is invoked once per legacy tool with the SAME
    async handler, so the model sees five familiar names backed by one runtime
    (no duplicate ``computer_use`` tool is registered here).
    """
    handler = call_tool
    names: list[str] = []
    for schema in get_computer_tool_schemas():
        register(schema, handler)
        names.append(str(schema["function"]["name"]))
    return names


# ---------------------------------------------------------------------------
# Status / doctor
# ---------------------------------------------------------------------------
def collect_doctor_report() -> dict[str, Any]:
    """Mirror ``tools.computer_use.doctor`` — cua-driver health_report, never raising."""
    platform = sys.platform
    try:
        from tools.computer_use import doctor as hermes_doctor
        from tools.computer_use.cua_backend_driver import resolve_cua_driver_cmd

        binary = resolve_cua_driver_cmd(None)
        if not binary:
            return {
                "schema_version": "1", "platform": platform, "overall": "failed",
                "driver_version": None, "checks": [{
                    "name": "binary_version", "status": "fail",
                    "message": "cua-driver 未安装（可运行 `hermes computer-use install`）",
                }],
            }
        try:
            return dict(hermes_doctor._drive_health_report(binary, timeout=8.0))
        except Exception as exc:  # noqa: BLE001 - degraded beats a 500
            return {
                "schema_version": "1", "platform": platform, "overall": "degraded",
                "driver_version": None, "checks": [{
                    "name": "health_report", "status": "fail",
                    "message": f"health_report 不可用：{exc}",
                }],
            }
    except Exception as exc:  # noqa: BLE001
        return {"schema_version": "1", "platform": platform, "overall": "failed",
                "driver_version": None, "checks": [], "error": str(exc)}


def status_snapshot() -> dict[str, Any]:
    """Readiness, driver version and diagnostics for GET /api/computer/status."""
    try:
        runtime = get_runtime()
        runtime.ensure_configured()  # best-effort: reflect the synced Hermes config
        permission_mode = get_config().computer_use_permission_mode
        report = collect_doctor_report()
        ready = report.get("overall") == "ok" and permission_mode == "full_access"
        return {
            "ok": True,
            "ready": bool(ready),
            "permission_mode": permission_mode,
            "backend": {
                "name": runtime.backend_name,
                "driver_binary": runtime.driver_binary,
                "legacy_fallback": os.name == "nt",
            },
            "driver": {
                "version": report.get("driver_version"),
                "platform": report.get("platform", sys.platform),
            },
            "doctor": report,
        }
    except Exception as exc:  # noqa: BLE001 - status endpoints must never raise
        return {"ok": False, "ready": False, "error": f"查询桌面控制状态失败：{exc}", "doctor": None}


async def shutdown() -> None:
    """Process-wide shutdown hook: cancel pending human waits, release backends."""
    from atlas.tools.x2 import pending as x2pending

    for run_id in x2pending.pending_runs():
        x2pending.cancel_run(run_id)
    global _runtime
    with _runtime_lock:
        runtime, _runtime = _runtime, None
    with _STEP_LOCK:
        _RUN_STEPS.clear()
        _RUN_ORDER.clear()
        _PAUSE_EVENTS.clear()
    if runtime is not None:
        await runtime.shutdown()


__all__ = [
    "X2ComputerRuntime",
    "call_tool",
    "collect_doctor_report",
    "get_computer_tool_schemas",
    "get_runtime",
    "register_computer_tools",
    "run_steps",
    "set_paused",
    "set_runtime",
    "status_snapshot",
    "shutdown",
    "translate_legacy_tool",
]

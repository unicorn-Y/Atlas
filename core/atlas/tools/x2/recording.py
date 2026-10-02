"""X2 learned browser workflow: capture → replay → per-step self-heal → to-skill.

While the model drives the single browser tool surface (a11y snapshots carry
``@eN`` element refs), :class:`Recorder` captures every mutating action into
``<data>/browser-cache/recordings/<id>.json`` as::

    {site, page-structure fingerprint, element ref, action, params, description}

:class:`ReplayEngine` re-executes a recording step by step with ZERO model
calls; a failed step gets exactly ONE single-step model replan (the injected
``replanner`` — in production a callback that prompts the Atlas model, in tests
a stub) and the healed step is written back into the stored recording.
:func:`to_skill_bundle` turns a recording into a ``{name, description,
skill_md, steps}`` skill bundle; :func:`save_skill` writes it as SKILL.md.

Import-light by design: stdlib only, and the browser is injected (an object
with ``async execute(step) -> {ok, error?, url?, snapshot?}``), so tests run
against a fake without any network or browser process.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

# Accessibility-snapshot line: `- heading "登录" [ref=e12]` (agent-browser format).
# Refs are page-local and shift between sessions, so the fingerprint is computed
# over the role+name structure WITHOUT refs, while the step keeps the concrete ref.
_SNAPSHOT_LINE_RE = re.compile(
    r'^\s*-\s+(?P<role>[A-Za-z_][\w-]*)\s+"(?P<name>[^"]*)"(?:\s+\[ref=(?P<ref>e\d+)\])?'
)

# Keys that must never survive into a skill bundle / stored params echo.
_SENSITIVE_PARAM_KEYS = frozenset({"password", "secret", "otp_secret", "cvc", "cvv", "card_number"})

_DEFAULT_DESCRIPTION = "步骤"


def recordings_dir() -> Path:
    """Storage root for learned recordings: ``<Atlas data>/browser-cache/recordings``."""
    from atlas.config import DATA_ROOT

    return Path(DATA_ROOT) / "data" / "browser-cache" / "recordings"


def new_recording_id() -> str:
    return f"rec-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


def origin_of(url: str) -> str:
    """``https://example.com`` from a full URL (empty string when unparsable)."""
    try:
        parts = urlparse(url or "")
        if parts.scheme and parts.netloc:
            return f"{parts.scheme}://{parts.netloc}"
    except ValueError:
        pass
    return ""


def parse_snapshot(snapshot_text: str) -> tuple[str, dict[str, dict[str, str]]]:
    """Extract ``(fingerprint, elements)`` from an a11y snapshot text.

    ``fingerprint`` — sha1 over the ordered ``role|name`` structure (refs stripped),
    so the same page yields the same fingerprint across sessions.
    ``elements`` — ``{"e12": {"role", "name", "description", "ref", "at_ref"}}``.
    """
    structure: list[str] = []
    elements: dict[str, dict[str, str]] = {}
    for line in (snapshot_text or "").splitlines():
        match = _SNAPSHOT_LINE_RE.match(line)
        if not match:
            continue
        role = match.group("role")
        name = match.group("name") or ""
        structure.append(f"{role}|{name}")
        ref = match.group("ref")
        if ref:
            elements[ref] = {
                "ref": ref,
                "at_ref": f"@{ref}",
                "role": role,
                "name": name,
                "description": f'{role} "{name}"',
            }
    digest = hashlib.sha1("\n".join(structure).encode("utf-8")).hexdigest()[:12]
    return digest, elements


def clean_params(params: dict[str, Any] | None) -> dict[str, Any]:
    """Copy of ``params`` safe to persist (task ids and secrets stripped)."""
    return {
        k: v for k, v in (params or {}).items()
        if k != "task_id" and str(k).casefold() not in _SENSITIVE_PARAM_KEYS
    }


@dataclass
class RecordingStore:
    """JSON-file persistence for recording documents."""

    base_dir: Path | None = None

    def _dir(self) -> Path:
        directory = self.base_dir if self.base_dir is not None else recordings_dir()
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _path(self, recording_id: str) -> Path:
        safe = "".join(ch for ch in recording_id if ch.isalnum() or ch in "-_")
        return self._dir() / f"{safe or 'unnamed'}.json"

    def create(self, site: str = "") -> dict[str, Any]:
        doc: dict[str, Any] = {
            "recording_id": new_recording_id(),
            "site": site,
            "status": "recording",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "steps": [],
        }
        self.save(doc)
        return doc

    def save(self, doc: dict[str, Any]) -> None:
        self._path(str(doc.get("recording_id"))).write_text(
            json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self, recording_id: str) -> dict[str, Any] | None:
        path = self._path(recording_id)
        if not path.exists():
            return None
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return doc if isinstance(doc, dict) else None

    def list(self) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for path in sorted(self._dir().glob("*.json")):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(doc, dict) and doc.get("recording_id"):
                summaries.append({
                    "recording_id": doc.get("recording_id"),
                    "site": doc.get("site", ""),
                    "status": doc.get("status", ""),
                    "step_count": len(doc.get("steps") or []),
                    "created_at": doc.get("created_at", ""),
                })
        return summaries


class Recorder:
    """Captures model-driven browser actions into a recording document.

    The runtime bridge feeds :meth:`observe` (snapshot text + URL after every
    navigation / snapshot) and :meth:`record` (every successful mutating
    action).  Each record is persisted immediately so a crashed run still
    leaves a replayable prefix.
    """

    def __init__(self, doc: dict[str, Any], store: RecordingStore | None = None) -> None:
        self.doc = doc
        self.store = store or RecordingStore()
        self._fingerprint: str = ""
        self._elements: dict[str, dict[str, str]] = {}
        self._site: str = str(doc.get("site") or "")

    @property
    def recording_id(self) -> str:
        return str(self.doc["recording_id"])

    @property
    def active(self) -> bool:
        return self.doc.get("status") == "recording"

    def observe(self, snapshot_text: str, url: str = "") -> None:
        """Update the page-structure context from the latest a11y snapshot."""
        self._fingerprint, self._elements = parse_snapshot(snapshot_text)
        if url:
            self._site = origin_of(url) or self._site
        self.doc["site"] = self._site

    def record(self, action: str, params: dict[str, Any] | None = None, ref: str = "") -> dict[str, Any]:
        """Append one step ``{site, fingerprint, ref, action, params, description}``."""
        ref = ref if not ref or ref.startswith("@") else f"@{ref}"
        element = self._elements.get(ref.lstrip("@"), {})
        params = clean_params(params)
        if ref:
            params = {"ref": ref, **{k: v for k, v in params.items() if k != "ref"}}
        step: dict[str, Any] = {
            "index": len(self.doc.get("steps") or []),
            "site": self._site,
            "fingerprint": self._fingerprint,
            "ref": ref,
            "element": element.get("description", ""),
            "action": action,
            "params": params,
            "description": f'{action} {element.get("description", ref or "")}'.strip(),
        }
        self.doc.setdefault("steps", []).append(step)
        self.doc["site"] = self._site
        try:
            self.store.save(self.doc)
        except OSError:
            pass  # persistence is best-effort; the in-memory doc stays authoritative
        return step

    def stop(self) -> dict[str, Any]:
        self.doc["status"] = "stopped"
        self.doc["stopped_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.store.save(self.doc)
        return self.doc


# ---------------------------------------------------------------------------
# Replay with per-step self-heal
# ---------------------------------------------------------------------------
# browser adapter protocol: async execute(step) -> {"ok": bool, "error"?: str,
# "url"?: str, "snapshot"?: str}; replanner protocol: async replan(step,
# failure) -> partial step fields (action/ref/params/element) or None.
Replanner = Callable[[dict[str, Any], dict[str, Any]], Awaitable[dict[str, Any] | None]]


def model_replanner(invoke_model: Callable[[str], Awaitable[str]]) -> Replanner:
    """Build a replanner from a ``prompt -> model answer`` callable.

    The answer must be JSON: ``{"action", "ref"?, "params"?, "element"?}`` to
    heal the step, or ``{"give_up": true}`` / invalid JSON to give up on it.
    """
    async def replan(step: dict[str, Any], failure: dict[str, Any]) -> dict[str, Any] | None:
        prompt = (
            "一次浏览器工作流回放中，以下步骤失败了。请根据当前页面快照给出修正后的单步操作。\n"
            f"原步骤：{json.dumps(step, ensure_ascii=False)}\n"
            f"失败原因：{failure.get('error', '')}\n"
            f"当前页面快照：\n{failure.get('snapshot') or '(无快照)'}\n"
            '只返回 JSON：{"action": "...", "ref": "@eN", "params": {...}, "element": "..."}，'
            '或 {"give_up": true}。'
        )
        raw = await invoke_model(prompt)
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return None
        if not isinstance(data, dict) or data.get("give_up"):
            return None
        healed = {k: data[k] for k in ("action", "ref", "params", "element") if k in data}
        return healed or None

    return replan


class ReplayEngine:
    """Executes recorded steps directly against the injected browser — no model
    calls on the happy path; exactly one replan attempt per failed step."""

    def __init__(
        self,
        browser: Any,
        store: RecordingStore | None = None,
        replanner: Replanner | None = None,
    ) -> None:
        self.browser = browser
        self.store = store or RecordingStore()
        self.replanner = replanner

    async def replay(self, doc: dict[str, Any]) -> dict[str, Any]:
        steps: list[dict[str, Any]] = list(doc.get("steps") or [])
        healed: list[Any] = []
        result: dict[str, Any] = {
            "recording_id": doc.get("recording_id"),
            "total": len(steps),
            "executed": 0,
            "healed": healed,
            "ok": True,
            "failed_index": None,
            "error": None,
        }
        for step in steps:
            outcome = await self._execute(step)
            if not outcome.get("ok", False):
                was_healed = await self._heal(step, outcome)
                if was_healed:
                    outcome = await self._execute(step)
                if not outcome.get("ok", False):
                    result.update({
                        "ok": False,
                        "failed_index": step.get("index"),
                        "error": outcome.get("error") or "步骤执行失败",
                    })
                    return result
                healed.append(step.get("index"))
            result["executed"] += 1
        if healed:
            self.store.save(doc)  # persist the healed step records
        return result

    async def _execute(self, step: dict[str, Any]) -> dict[str, Any]:
        try:
            outcome = await self.browser.execute(step)
        except Exception as exc:  # noqa: BLE001 - backend raises are step failures
            return {"ok": False, "error": str(exc)}
        return outcome if isinstance(outcome, dict) else {"ok": bool(outcome)}

    async def _heal(self, step: dict[str, Any], failure: dict[str, Any]) -> bool:
        """Single-step self-heal: one replan, then persist the updated record."""
        if self.replanner is None:
            return False
        try:
            healed = await self.replanner(step, {
                "error": failure.get("error", ""),
                "url": failure.get("url", ""),
                "snapshot": failure.get("snapshot", ""),
                "fingerprint": step.get("fingerprint", ""),
            })
        except Exception:  # noqa: BLE001 - a broken replanner must not crash replay
            return False
        if not healed:
            return False
        for key in ("action", "ref", "params", "element"):
            if key in healed and healed[key] is not None:
                step[key] = healed[key]
        if "params" in healed and isinstance(healed["params"], dict):
            step["params"] = clean_params(healed["params"])
        if healed.get("ref") and not step.get("element"):
            step["element"] = str(healed.get("element") or "")
        step["healed"] = True
        return True

    async def replay_recording(self, recording_id: str) -> dict[str, Any]:
        doc = self.store.load(recording_id)
        if doc is None:
            return {"ok": False, "error": f"没有 id 为 {recording_id!r} 的浏览器录制。"}
        return await self.replay(doc)


# ---------------------------------------------------------------------------
# to-skill
# ---------------------------------------------------------------------------
def to_skill_bundle(
    doc: dict[str, Any],
    name: str = "",
    description: str = "",
) -> dict[str, Any]:
    """Bundle a recording as ``{name, description, skill_md, steps}``.

    Step params are re-cleaned here so even a hand-edited recording document
    cannot smuggle secret-shaped values into a skill.
    """
    steps = [
        {**step, "params": clean_params(step.get("params"))} if isinstance(step, dict) else step
        for step in (doc.get("steps") or [])
    ]
    site = str(doc.get("site") or "")
    host = origin_of(site).split("://", 1)[-1] if site else ""
    if not name:
        base = host or str(doc.get("recording_id") or "browser-flow")
        slug = re.sub(r"[^a-z0-9-]+", "-", base.lower()).strip("-") or "browser-flow"
        name = f"{slug}-flow" if not slug.endswith("-flow") else slug
    if not description:
        first = steps[0]["description"] if steps else "浏览器工作流"
        description = f"在 {host or '目标网站'} 上学到的浏览器工作流（{len(steps)} 步，从「{first}」开始）。"
    lines = [
        "---",
        f"name: {name}",
        f"description: {description}",
        "---",
        "",
        f"# {name}",
        "",
        f"由 Atlas 浏览器录制学得（站点：{host or '未知'}，共 {len(steps)} 步）。",
        "",
        "## Steps",
        "",
    ]
    for step in steps:
        lines.append(f"{step.get('index', 0) + 1}. {step.get('description') or step.get('action')}"
                     f" — `{step.get('action')}` {json.dumps(step.get('params') or {}, ensure_ascii=False)}")
    lines += [
        "",
        "## Replay",
        "",
        "使用浏览器工具 `browser_replay {\"recording_id\": "
        f"\"{doc.get('recording_id')}\"}}` 逐步回放；失败步骤会自动进行单步自愈后更新本文件对应的录制。",
        "",
    ]
    return {
        "name": name,
        "description": description,
        "skill_md": "\n".join(lines),
        "steps": steps,
        "recording_id": doc.get("recording_id"),
    }


def save_skill(bundle: dict[str, Any], skills_dir: Path | None = None) -> Path:
    """Write the bundle as ``<skills_dir>/<name>/SKILL.md`` and return the path."""
    directory = Path(skills_dir) if skills_dir is not None else _default_skills_dir()
    target = directory / str(bundle["name"])
    target.mkdir(parents=True, exist_ok=True)
    path = target / "SKILL.md"
    path.write_text(str(bundle["skill_md"]), encoding="utf-8")
    return path


def _default_skills_dir() -> Path:
    from atlas.skills import SKILLS_DIR

    return Path(SKILLS_DIR)


__all__ = [
    "Recorder",
    "RecordingStore",
    "ReplayEngine",
    "clean_params",
    "model_replanner",
    "new_recording_id",
    "origin_of",
    "parse_snapshot",
    "recordings_dir",
    "save_skill",
    "to_skill_bundle",
]

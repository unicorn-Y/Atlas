"""Best-effort Python compatibility layer for ZCode Browser Use.

Source: zai-org/ZCode@aac4755666d09fdcd70272fcf063c077a639015f,
``apps/zcode-cli/packages/browser-use-plugin/docs/overview.md`` (Apache-2.0).
This implements the documented operation names and safety behavior against
Atlas's existing X2/Hermes browser session; no upstream source code is copied.

Atlas has no ZCode IAB host registry. In particular, this module never treats
the Atlas-controlled tab list as user tabs, never claims a desktop tab, and
never reports browser-pane visibility, a delivered pane state, or WebM
recording when the active runtime cannot provide it.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
import time
import uuid
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_RUNTIME_ID = "atlas-x2"
_WAIT_CAP_MS = 3000
_SCREENSHOT_MAX_BYTES = 8 * 1024 * 1024
_VIEWPORT_MIN = 320
_VIEWPORT_MAX_WIDTH = 3840
_VIEWPORT_MAX_HEIGHT = 2160


def _ok(data: Any = None, **fields: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        return {"success": True, **data, **fields}
    if data is None:
        return {"success": True, **fields}
    return {"success": True, "result": data, **fields}


def _error(message: str, code: str = "browser_use_error", **fields: Any) -> dict[str, Any]:
    return {"success": False, "error": str(message), "code": code, **fields}


def _as_result(value: Any) -> dict[str, Any]:
    """Normalize X2's ``{data, content, is_error}`` and Hermes CLI results."""
    if not isinstance(value, dict):
        return _ok(value)
    if "data" in value and "is_error" in value:
        data = value.get("data")
        if value.get("is_error"):
            data = data if isinstance(data, dict) else {"error": str(data or "browser action failed")}
            return _error(str(data.get("error") or "browser action failed"),
                          str(data.get("code") or "browser_use_error"), **{
                              k: v for k, v in data.items() if k not in {"error", "code"}
                          })
        return _ok(data)
    if value.get("success") is False or value.get("error"):
        return _error(str(value.get("error") or "browser action failed"),
                      str(value.get("code") or "browser_use_error"), **{
                          k: v for k, v in value.items() if k not in {"success", "error", "code"}
                      })
    if value.get("success") is True:
        return {k: v for k, v in value.items() if k != "success"} | {"success": True}
    return _ok(value)


def _ctx():
    from atlas.tools.x2.context import current_context

    return current_context()


def _runtime(runtime: Any = None):
    if runtime is not None:
        return runtime
    from atlas.tools.x2.browser import get_runtime

    return get_runtime()


def _descriptor(runtime: Any = None) -> dict[str, Any]:
    """Describe each surface item truthfully without starting a browser process."""
    from atlas.tools.x2.browser import HermesBrowserBackend, get_browser_settings

    rt = _runtime(runtime)
    backend = getattr(rt, "_backend", None)
    if backend is None and not getattr(rt, "_backend_injected", False):
        backend = HermesBrowserBackend()
    usable = isinstance(backend, HermesBrowserBackend)
    reason = "requires Atlas's Hermes agent-browser backend" if not usable else ""

    def item(supported: bool, detail: str = "") -> dict[str, Any]:
        return {"supported": supported, "reason": detail or (
            "implemented by Atlas X2" if supported else "not available in the active Atlas runtime"
        )}

    conditional = item(usable, reason)
    settings = get_browser_settings()
    dialog_available = False
    if usable:
        try:
            from atlas.tools.x2.context import current_context
            import tools.browser_tool as browser_tool
            from tools.browser_supervisor import SUPERVISOR_REGISTRY

            session_id = browser_tool._last_session_key(str(current_context().session_id or "default"))
            supervisor = SUPERVISOR_REGISTRY.get(session_id)
            dialog_available = bool(supervisor and supervisor.snapshot().active)
        except Exception:
            dialog_available = False
    capabilities = {
        "runtime.list": item(True), "runtime.get": item(True),
        "runtime.default": item(True), "runtime.select": item(True, "Atlas has one X2 runtime"),
        "tabs.list": conditional, "tabs.get": conditional, "tabs.new": conditional,
        "tabs.open": conditional,
        "tabs.finalize": item(False, "Atlas has no pane handoff/deliverable registry; tabs remain open."),
        "user.openTabs": item(False, "Atlas has no desktop IAB host registry to distinguish user tabs."),
        "user.claimTab": item(False, "Atlas cannot claim a host-owned desktop tab or verify its UI scope."),
        "tab.goto": item(True), "tab.back": item(True), "tab.forward": conditional,
        "tab.reload": conditional, "tab.close": conditional, "tab.url": conditional,
        "tab.title": conditional, "tab.snapshot": item(True), "tab.locator": conditional,
        "tab.frames": item(True, "CDP frame tree when a supervisor is active; otherwise same-page iframe metadata."),
        "tab.frame": conditional, "tab.evaluate": item(True, "Uses Atlas browser_console SSRF/evaluation policy."),
        "tab.waitForURL": conditional, "tab.waitForLoadState": conditional,
        "tab.waitForTimeout": conditional, "tab.waitForFunction": item(usable, "Uses Atlas browser evaluation policy."),
        "tab.cua": conditional,
        "tab.cua.click": conditional, "tab.cua.double_click": conditional,
        "tab.cua.move": conditional, "tab.cua.scroll": conditional,
        "tab.cua.drag": conditional, "tab.cua.keypress": item(True), "tab.cua.type": conditional,
        "tab.dom_cua": item(True), "tab.dom_cua.click": item(True),
        "tab.dom_cua.double_click": conditional, "tab.dom_cua.scroll": conditional,
        "tab.dom_cua.keypress": item(True), "tab.dom_cua.type": item(True),
        "tab.screenshot": conditional,
        "tab.viewportSize": item(True), "tab.setViewportSize": conditional,
        "tab.getJsDialog": item(dialog_available, "An active CDP supervisor is required."),
        "tab.respondJsDialog": item(dialog_available, "An active CDP supervisor is required."),
        "tab.markDeliverable": item(False, "No Atlas browser pane/deliverable owner exists."),
        "tab.markHandoff": item(True, "Routes through Atlas browser_handoff and its user-resolution channel."),
        "recording.start": item(True, "Atlas records replayable browser steps, not video."),
        "recording.status": item(True, "Atlas records replayable browser steps, not video."),
        "recording.cancel": item(True, "Cancels Atlas step recording; no WebM is produced."),
        "recording.video": item(False, "The Atlas X2 runtime records replayable steps and cannot capture WebM video."),
        "capability.visibility": item(False, "Atlas does not expose an in-app browser pane visibility control."),
        "capability.headless": item(False, "Atlas settings do not expose Browser Use headless launch selection."),
    }
    return {
        "id": _RUNTIME_ID,
        "type": "atlas-x2",
        "selected": True,
        "takeover_mode": settings.get("mode"),
        "capabilities": capabilities,
    }


def _backend_context(runtime: Any, task_id: str):
    """Resolve only the active X2 Hermes session; fail closed for other providers."""
    from atlas.tools.x2.browser import HermesBrowserBackend

    runtime.ensure_configured()
    backend = runtime.acquire_backend()
    if not isinstance(backend, HermesBrowserBackend):
        raise _Unsupported("This Browser Use operation needs Atlas's Hermes agent-browser session.")
    try:
        import tools.browser_tool as browser_tool
        from tools import browser_tool_session
    except Exception as exc:  # noqa: BLE001 - optional runtime import
        raise _Unsupported(f"Hermes browser command bridge is unavailable: {exc}") from exc
    if browser_tool._is_camofox_mode():
        raise _Unsupported("This operation is not available with the Camofox browser backend.")
    effective_id = browser_tool._last_session_key(task_id)
    return browser_tool, browser_tool_session, effective_id


class _Unsupported(RuntimeError):
    pass


def _guard(browser_tool: Any, session_id: str, *, read: bool, action: str) -> str | None:
    """Reuse Hermes's current-page SSRF/content-action guard before CLI access."""
    if read:
        return browser_tool._blocked_private_page_content(session_id)
    return browser_tool._blocked_private_page_action(session_id, action)


def _cli_call(browser_tool: Any, session_module: Any, session_id: str, command: str,
              args: list[str] | None = None, *, read: bool = False,
              action: str | None = None, timeout: int | None = None) -> dict[str, Any]:
    blocked = _guard(browser_tool, session_id, read=read, action=action or command)
    if blocked:
        try:
            return json.loads(blocked)
        except (TypeError, ValueError):
            return {"success": False, "error": blocked}
    return session_module._run_browser_command(
        session_id, command, args or [], timeout=timeout,
    )


def _redact(value: Any) -> Any:
    try:
        from tools.browser_tool_snapshot import _redact_browser_output

        return _redact_browser_output(value)
    except Exception:  # noqa: BLE001 - redaction helper is optional in embedded installs
        return value


def _x2_data(result: dict[str, Any]) -> dict[str, Any]:
    normalized = _as_result(result)
    if normalized.get("success"):
        return normalized
    return normalized


async def _x2_call(runtime: Any, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    result = await runtime.call_tool(tool_name, arguments)
    return _x2_data(result)


def _tab_args(args: dict[str, Any], task_id: str) -> tuple[list[str], str | None]:
    """Build one safe ``find`` command from a semantic locator description."""
    locator = str(args.get("locator") or args.get("by") or "").strip()
    value = str(args.get("value") or "")
    if not locator or not value:
        raise ValueError("locator and value are required")
    command_args = [locator, value]
    action = str(args.get("action") or "text").strip().lower()
    if action not in {"click", "fill", "check", "hover", "text"}:
        raise ValueError("locator action must be click, fill, check, hover, or text")
    command_args.append(action)
    if action == "fill" and args.get("text") is not None:
        command_args.append(str(args["text"]))
    if args.get("name") is not None:
        command_args.extend(["--name", str(args["name"])])
    if args.get("exact"):
        command_args.append("--exact")
    return command_args, action


async def _screenshot(browser_tool: Any, session_module: Any, session_id: str,
                      args: dict[str, Any]) -> dict[str, Any]:
    blocked = _guard(browser_tool, session_id, read=True, action="screenshot")
    if blocked:
        try:
            return _error(json.loads(blocked).get("error", "Screenshot blocked"), "policy_denied")
        except (TypeError, ValueError):
            return _error(blocked, "policy_denied")
    try:
        from hermes_constants import get_hermes_dir

        output_dir = Path(get_hermes_dir("cache/screenshots", "browser_screenshots"))
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"atlas-browser-use-{uuid.uuid4().hex}.png"
        remote_path = session_module.sandbox_screenshot_path(path)
        command_args: list[str] = []
        selector = str(args.get("selector") or "").strip()
        if selector:
            command_args.append(selector)
        if args.get("full"):
            command_args.append("--full")
        if args.get("annotate"):
            command_args.append("--annotate")
        command_args.append(str(remote_path or path))
        result = await asyncio.to_thread(
            _cli_call, browser_tool, session_module, session_id,
            "screenshot", command_args, read=True,
        )
        if not result.get("success"):
            return _error(str(result.get("error") or "Browser screenshot failed"))
        if remote_path:
            fetched = session_module.fetch_sandbox_file(
                str((result.get("data") or {}).get("path") or remote_path), path,
                max_bytes=_SCREENSHOT_MAX_BYTES,
            )
            if not fetched:
                return _error("Screenshot was created in the browser sandbox but could not be fetched.",
                              "capability_unavailable")
        if not path.is_file():
            return _error("Browser did not produce a screenshot file.", "capability_unavailable")
        size = path.stat().st_size
        if size <= 0 or size > _SCREENSHOT_MAX_BYTES:
            path.unlink(missing_ok=True)
            return _error(f"Screenshot size must be between 1 byte and {_SCREENSHOT_MAX_BYTES} bytes.",
                          "output_too_large")
        content_type = mimetypes.guess_type(path.name)[0] or "image/png"
        payload = base64.b64encode(path.read_bytes()).decode("ascii")
        return _ok({"mime_type": content_type, "data_url": f"data:{content_type};base64,{payload}",
                    "path": str(path), "size_bytes": size})
    except Exception as exc:  # noqa: BLE001 - optional backend can fail independently
        return _error(f"Browser screenshot unavailable: {exc}", "capability_unavailable")


async def _browser_use_call_impl(
    operation: str,
    arguments: dict[str, Any] | None = None,
    *,
    runtime: Any = None,
) -> dict[str, Any]:
    """Execute one ZCode Browser Use-style operation using the active Atlas X2 runtime.

    The parent kernel may expose this as one ``browser_use`` function with an
    ``operation`` string and operation-specific ``arguments`` object. Mutating
    operations should be registered as write-capable by that dispatcher.
    """
    op = str(operation or "").strip().lower()
    if op.startswith("browser."):
        op = op[len("browser."):]
    if op == "browsers.open":
        op = "tabs.open"
    if op in {"tab.domsnapshot", "tab.playwright.domsnapshot"}:
        op = "tab.snapshot"
    locator_methods = {
        "tab.getbyrole": "role", "tab.getbytext": "text", "tab.getbylabel": "label",
        "tab.getbyplaceholder": "placeholder", "tab.getbytestid": "testid",
        "tab.getbyalttext": "alt", "tab.getbytitle": "title",
    }
    if op in locator_methods:
        args_for_locator = dict(arguments or {})
        args_for_locator["locator"] = locator_methods[op]
        if locator_methods[op] == "role":
            args_for_locator["value"] = args_for_locator.get("role", args_for_locator.get("value", ""))
        else:
            args_for_locator["value"] = args_for_locator.get(
                "text", args_for_locator.get("value", ""),
            )
        arguments = args_for_locator
        op = "tab.locator"
    args = dict(arguments or {})
    rt = _runtime(runtime)
    ctx = _ctx()
    task_id = str(args.pop("task_id", None) or ctx.session_id or "default")

    if op in {"runtime.list", "browsers.list"}:
        return _ok({"runtimes": [_descriptor(rt)]})
    if op in {"runtime.get", "runtime.default", "runtime.getforurl", "browsers.get", "browsers.getdefault",
              "browsers.getforurl"}:
        requested = str(args.get("id") or args.get("type") or _RUNTIME_ID)
        if requested not in {_RUNTIME_ID, "default", "atlas-x2-hermes", "hermes"}:
            return _error(f"Browser runtime {requested!r} is not advertised by Atlas.", "runtime_unavailable")
        return _ok(_descriptor(rt))
    if op in {"runtime.select", "browsers.select"}:
        requested = str(args.get("id") or args.get("type") or _RUNTIME_ID)
        if requested not in {_RUNTIME_ID, "default", "atlas-x2-hermes", "hermes"}:
            return _error(f"Browser runtime {requested!r} is not advertised by Atlas.", "runtime_unavailable")
        return _ok({"selected": _RUNTIME_ID, "persistent_selection": False,
                    "note": "Atlas currently exposes one X2 runtime; no provider switch was made."})
    if op in {"capability.get", "capabilities.get"}:
        capability = str(args.get("name") or args.get("capability") or "")
        matrix = _descriptor(rt)["capabilities"]
        key = "capability.visibility" if capability == "visibility" else f"capability.{capability}"
        item = matrix.get(key)
        if item is None:
            return _error(f"Unknown browser capability {capability!r}.", "capability_unknown")
        return _ok({"name": capability, **item}) if item["supported"] else _error(
            item["reason"], "capability_unsupported", name=capability, supported=False,
        )
    if op in {"capability.list", "capabilities.list"}:
        return _ok({"capabilities": _descriptor(rt)["capabilities"]})
    if op in {"capability.set", "capabilities.set", "capability.visibility.set", "capability.headless.set"}:
        name = str(args.get("name") or args.get("capability") or op.removesuffix(".set").split(".")[-1])
        detail = (_descriptor(rt)["capabilities"].get(f"capability.{name}") or {}).get("reason")
        return _error(detail or "Atlas does not expose this browser capability control.",
                      "capability_unsupported", name=name, supported=False)
    if op in {"user.opentabs", "user.open_tabs", "user.open-tabs", "opentabs"}:
        return _error("Atlas has no desktop IAB host registry; controlled X2 tabs cannot be reported as user tabs.",
                      "capability_unsupported", user_tabs=[])
    if op in {"user.claimtab", "user.claim_tab", "user.claim-tab", "claimtab"}:
        return _error("Atlas cannot claim a host-owned desktop tab or verify its UI scope.",
                      "capability_unsupported")
    if op in {"tabs.finalize", "tabs.finalise"}:
        return _error("Atlas has no browser-pane handoff/deliverable registry; no tab was closed.",
                      "capability_unsupported")
    if op in {"tab.markdeliverable", "tab.mark_deliverable", "markdeliverable"}:
        return _error("Atlas has no browser-pane deliverable owner.", "capability_unsupported")

    # Atlas's existing X2 surface owns operations which already have safety,
    # receipt, recording, and panel-sync behavior.
    if op in {"tab.goto", "tab.back", "tab.snapshot", "tab.evaluate", "tab.markhandoff",
              "tab.mark_handoff", "tab.cua.keypress", "tab.dom_cua.click",
              "tab.dom_cua.keypress", "tab.dom_cua.type", "recording.start",
              "recording.status", "recording.cancel"}:
        tab_id = str(args.get("tab_id") or args.get("id") or "")
        if tab_id:
            focused = await _focus_tab(rt, task_id, tab_id)
            if not focused["success"]:
                return focused
        if op == "tab.goto":
            url = str(args.get("url") or "")
            if not url:
                return _error("tab.goto requires url", "invalid_arguments")
            navigated = await _x2_call(rt, "browser_navigate", {"url": url, "task_id": task_id})
            if not navigated.get("success"):
                return navigated
            waited = await browser_use_call(
                "tab.waitForLoadState", {"state": "domcontentloaded", "task_id": task_id}, runtime=rt,
            )
            if not waited.get("success"):
                return waited
            return {**navigated, "load_state_waited": "domcontentloaded"}
        if op == "tab.back":
            return await _x2_call(rt, "browser_back", {"task_id": task_id})
        if op == "tab.snapshot":
            return await _x2_call(rt, "browser_snapshot", {"full": bool(args.get("full")), "task_id": task_id})
        if op == "tab.evaluate":
            expression = str(args.get("expression") or "")
            if not expression:
                return _error("tab.evaluate requires expression", "invalid_arguments")
            return await _x2_call(rt, "browser_console", {"expression": expression, "task_id": task_id})
        if op in {"tab.markhandoff", "tab.mark_handoff"}:
            return await _x2_call(rt, "browser_handoff", {
                "reason": str(args.get("reason") or "Browser Use requested a human handoff"),
                "url": str(args.get("url") or ""),
            })
        if op == "tab.cua.keypress" or op == "tab.dom_cua.keypress":
            keys = args.get("keys", args.get("key", ""))
            key = "+".join(str(v) for v in keys) if isinstance(keys, list) else str(keys)
            return await _x2_call(rt, "browser_press", {"key": key, "task_id": task_id})
        if op == "tab.dom_cua.click":
            ref = str(args.get("node_id") or args.get("ref") or "")
            return await _x2_call(rt, "browser_click", {"ref": ref, "task_id": task_id})
        if op == "tab.dom_cua.type":
            ref = str(args.get("node_id") or args.get("ref") or "")
            return await _x2_call(rt, "browser_type", {
                "ref": ref, "text": str(args.get("text") or ""), "task_id": task_id,
            })
        if op == "recording.start":
            doc = rt.start_recording()
            return _ok({"recording_id": doc.get("recording_id"), "status": doc.get("status"),
                        "step_count": len(doc.get("steps") or []), "format": "atlas-steps"})
        if op == "recording.status":
            recorder = getattr(rt, "recorder", None)
            doc = recorder.doc if recorder is not None else None
            return _ok({"active": bool(recorder and recorder.active),
                        "recording": ({"recording_id": doc.get("recording_id"),
                                       "status": doc.get("status"),
                                       "step_count": len(doc.get("steps") or [])}
                                      if doc else None),
                        "format": "atlas-steps",
                        "video_supported": False,
                        "reason": "Atlas recording stores replayable steps; it does not capture WebM video."})
        doc = rt.stop_recording()
        if doc is None:
            return _error("There is no active Atlas browser recording.", "recording_not_active")
        doc["status"] = "cancelled"
        rt.recordings.save(doc)
        return _ok({"recording_id": doc.get("recording_id"), "status": "cancelled",
                    "step_count": len(doc.get("steps") or []), "format": "atlas-steps"})

    if op in {"tabs.list", "tabs.get", "tabs.new", "tabs.open", "tab.url", "tab.title",
              "tab.forward", "tab.reload", "tab.close", "tab.locator", "tab.frames", "tab.frame",
              "tab.waitforurl", "tab.wait_for_url", "tab.waitforloadstate", "tab.wait_for_load_state",
              "tab.waitfortimeout", "tab.wait_for_timeout", "tab.waitforfunction", "tab.wait_for_function",
              "tab.cua.click", "tab.cua.double_click", "tab.cua.move", "tab.cua.scroll", "tab.cua.drag",
              "tab.cua.type", "tab.dom_cua.double_click", "tab.dom_cua.scroll", "tab.screenshot",
              "tab.viewportsize", "tab.viewport_size", "tab.setviewportsize", "tab.set_viewport_size",
              "tab.getjsdialog", "tab.get_js_dialog", "tab.respondjsdialog", "tab.respond_js_dialog"}:
        try:
            browser_tool, session_module, session_id = _backend_context(rt, task_id)
        except _Unsupported as exc:
            return _error(str(exc), "capability_unsupported")
        except Exception as exc:  # noqa: BLE001
            return _error(f"Atlas X2 browser runtime is unavailable: {exc}", "backend_unavailable")

        tab_id = str(args.get("tab_id") or args.get("id") or "").strip()
        if op in {"tabs.list", "tabs.get", "tabs.new", "tabs.open"}:
            if op == "tabs.new":
                label = str(args.get("label") or "").strip()
                command_args = ["new"]
                if label:
                    command_args.extend(["--label", label])
                result = await asyncio.to_thread(_cli_call, browser_tool, session_module, session_id,
                                                 "tab", command_args, action="open a browser tab")
                if not result.get("success"):
                    return _error(str(result.get("error") or "Could not create browser tab"))
                if args.get("url"):
                    nav = await _x2_call(rt, "browser_navigate", {"url": str(args["url"]), "task_id": task_id})
                    if not nav.get("success"):
                        return nav
                    waited = await browser_use_call(
                        "tab.waitForLoadState", {"state": "domcontentloaded", "task_id": task_id}, runtime=rt,
                    )
                    if not waited.get("success"):
                        return waited
                    return {**nav, "load_state_waited": "domcontentloaded"}
                return _ok(result.get("data") if isinstance(result.get("data"), dict) else {"tab": result.get("data")})
            if op == "tabs.open":
                url = str(args.get("url") or "")
                if not url:
                    return _error("tabs.open requires url", "invalid_arguments")
                if args.get("reuse_tab", True):
                    tabs_result = await asyncio.to_thread(_cli_call, browser_tool, session_module, session_id,
                                                          "tab", ["list"], read=True)
                    tabs = _tab_items(tabs_result)
                    host = _url_host(url)
                    same_site = next((tab for tab in tabs if host and _url_host(str(tab.get("url") or "")) == host), None)
                    if same_site:
                        focused = await _focus_tab(rt, task_id, str(same_site.get("id") or same_site.get("targetId") or ""))
                        if not focused["success"]:
                            return focused
                        return await _x2_call(rt, "browser_navigate", {"url": url, "task_id": task_id})
                created = await browser_use_call("tabs.new", {"url": "", "task_id": task_id}, runtime=rt)
                if not created.get("success"):
                    return created
                return await _x2_call(rt, "browser_navigate", {"url": url, "task_id": task_id})
            result = await asyncio.to_thread(_cli_call, browser_tool, session_module, session_id,
                                             "tab", ["list"], read=True)
            if not result.get("success"):
                return _error(str(result.get("error") or "Could not list browser tabs"))
            tabs = _tab_items(result)
            if op == "tabs.get":
                requested = tab_id
                if not requested:
                    return _error("tabs.get requires id", "invalid_arguments")
                match = next((tab for tab in tabs if requested in {
                    str(tab.get("id") or ""), str(tab.get("targetId") or ""), str(tab.get("target_id") or "")
                }), None)
                if match is None:
                    return _error(f"Controlled tab {requested!r} was not found.", "tab_not_found")
                focused = await _focus_tab(rt, task_id, requested)
                return _ok(match) if focused["success"] else focused
            return _ok({"tabs": tabs, "scope": "atlas-controlled-session", "user_tabs_included": False})

        if op in {"tab.screenshot"}:
            return await _screenshot(browser_tool, session_module, session_id, args)

        # A target id is accepted by agent-browser. Keep every operation bound to
        # the selected Atlas session and explicitly focus only a supplied id.
        if tab_id and op not in {"tab.close", "tab.getjsdialog", "tab.get_js_dialog",
                                 "tab.respondjsdialog", "tab.respond_js_dialog"}:
            focused = await _focus_tab(rt, task_id, tab_id)
            if not focused["success"]:
                return focused

        if op in {"tab.url", "tab.title"}:
            prop = "url" if op == "tab.url" else "title"
            result = await asyncio.to_thread(_cli_call, browser_tool, session_module, session_id,
                                             "get", [prop], read=True)
            if not result.get("success"):
                return _error(str(result.get("error") or f"Could not read tab {prop}"))
            data = result.get("data")
            value = data.get("result", data.get(prop, "")) if isinstance(data, dict) else data
            return _ok({prop: _redact(value)})
        if op in {"tab.forward", "tab.reload", "tab.close"}:
            command = {"tab.forward": "forward", "tab.reload": "reload", "tab.close": "tab"}[op]
            command_args = ["close", tab_id] if op == "tab.close" and tab_id else (["close"] if op == "tab.close" else [])
            result = await asyncio.to_thread(_cli_call, browser_tool, session_module, session_id,
                                             command, command_args, action=op.removeprefix("tab."))
            if not result.get("success"):
                return _error(str(result.get("error") or f"{op} failed"))
            return _ok(result.get("data") if isinstance(result.get("data"), dict) else {"result": result.get("data")})
        if op == "tab.locator":
            try:
                command_args, locator_action = _tab_args(args, task_id)
            except ValueError as exc:
                return _error(str(exc), "invalid_arguments")
            result = await asyncio.to_thread(_cli_call, browser_tool, session_module, session_id,
                                             "find", command_args, read=locator_action == "text",
                                             action=locator_action)
            if not result.get("success"):
                return _error(str(result.get("error") or "Locator operation failed"))
            return _ok(_redact(result.get("data")))
        if op == "tab.frames":
            try:
                from tools.browser_supervisor import SUPERVISOR_REGISTRY

                supervisor = SUPERVISOR_REGISTRY.get(session_id)
                snapshot = supervisor.snapshot() if supervisor is not None else None
                if snapshot is not None and snapshot.active:
                    return _ok({"frames": _redact(snapshot.to_dict().get("frame_tree") or {}),
                                "source": "cdp-supervisor"})
            except Exception:
                pass
            expr = "JSON.stringify(Array.from(document.querySelectorAll('iframe,frame')).map((f,i)=>({index:i,name:f.name||'',id:f.id||'',src:f.src||'',title:f.title||''})))"
            result = await _x2_call(rt, "browser_console", {"expression": expr, "task_id": task_id})
            if not result["success"]:
                return result
            raw = result.get("result") or result.get("data") or "[]"
            try:
                frames = json.loads(raw) if isinstance(raw, str) else raw
            except (TypeError, ValueError):
                frames = []
            return _ok({"frames": _redact(frames), "source": "same-page-frame-elements",
                        "limitation": "This fallback does not expose cross-process CDP frame routing."})
        if op == "tab.frame":
            selector = str(args.get("selector") or "main").strip()
            result = await asyncio.to_thread(_cli_call, browser_tool, session_module, session_id,
                                             "frame", [selector], action="switch browser frame")
            if not result.get("success"):
                return _error(str(result.get("error") or "Could not switch frame"))
            return _ok(result.get("data") if isinstance(result.get("data"), dict) else {"frame": selector})
        if op in {"tab.waitforurl", "tab.wait_for_url"}:
            pattern = str(args.get("url") or args.get("pattern") or "")
            if not pattern:
                return _error("waitForURL requires url or pattern", "invalid_arguments")
            result = await asyncio.to_thread(_cli_call, browser_tool, session_module, session_id,
                                             "wait", ["--url", pattern], read=True, timeout=4)
            return _ok(result.get("data") or {"url_pattern": pattern}) if result.get("success") else _error(
                str(result.get("error") or "URL wait failed"), "wait_failed")
        if op in {"tab.waitforloadstate", "tab.wait_for_load_state"}:
            state = str(args.get("state") or "domcontentloaded").lower()
            if state not in {"load", "domcontentloaded", "networkidle"}:
                return _error("state must be load, domcontentloaded, or networkidle", "invalid_arguments")
            result = await asyncio.to_thread(_cli_call, browser_tool, session_module, session_id,
                                             "wait", ["--load", state], read=True, timeout=4)
            return _ok(result.get("data") or {"state": state}) if result.get("success") else _error(
                str(result.get("error") or "Load-state wait failed"), "wait_failed")
        if op in {"tab.waitfortimeout", "tab.wait_for_timeout"}:
            try:
                milliseconds = int(args.get("timeout_ms", args.get("milliseconds", 0)))
            except (TypeError, ValueError):
                return _error("timeout_ms must be an integer", "invalid_arguments")
            if milliseconds < 0 or milliseconds > _WAIT_CAP_MS:
                return _error(f"timeout_ms must be between 0 and {_WAIT_CAP_MS}", "invalid_arguments")
            result = await asyncio.to_thread(_cli_call, browser_tool, session_module, session_id,
                                             "wait", [str(milliseconds)], read=True,
                                             timeout=max(4, milliseconds // 1000 + 3))
            return _ok({"waited_ms": milliseconds}) if result.get("success") else _error(
                str(result.get("error") or "Timeout wait failed"), "wait_failed")
        if op in {"tab.waitforfunction", "tab.wait_for_function"}:
            expression = str(args.get("expression") or "")
            if not expression:
                return _error("waitForFunction requires expression", "invalid_arguments")
            try:
                import tools.browser_tool_eval_policy as eval_policy

                policy_error = eval_policy._enforce_browser_eval_policy(expression)
                if policy_error:
                    return _error(policy_error, "policy_denied")
            except Exception as exc:  # noqa: BLE001
                return _error(f"Browser evaluation policy unavailable: {exc}", "policy_unavailable")
            result = await asyncio.to_thread(_cli_call, browser_tool, session_module, session_id,
                                             "wait", ["--fn", expression], read=True, timeout=4)
            return _ok({"matched": True}) if result.get("success") else _error(
                str(result.get("error") or "Function wait failed"), "wait_failed")
        if op in {"tab.viewportsize", "tab.viewport_size"}:
            result = await _x2_call(rt, "browser_console", {
                "expression": "JSON.stringify({width:window.innerWidth,height:window.innerHeight})",
                "task_id": task_id,
            })
            if not result["success"]:
                return result
            value = result.get("result") or result.get("data") or "{}"
            try:
                viewport = json.loads(value) if isinstance(value, str) else value
            except (TypeError, ValueError):
                viewport = {}
            return _ok({"viewport": viewport})
        if op in {"tab.setviewportsize", "tab.set_viewport_size"}:
            try:
                width, height = int(args.get("width")), int(args.get("height"))
            except (TypeError, ValueError):
                return _error("width and height must be integers", "invalid_arguments")
            if not (_VIEWPORT_MIN <= width <= _VIEWPORT_MAX_WIDTH
                    and _VIEWPORT_MIN <= height <= _VIEWPORT_MAX_HEIGHT):
                return _error("viewport must be width 320–3840 and height 320–2160", "invalid_arguments")
            result = await asyncio.to_thread(_cli_call, browser_tool, session_module, session_id,
                                             "set", ["viewport", str(width), str(height)],
                                             action="resize browser viewport")
            return _ok({"width": width, "height": height}) if result.get("success") else _error(
                str(result.get("error") or "Could not resize viewport"))
        if op in {"tab.getjsdialog", "tab.get_js_dialog", "tab.respondjsdialog", "tab.respond_js_dialog"}:
            try:
                from tools.browser_supervisor import SUPERVISOR_REGISTRY

                supervisor = SUPERVISOR_REGISTRY.get(session_id)
            except Exception:
                supervisor = None
            if supervisor is None or not supervisor.snapshot().active:
                return _error("No active CDP dialog supervisor is available for this session.",
                              "capability_unsupported")
            if op in {"tab.getjsdialog", "tab.get_js_dialog"}:
                dialogs = [dialog.to_dict() for dialog in supervisor.snapshot().pending_dialogs]
                return _ok({"dialog": _redact(dialogs[0]) if dialogs else None, "pending": len(dialogs)})
            action = str(args.get("action") or "").lower()
            if action not in {"accept", "dismiss"}:
                return _error("action must be accept or dismiss", "invalid_arguments")
            response = supervisor.respond_to_dialog(
                action, prompt_text=str(args.get("prompt_text") or ""),
                dialog_id=str(args.get("dialog_id") or "") or None,
            )
            return _ok(_redact(response)) if response.get("ok") else _error(
                str(response.get("error") or "Dialog response failed"), "dialog_response_failed")

        # Remaining low-level operations share the session-specific command bridge.
        if op == "tab.cua.move":
            x, y = _xy(args)
            result = await asyncio.to_thread(_cli_call, browser_tool, session_module, session_id,
                                             "mouse", ["move", str(x), str(y)],
                                             action="move browser pointer")
        elif op in {"tab.cua.click", "tab.cua.double_click"}:
            x, y = _xy(args)
            result = await asyncio.to_thread(_coordinate_click, browser_tool, session_module,
                                             session_id, x, y,
                                             double=op.endswith("double_click"))
        elif op == "tab.cua.scroll":
            x, y = _xy(args, allow_missing=True)
            scroll_x, scroll_y = int(args.get("scroll_x", args.get("delta_x", 0))), int(
                args.get("scroll_y", args.get("delta_y", 0)))
            if x is not None and y is not None:
                moved = await asyncio.to_thread(_cli_call, browser_tool, session_module, session_id,
                                                "mouse", ["move", str(x), str(y)], action="position browser pointer")
                if not moved.get("success"):
                    return _error(str(moved.get("error") or "Could not position pointer"))
            result = await asyncio.to_thread(_cli_call, browser_tool, session_module, session_id,
                                             "mouse", ["wheel", str(scroll_y), str(scroll_x)],
                                             action="scroll browser viewport")
        elif op == "tab.cua.drag":
            path = args.get("path")
            if not isinstance(path, list) or len(path) < 2 or len(path) > 64:
                return _error("drag path must contain 2–64 viewport points", "invalid_arguments")
            if args.get("keys"):
                return _error("Modifier-key drag is unsupported by the installed Atlas browser command API.",
                              "capability_unsupported")
            result = await asyncio.to_thread(_coordinate_drag, browser_tool, session_module, session_id, path)
        elif op == "tab.cua.type":
            text = str(args.get("text") or "")
            result = await asyncio.to_thread(_cli_call, browser_tool, session_module, session_id,
                                             "keyboard", ["type", text], action="type into browser page")
        elif op == "tab.dom_cua.double_click":
            ref = str(args.get("node_id") or args.get("ref") or "")
            if not ref:
                return _error("node_id is required", "invalid_arguments")
            result = await asyncio.to_thread(_cli_call, browser_tool, session_module, session_id,
                                             "dblclick", [ref if ref.startswith("@") else f"@{ref}"],
                                             action="double click browser element")
        elif op == "tab.dom_cua.scroll":
            ref = str(args.get("node_id") or args.get("ref") or "").strip()
            delta = int(args.get("y", args.get("delta_y", 500)))
            if ref:
                visible = await asyncio.to_thread(_cli_call, browser_tool, session_module, session_id,
                                                  "scrollintoview", [ref if ref.startswith("@") else f"@{ref}"],
                                                  action="scroll browser element into view")
                if not visible.get("success"):
                    return _error(str(visible.get("error") or "Could not reveal scroll target"))
            direction = "down" if delta >= 0 else "up"
            result = await asyncio.to_thread(_cli_call, browser_tool, session_module, session_id,
                                             "scroll", [direction, str(max(1, abs(delta)))],
                                             action="scroll browser page")
        else:  # tab operation aliases
            return _error(f"Unsupported Browser Use operation {op!r}.", "capability_unsupported")

        if not result.get("success"):
            return _error(str(result.get("error") or f"{op} failed"))
        return _ok(_redact(result.get("data")) if isinstance(result.get("data"), dict)
                   else {"result": _redact(result.get("data"))})
async def browser_use_call(
    operation: str,
    arguments: dict[str, Any] | None = None,
    *,
    runtime: Any = None,
) -> dict[str, Any]:
    """Structured public boundary for one Browser Use-compatible operation."""
    try:
        return await _browser_use_call_impl(operation, arguments, runtime=runtime)
    except _Unsupported as exc:
        return _error(str(exc), "capability_unsupported")
    except (TypeError, ValueError) as exc:
        return _error(str(exc), "invalid_arguments")
    except Exception as exc:  # noqa: BLE001 - optional browser backends fail independently
        log.exception("browser_use_compat operation failed", extra={"operation": operation})
        return _error(f"Browser Use operation failed: {exc}", "browser_use_error")


async def _focus_tab(runtime: Any, task_id: str, tab_id: str) -> dict[str, Any]:
    try:
        browser_tool, session_module, session_id = _backend_context(runtime, task_id)
        result = await asyncio.to_thread(_cli_call, browser_tool, session_module, session_id,
                                         "tab", [tab_id], action="focus browser tab")
        if not result.get("success"):
            return _error(str(result.get("error") or f"Could not focus tab {tab_id!r}"), "tab_not_found")
        return _ok(result.get("data") if isinstance(result.get("data"), dict) else {"tab_id": tab_id})
    except _Unsupported as exc:
        return _error(str(exc), "capability_unsupported")
    except Exception as exc:  # noqa: BLE001
        return _error(f"Could not focus browser tab: {exc}", "backend_unavailable")


def _tab_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    data = result.get("data")
    if isinstance(data, dict):
        entries = data.get("tabs") or data.get("items") or []
    elif isinstance(data, list):
        entries = data
    else:
        entries = []
    return [_redact(item) for item in entries if isinstance(item, dict)]


def _url_host(url: str) -> str:
    from urllib.parse import urlsplit

    try:
        return (urlsplit(url).hostname or "").casefold()
    except ValueError:
        return ""


def _xy(args: dict[str, Any], *, allow_missing: bool = False) -> tuple[int | None, int | None]:
    if allow_missing and args.get("x") is None and args.get("y") is None:
        return None, None
    try:
        x, y = int(args.get("x")), int(args.get("y"))
    except (TypeError, ValueError) as exc:
        raise ValueError("x and y must be integer CSS viewport coordinates") from exc
    if x < 0 or y < 0:
        raise ValueError("x and y must be non-negative CSS viewport coordinates")
    return x, y


def _coordinate_click(browser_tool: Any, session_module: Any, session_id: str,
                      x: int, y: int, *, double: bool = False) -> dict[str, Any]:
    for command, argv in (("mouse", ["move", str(x), str(y)]),
                          ("mouse", ["down", "left"]), ("mouse", ["up", "left"])):
        result = _cli_call(browser_tool, session_module, session_id, command, argv,
                           action="click browser viewport coordinates")
        if not result.get("success"):
            return result
    if double:
        time.sleep(0.05)
        for command, argv in (("mouse", ["down", "left"]), ("mouse", ["up", "left"])):
            result = _cli_call(browser_tool, session_module, session_id, command, argv,
                               action="double-click browser viewport coordinates")
            if not result.get("success"):
                return result
    return {"success": True, "data": {"x": x, "y": y, "double": double}}


def _coordinate_drag(browser_tool: Any, session_module: Any, session_id: str,
                     path: list[Any]) -> dict[str, Any]:
    points: list[tuple[int, int]] = []
    for point in path:
        if isinstance(point, dict):
            x, y = _xy(point)
        elif isinstance(point, (list, tuple)) and len(point) == 2:
            x, y = _xy({"x": point[0], "y": point[1]})
        else:
            raise ValueError("each drag point must be {x,y} or [x,y]")
        points.append((int(x), int(y)))
    first = points[0]
    result = _cli_call(browser_tool, session_module, session_id, "mouse",
                       ["move", str(first[0]), str(first[1])], action="start browser drag")
    if not result.get("success"):
        return result
    result = _cli_call(browser_tool, session_module, session_id, "mouse", ["down", "left"],
                       action="start browser drag")
    if not result.get("success"):
        return result
    for x, y in points[1:]:
        result = _cli_call(browser_tool, session_module, session_id, "mouse",
                           ["move", str(x), str(y)], action="drag browser pointer")
        if not result.get("success"):
            _cli_call(browser_tool, session_module, session_id, "mouse", ["up", "left"],
                      action="release browser pointer")
            return result
    return _cli_call(browser_tool, session_module, session_id, "mouse", ["up", "left"],
                     action="finish browser drag")


__all__ = ["browser_use_call"]

"""Tests for the X2 computer bridge (Hermes computer_use runtime, fake-injected).

No real UI automation happens here: the Hermes backend seam is injected with a
fake (:class:`FakeBackend` subclassing Hermes' ``ComputerUseBackend``) and the
legacy Windows runtime with :class:`FakeLegacy`.  Auxiliary-vision routing is
pinned per test so nothing ever reaches a network.
"""
from __future__ import annotations

import base64
import json
from contextlib import asynccontextmanager
from io import BytesIO
from typing import Any, AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from PIL import Image

from tools.computer_use import tool as hermes_tool
from tools.computer_use.backend import ActionResult, CaptureResult, ComputerUseBackend

from atlas.tools.x2 import computer as x2computer
from atlas.tools.x2.context import (
    EVENT_COMPUTER_STEP,
    EVENT_FOREGROUND_REQUIRED,
    EVENT_FOREGROUND_RESUMED,
    X2Context,
    reset_context,
    set_context,
)

# A real 64x48 PNG so the Hermes capture pipeline can decode dimensions.
_PNG = BytesIO()
Image.new("RGB", (64, 48), (16, 32, 64)).save(_PNG, format="PNG")
PNG_B64 = base64.b64encode(_PNG.getvalue()).decode("ascii")


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class FakeBackend(ComputerUseBackend):
    """Records every call; scripted results per method (popped in order)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.captures: list[CaptureResult] = []
        self.click_results: list[ActionResult] = []
        self.windows: list[dict[str, Any]] = []

    def _record(self, name: str, kwargs: dict[str, Any]) -> None:
        self.calls.append((name, kwargs))

    def _pop(self, bucket: list[Any], default: Any) -> Any:
        return bucket.pop(0) if bucket else default

    def start(self) -> None:
        self._record("start", {})

    def stop(self) -> None:
        self._record("stop", {})

    def is_available(self) -> bool:
        return True

    def capture(self, mode: str = "som", app: str | None = None, pid: int | None = None,
                window_id: int | None = None) -> CaptureResult:
        self._record("capture", {"mode": mode, "app": app, "pid": pid, "window_id": window_id})
        return self._pop(self.captures, CaptureResult(
            mode=mode, width=64, height=48, png_b64=PNG_B64,
            elements=[], app=app or "", window_title="记事本"))

    def click(self, *, element: int | None = None, x: int | None = None, y: int | None = None,
              button: str = "left", click_count: int = 1, modifiers: Any = None,
              delivery_mode: str | None = None, bring_to_front: bool = False) -> ActionResult:
        self._record("click", {"element": element, "x": x, "y": y, "button": button,
                               "delivery_mode": delivery_mode})
        return self._pop(self.click_results, ActionResult(ok=True, action="click", effect="confirmed"))

    def drag(self, **kwargs: Any) -> ActionResult:
        self._record("drag", kwargs)
        return ActionResult(ok=True, action="drag", effect="confirmed")

    def scroll(self, *, direction: str, amount: int = 3, **kwargs: Any) -> ActionResult:
        self._record("scroll", {"direction": direction, "amount": amount, **kwargs})
        return ActionResult(ok=True, action="scroll", effect="confirmed")

    def type_text(self, text: str, **kwargs: Any) -> ActionResult:
        self._record("type_text", {"text": text, **kwargs})
        return ActionResult(ok=True, action="type", effect="confirmed")

    def key(self, keys: str, **kwargs: Any) -> ActionResult:
        self._record("key", {"keys": keys, **kwargs})
        return ActionResult(ok=True, action="key", effect="confirmed")

    def list_apps(self) -> list[dict[str, Any]]:
        self._record("list_apps", {})
        return []

    def list_windows(self) -> list[dict[str, Any]]:
        self._record("list_windows", {})
        return list(self.windows)

    def focus_app(self, app: str, raise_window: bool = False) -> ActionResult:
        self._record("focus_app", {"app": app, "raise_window": raise_window})
        return ActionResult(ok=True, action="focus_app", effect="confirmed")

    def set_value(self, value: str, element: int | None = None) -> ActionResult:
        self._record("set_value", {"value": value, "element": element})
        return ActionResult(ok=True, action="set_value", effect="confirmed")


class FakeLegacy:
    """Stands in for the legacy Windows ComputerUseRuntime."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append((name, dict(arguments or {})))
        return {"data": {"legacy": True, "tool": name}, "content": [], "is_error": False}


def make_context(events: list[tuple[str, dict[str, Any]]], choices: list[str]) -> X2Context:
    """X2Context with a recording emit and a scripted wait_input."""

    async def emit(event: str, data: dict[str, Any]) -> None:
        events.append((event, data))

    async def wait_input(prompt: str, options: list[str]) -> str:
        return choices.pop(0) if choices else "deny"

    return X2Context(run_id="run-1", session_id=None, emit=emit, wait_input=wait_input)


@asynccontextmanager
async def installed_ctx(
    events: list[tuple[str, dict[str, Any]]], choices: list[str],
) -> AsyncIterator[X2Context]:
    """Install the recording context inside the running task (contextvar tokens are
    only valid in their creating context, so this must wrap the awaited calls)."""
    ctx = make_context(events, choices)
    token = set_context(ctx)
    try:
        yield ctx
    finally:
        reset_context(token)


@pytest.fixture(autouse=True)
def fresh_runtime():
    x2computer.set_runtime(None)
    yield
    x2computer.set_runtime(None)


@pytest.fixture(autouse=True)
def hermetic_vision_routing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default: main model is vision-capable (no aux call). Vision tests override."""
    monkeypatch.setattr(hermes_tool, "_should_route_through_aux_vision", lambda: False, raising=False)
    monkeypatch.setattr(
        hermes_tool, "_route_capture_through_aux_vision", lambda *a, **k: None, raising=False)


# ---------------------------------------------------------------------------
# Alias translation
# ---------------------------------------------------------------------------
def test_alias_translation_maps_legacy_names_onto_hermes_actions() -> None:
    assert x2computer.translate_legacy_tool(
        "computer_observe", {"target": "desktop"}) == ("capture", {"mode": "som", "app": "desktop"})
    assert x2computer.translate_legacy_tool(
        "computer_observe", {"target": "window", "window_id": 7, "pid": 9}) == (
        "capture", {"mode": "som", "window_id": 7, "pid": 9})
    assert x2computer.translate_legacy_tool(
        "computer_mouse", {"action": "click", "x": 10, "y": 20, "button": "right"}) == (
        "click", {"coordinate": [10, 20], "button": "right"})
    assert x2computer.translate_legacy_tool(
        "computer_mouse", {"action": "double_click", "x": 1, "y": 2})[0] == "double_click"
    assert x2computer.translate_legacy_tool(
        "computer_mouse", {"action": "scroll", "amount": -3}) == ("scroll", {"direction": "down", "amount": 3})
    assert x2computer.translate_legacy_tool(
        "computer_keyboard", {"action": "hotkey", "keys": ["CTRL", "S"]}) == ("key", {"keys": "ctrl+s"})
    assert x2computer.translate_legacy_tool(
        "computer_keyboard", {"action": "type", "text": "你好", "element_index": 4}) == (
        "set_value", {"value": "你好", "element": 5})
    # Legacy-only actions fall through to the Windows runtime.
    assert x2computer.translate_legacy_tool("computer_clipboard", {"action": "read"}) is None
    assert x2computer.translate_legacy_tool("computer_mouse", {"action": "move", "x": 1, "y": 2}) is None
    assert x2computer.translate_legacy_tool(
        "computer_window", {"action": "move", "window_id": 3, "x": 0, "y": 0}) is None


def test_register_computer_tools_maps_all_legacy_names_to_one_handler() -> None:
    registered: list[tuple[dict[str, Any], Any]] = []
    names = x2computer.register_computer_tools(
        lambda schema, handler: registered.append((schema, handler)))
    assert names == ["computer_observe", "computer_window", "computer_mouse",
                     "computer_keyboard", "computer_clipboard"]
    schema_names = {schema["function"]["name"] for schema, _ in registered}
    assert schema_names == set(names)
    # All five legacy aliases share ONE handler -> the model never sees duplicates.
    assert len({id(handler) for _, handler in registered}) == 1


# ---------------------------------------------------------------------------
# Hermes-dispatched actions
# ---------------------------------------------------------------------------
async def test_background_mouse_click_succeeds_and_emits_step() -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    backend = FakeBackend()
    runtime = x2computer.X2ComputerRuntime(backend=backend, legacy=FakeLegacy())
    async with installed_ctx(events, ["allow"]):
        result = await runtime.call_tool("computer_mouse", {"action": "click", "x": 12, "y": 34})

    assert result["is_error"] is False
    assert result["data"]["verdict"]["decision"] == "done"
    assert ("click", {"element": None, "x": 12, "y": 34, "button": "left",
                      "delivery_mode": None}) in backend.calls
    steps = [e for e in events if e[0] == EVENT_COMPUTER_STEP]
    assert len(steps) == 1
    assert steps[0][1]["tool"] == "computer_mouse" and steps[0][1]["ok"] is True
    # Background-first: no foreground card was shown.
    assert all(e[0] != EVENT_FOREGROUND_REQUIRED for e in events)


async def test_foreground_escalation_approve_retries_in_foreground() -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    backend = FakeBackend()
    backend.click_results = [
        ActionResult(ok=True, action="click", effect="suspected_noop",
                     escalation={"recommended": "foreground", "reason": "no UIA path"}),
        ActionResult(ok=True, action="click", effect="confirmed"),
    ]
    runtime = x2computer.X2ComputerRuntime(backend=backend, legacy=FakeLegacy())
    async with installed_ctx(events, ["allow"]):
        result = await runtime.call_tool("computer_mouse", {"action": "click", "x": 5, "y": 6})

    assert result["is_error"] is False
    assert result["data"]["effect"] == "confirmed"
    clicks = [call for call in backend.calls if call[0] == "click"]
    assert len(clicks) == 2
    assert clicks[0][1]["delivery_mode"] is None  # background-first attempt
    assert clicks[1][1]["delivery_mode"] == "foreground"  # approved retry
    kinds = [event for event, _ in events]
    assert EVENT_FOREGROUND_REQUIRED in kinds
    assert EVENT_FOREGROUND_RESUMED in kinds
    assert sum(1 for e in events if e[0] == EVENT_COMPUTER_STEP) == 1


async def test_foreground_escalation_deny_cancels_without_retry() -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    backend = FakeBackend()
    backend.click_results = [
        ActionResult(ok=True, action="click", effect="suspected_noop",
                     escalation={"recommended": "foreground"}),
    ]
    runtime = x2computer.X2ComputerRuntime(backend=backend, legacy=FakeLegacy())
    async with installed_ctx(events, ["deny"]):
        result = await runtime.call_tool("computer_mouse", {"action": "click", "x": 5, "y": 6})

    assert result["is_error"] is True
    assert "拒绝" in result["data"]["error"]
    assert len([call for call in backend.calls if call[0] == "click"]) == 1
    kinds = [event for event, _ in events]
    assert EVENT_FOREGROUND_REQUIRED in kinds
    assert EVENT_FOREGROUND_RESUMED not in kinds  # denied -> no resume event


async def test_hard_background_unavailable_code_also_escalates() -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    backend = FakeBackend()
    backend.click_results = [
        ActionResult(ok=False, action="click", code="background_unavailable", effect="suspected_noop"),
        ActionResult(ok=True, action="click", effect="confirmed"),
    ]
    runtime = x2computer.X2ComputerRuntime(backend=backend, legacy=FakeLegacy())
    async with installed_ctx(events, ["allow"]):
        result = await runtime.call_tool("computer_mouse", {"action": "click", "x": 3, "y": 4})

    assert result["is_error"] is False
    assert result["data"]["effect"] == "confirmed"
    clicks = [call for call in backend.calls if call[0] == "click"]
    assert clicks[1][1]["delivery_mode"] == "foreground"
    assert EVENT_FOREGROUND_RESUMED in [event for event, _ in events]


async def test_stale_window_is_re_resolved_by_pid_before_failing() -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    backend = FakeBackend()
    backend.windows = [{"window_id": 4242, "title": "记事本", "pid": 99}]
    backend.click_results = [
        ActionResult(ok=False, action="click", code="window_gone", effect="suspected_noop"),
        ActionResult(ok=True, action="click", effect="confirmed"),
    ]
    runtime = x2computer.X2ComputerRuntime(backend=backend, legacy=FakeLegacy())
    async with installed_ctx(events, []):
        # Seed the remembered target through a window-scoped observation first.
        observe = await runtime.call_tool(
            "computer_observe", {"target": "window", "window_id": 111, "pid": 99})
        assert observe["is_error"] is False
        result = await runtime.call_tool("computer_mouse", {"action": "click", "x": 7, "y": 8})

    assert result["is_error"] is False
    assert result["data"]["effect"] == "confirmed"
    captures = [call for call in backend.calls if call[0] == "capture"]
    assert ("capture", {"mode": "ax", "app": None, "pid": 99, "window_id": 4242}) in captures
    assert len([call for call in backend.calls if call[0] == "click"]) == 2


async def test_vision_routing_call_through_on_capture(monkeypatch) -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(hermes_tool, "_should_route_through_aux_vision", lambda: True)
    routed: dict[str, Any] = {}

    def fake_route(cap: CaptureResult, summary: str, **kwargs: Any) -> str:
        routed["png"] = cap.png_b64
        routed["summary"] = summary
        return json.dumps({"window_title": "记事本", "vision_analysis": "桌面显示记事本窗口",
                           "vision_analysis_routed_via": "auxiliary.vision"})

    monkeypatch.setattr(hermes_tool, "_route_capture_through_aux_vision", fake_route)
    runtime = x2computer.X2ComputerRuntime(backend=FakeBackend(), legacy=FakeLegacy())
    async with installed_ctx(events, []):
        result = await runtime.call_tool("computer_observe", {"target": "desktop"})

    assert result["is_error"] is False
    assert result["data"]["vision_analysis_routed_via"] == "auxiliary.vision"
    assert routed["png"] == PNG_B64
    assert "记事本" in routed["summary"]


async def test_multimodal_envelope_when_main_model_sees_images() -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    runtime = x2computer.X2ComputerRuntime(backend=FakeBackend(), legacy=FakeLegacy())
    async with installed_ctx(events, []):
        result = await runtime.call_tool("computer_observe", {"target": "active_window"})

    assert result["is_error"] is False
    assert result["data"]["_multimodal"] is True
    image_blocks = [b for b in result["content"] if b.get("type") == "image_url"]
    assert image_blocks and image_blocks[0]["image_url"]["url"].endswith(PNG_B64)
    step = next(e for e in events if e[0] == EVENT_COMPUTER_STEP)
    # Step thumbnails are capped for the replay trail: re-encoded small JPEG.
    thumbnail = step[1]["thumbnail"]
    assert thumbnail.startswith("data:image/jpeg;base64,")
    assert max(Image.open(BytesIO(base64.b64decode(thumbnail.partition(",")[2]))).size) <= 256


async def test_step_thumbnail_is_capped_for_large_captures() -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    big = BytesIO()
    Image.new("RGB", (1024, 768), (255, 0, 0)).save(big, format="PNG")
    backend = FakeBackend()
    backend.captures = [CaptureResult(
        mode="som", width=1024, height=768,
        png_b64=base64.b64encode(big.getvalue()).decode("ascii"),
        elements=[], app="desktop", window_title="记事本")]
    runtime = x2computer.X2ComputerRuntime(backend=backend, legacy=FakeLegacy())
    async with installed_ctx(events, []):
        result = await runtime.call_tool("computer_observe", {"target": "desktop"})

    assert result["is_error"] is False
    step = next(e for e in events if e[0] == EVENT_COMPUTER_STEP)
    thumbnail = step[1]["thumbnail"]
    assert thumbnail.startswith("data:image/jpeg;base64,")
    assert max(Image.open(BytesIO(base64.b64decode(thumbnail.partition(",")[2]))).size) <= 256
    assert len(thumbnail) < 8192 * 2  # tiny event payload, unlike the raw 1024x768 grab


def test_cap_thumbnail_truncates_undecodable_payload() -> None:
    garbage = "data:image/png;base64,%%%" + "x" * 20000
    capped = x2computer._cap_thumbnail(garbage)
    assert "缩略图已截断" in capped
    assert len(capped) < 20000  # bounded even on the fallback path
    assert x2computer._cap_thumbnail(PNG_B64) == PNG_B64  # non data-URL passthrough


async def test_legacy_fallback_for_legacy_only_actions() -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    legacy = FakeLegacy()
    runtime = x2computer.X2ComputerRuntime(backend=FakeBackend(), legacy=legacy)
    async with installed_ctx(events, []):
        result = await runtime.call_tool(
            "computer_clipboard", {"action": "write", "text": "你好 Atlas"})

    assert result["data"]["legacy"] is True
    assert legacy.calls == [("computer_clipboard", {"action": "write", "text": "你好 Atlas"})]
    assert any(e[0] == EVENT_COMPUTER_STEP for e in events)


async def test_legacy_fallback_when_no_hermes_backend() -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    legacy = FakeLegacy()
    runtime = x2computer.X2ComputerRuntime(backend=None, legacy=legacy)
    async with installed_ctx(events, []):
        result = await runtime.call_tool("computer_mouse", {"action": "click", "x": 1, "y": 2})

    assert result["data"]["legacy"] is True
    assert legacy.calls[0][0] == "computer_mouse"


async def test_permission_mode_deny_blocks_all_computer_tools(monkeypatch) -> None:
    class DenyConfig:
        computer_use_permission_mode = "deny"

    monkeypatch.setattr(x2computer, "get_config", lambda: DenyConfig())
    legacy = FakeLegacy()
    runtime = x2computer.X2ComputerRuntime(backend=FakeBackend(), legacy=legacy)

    result = await runtime.call_tool("computer_observe", {})

    assert result["is_error"] is True
    assert "permission_mode" in result["data"]["error"]
    assert legacy.calls == []


# ---------------------------------------------------------------------------
# Status / router
# ---------------------------------------------------------------------------
def _build_app() -> FastAPI:
    from atlas.api.computer_router import router

    app = FastAPI()
    app.include_router(router)
    return app


async def test_status_snapshot_mirrors_doctor_report(monkeypatch) -> None:
    monkeypatch.setattr(x2computer, "collect_doctor_report", lambda: {
        "schema_version": "1", "platform": "win32", "overall": "ok",
        "driver_version": "0.10.0",
        "checks": [{"name": "binary_version", "status": "pass", "message": "cua-driver 0.10.0"}],
    })
    snapshot = x2computer.status_snapshot()
    assert snapshot["ok"] is True and snapshot["ready"] is True
    assert snapshot["driver"]["version"] == "0.10.0"
    assert snapshot["permission_mode"] == "full_access"
    assert snapshot["doctor"]["checks"][0]["name"] == "binary_version"
    assert snapshot["backend"]["legacy_fallback"] is True


async def test_status_snapshot_never_raises(monkeypatch) -> None:
    monkeypatch.setattr(x2computer, "get_runtime", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    snapshot = x2computer.status_snapshot()
    assert snapshot["ok"] is False and snapshot["ready"] is False
    assert "查询桌面控制状态失败" in snapshot["error"]


async def test_status_endpoint_shape(monkeypatch) -> None:
    monkeypatch.setattr(x2computer, "collect_doctor_report", lambda: {
        "schema_version": "1", "platform": "win32", "overall": "degraded",
        "driver_version": "0.10.0", "checks": [],
    })
    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
        response = await client.get("/api/computer/status")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True and body["ready"] is False  # degraded driver -> not ready
    assert body["doctor"]["overall"] == "degraded"
    assert {"permission_mode", "backend", "driver", "doctor"} <= set(body)


async def test_status_endpoint_survives_backend_failure(monkeypatch) -> None:
    def broken() -> dict[str, Any]:
        raise RuntimeError("doctor exploded")

    monkeypatch.setattr(x2computer, "collect_doctor_report", broken)
    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as client:
        response = await client.get("/api/computer/status")
    assert response.status_code == 200
    assert response.json()["ok"] is False


def test_ensure_configured_syncs_hermes_config(tmp_path, monkeypatch) -> None:
    from atlas.tools.x2 import hermes_config_sync

    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "engine"))
    runtime = x2computer.X2ComputerRuntime()
    runtime.ensure_configured()
    runtime.ensure_configured()  # idempotent
    config = hermes_config_sync.config_file()
    assert config.exists()

    import yaml

    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    assert data["computer_use"]["permission_mode"] == "standard"
    assert data["auxiliary"]["vision"]["provider"] == "auto"

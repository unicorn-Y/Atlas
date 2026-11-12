"""Deterministic fake X2 computer backend for offline tests and demos.

Selected ONLY through the ``ATLAS_X2_COMPUTER_FAKE`` environment-variable gate
in :func:`atlas.tools.x2.computer.get_runtime` (see there). It replaces the two
drivers underneath the production bridge — Hermes' ``ComputerUseBackend``
(:class:`FakeComputerBackend`) and the pinned ``tools.computer_use.tool``
dispatch module (:class:`FakeAtlasComputerTool`) — so the whole production
path (registration → ``call_tool`` → permission check → legacy translation →
``_dispatch`` → normalize → ``computer.step`` events) stays identical and only
the driver is fake.

Everything here is deterministic and offline: fixed payloads, no randomness,
no clock reads, no network, no win32/pyautogui/keyboard/mouse imports and no
OS side effects of any kind. Same input → same output, always.
"""
from __future__ import annotations

from typing import Any

# A real, small, hard-coded 64x48 PNG (solid color) as base64 — deterministic
# bytes, valid for PIL to decode downstream (``_cap_thumbnail``), and no PIL
# import needed to PRODUCE it.
FAKE_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAEAAAAAwCAIAAAAuKetIAAAAaUlEQVR4nNXOQREAIAzAsFIFSEAK"
    "/lUhYg+uUZC1z6VM4iRO4iRO4iRO4iRO4iRO4iRO4iRO4iRO4iRO4iRO4iRO4iRO4iRO4iRO4iRO"
    "4iRO4iRO4iRO4iRO4iRO4iRO4iRO4iTO34GpB8JqANCKq/pJAAAAAElFTkSuQmCC"
)

# Marker baked into every fake result so tests can prove the fake driver (and
# not a real desktop path) produced the evidence.
FAKE_MARKER = "K1_FAKE_DESKTOP"

# Non-capture actions the fake understands as recorded no-ops. Anything else
# is an unknown action (error result), mirroring the real dispatch contract.
_KNOWN_ACTIONS = frozenset({
    "click", "double_click", "type", "key", "scroll", "drag", "set_value",
    "list_windows",
})


class FakeComputerBackend:
    """Stand-in for Hermes' ``ComputerUseBackend``: records calls, fixed results."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def _record(self, name: str, kwargs: dict[str, Any]) -> None:
        self.calls.append((name, dict(kwargs)))

    def is_available(self) -> bool:
        return True

    def start(self) -> None:
        self._record("start", {})

    def stop(self) -> None:
        self._record("stop", {})

    def capture(self, mode: str = "som", app: str | None = None,
                pid: int | None = None, window_id: int | None = None) -> dict[str, Any]:
        """Return a fixed grab payload (the fake Hermes tool wraps it as multimodal)."""
        self._record("capture", {"mode": mode, "app": app, "pid": pid, "window_id": window_id})
        return {
            "mode": str(mode),
            "app": str(app or ""),
            "width": 64,
            "height": 48,
            "png_b64": FAKE_PNG_B64,
            "elements": [],
            "window_title": FAKE_MARKER,
        }

    def list_windows(self) -> list[dict[str, Any]]:
        self._record("list_windows", {})
        return [{
            "window_id": 1,
            "pid": 4242,
            "title": FAKE_MARKER,
            "app": "fake",
        }]


class FakeAtlasComputerTool:
    """Stand-in for the pinned ``tools.computer_use.tool`` module surface.

    Only the member the X2 bridge touches is implemented: ``_dispatch`` (the
    bridge never calls ``_get_backend`` / ``release_computer_use_session`` when
    a backend + tool are injected).
    """

    def _dispatch(self, backend: Any, action: str, args: dict[str, Any] | None = None,
                  session_id: str | None = None) -> Any:
        if action == "capture":
            grab = backend.capture(
                mode=str((args or {}).get("mode") or "som"),
                app=(args or {}).get("app"),
                pid=(args or {}).get("pid"),
                window_id=(args or {}).get("window_id"),
            )
            summary = f"{FAKE_MARKER} capture ok (mode={grab['mode']}, app={grab['app']})"
            return {
                "_multimodal": True,
                "text_summary": summary,
                "content": [
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/png;base64,{grab['png_b64']}"}},
                    {"type": "text", "text": summary},
                ],
                "action_result": {"ok": True, "action": "capture",
                                  "mode": grab["mode"], "app": grab["app"]},
                "meta": {"backend": "fake", "mode": grab["mode"], "app": grab["app"]},
            }
        if action in _KNOWN_ACTIONS:
            backend._record(action, dict(args or {}))
            return {"ok": True, "action": action, "backend": "fake"}
        return {"error": f"fake backend: unknown action {action}"}


__all__ = ["FAKE_MARKER", "FAKE_PNG_B64", "FakeComputerBackend", "FakeAtlasComputerTool"]

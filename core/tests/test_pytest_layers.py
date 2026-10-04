from pathlib import Path

import pytest


class _FakeItem:
    def __init__(self, module: str, name: str, markers=()) -> None:
        self.path = Path("tests") / module
        self.originalname = name
        self.name = name
        self.nodeid = f"tests/{module}::{name}"
        self._markers = list(markers)

    def get_closest_marker(self, name: str):
        return next((marker for marker in reversed(self._markers) if marker.name == name), None)

    def add_marker(self, marker) -> None:
        self._markers.append(marker)


def test_real_desktop_case_uses_desktop_lane_and_retries_once(_lane_policy) -> None:
    item = _FakeItem(
        "test_computer_use.py",
        "test_real_desktop_observe_input_clipboard_and_window_management",
    )

    assert _lane_policy(item) == "desktop"
    assert item.get_closest_marker("desktop") is not None
    assert item.get_closest_marker("flaky").kwargs["reruns"] == 1


def test_explicit_desktop_lane_also_retries_once(_lane_policy) -> None:
    item = _FakeItem("test_example.py", "test_ui", markers=(pytest.mark.desktop,))

    assert _lane_policy(item) == "desktop"
    assert item.get_closest_marker("flaky").kwargs["reruns"] == 1


def test_unmarked_isolated_test_defaults_to_unit(_lane_policy) -> None:
    item = _FakeItem("test_example.py", "test_fake_only")

    assert _lane_policy(item) == "unit"
    assert item.get_closest_marker("unit") is not None


def test_live_lane_is_skipped_without_explicit_opt_in(_lane_policy, monkeypatch) -> None:
    monkeypatch.delenv("ATLAS_LIVE", raising=False)
    item = _FakeItem("test_live_example.py", "test_real_provider", markers=(pytest.mark.live,))

    assert _lane_policy(item) == "live"
    assert item.get_closest_marker("skip") is not None


def test_live_lane_can_be_selected_with_opt_in(_lane_policy, monkeypatch) -> None:
    monkeypatch.setenv("ATLAS_LIVE", "1")
    item = _FakeItem("test_live_example.py", "test_real_provider", markers=(pytest.mark.live,))

    assert _lane_policy(item) == "live"
    assert item.get_closest_marker("skip") is None


def test_cross_component_module_is_integration(_lane_policy) -> None:
    item = _FakeItem("test_gateway_integration.py", "test_fake_gateway_flow")

    assert _lane_policy(item) == "integration"
    assert item.get_closest_marker("integration") is not None

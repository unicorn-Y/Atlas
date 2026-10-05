import os
import tempfile
from pathlib import Path

import pytest

# Collection imports application modules before fixtures run. Ordinary test
# lanes must not resolve settings, MCP clients, credentials, or state in the
# operator's home. An exclusive ATLAS_LIVE=1 -m live run deliberately uses the
# configured model and its own data root.
_LIVE_REQUESTED = os.environ.get("ATLAS_LIVE") == "1"
if not _LIVE_REQUESTED:
    _TEST_ROOT = Path(tempfile.mkdtemp(prefix="atlas-tests-"))
    for _key, _folder in {
        "HOME": "home", "USERPROFILE": "home", "APPDATA": "home/appdata",
        "LOCALAPPDATA": "home/localappdata", "HERMES_HOME": "hermes",
        "ATLAS_DATA_DIR": "atlas", "ATLAS_SKILLS_HOME": "atlas/skills-home",
    }.items():
        _path = _TEST_ROOT / _folder
        _path.mkdir(parents=True, exist_ok=True)
        os.environ[_key] = str(_path)
    for _key in list(os.environ):
        if _key.endswith(("_API_KEY", "_TOKEN", "_SECRET", "_PASSWORD", "_CREDENTIALS")):
            os.environ.pop(_key, None)
    os.environ["ATLAS_SCHEDULER_ENABLED"] = "false"
    _config = _TEST_ROOT / "atlas/config/atlas.toml"
    _config.parent.mkdir(parents=True, exist_ok=True)
    _config.write_text(
        '[agent]\nengine="hermes"\n[tools]\nauto_start=[]\n[tools.servers]\n',
        encoding="utf-8",
    )

# What the Electron main process attaches to renderer requests (see atlas.origin_guard).
API_TOKEN = "test-atlas-api-token"

# These modules cross a shipped service, process, persistence, or protocol
# boundary. New tests default to unit only when they use fakes or in-process
# collaborators; tests exercising real seams belong in integration.
_INTEGRATION_MODULES = {
    "test_agent_browser_acceptance.py",
    "test_automation_engine.py",
    "test_automation_router.py",
    "test_c1_websocket_acceptance.py",
    "test_c6_lsp_e2e.py",
    "test_c6_main_chain.py",
    "test_c6_lsp_wiring.py",
    "test_gateway_integration.py",
    "test_hermes_runtime_e2e.py",
    "test_long_lived_agent_e2e.py",
    "test_k1_daily_paths.py",
    "test_k1_daily_paths_x2x4x5.py",
    "test_lsp_lifecycle.py",
    "test_mcp_runtime_live.py",
    "test_release_acceptance.py",
    "test_release_build_scripts.py",
    "test_server.py",
    "test_server_agents_wiring.py",
    "test_hermes_session_sync.py",
    "test_run_usage_aggregation_e2e.py",
    "test_session_migration.py",
}
_DESKTOP_TESTS = {
    (
        "test_computer_use.py",
        "test_real_desktop_observe_input_clipboard_and_window_management",
    ),
}
_INTEGRATION_CLASSES = {("test_evolution.py", "TestWatcher")}
_LANE_MARKERS = ("unit", "integration", "desktop", "live")


def _test_lane(item) -> str:
    explicit_lanes = [name for name in _LANE_MARKERS if item.get_closest_marker(name)]
    if len(explicit_lanes) > 1:
        raise pytest.UsageError(
            f"{item.nodeid} has conflicting test lanes: {', '.join(explicit_lanes)}"
        )
    if explicit_lanes:
        return explicit_lanes[0]

    module = Path(str(item.path)).name
    test_name = getattr(item, "originalname", None) or item.name.split("[", 1)[0]
    if (module, test_name) in _DESKTOP_TESTS:
        return "desktop"
    if module in _INTEGRATION_MODULES:
        return "integration"
    cls = getattr(item, "cls", None)
    if cls is not None and (module, cls.__name__) in _INTEGRATION_CLASSES:
        return "integration"
    return "unit"


def _apply_test_lane(item) -> str:
    lane = _test_lane(item)
    item.add_marker(getattr(pytest.mark, lane))
    if lane == "desktop" and not item.get_closest_marker("flaky"):
        item.add_marker(pytest.mark.flaky(reruns=1))
    if lane == "live" and os.environ.get("ATLAS_LIVE") != "1":
        item.add_marker(pytest.mark.skip(reason="live model tests require ATLAS_LIVE=1"))
    return lane


@pytest.fixture
def _lane_policy():
    return _apply_test_lane

def pytest_configure(config):
    if _LIVE_REQUESTED and config.getoption("-m") != "live":
        raise pytest.UsageError(
            "ATLAS_LIVE=1 is only allowed with an exclusive -m live selection"
        )


def pytest_collection_modifyitems(items):
    for item in items:
        _apply_test_lane(item)


@pytest.fixture(autouse=True)
def _atlas_api_token(monkeypatch):
    monkeypatch.setenv("ATLAS_API_TOKEN", API_TOKEN)

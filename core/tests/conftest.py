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

# ---------------------------------------------------------------------------
# H1R4: shared-app pollution guard. The module-level FastAPI app
# (``atlas.server.app``) is process-global. A test that mounts routes, swaps
# services, or runs the server lifespan on it without fully restoring the
# change makes other, unrelated tests fail later in the run. The autouse
# fixture below snapshots the shared app's mutable surface before every test;
# the pytest_runtest_teardown hookwrapper re-checks it AFTER the test's FULL
# fixture teardown (so monkeypatch undo and every function-scoped fixture's
# restore run first) and fails the test whose teardown observed a net change —
# the polluter — naming exactly what changed. Design note:
# artifacts/h1r4/draft_guard_fixture.py.
# ---------------------------------------------------------------------------

_WATCH_OPENAPI_SCHEMA = True

_SHARED_APP_GUARD_SNAPSHOT: pytest.StashKey = pytest.StashKey()


class _AtlasGuardUnset:
    """Sentinel for an AppServices slot that is currently unbound."""


_ATLAS_GUARD_UNSET = _AtlasGuardUnset()


def _atlas_guard_getattr(obj: object, name: str) -> object:
    try:
        return getattr(obj, name)
    except AttributeError:
        return _ATLAS_GUARD_UNSET


def _atlas_guard_callable_signature(value: object) -> str:
    qualname = getattr(value, "__qualname__", None) or repr(value)
    return f"{qualname}#{id(value):#x}"


def _atlas_guard_route_signature(route: object) -> tuple:
    # starlette 1.7 / fastapi 0.141: APIRoute has .methods (upper-case set, HEAD
    # auto-added for GET) and .path; WebSocketRoute and Mount have no .methods
    # but do have .path. Lazy router wrappers from this FastAPI fork
    # (_IncludedRouter, appended by include_router) have NO .path and a repr
    # that mutates when their lazy candidate cache materializes — sign those by
    # (type, id): they are created once per include_router call and stay
    # identity-stable, so a mid-test include shows up as a brand-new id while
    # lazy-cache materialization stays invisible.
    path = getattr(route, "path", None)
    if isinstance(path, str):
        methods = getattr(route, "methods", None) or ()
        return (type(route).__name__, frozenset(str(m) for m in methods), path)
    return (type(route).__name__, id(route))


def _atlas_guard_route_text(signature: tuple) -> str:
    if len(signature) == 2 and isinstance(signature[1], int):
        # (type name, id) fallback signature — lazy router wrapper.
        return f"{signature[0]}#{signature[1]:#x}"
    if len(signature) == 1:
        return str(signature[0])
    kind, methods, path = signature
    if methods:
        return "+".join(sorted(methods)) + f" {path}"
    return f"{kind} {path}"


def _atlas_guard_slot_names(services: object) -> tuple[str, ...]:
    # AppServices is @dataclass(slots=True): __slots__ lists every field name.
    slots = getattr(type(services), "__slots__", None)
    if slots is not None:
        return tuple(str(name) for name in slots)
    # Defensive: a test swapped the container for a non-slots object.
    return tuple(sorted(vars(services)))  # type: ignore[assignment]


def _atlas_guard_slot_entry(services: object, name: str) -> tuple[str, str, int]:
    value = _atlas_guard_getattr(services, name)
    if value is _ATLAS_GUARD_UNSET:
        return (name, "<unset>", 0)
    return (name, type(value).__name__, id(value))


def _atlas_guard_app_snapshot(app: object) -> dict:
    routes = tuple(
        _atlas_guard_route_signature(route) for route in app.router.routes  # type: ignore[attr-defined]
    )
    dependency_overrides = tuple(sorted(
        f"{_atlas_guard_callable_signature(original)} -> {_atlas_guard_callable_signature(override)}"
        for original, override in app.dependency_overrides.items()  # type: ignore[attr-defined]
    ))
    services = app.state.services  # type: ignore[attr-defined]
    snapshot = {
        "routes": routes,
        "dependency_overrides": dependency_overrides,
        "services_container": (type(services).__name__, id(services)),
        "services_slots": tuple(sorted(
            _atlas_guard_slot_entry(services, name)
            for name in _atlas_guard_slot_names(services)
        )),
        "state_keys": tuple(sorted(app.state._state)),  # type: ignore[attr-defined]
    }
    if _WATCH_OPENAPI_SCHEMA:
        schema = app.openapi_schema  # type: ignore[attr-defined]
        snapshot["openapi_schema"] = (type(schema).__name__, id(schema))
    return snapshot


def _atlas_guard_diff(before: dict, after: dict) -> list[str]:
    changes: list[str] = []

    if before["routes"] != after["routes"]:
        old, new = before["routes"], after["routes"]
        added = [sig for sig in new if sig not in old]
        removed = [sig for sig in old if sig not in new]
        for sig in added[:5]:
            changes.append(f"route added: {_atlas_guard_route_text(sig)}")
        for sig in removed[:5]:
            changes.append(f"route removed: {_atlas_guard_route_text(sig)}")
        if len(added) > 5:
            changes.append(f"... and {len(added) - 5} more routes added")
        if len(removed) > 5:
            changes.append(f"... and {len(removed) - 5} more routes removed")
        if not added and not removed:
            changes.append("route table reordered (same routes, different order)")

    old_overrides, new_overrides = (
        before["dependency_overrides"], after["dependency_overrides"],
    )
    if old_overrides != new_overrides:
        for signature in [s for s in new_overrides if s not in old_overrides][:5]:
            changes.append(f"dependency override added for {signature}")
        for signature in [s for s in old_overrides if s not in new_overrides][:5]:
            changes.append(f"dependency override removed: {signature}")

    old_container = before["services_container"]
    new_container = after["services_container"]
    if (old_container[1] != new_container[1] or old_container[0] != new_container[0]) and (
        before["services_slots"] != after["services_slots"]
        or old_container[0] != new_container[0]
    ):
        changes.append(
            f"app.state.services container replaced "
            f"{old_container[0]}#{old_container[1]:#x} -> "
            f"{new_container[0]}#{new_container[1]:#x} (slot content differs)"
        )
    # Same type, different id, identical slot content (e.g. a dataclasses.replace
    # copy put back by a test's finally) is treated as fully restored.

    old_slots = {entry[0]: entry[1:] for entry in before["services_slots"]}
    new_slots = {entry[0]: entry[1:] for entry in after["services_slots"]}
    for name in sorted(set(old_slots) | set(new_slots)):
        old_entry, new_entry = old_slots.get(name), new_slots.get(name)
        if old_entry != new_entry:
            changes.append(
                f"app.state.services.{name} replaced "
                f"{old_entry[0]}#{old_entry[1]:#x} -> {new_entry[0]}#{new_entry[1]:#x}"
            )

    old_keys, new_keys = before["state_keys"], after["state_keys"]
    for key in [k for k in new_keys if k not in old_keys][:5]:
        changes.append(f"app.state key added: {key}")
    for key in [k for k in old_keys if k not in new_keys][:5]:
        changes.append(f"app.state key removed: {key}")

    if _WATCH_OPENAPI_SCHEMA and before["openapi_schema"] != after["openapi_schema"]:
        changes.append(
            "app.openapi_schema cache changed "
            f"({before['openapi_schema'][0]} -> {after['openapi_schema'][0]}); "
            "a stale OpenAPI cache leaks swapped-in routes into later /openapi.json reads"
        )
    return changes


@pytest.fixture(autouse=True)
def _atlas_shared_app_guard(request: pytest.FixtureRequest):
    """Snapshot the shared atlas.server.app; fail the test that changes it."""
    from atlas import server  # one-time import cost per xdist worker process

    request.node.stash[_SHARED_APP_GUARD_SNAPSHOT] = _atlas_guard_app_snapshot(server.app)
    yield
    # The comparison deliberately does NOT happen here: fixture teardown would
    # run BEFORE monkeypatch undo (the existing _atlas_api_token autouse fixture
    # hoists monkeypatch's setup, so monkeypatch finalizes after this fixture).
    # pytest_runtest_teardown below checks after ALL finalizers instead.


_MODULE_BASELINES: dict[str, dict] = {}


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_setup(item: pytest.Item):
    # Before the first test of a module sets up module-scoped fixtures (e.g. a shared
    # app lifespan), record the shared-app state they must restore by module end.
    module = getattr(item, "module", None)
    key = getattr(module, "__name__", "")
    if key and key not in _MODULE_BASELINES:
        from atlas import server

        _MODULE_BASELINES[key] = _atlas_guard_app_snapshot(server.app)
    return (yield)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item: pytest.Item, nextitem: pytest.Item | None):
    result = yield  # inner exceptions propagate; the guard stands down
    snapshot = item.stash.get(_SHARED_APP_GUARD_SNAPSHOT, None)
    module_name = getattr(getattr(item, "module", None), "__name__", "")
    leaving_module = nextitem is None or getattr(
        getattr(nextitem, "module", None), "__name__", "") != module_name
    if leaving_module and module_name in _MODULE_BASELINES:
        # Module-scoped fixtures were torn down with this test: judge the module as a
        # whole against the state before its fixtures existed, not this test's start.
        snapshot = _MODULE_BASELINES[module_name]
    if snapshot is not None:
        from atlas import server

        changes = _atlas_guard_diff(snapshot, _atlas_guard_app_snapshot(server.app))
        if changes:
            summary = "; ".join(changes[:10])
            pytest.fail(
                f"shared atlas.server.app state changed during this test "
                f"(cross-test pollution guard): {summary}",
                pytrace=False,
            )
    return result

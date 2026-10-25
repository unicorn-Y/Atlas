"""X2 browser bridge tests — fake browser backend only, no network.

Covers: takeover-mode config → correct backend requested (+ Hermes config.yaml
[browser] section), handoff block/resume/give-up (scripted + broker), vault
no-secret guarantees and bank-card confirmation, offline Chinese error, panel
sync + step events, and the /api/browser router contract (handoff, settings,
recordings, to-skill, vault CRUD).
"""
from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import pytest
import yaml
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from atlas.api import browser_router as browser_router_module
from atlas.tools.x2 import browser as x2browser
from atlas.tools.x2.context import (
    EVENT_BROWSER_STEP,
    EVENT_HANDOFF_REQUIRED,
    EVENT_HANDOFF_RESOLVED,
    EVENT_PANEL_SYNC,
    X2Context,
    reset_context,
    set_context,
)

SNAPSHOT = "\n".join([
    '- heading "登录 Example" [ref=e1]',
    '- textbox "用户名" [ref=e2]',
    '- textbox "密码" [ref=e3]',
    '- button "提交" [ref=e4]',
])


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class FakeBrowser:
    """Stands in for the Hermes browser backend; records every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.payloads: dict[str, Any] = {}

    async def call(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((action, dict(params)))
        payload = self.payloads.get(action)
        if payload is not None:
            if isinstance(payload, Exception):
                raise payload
            return payload
        if action == "navigate":
            return {"success": True, "url": params.get("url", ""), "title": "示例页面",
                    "snapshot": SNAPSHOT, "element_count": 4}
        if action == "snapshot":
            return {"success": True, "snapshot": SNAPSHOT, "element_count": 4}
        if action == "click":
            return {"success": True, "clicked": params.get("ref", "")}
        if action == "type":
            return {"success": True, "typed": "•••", "element": params.get("ref", "")}
        if action == "scroll":
            return {"success": True, "scrolled": params.get("direction", "")}
        if action == "press":
            return {"success": True, "pressed": params.get("key", "")}
        if action == "back":
            return {"success": True}
        if action == "vault_list":
            return {"success": True, "items": [
                {"handle": "vault_login1", "kind": "login", "label": "Example",
                 "origin": "https://example.com", "identifier": "alice@example.com"},
            ]}
        return {"success": True}


class FakeVaultStore:
    """In-memory stand-in for Hermes ``VaultStore`` (meta only)."""

    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def add_item(
        self, kind: str, label: str, secret: dict[str, Any], origin: str | None = None,
        *, login_method: dict[str, Any] | None = None,
    ):
        meta = {
            "id": f"vault_{len(self.items) + 1}",
            "kind": kind,
            "label": label,
            "origin": origin,
            "created_at": "2026-10-03T00:00:00",
            "identifier": secret.get("identifier"),
            "identifier_type": secret.get("identifier_type"),
            "login_method": login_method,
        }
        self.items.append({**meta, "secret": dict(secret)})  # secret kept server-side only
        return _Meta(meta)

    def list_items(self) -> list["_Meta"]:
        return [_Meta(item) for item in self.items]

    def remove_item(self, item_id: str) -> bool:
        before = len(self.items)
        self.items = [item for item in self.items if item["id"] != item_id]
        return len(self.items) < before


class _Meta(dict):
    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.items() if k != "secret"}


def make_context(
    events: list[tuple[str, dict[str, Any]]],
    choices: list[str] | None = None,
    run_id: str = "run-1",
    wait_input: Any = None,
) -> X2Context:
    async def emit(event: str, data: dict[str, Any]) -> None:
        events.append((event, dict(data)))

    async def scripted(prompt: str, options: list[str]) -> str:
        if wait_input is not None:
            return await wait_input(prompt, options)
        return choices.pop(0) if choices else "give_up"

    return X2Context(run_id=run_id, session_id="sess-1", emit=emit,
                     wait_input=scripted if (choices is not None or wait_input is not None) else None)


@asynccontextmanager
async def installed_ctx(ctx: X2Context) -> AsyncIterator[X2Context]:
    token = set_context(ctx)
    try:
        yield ctx
    finally:
        reset_context(token)


@pytest.fixture(autouse=True)
def fresh_runtime():
    x2browser.set_runtime(None)
    yield
    x2browser.set_runtime(None)


@pytest.fixture(autouse=True)
def clean_user_settings():
    """Keep user-settings.json clean between tests (mode choice is sticky)."""
    from atlas.config import USER_SETTINGS_PATH, save_user_settings

    save_user_settings({}, USER_SETTINGS_PATH)
    yield
    save_user_settings({}, USER_SETTINGS_PATH)


def hermes_config() -> dict[str, Any]:
    from atlas.tools.x2.hermes_config_sync import config_file

    return yaml.safe_load(config_file().read_text(encoding="utf-8")) or {}


async def wait_for(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "condition not reached in time"
        await asyncio.sleep(0.01)


def runtime_with(backend: Any, **kw: Any) -> x2browser.X2BrowserRuntime:
    rt = x2browser.X2BrowserRuntime(backend=backend, **kw)
    x2browser.set_runtime(rt)
    return rt


# ---------------------------------------------------------------------------
# Mode config → correct backend requested
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(("frontend_mode", "internal", "backend_name"), [
    ("standalone", "standalone", "local"),
    ("copied-profile", "real_profile", "real_profile"),
    ("cdp", "cdp", "cdp"),
    ("extension", "extension", "extension"),
])
def test_mode_config_requests_correct_backend(
    frontend_mode: str, internal: str, backend_name: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = {"mode": frontend_mode, "cdp_url": "http://127.0.0.1:9222" if frontend_mode == "cdp" else ""}
    monkeypatch.setattr(x2browser, "load_user_settings", lambda: {"browser": settings})

    requests: list[dict[str, Any]] = []

    def factory(request: dict[str, Any]) -> FakeBrowser:
        requests.append(request)
        return FakeBrowser()

    rt = x2browser.X2BrowserRuntime(backend_factory=factory)
    rt.ensure_configured()

    assert requests == [{
        "mode": internal,
        "backend": backend_name,
        "cdp_url": "http://127.0.0.1:9222" if frontend_mode == "cdp" else "",
    }]

    section = hermes_config().get("browser") or {}
    assert section.get("mode") == internal
    assert section.get("use_real_profile") is (internal == "real_profile")
    assert (section.get("extension_control") or {}).get("enabled") is (internal == "extension")
    if frontend_mode == "cdp":
        assert section.get("cdp_url") == "http://127.0.0.1:9222"


def test_apply_browser_settings_roundtrip_and_validation() -> None:
    saved = x2browser.apply_browser_settings(mode="copied-profile")
    assert saved == {
        "mode": "copied-profile", "cdp_url": "", "proxy": "",
        "profile_browser": "chrome", "profile": "Default",
        "profile_sync_interval_minutes": 30, "incognito": False,
    }
    # cdp without a URL is refused (Chinese validation error).
    with pytest.raises(ValueError, match="cdp_url"):
        x2browser.apply_browser_settings(mode="cdp")
    with pytest.raises(ValueError, match="接管方式"):
        x2browser.apply_browser_settings(mode="teleport")


# ---------------------------------------------------------------------------
# Handoff: block / resume / give-up
# ---------------------------------------------------------------------------
async def test_handoff_blocks_then_resumes_done() -> None:
    backend = FakeBrowser()
    rt = runtime_with(backend)
    events: list[tuple[str, dict[str, Any]]] = []

    async def scripted(prompt: str, options: list[str]) -> str:
        assert options == ["open_panel", "done", "give_up"]
        return "done"

    ctx = make_context(events, wait_input=scripted)
    async with installed_ctx(ctx):
        result = await rt.call_tool("browser_handoff", {"reason": "需要登录验证", "url": "https://example.com"})

    assert not result["is_error"]
    kinds = [event for event, _ in events]
    assert EVENT_HANDOFF_REQUIRED in kinds and EVENT_HANDOFF_RESOLVED in kinds
    assert "继续" in result["content"][0]["text"]


async def test_handoff_give_up_is_model_visible_error() -> None:
    rt = runtime_with(FakeBrowser())
    events: list[tuple[str, dict[str, Any]]] = []
    ctx = make_context(events, choices=["give_up"])
    async with installed_ctx(ctx):
        result = await rt.call_tool("browser_handoff", {"reason": "验证码"})
    assert result["is_error"]
    assert "放弃" in result["data"]["error"]


async def test_handoff_broker_routes_router_resolution_into_blocked_call() -> None:
    rt = runtime_with(FakeBrowser())
    events: list[tuple[str, dict[str, Any]]] = []
    ctx = make_context(events, wait_input=x2browser.handoff_wait_input)
    async with installed_ctx(ctx):
        task = asyncio.create_task(rt.call_tool("browser_handoff", {"reason": "支付确认"}))
        await wait_for(lambda: "run-1" in x2browser.pending_handoffs())
        assert x2browser.resolve_handoff("run-1", "open_panel")
        result = await asyncio.wait_for(task, timeout=2.0)

    assert not result["is_error"]
    assert result["data"]["choice"] == "open_panel"
    assert "面板" in result["content"][0]["text"]  # resumed in place


# ---------------------------------------------------------------------------
# Panel sync + step events
# ---------------------------------------------------------------------------
async def test_navigate_emits_panel_sync_and_step() -> None:
    rt = runtime_with(FakeBrowser())
    events: list[tuple[str, dict[str, Any]]] = []
    ctx = make_context(events)
    async with installed_ctx(ctx):
        result = await rt.call_tool("browser_navigate", {"url": "https://example.com/login"})

    assert not result["is_error"]
    syncs = [data for event, data in events if event == EVENT_PANEL_SYNC]
    assert syncs == [{"url": "https://example.com/login", "title": "示例页面", "run_id": "run-1"}]
    steps = [data for event, data in events if event == EVENT_BROWSER_STEP]
    assert len(steps) == 1 and steps[0]["tool"] == "browser_navigate" and steps[0]["ok"] is True
    # Session isolation: task_id defaults to the X2 session id.
    assert backend_task_id(rt) == "sess-1"


def backend_task_id(rt: x2browser.X2BrowserRuntime) -> str | None:
    backend = rt.acquire_backend()
    return backend.calls[0][1].get("task_id")  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Vault: no secrets anywhere; bank-card needs confirmation
# ---------------------------------------------------------------------------
async def test_vault_list_never_leaks_secrets() -> None:
    backend = FakeBrowser()
    backend.payloads["vault_list"] = {
        "success": True,
        "items": [{
            "handle": "vault_card1", "kind": "payment", "label": "工资卡",
            "origin": "https://pay.example.com",
            "identifier": "private-user@example.com",
            "password": "s3cret!", "card_number": "4111111111111111", "cvc": "123",
        }],
    }
    rt = runtime_with(backend)
    events: list[tuple[str, dict[str, Any]]] = []
    ctx = make_context(events)  # no wait_input: confirmations impossible
    async with installed_ctx(ctx):
        result = await rt.call_tool("browser_vault_list", {})

    assert not result["is_error"]
    blob = json.dumps(result, ensure_ascii=False)
    for needle in ("s3cret!", "4111111111111111", '"cvc"', "private-user@example.com", '"identifier"'):
        assert needle not in blob
    item = result["data"]["items"][0]
    assert item["handle"] == "vault_card1" and item["kind"] == "payment"  # metadata survives
    for _, data in events:  # events must not carry secrets either
        assert "s3cret!" not in json.dumps(data, ensure_ascii=False)


async def test_vault_fill_payment_requires_confirmation() -> None:
    backend = FakeBrowser()
    backend.payloads["vault_list"] = {"success": True, "items": [
        {"handle": "vault_card1", "kind": "payment", "label": "工资卡",
         "origin": "https://pay.example.com"},
    ]}
    rt = runtime_with(backend)
    prompts: list[str] = []

    async def deny(prompt: str, options: list[str]) -> str:
        prompts.append(prompt)
        return "deny"

    ctx = make_context([], wait_input=deny)
    async with installed_ctx(ctx):
        result = await rt.call_tool("browser_vault_fill", {"handle": "vault_card1"})
    assert result["is_error"] and prompts and "银行卡" in prompts[0]
    assert [c for c, _ in backend.calls] == ["vault_list"]  # fill never dispatched

    async def allow(prompt: str, options: list[str]) -> str:
        return "allow"

    ctx = make_context([], wait_input=allow)
    async with installed_ctx(ctx):
        result = await rt.call_tool("browser_vault_fill", {"handle": "vault_card1"})
    assert not result["is_error"]
    assert [c for c, _ in backend.calls] == ["vault_list", "vault_list", "vault_fill"]
    assert backend.calls[-1][1]["handle"] == "vault_card1"


async def test_vault_fill_without_confirmation_channel_is_refused() -> None:
    backend = FakeBrowser()
    backend.payloads["vault_list"] = {"success": True, "items": [
        {"handle": "vault_card1", "kind": "payment", "label": "工资卡"},
    ]}
    rt = runtime_with(backend)
    ctx = make_context([])  # wait_input=None → fail closed
    async with installed_ctx(ctx):
        result = await rt.call_tool("browser_vault_fill", {"handle": "vault_card1"})
    assert result["is_error"] and "确认" in result["data"]["error"]


async def test_vault_fill_login_requires_origin_match_and_confirmation() -> None:
    backend = FakeBrowser()
    rt = runtime_with(backend)
    ctx = make_context([])
    async with installed_ctx(ctx):
        await rt.call_tool("browser_navigate", {"url": "https://evil.example/login"})
        result = await rt.call_tool("browser_vault_fill", {"handle": "vault_login1"})
    assert result["is_error"] and "origin" in result["data"]["error"]
    assert [action for action, _ in backend.calls] == ["navigate", "vault_list"]

    prompts: list[str] = []

    async def allow(prompt: str, options: list[str]) -> str:
        prompts.append(prompt)
        return "allow"

    async with installed_ctx(make_context([], wait_input=allow)):
        await rt.call_tool("browser_navigate", {"url": "https://example.com/login"})
        result = await rt.call_tool("browser_vault_fill", {"handle": "vault_login1"})
    assert not result["is_error"] and prompts and "https://example.com" in prompts[0]
    assert backend.calls[-1][0] == "vault_fill"


# ---------------------------------------------------------------------------
# Offline / backend-unavailable: Chinese error
# ---------------------------------------------------------------------------
async def test_offline_backend_yields_chinese_error() -> None:
    rt = runtime_with(False)  # explicit "Hermes browser stack unavailable"
    events: list[tuple[str, dict[str, Any]]] = []
    async with installed_ctx(make_context(events)):
        result = await rt.call_tool("browser_navigate", {"url": "https://example.com"})
    assert result["is_error"]
    assert "浏览器后端不可用" in result["content"][0]["text"]
    assert result["data"]["code"] == "backend_unavailable"
    assert events == []  # failed actions leave no step trail


async def test_hermes_import_failure_maps_to_backend_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    def broken_import(name: str, *a: Any, **kw: Any):
        if name == "tools.browser_tool":
            raise ImportError("no such module")
        return importlib.import_module(name, *a, **kw)

    monkeypatch.setattr(importlib, "import_module", broken_import)
    rt = runtime_with(x2browser._UNSET)
    ctx = make_context([])
    async with installed_ctx(ctx):
        result = await rt.call_tool("browser_snapshot", {})
    assert result["is_error"]
    assert "浏览器后端不可用" in result["content"][0]["text"]


def test_hermes_backend_import_error_message() -> None:
    import importlib

    backend = x2browser.HermesBrowserBackend()

    def broken(name: str, *a: Any, **kw: Any):
        raise ImportError("boom")

    import asyncio

    async def run() -> None:
        real = importlib.import_module

        def fake(name: str, *a: Any, **kw: Any):
            if name == "atlas.engine_core.tools.browser_tool":
                raise ImportError("boom")
            return real(name, *a, **kw)

        importlib.import_module = fake  # type: ignore[method-assign]
        try:
            await backend.call("navigate", {"url": "https://x"})
        except x2browser.BackendUnavailable as exc:
            assert "浏览器模块" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("expected BackendUnavailable")
        finally:
            importlib.import_module = real  # type: ignore[method-assign]

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Tool surface / registry contract
# ---------------------------------------------------------------------------
def test_tool_surface_is_one_handler_and_has_handoff() -> None:
    schemas = x2browser.get_browser_tool_schemas()
    names = [s["function"]["name"] for s in schemas]
    assert "browser_handoff" in names and "browser_vault_fill" in names
    assert "browser_replay" in names
    registered: list[tuple[dict[str, Any], Any]] = []
    registered_names = x2browser.register_browser_tools(
        lambda schema, handler: registered.append((schema, handler)))
    assert registered_names == names
    assert all(handler is x2browser.call_tool for _, handler in registered)


def test_scrub_secrets_recurses() -> None:
    dirty = {"a": 1, "password": "x", "nested": {"card_number": "4111", "keep": 2}, "list": [{"otp_secret": "s"}]}
    assert x2browser.scrub_secrets(dirty) == {"a": 1, "nested": {"keep": 2}, "list": [{}]}


async def test_shutdown_closes_runtime_without_raising() -> None:
    rt = runtime_with(FakeBrowser())  # injected backend owns no Hermes sessions
    await x2browser.shutdown()
    assert x2browser.get_runtime() is not rt  # module hook drops the runtime
    x2browser.set_runtime(None)
    await x2browser.shutdown()  # no runtime installed: still a safe no-op


# ---------------------------------------------------------------------------
# Router (/api/browser/*)
# ---------------------------------------------------------------------------
def build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(browser_router_module.router)
    return app


async def test_router_settings_roundtrip() -> None:
    async with AsyncClient(transport=ASGITransport(app=build_app()), base_url="test://x") as client:
        saved = (await client.post("/api/browser/settings",
                                   json={"mode": "copied-profile", "proxy": "http://127.0.0.1:7890"})).json()
        assert saved["mode"] == "copied-profile"
        fetched = (await client.get("/api/browser/settings")).json()
        assert fetched["mode"] == "copied-profile" and fetched["proxy"] == "http://127.0.0.1:7890"
        bad = await client.post("/api/browser/settings", json={"mode": "teleport"})
        assert bad.status_code == 422


async def test_router_recordings_start_get_stop_and_to_skill(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    rt = runtime_with(FakeBrowser())
    events: list[tuple[str, dict[str, Any]]] = []
    ctx = make_context(events)

    async with AsyncClient(transport=ASGITransport(app=build_app()), base_url="test://x") as client:
        started = (await client.post("/api/browser/recordings", json={"action": "start"})).json()
        assert started["status"] == "recording" and started["recording_id"]
        async with installed_ctx(ctx):
            await rt.call_tool("browser_navigate", {"url": "https://example.com/login"})
            await rt.call_tool("browser_click", {"ref": "@e2"})
        stopped = (await client.post("/api/browser/recordings", json={"action": "stop"})).json()
        assert stopped["status"] == "stopped" and stopped["step_count"] == 2

        again = await client.post("/api/browser/recordings", json={"action": "stop"})
        assert again.status_code == 409

        doc = (await client.get(f"/api/browser/recordings/{started['recording_id']}")).json()
        assert doc["step_count"] == 2
        assert doc["steps"][0]["action"] == "navigate"
        assert doc["steps"][1]["ref"] == "@e2" and doc["steps"][1]["fingerprint"]

        preview = (await client.post(
            f"/api/browser/recordings/{started['recording_id']}/to-skill",
            json={"dry_run": True})).json()
        assert {"name", "description", "skill_md", "steps"} <= set(preview)
        assert preview["skill_md"].startswith("---\nname:")

        # 保存走统一技能注册表：像生产环境一样由 server 提供唯一 SkillMarket
        # （router 在 server lifespan 之外拿不到 atlas.server 全局，测试用
        # set_market_supplier 接缝注入同一套真实持久化路径）。
        from atlas.api import skills_market_router as market_router_module
        from atlas.skills import SkillManager, default_skill_sources
        from atlas.skills.market import SkillMarket
        from atlas.skills.registry import SkillRegistry

        user_skills = tmp_path / "skills"
        workspace = tmp_path / "ws"
        registry = SkillRegistry(tmp_path / "skill-registry.db")
        manager = SkillManager(skills_dir=user_skills)
        for source in default_skill_sources(workspace=workspace, atlas_home=tmp_path):
            manager.register_skill_source(source)
        manager.scan_skills_sync()
        market = SkillMarket(
            registry, data_dir=tmp_path, user_skills_dir=user_skills,
            project_skills_dir=workspace / ".claude" / "skills", skill_manager=manager,
        )
        market_router_module.set_market_supplier(lambda: market)
        try:
            saved = (await client.post(
                f"/api/browser/recordings/{started['recording_id']}/to-skill",
                json={"dry_run": False, "name": "example-login"})).json()
        finally:
            market_router_module.set_market_supplier(None)
        assert saved["skill_id"] == "example-login"
        saved_dir = Path(saved["path"])
        saved_path = saved_dir / "SKILL.md"
        assert saved_dir == user_skills / "community" / "example-login"
        assert saved_path.read_text(encoding="utf-8") == saved["skill_md"]
        rows = [row for row in registry.list() if row["name"] == "example-login"]
        assert rows and (rows[0].get("provenance") or {}).get("origin_kind") == "local_recorded"

        missing = await client.get("/api/browser/recordings/rec-nope")
        assert missing.status_code == 404


async def test_router_handoff_resolution_reaches_blocked_tool() -> None:
    rt = runtime_with(FakeBrowser())
    ctx = make_context([], wait_input=x2browser.handoff_wait_input)
    async with AsyncClient(transport=ASGITransport(app=build_app()), base_url="test://x") as client:
        nothing = await client.post(
            "/api/browser/handoff", json={"run_id": "run-404", "resolution": "done"})
        assert nothing.status_code == 404

        bad = await client.post(
            "/api/browser/handoff", json={"run_id": "run-1", "resolution": "maybe"})
        assert bad.status_code == 422

        async with installed_ctx(ctx):
            task = asyncio.create_task(rt.call_tool("browser_handoff", {"reason": "登录"}))
            await wait_for(lambda: "run-1" in x2browser.pending_handoffs())
            resolved = await client.post(
                "/api/browser/handoff", json={"run_id": "run-1", "resolution": "give_up"})
            assert resolved.status_code == 200
            result = await asyncio.wait_for(task, timeout=2.0)
        assert result["is_error"] and "放弃" in result["data"]["error"]


async def test_router_vault_handles_only_password_write_only() -> None:
    store = FakeVaultStore()
    browser_router_module.set_vault_store_factory(lambda: store)
    try:
        async with AsyncClient(transport=ASGITransport(app=build_app()), base_url="test://x") as client:
            created = await client.post("/api/browser/vault", json={
                "label": "Example 登录", "username": "alice", "password": "s3cret!",
                "url": "https://example.com"})
            assert created.status_code == 200
            entry = created.json()
            assert entry["label"] == "Example 登录" and entry["username"] == "alice"
            assert "s3cret!" not in created.text  # password never echoed

            listing = await client.get("/api/browser/vault")
            assert "s3cret!" not in listing.text
            entries = listing.json()["entries"]
            assert len(entries) == 1 and entries[0]["id"] == entry["id"]
            assert entries[0]["kind"] == "login"

            removed = await client.delete(f"/api/browser/vault/{entry['id']}")
            assert removed.status_code == 200
            gone = await client.delete(f"/api/browser/vault/{entry['id']}")
            assert gone.status_code == 404
    finally:
        browser_router_module.set_vault_store_factory(None)

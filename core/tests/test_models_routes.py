"""C5 B4 — provider/model management routes (routes.py) behind the server app."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from atlas import config
from atlas.server import app


EVIL_ORIGIN = "https://evil.example"

# contract: list_keys entries carry metadata + pool state only, never the secret
ALLOWED_KEY_FIELDS = {"id", "label", "added_at", "cooldown_until", "last_error", "request_count"}
SECRET_FIELDS = {"secret", "api_key", "key", "runtime_api_key", "password"}
API_TOKEN_HEADER = "X-Atlas-Api-Token"


@pytest.fixture(autouse=True)
def isolated_atlas_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep server tests off machine-local config and external MCP processes."""
    data_root = tmp_path / "atlas-data"
    config_path = tmp_path / "config" / "atlas.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "[scheduler]\nenabled = false\n\n[tools]\nauto_start = []\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)
    monkeypatch.setattr(config, "DATA_ROOT", data_root)
    monkeypatch.setattr(config, "USER_SETTINGS_PATH", data_root / "data" / "user-settings.json")
    monkeypatch.setattr(config, "_config", None)


@pytest.fixture(autouse=True)
def restore_app_services():
    """Snapshot ``app.state.services`` around every test.

    The ``client`` fixture drives the shared app's real lifespan, which
    repopulates the container in place (fresh managers, ``startup``, the W10
    services) and whose shutdown restores routes but never the container
    slots. Without this restore every service built inside ``tmp_path`` leaks
    into later tests in the process — dead stores bound to deleted dirs.
    """
    from dataclasses import fields

    from atlas.api.app_services import AppServices

    services = app.state.services
    snapshot = {f.name: getattr(services, f.name) for f in fields(AppServices)}
    runtime_manager = services.runtime_mgr
    yield
    for field in fields(AppServices):
        setattr(services, field.name, snapshot[field.name])
    # create_app bound the container to its runtime manager; the lifespan's
    # shutdown path clears that back-reference, so restore the import-time one.
    runtime_manager.services = services


@pytest.fixture
async def client(monkeypatch):
    """Async test client using httpx + ASGI transport with lifespan."""
    import asyncio
    import os

    for key in ("OPENAI_API_BASE", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    old_val = os.environ.get("ATLAS_SCHEDULER_ENABLED")
    os.environ["ATLAS_SCHEDULER_ENABLED"] = "false"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        from atlas.server import lifespan

        async with lifespan(app):
            yield ac

    current_task = asyncio.current_task()
    pending_tasks = [
        task for task in asyncio.all_tasks()
        if task is not current_task and not task.done()
    ]
    assert not pending_tasks, [
        f"{task.get_name()}: {task.get_coro().__qualname__}"
        for task in pending_tasks
    ]

    if old_val is None:
        os.environ.pop("ATLAS_SCHEDULER_ENABLED", None)
    else:
        os.environ["ATLAS_SCHEDULER_ENABLED"] = old_val


@pytest.fixture
def fake_keyring(monkeypatch: pytest.MonkeyPatch) -> dict[tuple[str, str], str]:
    """In-memory OS keyring — add_key writes here, resolve_api_key reads here."""
    import keyring

    store: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(
        keyring, "set_password",
        lambda service, account, value: store.__setitem__((service, account), value),
    )
    monkeypatch.setattr(
        keyring, "get_password",
        lambda service, account: store.get((service, account)),
    )
    monkeypatch.setattr(
        keyring, "delete_password",
        lambda service, account: store.pop((service, account), None),
    )
    return store


def _settings() -> dict[str, Any]:
    return config.load_user_settings()


def _assert_no_secret(text: str, secrets: list[str]) -> None:
    for secret in secrets:
        assert secret not in text


# ---------------------------------------------------------------------------
# GET /api/providers
# ---------------------------------------------------------------------------


async def test_providers_list_has_full_catalog_without_secrets(client: AsyncClient) -> None:
    resp = await client.get("/api/providers")
    assert resp.status_code == 200
    providers = resp.json()
    assert len(providers) == 16
    by_id = {p["id"]: p for p in providers}
    assert "deepseek" in by_id and "siliconflow" in by_id and "custom" in by_id
    for provider in providers:
        assert provider["label"]  # 中文标签
        assert provider["hermes_provider"]
        assert provider["api_mode"] in {"openai", "anthropic_messages"}
        assert provider["docs_url"] == "" or provider["docs_url"].startswith("http")
        assert isinstance(provider["configured"], bool)
        assert isinstance(provider["keys"], list)
        assert not SECRET_FIELDS & set(provider)
    deepseek = by_id["deepseek"]
    assert deepseek["base_url"] == deepseek["default_base_url"]
    assert deepseek["key_count"] == 0


# ---------------------------------------------------------------------------
# PUT /api/providers/{pid}/config
# ---------------------------------------------------------------------------


async def test_put_provider_config_overrides_base_url_and_persists(client: AsyncClient) -> None:
    resp = await client.put(
        "/api/providers/deepseek/config",
        json={"base_url": "https://api.deepseek.example/v1"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    listing = (await client.get("/api/providers")).json()
    deepseek = next(p for p in listing if p["id"] == "deepseek")
    assert deepseek["base_url"] == "https://api.deepseek.example/v1"
    assert deepseek["configured"] is True  # base_url 覆盖也算已配置
    assert _settings()["providers"]["deepseek"]["base_url"] == "https://api.deepseek.example/v1"


async def test_put_provider_config_rejects_bad_url_and_unknown_provider(client: AsyncClient) -> None:
    bad = await client.put("/api/providers/deepseek/config", json={"base_url": "ftp://nope"})
    assert bad.status_code == 422
    unknown = await client.put("/api/providers/no-such/config", json={"base_url": None})
    assert unknown.status_code == 404


# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------


async def test_add_key_returns_metadata_only_and_never_leaks_secret(
    client: AsyncClient, fake_keyring: dict[tuple[str, str], str],
) -> None:
    secret = "sk-atlas-super-secret-42"
    resp = await client.post("/api/providers/deepseek/keys", json={"secret": secret, "label": "主密钥"})
    assert resp.status_code == 201
    created = resp.json()
    assert created["label"] == "主密钥"
    assert set(created) <= {"id", "label"}
    _assert_no_secret(resp.text, [secret])

    keys_body = (await client.get("/api/providers/deepseek/keys")).json()
    assert set(keys_body) == {"keys"}  # 前端按 {"keys": [...]} 包一层解析
    keys = keys_body["keys"]
    assert len(keys) == 1
    assert keys[0]["id"] == created["id"]
    assert keys[0]["label"] == "主密钥"
    assert set(keys[0]) <= ALLOWED_KEY_FIELDS
    assert not SECRET_FIELDS & set(keys[0])
    _assert_no_secret(json.dumps(keys), [secret])

    # 设置文件只存元数据，原文进了 keyring
    stored = _settings()["providers"]["deepseek"]["keys"]
    assert [k["id"] for k in stored] == [created["id"]]
    _assert_no_secret(json.dumps(_settings()), [secret])
    assert any(value == secret for value in fake_keyring.values())

    listing = (await client.get("/api/providers")).json()
    deepseek = next(p for p in listing if p["id"] == "deepseek")
    assert deepseek["configured"] is True
    assert deepseek["key_count"] == 1


async def test_add_key_requires_secret_and_known_provider(
    client: AsyncClient, fake_keyring: dict[tuple[str, str], str],
) -> None:
    empty = await client.post("/api/providers/deepseek/keys", json={"secret": "   "})
    assert empty.status_code == 422
    unknown = await client.post("/api/providers/no-such/keys", json={"secret": "x"})
    assert unknown.status_code == 404


async def test_add_key_keyring_failure_returns_500_without_ghost_slot(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """keyring 写失败 → 500；不留假 key 槽位（元数据/provider 配置/settings 均无痕）。"""
    import keyring

    def broken_set_password(service: str, account: str, value: str) -> None:
        raise RuntimeError("keyring backend unavailable")

    monkeypatch.setattr(keyring, "set_password", broken_set_password)

    resp = await client.post("/api/providers/deepseek/keys", json={"secret": "sk-ghost"})
    assert resp.status_code == 500
    assert "凭据库" in resp.json()["detail"]

    assert (await client.get("/api/providers/deepseek/keys")).json() == {"keys": []}
    assert _settings().get("providers", {}).get("deepseek") is None
    deepseek = next(
        p for p in (await client.get("/api/providers")).json() if p["id"] == "deepseek"
    )
    assert deepseek["configured"] is False
    assert deepseek["key_count"] == 0


async def test_delete_key_returns_204(client: AsyncClient, fake_keyring: dict[tuple[str, str], str]) -> None:
    created = (await client.post(
        "/api/providers/deepseek/keys", json={"secret": "sk-gone-soon"},
    )).json()
    resp = await client.delete(f"/api/providers/deepseek/keys/{created['id']}")
    assert resp.status_code == 204
    assert (await client.get("/api/providers/deepseek/keys")).json()["keys"] == []

    missing_key = await client.delete("/api/providers/deepseek/keys/k_absent")
    assert missing_key.status_code == 404
    missing_provider = await client.delete("/api/providers/no-such/keys/whatever")
    assert missing_provider.status_code == 404


# ---------------------------------------------------------------------------
# Custom model editing (M6)
# ---------------------------------------------------------------------------


async def _add_custom_model(client: AsyncClient, model_id: str) -> None:
    resp = await client.post("/api/models/custom", json={
        "id": model_id, "name": "旧名字", "provider": "deepseek",
        "litellm_model": "deepseek/deepseek-chat", "max_output_tokens": 4096,
    })
    assert resp.status_code == 200, resp.text


async def test_update_custom_model_changes_name_and_price_and_persists(client: AsyncClient) -> None:
    await _add_custom_model(client, "my-model")
    resp = await client.put("/api/models/custom/my-model", json={
        "name": "新名字",
        "price": {"input": 0.5, "output": 1.0, "cached_input": 0.01},
    })
    assert resp.status_code == 200, resp.text
    updated = resp.json()
    assert updated["name"] == "新名字"
    assert updated["price"] == {"input": 0.5, "output": 1.0, "cached_input": 0.01}

    models = (await client.get("/api/models")).json()["models"]
    entry = next(m for m in models if m["id"] == "my-model")
    assert entry["name"] == "新名字"
    assert entry["price"]["input"] == 0.5

    persisted = next(
        m for m in _settings()["custom_models"] if m["id"] == "my-model"
    )
    assert persisted["name"] == "新名字"
    assert persisted["price"]["output"] == 1.0


async def test_update_custom_model_unknown_id_404(client: AsyncClient) -> None:
    resp = await client.put("/api/models/custom/ghost", json={"name": "x"})
    assert resp.status_code == 404


async def test_delete_custom_model_returns_204_and_switches_selection(client: AsyncClient) -> None:
    await _add_custom_model(client, "doomed-model")
    selected = await client.post("/api/models/select", json={"model": "doomed-model"})
    assert selected.status_code == 200

    resp = await client.delete("/api/models/custom/doomed-model")
    assert resp.status_code == 204

    data = (await client.get("/api/models")).json()
    remaining = {m["id"] for m in data["models"]}
    assert "doomed-model" not in remaining
    assert data["current"] in remaining

    missing = await client.delete("/api/models/custom/doomed-model")
    assert missing.status_code == 404


# ---------------------------------------------------------------------------
# Reasoning stages
# ---------------------------------------------------------------------------


async def test_reasoning_stages_default_off_and_roundtrip(client: AsyncClient) -> None:
    default = (await client.get("/api/models/reasoning-stages")).json()
    assert default == {
        "enabled": False, "planning": "high", "execution": "medium", "verification": "high",
    }

    resp = await client.put("/api/models/reasoning-stages", json={"enabled": True, "execution": "low"})
    assert resp.status_code == 200
    assert resp.json()["enabled"] is True
    assert resp.json()["execution"] == "low"
    assert (await client.get("/api/models/reasoning-stages")).json()["enabled"] is True
    assert _settings()["reasoning_stages"]["execution"] == "low"


async def test_reasoning_stages_rejects_invalid_effort(client: AsyncClient) -> None:
    resp = await client.put("/api/models/reasoning-stages", json={"planning": "mega"})
    assert resp.status_code == 422
    assert "思考档位" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# OriginGuard coverage
# ---------------------------------------------------------------------------


async def test_providers_route_rejects_untrusted_origin(client: AsyncClient) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as raw:
        refused = await raw.get("/api/providers", headers={"Origin": EVIL_ORIGIN})
    assert refused.status_code == 403

    # 恶源 + 正确的 ATLAS_API_TOKEN（conftest 注入）仍可访问 —— 与既有路由的 Guard 语义一致。
    tokened = await client.get("/api/providers", headers={
        "Origin": EVIL_ORIGIN, API_TOKEN_HEADER: os.environ["ATLAS_API_TOKEN"],
    })
    assert tokened.status_code == 200


# ---------------------------------------------------------------------------
# POST /api/models/test
# ---------------------------------------------------------------------------


async def test_model_test_without_key_is_400_in_chinese(client: AsyncClient) -> None:
    resp = await client.post("/api/models/test", json={"model_id": "deepseek-v3"})
    assert resp.status_code == 400
    assert "密钥" in resp.json()["detail"]


async def test_model_test_unknown_model_404(client: AsyncClient) -> None:
    resp = await client.post("/api/models/test", json={"model_id": "ghost"})
    assert resp.status_code == 404


async def test_model_test_uses_provider_key_and_base_url(
    client: AsyncClient, fake_keyring: dict[tuple[str, str], str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """端点经共享模型路由出请求，不再自建 litellm 客户端。"""
    import agent.auxiliary_client as auxiliary_client

    secret = "sk-atlas-test-key"
    added = (await client.post(
        "/api/providers/deepseek/keys", json={"secret": secret, "label": "测试"},
    )).json()
    assert added["id"]

    deepseek = next(
        p for p in (await client.get("/api/providers")).json()
        if p["id"] == "deepseek"
    )

    calls: list[dict[str, Any]] = []

    def fake_call_llm(**kwargs: Any) -> Any:
        calls.append(kwargs)
        from types import SimpleNamespace

        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="OK"))])

    monkeypatch.setattr(auxiliary_client, "call_llm", fake_call_llm)
    resp = await client.post("/api/models/test", json={"model_id": "deepseek-v3"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert isinstance(body["latency_ms"], int)
    _assert_no_secret(resp.text, [secret])

    assert len(calls) == 1
    kwargs = calls[0]
    # bare wire id on the transport call: the litellm routing prefix never
    # reaches a provider (H10.2-DEFECT-1 — real relays 404 the prefixed form)
    assert kwargs["model"] == "deepseek-chat"
    assert kwargs["api_key"] == secret  # keyring 里的原文，请求内只此一处
    assert kwargs["max_tokens"] == 2
    assert kwargs["stream"] is False
    assert kwargs["base_url"] == deepseek["base_url"]
    assert kwargs["api_mode"] == "chat_completions"


async def test_model_test_reports_gateway_error(client: AsyncClient,
                                                fake_keyring: dict[tuple[str, str], str],
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    import agent.auxiliary_client as auxiliary_client

    await client.post("/api/providers/deepseek/keys", json={"secret": "sk-bad"})

    def failing_call_llm(**kwargs: Any) -> Any:
        raise RuntimeError("连接被拒绝")

    monkeypatch.setattr(auxiliary_client, "call_llm", failing_call_llm)
    resp = await client.post("/api/models/test", json={"model_id": "deepseek-v3"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "连接被拒绝" in body["error"]
    assert isinstance(body["latency_ms"], int)


async def test_connection_test_reports_sdk_exception_and_logs_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from atlas.api import models_settings_router
    from atlas.api.app_services import AppServices
    from atlas.api.models_settings_router import ConnectionTestRequest

    class ProviderAPIError(Exception):
        pass

    class FailingModelRouter:
        async def resolve(self, *_args: Any) -> object:
            return object()

        async def complete(self, *_args: Any, **_kwargs: Any) -> None:
            raise ProviderAPIError("provider request failed with status 429")

    class ModelManager:
        current_model = "test-model"
        model_router = FailingModelRouter()

        def list_models(self) -> list[dict[str, str]]:
            return [{"id": self.current_model}]

    logged: list[str] = []

    class CapturingLog:
        def exception(self, event: str, **_fields: Any) -> None:
            logged.append(event)

    monkeypatch.setattr(models_settings_router, "log", CapturingLog())
    result = await models_settings_router.test_connection(
        AppServices(model_mgr=ModelManager()), ConnectionTestRequest(model="test-model"),
    )

    assert result == {
        "ok": False, "model": "test-model",
        "message": "provider request failed with status 429",
    }
    assert logged == ["models.connection_test_failed"]

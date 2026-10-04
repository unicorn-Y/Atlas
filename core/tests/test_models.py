"""Tests for ModelManager — model selection, listing, favorites."""

from __future__ import annotations

import os

import pytest

from atlas.models import ModelManager


@pytest.fixture
def mgr(tmp_path, monkeypatch) -> ModelManager:
    """Create a ModelManager with default settings."""
    from atlas import config

    monkeypatch.setattr(config, "USER_SETTINGS_PATH", tmp_path / "user-settings.json")
    # Ensure env vars don't interfere
    return ModelManager(default_model="claude-sonnet-4")


class TestModelSelection:
    def test_default_model(self, mgr: ModelManager) -> None:
        assert mgr.current_model == "claude-sonnet-4"

    def test_select_valid(self, mgr: ModelManager) -> None:
        mgr.select("gpt-4o")
        assert mgr.current_model == "gpt-4o"

    def test_select_invalid_raises(self, mgr: ModelManager) -> None:
        with pytest.raises(ValueError, match="Unknown model"):
            mgr.select("nonexistent-model")

    def test_current_litellm_model(self, mgr: ModelManager) -> None:
        mgr.select("claude-opus-4")
        assert mgr.current_litellm_model == "anthropic/claude-opus-4-20250514"

        mgr.select("deepseek-v3")
        assert mgr.current_litellm_model == "deepseek/deepseek-chat"


class TestModelListing:
    def test_list_returns_all(self, mgr: ModelManager) -> None:
        models = mgr.list_models()
        ids = {m["id"] for m in models}
        assert "claude-opus-4" in ids
        assert "claude-sonnet-4" in ids
        assert "gpt-4o" in ids
        assert "gpt-4o-mini" in ids
        assert "claude-haiku-3.5" in ids
        assert "deepseek-v3" in ids
        assert "deepseek-r1" in ids

    def test_selected_flag(self, mgr: ModelManager) -> None:
        mgr.select("gpt-4o")
        models = mgr.list_models()
        selected = [m for m in models if m["selected"]]
        assert len(selected) == 1
        assert selected[0]["id"] == "gpt-4o"

    def test_favorites_first(self, mgr: ModelManager) -> None:
        """Favorites should appear before non-favorites."""
        models = mgr.list_models()
        fav_indices = [i for i, m in enumerate(models) if m["favorite"]]
        non_fav_indices = [i for i, m in enumerate(models) if not m["favorite"]]
        if fav_indices and non_fav_indices:
            assert max(fav_indices) < min(non_fav_indices)


class TestFavorites:
    def test_add_favorite(self, mgr: ModelManager) -> None:
        mgr.add_favorite("deepseek-v3")
        models = mgr.list_models()
        ds = next(m for m in models if m["id"] == "deepseek-v3")
        assert ds["favorite"] is True

    def test_remove_favorite(self, mgr: ModelManager) -> None:
        mgr.remove_favorite("gpt-4o")
        models = mgr.list_models()
        gpt = next(m for m in models if m["id"] == "gpt-4o")
        assert gpt["favorite"] is False


class TestCustomModels:
    def test_add_model(self, mgr: ModelManager) -> None:
        mgr.add_model({
            "id": "local-llama",
            "name": "Local Llama 3.1",
            "provider": "ollama",
            "litellm_model": "ollama/llama3.1",
            "category": "local",
        })
        models = mgr.list_models()
        ids = {m["id"] for m in models}
        assert "local-llama" in ids

        # Should be selectable
        mgr.select("local-llama")
        assert mgr.current_model == "local-llama"
        assert mgr.current_litellm_model == "ollama/llama3.1"


# ---------------------------------------------------------------------------
# C5 追加：服务商配置 / 密钥 / 自定义模型编辑 / list_models 附加元数据
# （追加式扩展；上方既有类与断言保持原样）
# ---------------------------------------------------------------------------

class FakeKeyringStore:
    """内存 dict 假 keyring，整体替换 atlas.telegram.KeyringCredentialStore。"""

    def __init__(self, store: dict) -> None:
        self._store = store

    def get(self, key: str) -> str | None:
        return self._store.get(key)

    def set(self, key: str, value: str) -> None:
        self._store[key] = value

    def delete(self, key: str) -> None:
        self._store.pop(key, None)


@pytest.fixture
def keyring_store(monkeypatch) -> dict:
    """返回内存凭据库 dict；Manager 的密钥原文都会写进这里（account=atlas.provider.<pid>.key.<key_id>）。"""
    import atlas.telegram as telegram_module

    store: dict = {}
    monkeypatch.setattr(telegram_module, "KeyringCredentialStore", lambda: FakeKeyringStore(store))
    return store


@pytest.fixture
def glm_model(mgr: ModelManager) -> str:
    mgr.add_model({
        "id": "glm-5.3",
        "name": "GLM-5.3",
        "provider": "zai",
        "litellm_model": "zai/glm-5.3",
        "category": "reasoning",
        "hermes_provider": "zai",
        "native_model": "glm-5.3",
    })
    return "glm-5.3"


class TestUpdateModel:
    def test_update_fields_effective_and_persisted(self, mgr: ModelManager, glm_model: str) -> None:
        updated = mgr.update_model("glm-5.3", {
            "name": "GLM-5.3 改",
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "max_output_tokens": 16384,
        })
        assert updated["name"] == "GLM-5.3 改"
        assert updated["base_url"] == "https://open.bigmodel.cn/api/paas/v4"
        assert updated["max_output_tokens"] == 16384

        # 重新加载（同一 settings 路径）验证已持久化
        reloaded = ModelManager(default_model="claude-sonnet-4")
        entry = next(m for m in reloaded.list_models() if m["id"] == "glm-5.3")
        assert entry["name"] == "GLM-5.3 改"
        assert entry["base_url"] == "https://open.bigmodel.cn/api/paas/v4"
        assert entry["max_output_tokens"] == 16384

    def test_update_unknown_id_raises(self, mgr: ModelManager) -> None:
        with pytest.raises(ValueError, match="未知模型"):
            mgr.update_model("no-such-model", {"name": "x"})

    def test_update_builtin_rejected(self, mgr: ModelManager) -> None:
        with pytest.raises(ValueError, match="自定义"):
            mgr.update_model("claude-opus-4", {"name": "x"})

    def test_update_unknown_provider_raises(self, mgr: ModelManager, glm_model: str) -> None:
        with pytest.raises(ValueError, match="未知服务商"):
            mgr.update_model("glm-5.3", {"hermes_provider": "not-a-provider"})

    def test_update_accepts_alias_hermes_provider(self, mgr: ModelManager) -> None:
        """qwen 模型的 hermes_provider 是 alibaba（hermes id ≠ catalog id）；编辑不得误判未知服务商。"""
        mgr.add_model({
            "id": "qwen3-max",
            "name": "Qwen3 Max",
            "provider": "qwen",
            "litellm_model": "qwen/qwen3-max",
            "category": "flagship",
            "hermes_provider": "alibaba",
            "native_model": "qwen3-max",
        })
        # 前端 buildUpdatePatch() 回传模型已有的 hermes_provider（此处为 hermes id "alibaba"）
        updated = mgr.update_model("qwen3-max", {
            "name": "Qwen3 Max 改",
            "base_url": None,
            "litellm_model": "qwen/qwen3-max",
            "native_model": "qwen3-max",
            "hermes_provider": "alibaba",
            "capabilities": {},
        })
        assert updated["name"] == "Qwen3 Max 改"
        assert updated["hermes_provider"] == "alibaba"  # 存储/返回仍是 hermes id
        reloaded = ModelManager(default_model="claude-sonnet-4")
        entry = next(m for m in reloaded.list_models() if m["id"] == "qwen3-max")
        assert entry["hermes_provider"] == "alibaba"


class TestDeleteModel:
    def test_delete_selected_switches_to_first(self, mgr: ModelManager, glm_model: str) -> None:
        mgr.select("glm-5.3")
        assert mgr.current_model == "glm-5.3"
        mgr.delete_model("glm-5.3")
        assert all(m["id"] != "glm-5.3" for m in mgr.list_models())
        assert mgr.current_model == "claude-opus-4"  # 列表第一个（DEFAULT_MODELS[0]）
        # 持久化：重载后选中项回落到列表第一个
        reloaded = ModelManager()
        assert reloaded.current_model == "claude-opus-4"

    def test_delete_non_selected_keeps_selection(self, mgr: ModelManager, glm_model: str) -> None:
        mgr.select("claude-opus-4")
        mgr.delete_model("glm-5.3")
        assert mgr.current_model == "claude-opus-4"

    def test_delete_unknown_or_builtin_raises(self, mgr: ModelManager) -> None:
        with pytest.raises(ValueError, match="未知模型"):
            mgr.delete_model("no-such-model")
        with pytest.raises(ValueError, match="自定义"):
            mgr.delete_model("gpt-4o")


class TestProviderKeys:
    def test_add_key_writes_keyring_metadata_only(self, mgr: ModelManager, keyring_store: dict) -> None:
        import json

        from atlas.config import load_user_settings

        added = mgr.add_key("zai", "sk-zai-123", "主密钥")
        assert added["id"].startswith("k_")
        assert added["label"] == "主密钥"
        account = f"atlas.provider.zai.key.{added['id']}"
        assert keyring_store[account] == "sk-zai-123"  # 原文只进凭据库
        assert mgr.list_keys("zai") == [{
            "id": added["id"], "label": "主密钥",
            "cooldown_until": None, "last_error": None, "request_count": 0,
        }]
        # settings 文件里不落原文
        assert "sk-zai-123" not in json.dumps(load_user_settings(), ensure_ascii=False)

    def test_remove_key_clears_metadata_and_keyring(self, mgr: ModelManager, keyring_store: dict) -> None:
        added = mgr.add_key("deepseek", "sk-ds-1")
        mgr.remove_key("deepseek", added["id"])
        assert mgr.list_keys("deepseek") == []
        assert f"atlas.provider.deepseek.key.{added['id']}" not in keyring_store

    def test_key_errors(self, mgr: ModelManager, keyring_store: dict) -> None:
        with pytest.raises(ValueError, match="未知服务商"):
            mgr.add_key("no-such-provider", "sk-x")
        with pytest.raises(ValueError, match="密钥内容不能为空"):
            mgr.add_key("zai", "   ")
        added = mgr.add_key("zai", "sk-zai-1")
        with pytest.raises(ValueError, match="未知密钥"):
            mgr.remove_key("zai", "k_deadbe")
        assert mgr.list_keys("zai")[0]["id"] == added["id"]

    def test_provider_config_base_url_override(self, mgr: ModelManager, keyring_store: dict) -> None:
        assert mgr.provider_config("zai") == {}
        mgr.update_provider_config("zai", "https://open.bigmodel.cn/api/paas/v4/")
        assert mgr.provider_config("zai") == {"base_url": "https://open.bigmodel.cn/api/paas/v4", "keys": []}
        mgr.update_provider_config("zai", None)
        assert mgr.provider_config("zai") == {}
        with pytest.raises(ValueError, match="未知服务商"):
            mgr.update_provider_config("no-such-provider", "https://x.example")


class TestResolveApiKey:
    def test_returns_first_non_cooldown_key(self, mgr: ModelManager, keyring_store: dict) -> None:
        import time as _time

        k1 = mgr.add_key("deepseek", "sk-1")
        k2 = mgr.add_key("deepseek", "sk-2")
        assert mgr.resolve_api_key("deepseek") == "sk-1"
        # key1 冷却中 → 返回 key2
        mgr._providers["deepseek"]["keys"][0]["cooldown_until"] = _time.time() + 999
        assert mgr.resolve_api_key("deepseek") == "sk-2"
        # 全部冷却 → None
        mgr._providers["deepseek"]["keys"][1]["cooldown_until"] = _time.time() + 999
        assert mgr.resolve_api_key("deepseek") is None
        # 冷却到期（cooldown_until 已成过去时）恢复
        for key in mgr._providers["deepseek"]["keys"]:
            key["cooldown_until"] = _time.time() - 1
        assert mgr.resolve_api_key("deepseek") == "sk-1"
        assert k1 and k2  # 元数据 id 仅用于构造冷却状态

    def test_unconfigured_provider_returns_none(self, mgr: ModelManager, keyring_store: dict) -> None:
        assert mgr.resolve_api_key("zai") is None

    def test_pool_requires_two_keys(self, mgr: ModelManager, keyring_store: dict) -> None:
        assert mgr.credential_pool("deepseek") is None  # 无配置
        mgr.add_key("deepseek", "sk-1")
        assert mgr.credential_pool("deepseek") is None  # 仅 1 把 key


class TestListModelMetadata:
    def test_capabilities_models_dev_with_manual_override(
        self, mgr: ModelManager, monkeypatch, glm_model: str,
    ) -> None:
        from atlas.models import models_dev as models_dev_module

        def fake_caps(provider, model, *, allow_network=False):
            return models_dev_module.ModelCapabilities(
                supports_tools=True, supports_vision=False, supports_reasoning=True,
                context_window=200000, max_output_tokens=32000, model_family="glm",
            )

        monkeypatch.setattr(models_dev_module, "get_model_capabilities", fake_caps)
        mgr.update_model("glm-5.3", {"capabilities": {"context_window": 128000, "supports_vision": True}})
        entry = next(m for m in mgr.list_models() if m["id"] == "glm-5.3")
        # models.dev 打底 ← 手填 capabilities 覆盖
        assert entry["capabilities"] == {
            "supports_tools": True, "supports_vision": True, "supports_reasoning": True,
            "context_window": 128000, "max_output_tokens": 32000,
        }
        assert entry["reasoning_efforts"] == ["none", "minimal", "low", "medium", "high", "xhigh", "max"]
        # 无 hermes_provider 的默认模型走 provider 字段兜底（additive，不破坏既有字段）
        ds = next(m for m in mgr.list_models() if m["id"] == "deepseek-v3")
        assert ds["capabilities"]["supports_tools"] is True
        assert ds["reasoning_efforts"] is None

    def test_capabilities_none_when_unknown(self, mgr: ModelManager, monkeypatch) -> None:
        from atlas.models import models_dev as models_dev_module

        monkeypatch.setattr(models_dev_module, "get_model_capabilities", lambda *a, **k: None)
        unknown = next(m for m in mgr.list_models() if m["id"] == "gpt-4o-mini")
        assert unknown["capabilities"] is None
        assert unknown["reasoning_efforts"] is None


class TestLegacySettings:
    def test_settings_without_providers_key(self, tmp_path, monkeypatch, keyring_store: dict) -> None:
        import json

        from atlas import config

        settings_path = tmp_path / "legacy-settings.json"
        settings_path.write_text(json.dumps({
            "custom_models": [{
                "id": "legacy-1", "name": "旧模型", "provider": "deepseek",
                "litellm_model": "deepseek/deepseek-chat", "custom": True,
            }],
            "selected_model": "legacy-1",
            "gateway_base_url": "https://gw.example",
            "api_key": "sk-legacy",
        }), encoding="utf-8")
        monkeypatch.setattr(config, "USER_SETTINGS_PATH", settings_path)

        m = ModelManager()
        assert m.current_model == "legacy-1"
        assert m.provider_config("deepseek") == {}
        assert m.resolve_api_key("deepseek") is None
        assert m.credential_pool("deepseek") is None
        # 扩展功能在旧 settings 上照常可用
        added = m.add_key("deepseek", "sk-new")
        assert m.resolve_api_key("deepseek") == "sk-new"
        assert added["id"].startswith("k_")

    def test_malformed_providers_key_tolerated(self, tmp_path, monkeypatch) -> None:
        import json

        from atlas import config

        settings_path = tmp_path / "broken-settings.json"
        settings_path.write_text(json.dumps({
            "providers": "garbage",
            "custom_models": [{"id": "legacy-2", "name": "旧模型", "litellm_model": "x/y", "custom": True}],
        }), encoding="utf-8")
        monkeypatch.setattr(config, "USER_SETTINGS_PATH", settings_path)
        m = ModelManager()
        assert m.provider_config("deepseek") == {}


class TestProviderIdNamespaceAlias:
    """settings 按 catalog id 存储；模型条目/调用方可能传 hermes id（qwen→alibaba 等）。"""

    def test_hermes_id_alias_resolves_to_catalog_entry(
        self, mgr: ModelManager, keyring_store: dict,
    ) -> None:
        mgr.add_key("qwen", "sk-qwen-1")           # routes/UI 用 catalog id 写入
        assert mgr.resolve_api_key("alibaba") == "sk-qwen-1"   # hermes id 读出
        assert mgr.resolve_api_key("qwen") == "sk-qwen-1"
        assert mgr.provider_config("alibaba")["keys"]
        mgr.update_provider_config("alibaba", "https://dashscope.example/v1")
        assert mgr.provider_config("qwen")["base_url"] == "https://dashscope.example/v1"

    def test_resolve_catalog_id_bidirectional(self) -> None:
        from atlas.models.catalog import resolve_catalog_id

        assert resolve_catalog_id("qwen") == "qwen"
        assert resolve_catalog_id("alibaba") == "qwen"
        assert resolve_catalog_id("kimi-coding") == "kimi"
        assert resolve_catalog_id("unknown-x") is None
        assert resolve_catalog_id("") is None


class TestGatewaySource:
    def test_user_settings_base_wins_and_is_reported(self, tmp_path, monkeypatch) -> None:
        """user-settings.json 是设置界面持久化的存储，静默压过 atlas.toml；
        ModelManager 必须如实报告生效来源，冲突可被 API/日志暴露。"""
        from atlas import config

        settings_path = tmp_path / "user-settings.json"
        settings_path.write_text(
            '{"gateway_base_url": "https://ui-gateway.example/v1", "api_key": "sk-ui"}',
            encoding="utf-8",
        )
        monkeypatch.setattr(config, "USER_SETTINGS_PATH", settings_path)
        mgr = ModelManager(default_model="claude-sonnet-4")
        assert mgr.gateway_base_url == "https://ui-gateway.example/v1"
        assert mgr.gateway_source == "user-settings"
        assert mgr.atlas_toml_gateway_base_url == config.get_config().gateway_base_url
        assert mgr.gateway_base_url != mgr.atlas_toml_gateway_base_url

    def test_atlas_toml_used_when_no_user_setting(self, tmp_path, monkeypatch) -> None:
        from atlas import config

        settings_path = tmp_path / "user-settings.json"
        settings_path.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(config, "USER_SETTINGS_PATH", settings_path)
        mgr = ModelManager(default_model="claude-sonnet-4")
        assert mgr.gateway_source == "atlas.toml"
        assert mgr.gateway_base_url == config.get_config().gateway_base_url
        assert mgr.atlas_toml_gateway_base_url == mgr.gateway_base_url

    def test_update_provider_marks_user_settings_source(self, tmp_path, monkeypatch) -> None:
        from atlas import config

        settings_path = tmp_path / "user-settings.json"
        settings_path.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(config, "USER_SETTINGS_PATH", settings_path)
        mgr = ModelManager(default_model="claude-sonnet-4")
        mgr.update_provider("https://new.example/v1", None)
        assert mgr.gateway_source == "user-settings"
        assert mgr.gateway_base_url == "https://new.example/v1"

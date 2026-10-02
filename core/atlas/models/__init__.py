"""Atlas Model Manager — manual model selection + LiteLLM unified proxy."""

from __future__ import annotations

import os
import secrets
import time
from datetime import datetime, timezone
from typing import Any

import structlog

from atlas.config import get_config, load_user_settings, save_user_settings
from atlas.models import catalog as _catalog
from atlas.models import models_dev as _models_dev
from atlas.models import reasoning_effort as _reasoning_effort

log = structlog.get_logger()

# 手填 capabilities 只允许这组规范字段（C5 契约 §1），其余键丢弃。
_CAPABILITY_FIELDS = ("context_window", "max_output_tokens", "supports_vision", "supports_tools", "supports_reasoning")
# 模型编辑（M6）允许修改的字段；id 与 custom 标记不可改，密钥不在这里改。
_MODEL_PATCH_FIELDS = ("name", "base_url", "litellm_model", "native_model", "hermes_provider", "max_output_tokens", "price", "capabilities")

# Default model configurations
DEFAULT_MODELS: list[dict[str, Any]] = [
    {
        "id": "claude-opus-4",
        "name": "Claude Opus 4",
        "provider": "anthropic",
        "litellm_model": "anthropic/claude-opus-4-20250514",
        "category": "flagship",
    },
    {
        "id": "claude-sonnet-4",
        "name": "Claude Sonnet 4",
        "provider": "anthropic",
        "litellm_model": "anthropic/claude-sonnet-4-20250514",
        "category": "balanced",
    },
    {
        "id": "gpt-4o",
        "name": "GPT-4o",
        "provider": "openai",
        "litellm_model": "openai/gpt-4o",
        "category": "balanced",
    },
    {
        "id": "gpt-4o-mini",
        "name": "GPT-4o Mini",
        "provider": "openai",
        "litellm_model": "openai/gpt-4o-mini",
        "category": "fast",
    },
    {
        "id": "claude-haiku-3.5",
        "name": "Claude 3.5 Haiku",
        "provider": "anthropic",
        "litellm_model": "anthropic/claude-3-5-haiku-20241022",
        "category": "fast",
    },
    {
        "id": "deepseek-v3",
        "name": "DeepSeek V3",
        "provider": "deepseek",
        "litellm_model": "deepseek/deepseek-chat",
        "category": "balanced",
    },
    {
        "id": "deepseek-r1",
        "name": "DeepSeek R1",
        "provider": "deepseek",
        "litellm_model": "deepseek/deepseek-reasoner",
        "category": "reasoning",
    },
]


class ModelManager:
    """Manages available models and the user's current selection.

    No auto-routing — the user picks the model manually.
    LiteLLM handles the actual API call unification.
    """

    def __init__(self, default_model: str | None = None) -> None:
        cfg = get_config()
        settings = load_user_settings()
        self._models: list[dict[str, Any]] = list(DEFAULT_MODELS)
        custom_models = settings.get("custom_models", [])
        if not isinstance(custom_models, list):
            custom_models = []
        self._current: str = default_model or str(settings.get("selected_model") or cfg.default_model)
        self._favorites: set[str] = {"claude-opus-4", "claude-sonnet-4", "gpt-4o"}
        self._api_base = str(settings.get("gateway_base_url") or cfg.gateway_base_url)
        self._api_key = str(settings.get("api_key") or cfg.gateway_api_key)
        # 服务商配置（base_url 覆盖 + 密钥元数据；密钥原文在系统凭据库，见 add_key）。
        self._providers: dict[str, dict[str, Any]] = self._load_providers(settings)

        # Config-defined models are loaded but are not copied to user preferences.
        for custom in cfg.custom_models:
            if custom.get("id"):
                self._models.append({**custom, "custom": False})
        for custom in custom_models:
            if custom.get("id") and not any(model["id"] == custom["id"] for model in self._models):
                self.add_model(custom, persist=False)

        # Configure LiteLLM to use gateway
        self._apply_provider_environment()

        log.info("model_manager.init", default=self._current, api_base=self._api_base)

    def _apply_provider_environment(self) -> None:
        if self._api_base:
            os.environ["OPENAI_API_BASE"] = self._api_base
        if self._api_key:
            os.environ["OPENAI_API_KEY"] = self._api_key
            os.environ["ANTHROPIC_API_KEY"] = self._api_key

    @property
    def gateway_base_url(self) -> str:
        return self._api_base

    @property
    def api_key_configured(self) -> bool:
        return bool(self._api_key)

    def update_provider(self, base_url: str, api_key: str | None) -> None:
        self._api_base = base_url.rstrip("/")
        if api_key:
            self._api_key = api_key
        self._apply_provider_environment()
        self._persist_settings()

    def _persist_settings(self) -> None:
        current = load_user_settings()
        current.update({
            "gateway_base_url": self._api_base,
            "api_key": self._api_key,
            "selected_model": self._current,
            "custom_models": [model for model in self._models if model.get("custom")],
            "providers": self._providers,
        })
        save_user_settings(current)

    @property
    def current_model(self) -> str:
        return self._current

    @property
    def current_litellm_model(self) -> str:
        """Return the LiteLLM model string for the currently selected model."""
        for m in self._models:
            if m["id"] == self._current:
                return m["litellm_model"]
        return self._current  # fallback: use raw ID

    def select(self, model_id: str) -> None:
        """Switch the active model."""
        valid_ids = {m["id"] for m in self._models}
        if model_id not in valid_ids:
            raise ValueError(f"Unknown model: {model_id}. Available: {valid_ids}")
        self._current = model_id
        self._persist_settings()
        log.info("model_manager.select", model=model_id)

    def list_models(self) -> list[dict[str, Any]]:
        """Return all available models with favorite status."""
        result = []
        for m in self._models:
            result.append({
                **m,
                "favorite": m["id"] in self._favorites,
                "selected": m["id"] == self._current,
                # 附加字段（additive）：models.dev（allow_network=False）← 模型条目手填 capabilities 覆盖。
                "capabilities": self._model_capabilities(m),
                "reasoning_efforts": self._model_reasoning_efforts(m),
            })
        # Favorites first, then alphabetical
        result.sort(key=lambda x: (not x["favorite"], x["name"]))
        return result

    def add_favorite(self, model_id: str) -> None:
        self._favorites.add(model_id)

    def remove_favorite(self, model_id: str) -> None:
        self._favorites.discard(model_id)

    def add_model(self, model: dict[str, Any], persist: bool = True) -> None:
        """Register a custom model."""
        if any(existing["id"] == model.get("id") for existing in self._models):
            raise ValueError(f"Model already exists: {model.get('id')}")
        self._models.append({**model, "custom": True})
        if persist:
            self._persist_settings()
        log.info("model_manager.add_model", model_id=model.get("id"))

    # ------------------------------------------------------------------
    # 服务商配置与密钥（C5；密钥原文只进系统凭据库，settings 只存元数据）
    # ------------------------------------------------------------------

    @staticmethod
    def _load_providers(settings: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """settings["providers"] → 规范化的内存态；旧 settings 无该键时为空表。"""
        raw = settings.get("providers")
        if not isinstance(raw, dict):
            return {}
        providers: dict[str, dict[str, Any]] = {}
        for pid, entry in raw.items():
            if not isinstance(entry, dict):
                continue
            keys = entry.get("keys")
            providers[str(pid)] = {
                "base_url": entry.get("base_url") or None,
                "keys": [key for key in keys if isinstance(key, dict)] if isinstance(keys, list) else [],
            }
        return providers

    @staticmethod
    def _require_provider(provider_id: str) -> str:
        """mutator 类方法用的校验：必须是 catalog 里的服务商 id（接受 hermes id 别名）。"""
        pid = _catalog.resolve_catalog_id(str(provider_id or "").strip()) or str(provider_id or "").strip()
        if _catalog.get_provider(pid) is None:
            raise ValueError(f"未知服务商: {pid}")
        return pid

    @staticmethod
    def _keyring_account(provider_id: str, key_id: str) -> str:
        return f"atlas.provider.{provider_id}.key.{key_id}"

    @staticmethod
    def _credential_store() -> Any:
        # 函数内 import：tests 可整体 monkeypatch atlas.telegram.KeyringCredentialStore。
        from atlas.telegram import KeyringCredentialStore

        return KeyringCredentialStore()

    def provider_config(self, provider_id: str) -> dict:
        """服务商配置 {"base_url":..., "keys":[...]}；未配置过返回 {}（读取路径不抛错）。"""
        pid = _catalog.resolve_catalog_id(str(provider_id or "").strip()) or str(provider_id or "").strip()
        entry = self._providers.get(pid)
        if not entry:
            return {}
        return {"base_url": entry.get("base_url"), "keys": [dict(key) for key in entry.get("keys", [])]}

    def update_provider_config(self, provider_id: str, base_url: str | None) -> None:
        """设置/清除服务商的 base_url 覆盖（None = 回退 catalog 默认）。"""
        pid = self._require_provider(provider_id)
        url = str(base_url).strip().rstrip("/") if base_url and str(base_url).strip() else None
        entry = self._providers.setdefault(pid, {"base_url": None, "keys": []})
        entry["base_url"] = url
        if not url and not entry["keys"]:
            self._providers.pop(pid, None)
        self._persist_settings()
        log.info("model_manager.provider_config_updated", provider=pid)

    def add_key(self, provider_id: str, secret: str, label: str = "") -> dict:
        """新增密钥：原文写入系统凭据库，settings 只留 {"id","label","added_at"} 元数据。"""
        pid = self._require_provider(provider_id)
        secret = str(secret or "").strip()
        if not secret:
            raise ValueError("密钥内容不能为空")
        entry = self._providers.setdefault(pid, {"base_url": None, "keys": []})
        existing = {str(key.get("id")) for key in entry["keys"]}
        key_id = f"k_{secrets.token_hex(3)}"
        while key_id in existing:
            key_id = f"k_{secrets.token_hex(3)}"
        meta = {
            "id": key_id,
            "label": str(label or "").strip(),
            "added_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        try:
            self._credential_store().set(self._keyring_account(pid, key_id), secret)
        except Exception as exc:  # 凭据库缺失/失败不崩：留元数据，resolve 时读不到即跳过
            log.warning("model_manager.keyring_write_failed", provider=pid, key_id=key_id, error=str(exc))
        entry["keys"].append(meta)
        self._persist_settings()
        log.info("model_manager.key_added", provider=pid, key_id=key_id)
        return {"id": key_id, "label": meta["label"]}

    def remove_key(self, provider_id: str, key_id: str) -> None:
        """删除密钥：凭据库条目 best-effort 清除 + settings 元数据移除。"""
        pid = self._require_provider(provider_id)
        entry = self._providers.get(pid)
        keys = (entry or {}).get("keys", [])
        remaining = [key for key in keys if str(key.get("id")) != str(key_id)]
        if len(remaining) == len(keys):
            raise ValueError(f"未知密钥: {key_id}")
        try:
            self._credential_store().delete(self._keyring_account(pid, str(key_id)))
        except Exception as exc:  # 同上：凭据库失败不阻断元数据清理
            log.warning("model_manager.keyring_delete_failed", provider=pid, key_id=key_id, error=str(exc))
        entry["keys"] = remaining
        if not remaining and not entry.get("base_url"):
            self._providers.pop(pid, None)
        self._persist_settings()
        log.info("model_manager.key_removed", provider=pid, key_id=key_id)

    def list_keys(self, provider_id: str) -> list[dict]:
        """密钥元数据 + 池状态（无原文）；供 B4 的 GET /api/providers/{pid}/keys 使用。"""
        pid = self._require_provider(provider_id)
        return [
            {
                "id": str(key.get("id") or ""),
                "label": str(key.get("label") or ""),
                "cooldown_until": key.get("cooldown_until"),
                "last_error": key.get("last_error"),
                "request_count": int(key.get("request_count") or 0),
            }
            for key in self._providers.get(pid, {}).get("keys", [])
        ]

    def resolve_api_key(self, provider_id: str) -> str | None:
        """池中首个非冷却 key 的原文（keyring 读取）；无可用 key / 未配置返回 None。"""
        pid = _catalog.resolve_catalog_id(str(provider_id or "").strip()) or ""
        keys = self._providers.get(pid, {}).get("keys", [])
        now = time.time()
        store: Any = None
        for key in keys:
            cooldown = key.get("cooldown_until")
            if isinstance(cooldown, (int, float)) and cooldown > now:
                continue
            key_id = str(key.get("id") or "")
            if not key_id:
                continue
            if store is None:
                try:
                    store = self._credential_store()
                except Exception as exc:
                    log.warning("model_manager.keyring_unavailable", error=str(exc))
                    return None
            try:
                secret = store.get(self._keyring_account(pid, key_id))
            except Exception as exc:
                log.warning("model_manager.keyring_read_failed", provider=pid, key_id=key_id, error=str(exc))
                continue
            if secret:
                return str(secret)
        return None

    def credential_pool(self, provider_id: str) -> Any | None:
        """B2 的 AtlasCredentialPool；该服务商 keys<2 或未配置时返回 None。

        函数内 import：credentials 模块由并行组 B2 提供，避免无谓的启动期依赖。
        """
        pid = _catalog.resolve_catalog_id(str(provider_id or "").strip()) or ""
        if len(self._providers.get(pid, {}).get("keys", [])) < 2:
            return None
        from atlas.models.credentials import AtlasCredentialPool  # noqa: PLC0415 — B2 模块

        return AtlasCredentialPool(pid)

    # ------------------------------------------------------------------
    # 自定义模型编辑/删除（M6）
    # ------------------------------------------------------------------

    def _find_model(self, model_id: str) -> dict[str, Any] | None:
        return next((m for m in self._models if m["id"] == model_id), None)

    def update_model(self, model_id: str, patch: dict) -> dict:
        """编辑自定义模型（仅 custom 模型；id/custom 标记与密钥不在此改）。返回更新后条目。"""
        target = self._find_model(model_id)
        if target is None:
            raise ValueError(f"未知模型: {model_id}")
        if not target.get("custom"):
            raise ValueError("仅支持编辑自定义模型")
        patch = patch if isinstance(patch, dict) else {}
        hermes_pid = patch.get("hermes_provider")
        if hermes_pid and _catalog.get_provider(str(hermes_pid)) is None:
            raise ValueError(f"未知服务商: {hermes_pid}")
        for field in _MODEL_PATCH_FIELDS:
            if field not in patch:
                continue
            value = patch[field]
            if field in ("name", "base_url", "litellm_model", "native_model", "hermes_provider"):
                target[field] = str(value).strip() if value is not None else None
            else:
                target[field] = value
        self._persist_settings()
        log.info("model_manager.update_model", model_id=model_id)
        return dict(target)

    def delete_model(self, model_id: str) -> None:
        """删除自定义模型；若删除的是当前选中模型则自动切到列表第一个。"""
        target = self._find_model(model_id)
        if target is None:
            raise ValueError(f"未知模型: {model_id}")
        if not target.get("custom"):
            raise ValueError("仅支持删除自定义模型")
        self._models.remove(target)
        if self._current == model_id and self._models:
            self._current = self._models[0]["id"]
            log.info("model_manager.selection_reset", model=self._current)
        self._persist_settings()
        log.info("model_manager.delete_model", model_id=model_id)

    # ------------------------------------------------------------------
    # list_models 附加元数据（capabilities / reasoning_efforts）
    # ------------------------------------------------------------------

    @staticmethod
    def _native_model_id(model: dict[str, Any]) -> str:
        """原生模型 id：手填 native_model 优先，否则剥掉 litellm_model 的第一段前缀。"""
        native = str(model.get("native_model") or "").strip()
        if native:
            return native
        litellm = str(model.get("litellm_model") or "").strip()
        return litellm.split("/", 1)[1] if "/" in litellm else litellm

    def _model_capabilities(self, model: dict[str, Any]) -> dict[str, Any] | None:
        """models.dev（allow_network=False，永不联网）← 模型条目手填 capabilities 覆盖。"""
        provider_pid = str(model.get("hermes_provider") or model.get("provider") or "").strip()
        native = self._native_model_id(model)
        merged: dict[str, Any] = {}
        if provider_pid and native:
            try:
                caps = _models_dev.get_model_capabilities(provider_pid, native, allow_network=False)
            except Exception as exc:
                log.debug("model_manager.models_dev_lookup_failed", provider=provider_pid, error=str(exc))
                caps = None
            if caps is not None:
                merged = {
                    "supports_tools": caps.supports_tools,
                    "supports_vision": caps.supports_vision,
                    "supports_reasoning": caps.supports_reasoning,
                    "context_window": caps.context_window,
                    "max_output_tokens": caps.max_output_tokens,
                }
        manual = model.get("capabilities")
        if isinstance(manual, dict):
            merged.update({k: v for k, v in manual.items() if k in _CAPABILITY_FIELDS})
        return merged or None

    def _model_reasoning_efforts(self, model: dict[str, Any]) -> list[str] | None:
        """该模型路由支持的思考档位（vendored reasoning_effort；有 hermes_provider 时可得）。"""
        provider_pid = str(model.get("hermes_provider") or "").strip()
        if not provider_pid:
            return None
        try:
            return list(_reasoning_effort.route_supported_efforts(provider_pid, self._native_model_id(model)))
        except Exception as exc:
            log.debug("model_manager.reasoning_efforts_failed", provider=provider_pid, error=str(exc))
            return None

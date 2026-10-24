"""Atlas Model Manager — manual model selection + LiteLLM unified proxy."""

from __future__ import annotations

import os
import secrets
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

import structlog

from atlas.config import get_config, load_user_settings, save_user_settings
from atlas.models import catalog as _catalog
from atlas.models import models_dev as _models_dev
from atlas.models import reasoning_effort as _reasoning_effort
from atlas.project_context import current_project_id, current_session_id
from atlas.project_settings import get_project_gateway_key, get_session_gateway_key, set_project_gateway_key

log = structlog.get_logger()

# 手填 capabilities 只允许这组规范字段（C5 契约 §1），其余键丢弃。
_CAPABILITY_FIELDS = ("context_window", "max_output_tokens", "supports_vision", "supports_tools", "supports_reasoning")
# Anthropic SDK beta accepted for the million-token context window. Keep the
# accepted set deliberately narrow; arbitrary beta strings must never leak to
# provider requests from user settings.
CONTEXT_1M_BETA = "context-1m-2025-08-07"
_ALLOWED_SDK_BETAS = frozenset({CONTEXT_1M_BETA})
_MIN_OUTPUT_LIMIT_OVERRIDE = 4096
# 模型编辑（M6）允许修改的字段；id 与 custom 标记不可改，密钥不在这里改。
_MODEL_PATCH_FIELDS = ("name", "base_url", "litellm_model", "native_model", "hermes_provider", "max_output_tokens", "price", "capabilities", "api_mode")

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
        settings_base = str(settings.get("gateway_base_url") or "")
        self._api_base = settings_base or cfg.gateway_base_url
        # A plaintext key only survives migration when the keyring holds a *different* key (another
        # checkout of Atlas for this OS user), so a key still present in user-settings must win.
        self._global_api_key = str(settings.get("api_key") or "")
        if not self._global_api_key:
            self._global_api_key = cfg.gateway_api_key
        self._model_router = None
        self._gateway_source = "user-settings" if settings_base else "atlas.toml"
        self._toml_gateway_base_url = cfg.gateway_base_url
        if settings_base and cfg.gateway_base_url \
                and settings_base.rstrip("/") != cfg.gateway_base_url.rstrip("/"):
            # The settings UI silently wins over atlas.toml; surface that or an edited
            # toml appears ignored (2026-10-04: desktop pointed at a dead gateway for a day).
            log.warning(
                "model_manager.gateway_source_conflict",
                effective=settings_base, effective_source="user-settings.json",
                ignored=cfg.gateway_base_url, ignored_source="atlas.toml",
            )
        # 服务商配置（base_url 覆盖 + 密钥元数据；密钥原文在系统凭据库，见 add_key）。
        self._providers: dict[str, dict[str, Any]] = self._load_providers(settings)

        # Config-defined models are loaded but are not copied to user preferences.
        for custom in cfg.custom_models:
            if custom.get("id"):
                self._models.append({**custom, "custom": False})
        for custom in custom_models:
            if not custom.get("id"):
                continue
            # 用户设置里的模型优先：同 id 的内置/atlas.toml 条目被覆盖（并标为 custom，
            # 保存设置时才会写回）。以前这里直接跳过同 id 条目，导致用户配置的模型名不生效，
            # 且下一次保存设置时被从 user-settings.json 里悄悄删掉。
            existing = next((index for index, model in enumerate(self._models)
                             if model["id"] == custom["id"]), None)
            if existing is None:
                self.add_model(custom, persist=False)
            else:
                # 整条替换而不是合并：合并会把 atlas.toml 条目里的 base_url 等字段带进来，
                # 用户定义里没写的接口地址会被旧值顶替，请求发到错误的服务商。
                self._models[existing] = {**custom, "custom": True}

        # A user may keep a provider-specific display name for an ID that also exists in
        # the built-in catalog (for example the same DeepSeek route through d1api). Keep
        # the catalog's routing metadata, but honor the user's label in the UI.
        display_names: dict[str, str] = {}
        for custom in [*cfg.custom_models, *custom_models]:
            if isinstance(custom, dict) and custom.get("id") and isinstance(custom.get("name"), str) and custom["name"].strip():
                display_names[str(custom["id"])] = custom["name"].strip()
        if display_names:
            self._models = [
                {**model, "name": display_names.get(str(model.get("id")), model.get("name"))}
                for model in self._models
            ]

        # settings["hidden_models"]: 用户隐藏的内置模型（内置条目硬编码在 DEFAULT_MODELS，
        # 无法删除，只能从列表里过滤；用于「这张密钥只给某一个模型用」的部署）。
        hidden = settings.get("hidden_models")
        if isinstance(hidden, list):
            hidden_ids = {str(item).strip() for item in hidden if str(item).strip()}
            if hidden_ids:
                self._models = [m for m in self._models if m["id"] not in hidden_ids]
                if self._current in hidden_ids:
                    self._current = self._models[0]["id"] if self._models else self._current

        valid_ids = {str(model.get("id") or "") for model in self._models}
        if valid_ids and self._current not in valid_ids:
            self._current = str(self._models[0]["id"])

        log.info("model_manager.init", default=self._current, api_base=self._api_base,
                 source=self._gateway_source)

    @property
    def gateway_base_url(self) -> str:
        project_id = current_project_id()
        if project_id:
            return str(get_config().get("models.gateway.base_url", self._api_base))
        return self._api_base

    @property
    def gateway_source(self) -> str:
        """Where the effective gateway base_url came from: ``user-settings`` or ``atlas.toml``."""
        return self._gateway_source

    @property
    def atlas_toml_gateway_base_url(self) -> str:
        return self._toml_gateway_base_url

    @property
    def api_key_configured(self) -> bool:
        return bool(self.gateway_api_key)

    @property
    def gateway_api_key(self) -> str:
        session_id = current_session_id()
        if session_id:
            return str(get_session_gateway_key(session_id)
                       or (get_project_gateway_key(current_project_id()) if current_project_id() else None)
                       or self._global_api_key)
        project_id = current_project_id()
        return str(get_project_gateway_key(project_id) or "") if project_id else self._global_api_key

    @property
    def model_router(self):
        """One router instance per model manager/app."""
        if self._model_router is None:
            from atlas.models.router import ModelRouter

            self._model_router = ModelRouter(self)
        return self._model_router

    def update_provider(self, base_url: str, api_key: str | None) -> None:
        project_id = current_project_id()
        if project_id:
            from atlas.project_settings import load_project_config, save_project_config

            project_config = load_project_config(project_id)
            models = project_config.setdefault("models", {})
            gateway = models.setdefault("gateway", {})
            gateway["base_url"] = base_url.rstrip("/")
            save_project_config(project_id, project_config)
            if api_key:
                set_project_gateway_key(project_id, api_key)
            return
        if self._api_base != base_url.rstrip("/"):
            for entry in self._providers.values():
                entry.pop("api_mode_probe", None)
        self._api_base = base_url.rstrip("/")
        if api_key:
            from atlas.config_migrations import GLOBAL_GATEWAY_KEY

            self._credential_store().set(GLOBAL_GATEWAY_KEY, api_key)
            self._global_api_key = api_key
            for entry in self._providers.values():
                entry.pop("api_mode_probe", None)
        self._gateway_source = "user-settings"
        self._persist_settings()

    def _persist_settings(self) -> None:
        current = load_user_settings()
        current.pop("api_key", None)
        current.update({
            "gateway_base_url": self._api_base,
            "selected_model": self._current,
            "custom_models": [model for model in self._models if model.get("custom")],
            "providers": self._providers,
        })
        save_user_settings(current)

    @property
    def current_model(self) -> str:
        session_id = current_session_id()
        if session_id:
            from atlas.project_settings import load_session_config

            value = load_session_config(session_id).get("models", {}).get("default")
            if value:
                return str(value)
        project_id = current_project_id()
        if project_id:
            return str(get_config().get("models.default", self._current))
        return self._current

    @property
    def current_litellm_model(self) -> str:
        """Return the LiteLLM model string for the currently selected model."""
        selected = self.current_model
        for m in self._models:
            if m["id"] == selected:
                return m["litellm_model"]
        return selected  # fallback: use raw ID

    def select(self, model_id: str) -> None:
        """Switch the active model."""
        valid_ids = {m["id"] for m in self._models}
        if model_id not in valid_ids:
            raise ValueError(f"Unknown model: {model_id}. Available: {valid_ids}")
        project_id = current_project_id()
        session_id = current_session_id()
        if session_id:
            from atlas.project_settings import load_session_config, save_session_config

            session_config = load_session_config(session_id)
            session_config.setdefault("models", {})["default"] = model_id
            save_session_config(session_id, session_config)
        elif project_id:
            from atlas.project_settings import load_project_config, save_project_config

            project_config = load_project_config(project_id)
            project_config.setdefault("models", {})["default"] = model_id
            save_project_config(project_id, project_config)
        else:
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
                "selected": m["id"] == self.current_model,
                "api_key_configured": bool(self.resolve_model_api_key(str(m["id"])))
                if m.get("custom") else False,
                # 附加字段（additive）：models.dev（allow_network=False）← 模型条目手填 capabilities 覆盖。
                "capabilities": self._model_capabilities(m),
                "reasoning_efforts": self._model_reasoning_efforts(m),
            })
        # Keep the active route visible first; remaining favorites precede the
        # alphabetical catalog so startup/default priority is explicit in UI.
        result.sort(key=lambda x: (not x["selected"], not x["favorite"], x["name"]))
        return result

    def missing_model_credentials(self, model_id: str) -> str | None:
        """Validate routes whose provider requires a key, without network I/O."""
        model = self._find_model(model_id)
        if model is None or model.get("local_only"):
            return None
        provider = _catalog.resolve_catalog_id(str(model.get("hermes_provider") or model.get("provider") or ""))
        if provider != "anthropic":
            return None
        if self.gateway_api_key or self.resolve_api_key(provider) or (not current_project_id() and os.environ.get("ANTHROPIC_API_KEY")):
            return None
        return "所选 Claude 模型尚未配置可用密钥。请在设置 → 模型中配置服务商或网关密钥，再重新发送。"

    def model_availability(self, model_id: str) -> dict[str, Any]:
        """Return a local, deterministic availability check for a model.

        This checks selection and required credentials only; it does not make a
        network request or claim that a remote provider is healthy.
        """
        model = self._find_model(model_id)
        if model is None:
            return {"available": False, "reason": "unknown_model", "message": f"未知模型: {model_id}"}
        credential_error = self.missing_model_credentials(model_id)
        if credential_error:
            return {"available": False, "reason": "missing_credentials", "message": credential_error}
        return {"available": True, "reason": None, "message": None}

    def allowed_sdk_betas(self, values: Any) -> list[str]:
        """Filter caller supplied SDK beta flags through the 1M-only allowlist."""
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, (list, tuple, set, frozenset)):
            return []
        allowed = []
        for value in values:
            beta = str(value).strip()
            if beta in _ALLOWED_SDK_BETAS and beta not in allowed:
                allowed.append(beta)
            elif beta:
                log.warning("model_manager.sdk_beta_ignored", beta=beta)
        return allowed

    def supports_context_1m(self, model_id: str) -> bool:
        """Require explicit model metadata before enabling the 1M beta."""
        model = self._find_model(model_id)
        if model is None:
            return False
        provider = _catalog.resolve_catalog_id(str(model.get("hermes_provider") or model.get("provider") or ""))
        if provider != "anthropic":
            return False
        capabilities = self._model_capabilities(model) or {}
        context_window = capabilities.get("context_window")
        return isinstance(context_window, int) and not isinstance(context_window, bool) and context_window >= 1_000_000

    def context_window_for_model(self, model_id: str, sdk_betas: Any = None) -> int | None:
        """Resolve the runtime model's context window, including eligible 1M beta."""
        model = self._find_model(model_id)
        if model is None:
            return None
        capabilities = self._model_capabilities(model) or {}
        window = capabilities.get("context_window")
        if not isinstance(window, int) or isinstance(window, bool) or window <= 0:
            # A routed model can be selected through a generic OpenAI-compatible
            # entry while another configured entry carries its provider metadata.
            # Reuse capability data only for an identical wire model.
            wire_model = str(model.get("litellm_model") or "")
            native_model = self._native_model_id(model)
            if wire_model or native_model:
                for candidate in self._models:
                    if candidate is model:
                        continue
                    same_wire = wire_model and str(candidate.get("litellm_model") or "") == wire_model
                    same_native = native_model and self._native_model_id(candidate) == native_model
                    if not (same_wire or same_native):
                        continue
                    candidate_caps = self._model_capabilities(candidate) or {}
                    candidate_window = candidate_caps.get("context_window")
                    if isinstance(candidate_window, int) and not isinstance(candidate_window, bool) and candidate_window > 0:
                        window = candidate_window
                        break
        if not isinstance(window, int) or isinstance(window, bool) or window <= 0:
            return None
        if CONTEXT_1M_BETA in self.allowed_sdk_betas(sdk_betas) and self.supports_context_1m(model_id):
            return max(window, 1_000_000)
        return window

    def output_tokens_for_model(
        self, model_id: str, requested: int | None, default: int | None = None,
    ) -> int | None:
        """Apply a trustworthy provider output limit without inventing one.

        As in Claude's API capability handling, tiny/stale limits are ignored;
        limits of at least 4096 cap both an explicit request and the default.
        """
        model = self._find_model(model_id)
        if model is None:
            return None
        capabilities = self._model_capabilities(model) or {}
        limit = capabilities.get("max_output_tokens")
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < _MIN_OUTPUT_LIMIT_OVERRIDE:
            limit = None
        desired = requested if requested is not None else default
        if desired is None:
            return limit
        if isinstance(desired, bool) or not isinstance(desired, int) or desired <= 0:
            raise ValueError("输出 token 预算必须是正整数")
        return min(desired, limit) if limit is not None else desired

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
                "api_mode_override": entry.get("api_mode_override")
                if entry.get("api_mode_override") in {None, "auto", "openai", "chat_completions", "anthropic_messages", "codex_responses"}
                else None,
                "api_mode_probe": dict(entry["api_mode_probe"])
                if isinstance(entry.get("api_mode_probe"), dict) else None,
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
        result = {
            "base_url": entry.get("base_url"),
            "keys": [dict(key) for key in entry.get("keys", [])],
        }
        if entry.get("api_mode_override") is not None:
            result["api_mode_override"] = entry["api_mode_override"]
        if isinstance(entry.get("api_mode_probe"), dict):
            result["api_mode_probe"] = dict(entry["api_mode_probe"])
        return result

    def update_provider_config(self, provider_id: str, base_url: str | None) -> None:
        """设置/清除服务商的 base_url 覆盖（None = 回退 catalog 默认）。"""
        pid = self._require_provider(provider_id)
        url = str(base_url).strip().rstrip("/") if base_url and str(base_url).strip() else None
        if url:
            parsed = urlsplit(url)
            if (parsed.scheme not in {"http", "https"} or not parsed.netloc
                    or parsed.username is not None or parsed.password is not None
                    or parsed.query or parsed.fragment):
                raise ValueError(
                    "服务商地址必须是无凭据、无查询参数的 HTTP(S) URL；密钥请单独保存。"
                )
        entry = self._providers.setdefault(pid, {"base_url": None, "keys": []})
        if entry.get("base_url") != url:
            entry.pop("api_mode_probe", None)
        entry["base_url"] = url
        if not url and not entry["keys"]:
            self._providers.pop(pid, None)
        self._persist_settings()
        log.info("model_manager.provider_config_updated", provider=pid)

    def get_api_mode_override(self, provider_id: str) -> str | None:
        pid = _catalog.resolve_catalog_id(str(provider_id or "").strip()) or str(provider_id or "").strip()
        value = self._providers.get(pid, {}).get("api_mode_override")
        return value if value not in (None, "", "auto") else None

    def set_api_mode_override(self, provider_id: str, api_mode: str | None) -> None:
        pid = self._require_provider(provider_id)
        if api_mode in (None, "", "auto"):
            value = None
        elif api_mode in {"openai", "chat_completions", "anthropic_messages", "codex_responses"}:
            value = "chat_completions" if api_mode == "openai" else api_mode
        else:
            raise ValueError(f"不支持的 API 模式: {api_mode}")
        entry = self._providers.setdefault(pid, {"base_url": None, "keys": []})
        entry["api_mode_override"] = value
        self._persist_settings()

    def get_api_mode_probe(self, provider_id: str) -> dict[str, Any] | None:
        pid = _catalog.resolve_catalog_id(str(provider_id or "").strip()) or str(provider_id or "").strip()
        probe = self._providers.get(pid, {}).get("api_mode_probe")
        return dict(probe) if isinstance(probe, dict) else None

    def set_api_mode_probe(self, provider_id: str, probe: dict[str, Any]) -> None:
        pid = self._require_provider(provider_id)
        allowed = {"endpoint", "base_url", "credential_fingerprint", "supported", "reason", "checked_at"}
        entry = self._providers.setdefault(pid, {"base_url": None, "keys": []})
        entry["api_mode_probe"] = {key: value for key, value in probe.items() if key in allowed}
        self._persist_settings()

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
        except Exception as exc:  # 凭据库写失败：不留假 key 槽位，由路由转 500 上报
            if not entry["keys"] and not entry.get("base_url"):
                self._providers.pop(pid, None)  # 本次新建的空服务商槽位一并回收
            log.warning("model_manager.keyring_write_failed", provider=pid, key_id=key_id, error=str(exc))
            raise RuntimeError(f"密钥写入系统凭据库失败: {exc}") from exc
        entry["keys"].append(meta)
        entry.pop("api_mode_probe", None)
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
            log.warning("model_manager.keyring_delete_failed", provider=pid, key_id=key_id, error=str(exc), exc_info=True)
        entry["keys"] = remaining
        entry.pop("api_mode_probe", None)
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
        # Provider pools are global until a project has explicitly provisioned
        # its own pool; never borrow a different project's provider credentials.
        if current_project_id():
            return None
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
                    log.warning("model_manager.keyring_unavailable", error=str(exc), exc_info=True)
                    return None
            try:
                secret = store.get(self._keyring_account(pid, key_id))
            except Exception as exc:
                log.warning("model_manager.keyring_read_failed", provider=pid, key_id=key_id, error=str(exc), exc_info=True)
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

    @staticmethod
    def _model_keyring_account(model_id: str) -> str:
        return f"atlas:model:{model_id}"

    def set_model_api_key(self, model_id: str, secret: str | None) -> None:
        """Store a custom model key in the OS credential store, never settings."""
        if not any(str(model.get("id")) == str(model_id) and model.get("custom") for model in self._models):
            raise ValueError(f"未知自定义模型: {model_id}")
        account = self._model_keyring_account(model_id)
        try:
            store = self._credential_store()
            if secret and str(secret).strip():
                store.set(account, str(secret).strip())
            else:
                store.delete(account)
        except Exception as exc:
            raise RuntimeError(f"自定义模型密钥写入系统凭据库失败: {exc}") from exc

    def resolve_model_api_key(self, model_id: str) -> str | None:
        """Return the OS-stored key for one custom model, if configured."""
        if current_project_id():
            return None
        try:
            return self._credential_store().get(self._model_keyring_account(model_id))
        except Exception as exc:
            log.warning("model_manager.model_keyring_read_failed", model_id=model_id, error=str(exc))
            return None

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
        if not isinstance(patch, dict):
            raise ValueError("模型更新内容必须是对象")
        if "api_mode" in patch and patch["api_mode"] not in {
            None, "openai", "chat_completions", "anthropic_messages",
        }:
            raise ValueError("api_mode must be openai, chat_completions, or anthropic_messages")
        # hermes_provider 存的是 hermes id（qwen→alibaba、kimi→kimi-coding），
        # 校验必须走别名映射；存储/返回仍保持运行时路由期望的 hermes id。
        hermes_pid = patch.get("hermes_provider")
        if hermes_pid and _catalog.resolve_catalog_id(str(hermes_pid)) is None:
            raise ValueError(f"未知服务商: {hermes_pid}")
        candidate = dict(target)
        for field in _MODEL_PATCH_FIELDS:
            if field not in patch:
                continue
            value = patch[field]
            if field in ("name", "base_url", "litellm_model", "native_model", "hermes_provider"):
                candidate[field] = str(value).strip() if value is not None else None
            else:
                candidate[field] = value
        for field in ("max_output_tokens",):
            value = candidate.get(field)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value <= 0
            ):
                raise ValueError(f"{field} 必须是正整数")
        capabilities = candidate.get("capabilities")
        if capabilities is not None:
            if not isinstance(capabilities, dict):
                raise ValueError("capabilities 必须是对象")
            for name, value in capabilities.items():
                if name not in _CAPABILITY_FIELDS:
                    raise ValueError(f"不支持的模型能力字段: {name}")
                if name in {"context_window", "max_output_tokens"}:
                    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                        raise ValueError(f"capabilities.{name} 必须是正整数")
                elif not isinstance(value, bool):
                    raise ValueError(f"capabilities.{name} 必须是布尔值")
        price = candidate.get("price")
        if price is not None and not isinstance(price, dict):
            raise ValueError("price 必须是对象")
        if "api_key" in patch:
            # Validate the full public patch before changing the OS keyring so a
            # rejected metadata update cannot leave a partially applied edit.
            self.set_model_api_key(model_id, patch.get("api_key"))
        target.clear()
        target.update(candidate)
        self._persist_settings()
        log.info("model_manager.update_model", model_id=model_id)
        result = dict(target)
        result["api_key_configured"] = bool(self.resolve_model_api_key(model_id))
        return result

    def delete_model(self, model_id: str) -> None:
        """删除模型。自定义模型直接移除；内置模型（DEFAULT_MODELS 硬编码、无法真正删除）
        改为写入 settings["hidden_models"] 永久隐藏，下次启动初始化时过滤掉。"""
        target = self._find_model(model_id)
        if target is None:
            raise ValueError(f"未知模型: {model_id}")
        builtin = not target.get("custom")
        self._models.remove(target)
        if target.get("custom"):
            try:
                self._credential_store().delete(self._model_keyring_account(model_id))
            except Exception as exc:
                log.warning("model_manager.model_keyring_delete_failed", model_id=model_id, error=str(exc))
        if builtin:
            settings = load_user_settings()
            raw = settings.get("hidden_models")
            hidden = [str(x).strip() for x in raw if str(x).strip()] if isinstance(raw, list) else []
            if model_id not in hidden:
                hidden.append(model_id)
            settings["hidden_models"] = hidden
            save_user_settings(settings)
        if self._current == model_id and self._models:
            self._current = self._models[0]["id"]
            log.info("model_manager.selection_reset", model=self._current)
        self._persist_settings()
        log.info("model_manager.delete_model", model_id=model_id, builtin=builtin)

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
                log.debug("model_manager.models_dev_lookup_failed", provider=provider_pid, error=str(exc), exc_info=True)
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
            log.debug("model_manager.reasoning_efforts_failed", provider=provider_pid, error=str(exc), exc_info=True)
            return None

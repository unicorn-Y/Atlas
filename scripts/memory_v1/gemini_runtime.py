"""F1-D shared Gemini routing bootstrap and safe settings isolation."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

MODEL_ID = "gemini-3.8-flash"
PROVIDER_ID = "custom"
PROVIDER_BASE_URL = "http://127.0.0.1:8045/v1"
_USER_SETTINGS_FIELDS = {"custom_models", "providers", "memory_model"}
_MODEL_FIELDS = ("id", "name", "provider", "litellm_model", "category", "custom")
_KEY_METADATA_FIELDS = ("id", "label", "added_at")


def clear_inherited_gateway_credentials() -> None:
    """Remove process-inherited gateway overrides so keyring is the only credential source."""
    os.environ.pop("ATLAS_API_KEY", None)
    os.environ.pop("ATLAS_API_BASE", None)


def clear_gateway_fallback_config(raw_config: dict[str, Any]) -> None:
    models = raw_config.get("models")
    gateway = models.get("gateway") if isinstance(models, dict) else None
    if isinstance(gateway, dict):
        gateway["base_url"] = ""
        gateway["api_key"] = ""


def read_isolated_model_settings(source_path: Path) -> dict[str, Any]:
    """Read only the authorized Gemini/custom-provider metadata; never copy secret fields."""
    source = json.loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(source, dict):
        raise ValueError("configured Atlas user settings must be a JSON object")
    models = source.get("custom_models")
    safe_models = [
        {key: model[key] for key in _MODEL_FIELDS if key in model}
        for model in models
        if isinstance(model, dict) and model.get("id") == MODEL_ID
    ] if isinstance(models, list) else []
    if len(safe_models) != 1 or safe_models[0].get("provider") != PROVIDER_ID:
        raise RuntimeError("isolated F1-D requires exactly one Gemini custom model entry")
    if safe_models[0].get("litellm_model") != MODEL_ID:
        raise RuntimeError("configured Gemini LiteLLM model id does not match the fixed F1-D model")

    providers = source.get("providers")
    custom = providers.get(PROVIDER_ID) if isinstance(providers, dict) else None
    if not isinstance(custom, dict):
        raise RuntimeError("configured Atlas custom provider is unavailable")
    base_url = str(custom.get("base_url") or "").rstrip("/")
    if base_url != PROVIDER_BASE_URL.rstrip("/"):
        raise RuntimeError("configured Atlas custom provider does not target the authorized Antigravity endpoint")
    keys = [
        {key: item[key] for key in _KEY_METADATA_FIELDS if key in item}
        for item in custom.get("keys", [])
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    ] if isinstance(custom.get("keys"), list) else []
    if not keys:
        raise RuntimeError("configured Atlas custom provider has no Windows credential metadata")

    safe_provider: dict[str, Any] = {"base_url": base_url, "keys": keys}
    api_mode = custom.get("api_mode_override")
    if api_mode in {"openai", "chat_completions", "anthropic_messages", "codex_responses"}:
        safe_provider["api_mode_override"] = api_mode
    memory_model = str(source.get("memory_model") or "").strip()
    if memory_model != MODEL_ID:
        raise RuntimeError("configured Atlas memory model is not the fixed F1-D Gemini model")
    return {
        "custom_models": safe_models,
        "providers": {PROVIDER_ID: safe_provider},
        "memory_model": MODEL_ID,
    }


def write_isolated_user_settings(atlas_data_root: Path, settings: dict[str, Any]) -> Path:
    if set(settings) != _USER_SETTINGS_FIELDS:
        raise ValueError("isolated F1-D settings must contain only custom_models, providers.custom and memory_model")
    models = settings.get("custom_models")
    if not isinstance(models, list) or len(models) != 1 or not isinstance(models[0], dict):
        raise ValueError("isolated F1-D custom model metadata is invalid")
    model = models[0]
    if set(model) - set(_MODEL_FIELDS):
        raise ValueError("isolated F1-D settings contain nested fields outside the metadata allowlist")
    if (
        model.get("id") != MODEL_ID
        or model.get("provider") != PROVIDER_ID
        or model.get("litellm_model") != MODEL_ID
        or model.get("custom") is not True
        or any(not isinstance(value, (str, bool, int, float, type(None))) for value in model.values())
    ):
        raise ValueError("isolated F1-D Gemini model metadata does not match the fixed route")

    providers = settings.get("providers")
    if not isinstance(providers, dict) or set(providers) != {PROVIDER_ID}:
        raise ValueError("isolated F1-D settings must contain only the custom provider")
    provider = providers[PROVIDER_ID]
    if not isinstance(provider, dict) or set(provider) - {"base_url", "keys", "api_mode_override"}:
        raise ValueError("isolated F1-D settings contain nested fields outside the provider allowlist")
    if str(provider.get("base_url") or "").rstrip("/") != PROVIDER_BASE_URL.rstrip("/"):
        raise ValueError("isolated F1-D provider metadata does not match the authorized endpoint")
    keys = provider.get("keys")
    if not isinstance(keys, list) or not keys:
        raise ValueError("isolated F1-D custom provider has no credential metadata")
    for key in keys:
        if (
            not isinstance(key, dict)
            or set(key) - set(_KEY_METADATA_FIELDS)
            or not str(key.get("id") or "").strip()
            or any(not isinstance(value, (str, bool, int, float, type(None))) for value in key.values())
        ):
            raise ValueError("isolated F1-D settings contain nested fields outside the key metadata allowlist")
    api_mode = provider.get("api_mode_override")
    if api_mode is not None and api_mode not in {
        "openai", "chat_completions", "anthropic_messages", "codex_responses",
    }:
        raise ValueError("isolated F1-D provider API mode is invalid")
    if settings.get("memory_model") != MODEL_ID:
        raise ValueError("isolated F1-D memory model is not the fixed Gemini model")

    path = atlas_data_root / "data" / "user-settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def configured_observer_model_id(model_manager: Any, settings: dict[str, Any]) -> str | None:
    models = model_manager.list_models()
    for candidate in (
        settings.get("memory_model"),
        settings.get("compression_model"),
        getattr(model_manager, "current_model", None),
    ):
        chosen = str(candidate or "").strip()
        if not chosen:
            continue
        match = next((item for item in models if chosen in {
            str(item.get("id") or ""), str(item.get("litellm_model") or ""),
        }), None)
        if match is not None:
            return str(match.get("id") or match.get("litellm_model") or "")
        if candidate == getattr(model_manager, "current_model", None):
            return chosen
    return None


def validate_f1_model_route(model_manager: Any, settings: dict[str, Any]) -> dict[str, Any]:
    if str(getattr(model_manager, "current_model", "")) != MODEL_ID:
        raise RuntimeError("Atlas main model is not the fixed F1-D Gemini model")
    observer_model_id = configured_observer_model_id(model_manager, settings)
    if observer_model_id != MODEL_ID:
        raise RuntimeError("Atlas Observer/Reflector model is not the fixed F1-D Gemini model")
    selected = next(
        (item for item in model_manager.list_models() if str(item.get("id") or "") == MODEL_ID),
        None,
    )
    if not isinstance(selected, dict) or str(selected.get("provider") or "") != PROVIDER_ID:
        raise RuntimeError("fixed F1-D Gemini model is not routed through the authorized custom provider")
    provider = model_manager.provider_config(PROVIDER_ID)
    base_url = str(provider.get("base_url") or "").rstrip("/")
    if base_url != PROVIDER_BASE_URL.rstrip("/"):
        raise RuntimeError("Atlas ModelRouter custom provider endpoint differs from the authorized Antigravity endpoint")
    credential = model_manager.resolve_api_key(PROVIDER_ID)
    credential_present = bool(credential)
    del credential
    if not credential_present:
        raise RuntimeError("Atlas ModelRouter cannot read the custom provider key from Windows Credential Manager")
    if str(getattr(model_manager, "gateway_api_key", "") or ""):
        raise RuntimeError("an inherited or configured Atlas gateway credential could bypass the F1-D custom provider")
    return {
        "model_id": MODEL_ID,
        "observer_model_id": observer_model_id,
        "provider_id": PROVIDER_ID,
        "provider_endpoint_host": urlsplit(base_url).netloc,
        "credential_present": True,
        "credential_source": "Atlas ModelManager Windows Credential Manager lookup",
        "credential_value_recorded": False,
    }


def bootstrap_model_manager(
    config: Any,
    settings: dict[str, Any],
    settings_path: Path,
) -> tuple[Any, dict[str, Any]]:
    """Install one read-only Atlas ModelManager backed by isolated settings and the OS keyring."""
    clear_inherited_gateway_credentials()
    isolated_data_root = Path(os.environ.get("ATLAS_DATA_DIR") or "").resolve()
    expected_settings_path = isolated_data_root / "data" / "user-settings.json"
    if not os.environ.get("ATLAS_DATA_DIR") or settings_path.resolve() != expected_settings_path:
        raise ValueError("F1-D ModelManager settings path must be inside the isolated ATLAS_DATA_DIR")

    import atlas.agent as atlas_agent
    import atlas.config as atlas_config
    import atlas.memory as atlas_memory
    import atlas.models as atlas_models
    from atlas.models import ModelManager

    def read_isolated_settings(path: Path | None = None) -> dict[str, Any]:
        return copy.deepcopy(settings)

    def reject_settings_write(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("F1-D Atlas settings are read-only")

    atlas_config._config = config
    atlas_config.DATA_ROOT = isolated_data_root
    atlas_config.get_config = lambda: config
    atlas_config.USER_SETTINGS_PATH = settings_path
    atlas_config.load_user_settings = read_isolated_settings
    atlas_config.save_user_settings = reject_settings_write
    atlas_agent.get_config = lambda: config
    atlas_memory.get_config = lambda: config
    atlas_models.get_config = lambda: config
    atlas_models.load_user_settings = read_isolated_settings
    atlas_models.save_user_settings = reject_settings_write
    manager = ModelManager(default_model=MODEL_ID)
    return manager, validate_f1_model_route(manager, settings)



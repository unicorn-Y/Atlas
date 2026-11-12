"""Introspection provider: effective configuration, redacted.

The config provider exists because "what is this app actually running with" is
surprisingly hard to answer and surprisingly dangerous to answer carelessly.

Two traps, both real in this repository:

**Redaction.** ``config/atlas.toml`` holds provider API keys in plaintext. They
never went through the keyring stack, so the keyring being clean says nothing
about the file. ``atlas.secrets_store.redact`` alone is therefore *not enough* —
it hides values it can recognise by content, and a key typed straight into the
TOML was never registered as a secret, so it is invisible to that function. The
second rule is masking by key *name*: :func:`atlas.secrets_store.scrub` applies
both, and this module calls only that. Any provider that echoes configuration
must do the same, or the introspection surface becomes a key-leak surface.

**Layering.** ``AtlasConfig`` keeps two views: ``base_raw`` (atlas.toml only) and
``raw`` (with the expert-mode overlay applied). Reporting the wrong one produces
a confident wrong answer about what the process is using. ``raw`` is the truth.

Keys are returned as paths with their values; the alternative — returning the
whole document — makes the caller filter, and a caller who forgets is the leak.
"""

from __future__ import annotations

from typing import Any

from atlas.introspect.registry import Context, Method, Provider, object_schema

_MAX_VALUE_CHARS = 300


def _config() -> Any:
    from atlas.config import get_config

    return get_config()


def _redact(value: Any, key: str = "") -> Any:
    """Redact through the one redaction authority.

    ``scrub`` handles recursion, the content-based pass, and the name-based pass
    together. Passing ``key`` down matters: a nested ``models.custom[].api_key``
    is only recognisable as a credential by its name, never by content.
    """
    from atlas.secrets_store import scrub

    return scrub(value, key)


def _flatten(node: Any, prefix: str = "") -> list[dict[str, Any]]:
    """Dotted-path rows, redacted. Scalars keep their value; tables recurse."""
    rows: list[dict[str, Any]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, dict) and value:
                rows.extend(_flatten(value, path))
            else:
                rendered = _redact(value, path)
                if isinstance(rendered, str) and len(rendered) > _MAX_VALUE_CHARS:
                    rendered = rendered[:_MAX_VALUE_CHARS] + "…"
                rows.append({"key": path, "value": rendered})
    return rows


def _layers(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    cfg = _config()
    base_keys = {row["key"] for row in _flatten(cfg.base_raw or {})}
    eff_keys = {row["key"] for row in _flatten(cfg.raw or {})}
    return {
        "base_keys": len(base_keys),
        "effective_keys": len(eff_keys),
        "overlay_only": sorted(eff_keys - base_keys),
        "note": "overlay_only 是专家模式叠加进来的键，只存在于生效配置里。",
    }


def _list_keys(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    rows = _flatten(_config().raw or {})
    prefix = str(args.get("prefix") or "")
    search = str(args.get("search") or "").lower()
    include_values = args.get("include_values") is not False
    if prefix:
        rows = [row for row in rows if row["key"].startswith(prefix)]
    if search:
        rows = [row for row in rows if search in row["key"].lower()]
    if not include_values:
        rows = [{"key": row["key"]} for row in rows]
    return {"count": len(rows), "keys": rows}


def _get_key(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    key = args["key"]
    cfg = _config()
    value = cfg.get(key, None)
    if value is None:
        known = [row["key"] for row in _flatten(cfg.raw or {})]
        near = [item for item in known if key.lower() in item.lower()][:10]
        return {"key": key, "found": False, "near_matches": near}
    return {"key": key, "found": True, "value": _redact(value, key)}


def _paths(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    from atlas import config as config_module

    cfg = _config()
    return {
        "project_root": str(config_module.PROJECT_ROOT),
        "data_root": str(config_module.DATA_ROOT),
        "config_path": str(config_module.CONFIG_PATH),
        "config_exists": config_module.CONFIG_PATH.exists(),
        "db_path": str(cfg.db_path),
        "db_exists": cfg.db_path.exists(),
        "server": {"host": cfg.server_host, "port": cfg.server_port},
        "default_model": cfg.default_model,
    }


PROVIDER = Provider(
    id="config",
    title="配置",
    summary="生效配置的键值（密钥已替换为 handle）、配置分层、以及各数据路径。",
    methods=(
        Method(
            name="keys",
            summary="按点号路径列出生效配置，默认脱敏。",
            input_schema=object_schema(
                {
                    "prefix": {"type": "string", "description": "只保留该前缀的键。"},
                    "search": {"type": "string", "description": "键名子串。"},
                    "include_values": {
                        "type": "boolean",
                        "description": "是否返回值，默认 true（值仍会脱敏）。",
                    },
                }
            ),
            run=_list_keys,
        ),
        Method(
            name="get",
            summary="读单个配置键的生效值。",
            input_schema=object_schema(
                {"key": {"type": "string", "description": "点号路径，如 gateway.base_url。"}},
                required=("key",),
            ),
            run=_get_key,
        ),
        Method(
            name="layers",
            summary="对比 atlas.toml 与生效配置，看专家模式叠加了哪些键。",
            input_schema=object_schema(),
            run=_layers,
        ),
        Method(
            name="paths",
            summary="项目根、数据根、配置文件与数据库的位置。",
            input_schema=object_schema(),
            run=_paths,
        ),
    ),
)

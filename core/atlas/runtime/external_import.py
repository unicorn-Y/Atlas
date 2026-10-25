"""E6 — scan and import extensions from Claude Code / Codex into Atlas.

``scan_external`` builds a reviewable manifest (kind/name/path/action/
conflict/detail per item); ``import_external`` applies only the items the
user selected. Source directories are strictly read-only — every write lands
on the Atlas side through the existing persistence layers:

- MCP        -> ``atlas.toml`` ``[tools.servers.*]`` (read by tools/mcp_client.py)
- hooks      -> ``HookStore`` TOML (atlas/runtime/hooks.py), Claude events that
                have no Atlas-native equivalent stay in the live-read layer
- rules      -> ``<workspace>/AGENTS.md`` paragraphs, merge + dedupe, never overwrite
- skills     -> ``<data_root>/skills/<name>/`` copies (SkillManager scans this dir)
- commands   -> ``<data_root>/data/commands/<rel>.md`` (atlas/runtime/commands.py)
- agents     -> ``<data_root>/data/agents/<name>.md`` (atlas/agent/definitions.py)
- model prefs-> user settings key ``selected_model`` via save_user_settings
- history    -> session counts in this legacy manifest; visible text turns are
                selected and imported by ``atlas.api.external_history_router``
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import tomllib
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from atlas.config import DATA_ROOT, load_user_settings, save_user_settings
from atlas.runtime.hooks import HookStore, parse_claude_hooks

SOURCES = ("claude", "codex", "openclaw")

# Claude hook events Atlas owns natively; all other Claude events keep working
# through the live-read Claude settings layer and are not imported.
_CLAUDE_TO_ATLAS_EVENTS = {
    "SessionStart": "run.started",
    "PreToolUse": "tool.before",
    "PostToolUse": "tool.after",
    "Stop": "run.completed",
    "StopFailure": "run.failed",
}

_KIND_LABELS = {
    "mcp": "MCP 服务器", "hooks": "Hooks", "rules": "规则",
    "skills": "技能", "agents": "子 Agent", "commands": "命令",
    "model_prefs": "模型偏好", "history": "历史",
}
_KIND_ORDER = ("mcp", "hooks", "rules", "skills", "agents", "commands", "model_prefs", "history")

# History import is deliberately narrower than extension import: only text
# turns from Claude Code project transcripts and Codex rollout transcripts are
# considered. Source paths never cross the API boundary; session keys are
# opaque hashes of root-relative paths.
_HISTORY_MAX_RESULTS = 500
_HISTORY_MAX_DISCOVERED = 10_000
_HISTORY_MAX_FILE_BYTES = 32 * 1024 * 1024
_HISTORY_MAX_RECORDS = 50_000
_HISTORY_PREVIEW_CHARS = 320
_HISTORY_INDEX_PATH = DATA_ROOT / "data" / "external-history-imports.json"


# ---------------------------------------------------------------------------
# Small read/hash helpers (source side is read-only)
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def _load_toml(path: Path) -> Any:
    try:
        with path.open("rb") as stream:
            return tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError):
        return None


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha_dir(path: Path) -> str:
    digest = hashlib.sha256()
    for file in sorted(path.rglob("*"), key=lambda item: item.relative_to(path).as_posix()):
        if file.is_file():
            digest.update(file.relative_to(path).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(file.read_bytes())
    return digest.hexdigest()


def _item(kind: str, name: str, path: Path | None, action: str, *,
          conflict: bool = False, detail: str = "") -> dict[str, Any]:
    return {
        "kind": kind, "name": name, "path": str(path) if path else "",
        "action": action, "conflict": conflict, "detail": detail,
    }


def _atlas_layout(atlas_home: Path | None) -> dict[str, Path]:
    """Atlas-side targets. Default mirrors the live server layout:
    skills under the data root, user state under ``<data root>/data``."""
    root = Path(atlas_home).expanduser() if atlas_home else DATA_ROOT
    data = root / "data"
    return {
        "root": root,
        "skills": root / "skills",
        "commands": data / "commands",
        "agents": data / "agents",
        "hooks_toml": data / "hooks.toml",
        "user_settings": data / "user-settings.json",
        "config_toml": root / "config" / "atlas.toml",
    }


def _source_home(source_home: Path | None) -> Path:
    return Path(source_home).expanduser() if source_home else Path.home()


# ---------------------------------------------------------------------------
# MCP conversion / atlas.toml [tools.servers] writing
# ---------------------------------------------------------------------------

def _canonical_mcp(raw: Mapping[str, Any]) -> dict[str, Any]:
    if raw.get("url") and not raw.get("command"):
        return {"transport": "sse", "url": str(raw["url"]), "command": "", "args": [], "env": {}}
    return {
        "transport": "stdio", "url": "",
        "command": str(raw.get("command") or ""),
        "args": [str(arg) for arg in (raw.get("args") or [])],
        "env": {str(key): str(value) for key, value in (raw.get("env") or {}).items()},
    }


def _protect_mcp_env(source: str, path: Path | None, name: str,
                     env: Mapping[str, Any]) -> dict[str, str]:
    """Move imported credential-looking environment values to the local vault."""
    from atlas.secrets_store import set_secret

    protected: dict[str, str] = {}
    for key, value in env.items():
        key_text, value_text = str(key), str(value)
        upper = key_text.upper()
        if value_text and not value_text.startswith("{{secret:") and any(
            token in upper for token in ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
        ):
            identity = hashlib.sha256(f"{source}\0{path}\0{name}\0{key_text}".encode("utf-8")).hexdigest()[:24].upper()
            secret_name = f"IMPORT_{identity}"
            set_secret(secret_name, value_text, f"Imported MCP credential for {name}: {key_text}")
            protected[key_text] = f"{{{{secret:{secret_name}}}}}"
        else:
            protected[key_text] = value_text
    return protected


def _servers_equal(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    keys = ("transport", "command", "args", "env", "url")
    return all(left.get(key) == right.get(key) for key in keys)


def _toml_inline_table(mapping: Mapping[str, Any]) -> str:
    inner = ", ".join(
        f"{json.dumps(key, ensure_ascii=False)} = {json.dumps(value, ensure_ascii=False)}"
        for key, value in mapping.items()
    )
    return "{" + inner + "}"


def _server_block(name: str, entry: Mapping[str, Any]) -> str:
    lines = [
        f"[tools.servers.{json.dumps(name, ensure_ascii=False)}]",
        f"transport = {json.dumps(entry['transport'])}",
    ]
    if entry["transport"] == "sse":
        lines.append(f"url = {json.dumps(entry['url'], ensure_ascii=False)}")
    else:
        lines.append(f"command = {json.dumps(entry['command'], ensure_ascii=False)}")
        lines.append("args = " + json.dumps(entry["args"], ensure_ascii=False))
        if entry["env"]:
            lines.append("env = " + _toml_inline_table(entry["env"]))
    return "\n".join(lines)


def _remove_server_table(text: str, name: str) -> str:
    headers = {f"[tools.servers.{json.dumps(name, ensure_ascii=False)}]"}
    if re.fullmatch(r"[A-Za-z0-9_-]+", name):
        headers.add(f"[tools.servers.{name}]")
    out: list[str] = []
    skipping = False
    for line in text.splitlines(keepends=True):
        if line.strip() in headers:
            skipping = True
            continue
        if skipping:
            if line.strip().startswith("["):
                skipping = False
            else:
                continue
        out.append(line)
    return "".join(out)


def _extend_auto_start(text: str, names: Sequence[str]) -> str:
    """Extend a single-line ``auto_start = [...]``; absent/empty/multiline lists
    need no edit (empty auto_start means every configured server starts)."""
    match = re.search(r"(?m)^(\s*auto_start\s*=\s*)\[([^\]]*)\]", text)
    if not match:
        return text
    inner = match.group(2).strip()
    values = []
    for piece in inner.split(",") if inner else []:
        piece = piece.strip().strip("\"'")
        if piece:
            values.append(piece)
    values.extend(name for name in names if name not in values)
    prefix = match.group(1)
    rendered = json.dumps(values, ensure_ascii=False)
    return text[:match.start()] + prefix + rendered + text[match.end():]


def _read_source_mcp(source: str, path: Path, name: str) -> Mapping[str, Any] | None:
    data = _load_json(path) if source in {"claude", "openclaw"} else _load_toml(path)
    if not isinstance(data, dict):
        return None
    if source == "claude":
        servers = data.get("mcpServers", {})
    elif source == "openclaw":
        servers = data.get("mcpServers")
        if not isinstance(servers, dict):
            tools = data.get("tools") if isinstance(data.get("tools"), dict) else {}
            mcp = tools.get("mcp") if isinstance(tools.get("mcp"), dict) else {}
            servers = tools.get("servers") if isinstance(tools.get("servers"), dict) else mcp.get("servers", {})
    else:
        servers = data.get("mcp_servers", {})
    raw = servers.get(name) if isinstance(servers, dict) else None
    return raw if isinstance(raw, dict) else None


# ---------------------------------------------------------------------------
# Hooks conversion into the legacy HookStore format
# ---------------------------------------------------------------------------

def _hook_entries(groups: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for group in groups:
        event = _CLAUDE_TO_ATLAS_EVENTS.get(str(group.get("event")))
        if event is None:
            continue
        for spec in group.get("hooks", []):
            command = str(spec.get("command") or "")
            if not command:
                continue
            try:
                timeout = int(spec.get("timeout", 30))
            except (TypeError, ValueError):
                timeout = 30
            identity = f"{event}\n{command}"
            entries.append({
                "id": "claude-import-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12],
                "event": event, "command": command,
                "timeout_s": max(1, min(300, timeout)), "enabled": True,
            })
    return entries


# ---------------------------------------------------------------------------
# Rules merge (workspace AGENTS.md, paragraph-level dedupe)
# ---------------------------------------------------------------------------

def _paragraphs(text: str) -> list[str]:
    return [block.strip() for block in re.split(r"\n[ \t]*\n", text) if block.strip()]


def _missing_paragraphs(target_text: str, source_text: str) -> list[str]:
    have = set(_paragraphs(target_text))
    return [block for block in _paragraphs(source_text) if block not in have]


def _merge_markdown(target: Path, source_text: str) -> str:
    """Append source paragraphs missing from target; returns created/merged/identical."""
    if target.exists():
        current = target.read_text(encoding="utf-8")
        missing = _missing_paragraphs(current, source_text)
        if not missing:
            return "identical"
        merged = current.rstrip("\n") + "\n\n" + "\n\n".join(missing) + "\n"
        target.write_text(merged, encoding="utf-8")
        return "merged"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not source_text.endswith("\n"):
        source_text += "\n"
    target.write_text(source_text, encoding="utf-8")
    return "created"


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def scan_external(source: str, *, workspace: Path | None = None,
                  atlas_home: Path | None = None,
                  source_home: Path | None = None) -> dict:
    """Scan Claude Code or Codex config directories and return an import manifest.

    Returns ``{"source", "items", "sources"}``; items follow the frozen
    kind/name/path/action/conflict/detail shape. Neither the source home nor
    the workspace is modified.
    """
    if source not in SOURCES:
        raise ValueError(f"source must be one of {SOURCES}: got {source!r}")
    home = _source_home(source_home)
    ws = Path(workspace).expanduser() if workspace else None
    paths = _atlas_layout(atlas_home)
    scanner = {"claude": _scan_claude, "codex": _scan_codex, "openclaw": _scan_openclaw}[source]
    items, roots = scanner(home, ws, paths)
    sources = [str(root) for root in roots if root.exists()]
    return {"source": source, "items": items, "sources": sources}


def _mcp_detail(entry: Mapping[str, Any]) -> str:
    if entry["transport"] == "sse":
        return "SSE 服务器，写入 atlas.toml [tools.servers]"
    return f"stdio 服务器 {entry['command']}，写入 atlas.toml [tools.servers]"


def _claude_roots(home: Path, ws: Path | None) -> list[Path]:
    roots = [home / ".claude", home / ".claude.json"]
    if ws is not None:
        roots.extend((ws / ".claude", ws / ".mcp.json", ws / "CLAUDE.md"))
    return roots


def _scan_claude(home: Path, ws: Path | None,
                 paths: dict[str, Path]) -> tuple[list[dict[str, Any]], list[Path]]:
    user = home / ".claude"
    items: list[dict[str, Any]] = []
    existing_servers = _atlas_servers(paths["config_toml"])

    # MCP: user ~/.claude.json + project .mcp.json
    mcp_files = [(home / ".claude.json", "用户级")]
    if ws is not None:
        mcp_files.append((ws / ".mcp.json", "项目级"))
    for path, scope in mcp_files:
        data = _load_json(path)
        servers = data.get("mcpServers", {}) if isinstance(data, dict) else {}
        for name, raw in servers.items():
            if not isinstance(raw, dict) or not (raw.get("command") or raw.get("url")):
                continue
            entry = _canonical_mcp(raw)
            detail = _mcp_detail(entry)
            if name in existing_servers:
                if _servers_equal(_canonical_mcp(existing_servers[name]), entry):
                    items.append(_item("mcp", name, path, "skip",
                                       detail="Atlas 已有内容一致的同名服务器"))
                else:
                    items.append(_item("mcp", name, path, "skip", conflict=True,
                                       detail="Atlas 已有同名但配置不同的服务器，默认跳过"))
            else:
                items.append(_item("mcp", name, path, "import", detail=detail))

    # Hooks: user + project settings.json (Claude events without an Atlas
    # native event stay live-read, so only the mappable subset is offered)
    hook_files = [(user / "settings.json", "用户设置")]
    if ws is not None:
        hook_files.append((ws / ".claude" / "settings.json", "项目设置"))
    for path, scope in hook_files:
        data = _load_json(path)
        if not isinstance(data, dict) or not isinstance(data.get("hooks"), dict):
            continue
        entries = _hook_entries(parse_claude_hooks(data))
        if not entries:
            items.append(_item("hooks", f"hooks（{scope}）", path, "skip",
                               detail="hooks 事件均无 Atlas 对应事件，继续由 Claude 直读"))
            continue
        have = {(h.get("event"), h.get("command")) for h in HookStore(paths["hooks_toml"]).list()}
        fresh = [entry for entry in entries if (entry["event"], entry["command"]) not in have]
        label = f"hooks（{scope}）"
        if not fresh:
            items.append(_item("hooks", label, path, "skip",
                               detail=f"{len(entries)} 条 hooks 已存在，内容一致"))
        else:
            events = "、".join(sorted({entry["event"] for entry in fresh}))
            items.append(_item("hooks", label, path, "import",
                               detail=f"可导入 {len(fresh)} 条到 Atlas 事件（{events}），"
                                     f"其余事件保持 Claude 直读"))

    # Rules: CLAUDE.md merged into workspace AGENTS.md
    rule_files = [(user / "CLAUDE.md", "用户级")]
    if ws is not None:
        rule_files.insert(0, (ws / "CLAUDE.md", "项目级"))
    for path, scope in rule_files:
        item = _rules_item(path, f"CLAUDE.md（{scope}）", ws)
        if item:
            items.append(item)

    # Skills / agents / commands copies
    pairs = [
        ("skills", user / "skills", ws / ".claude" / "skills" if ws else None),
        ("agents", user / "agents", ws / ".claude" / "agents" if ws else None),
        ("commands", user / "commands", ws / ".claude" / "commands" if ws else None),
    ]
    for kind, user_dir, project_dir in pairs:
        if kind == "skills":
            items.extend(_scan_skill_dirs(user_dir, "用户级", paths["skills"]))
            if project_dir is not None:
                items.extend(_scan_skill_dirs(project_dir, "项目级", paths["skills"]))
        else:
            items.extend(_scan_md_files(kind, user_dir, "用户级", paths[kind]))
            if project_dir is not None:
                items.extend(_scan_md_files(kind, project_dir, "项目级", paths[kind]))

    # Model preference: Claude settings.json "model" -> Atlas selected_model
    model_item = _model_prefs_item("claude", user / "settings.json", paths["user_settings"])
    if model_item:
        items.append(model_item)

    # Legacy count only. Selectable transcript import is handled by the
    # dedicated external-history endpoints, which do not expose source paths.
    history_root = user / "projects"
    if history_root.is_dir():
        count = sum(1 for _ in history_root.rglob("*.jsonl"))
        items.append(_item("history", f"Claude 会话历史（{count} 条）", history_root, "skip",
                           detail="请在下方逐条预览并选择可导入的文本会话"))

    items.sort(key=lambda item: _KIND_ORDER.index(item["kind"]))
    return items, _claude_roots(home, ws)


def _codex_roots(home: Path) -> list[Path]:
    return [home / ".codex"]


def _scan_codex(home: Path, ws: Path | None,
                paths: dict[str, Path]) -> tuple[list[dict[str, Any]], list[Path]]:
    user = home / ".codex"
    items: list[dict[str, Any]] = []
    existing_servers = _atlas_servers(paths["config_toml"])

    # MCP: config.toml [mcp_servers.*]
    data = _load_toml(user / "config.toml")
    servers = data.get("mcp_servers", {}) if isinstance(data, dict) else {}
    for name, raw in servers.items():
        if not isinstance(raw, dict) or not (raw.get("command") or raw.get("url")):
            continue
        entry = _canonical_mcp(raw)
        detail = _mcp_detail(entry)
        if name in existing_servers:
            if _servers_equal(_canonical_mcp(existing_servers[name]), entry):
                items.append(_item("mcp", name, user / "config.toml", "skip",
                                   detail="Atlas 已有内容一致的同名服务器"))
            else:
                items.append(_item("mcp", name, user / "config.toml", "skip", conflict=True,
                                   detail="Atlas 已有同名但配置不同的服务器，默认跳过"))
        else:
            items.append(_item("mcp", name, user / "config.toml", "import", detail=detail))

    # Rules: global AGENTS.md -> workspace AGENTS.md
    item = _rules_item(user / "AGENTS.md", "AGENTS.md（Codex 全局）", ws)
    if item:
        items.append(item)

    # Custom prompts -> Atlas user commands
    items.extend(_scan_md_files("commands", user / "prompts", "Codex 提示词", paths["commands"]))

    # Codex agents are read live by Atlas (atlas/agent/definitions.py reads
    # ~/.codex/agents), so importing would only duplicate them.
    agents_dir = user / "agents"
    if agents_dir.is_dir():
        for path in sorted(agents_dir.glob("*.toml")):
            items.append(_item("agents", path.stem, path, "skip",
                               detail="Atlas 运行时直接读取 ~/.codex/agents，无需导入"))

    model_item = _model_prefs_item("codex", user / "config.toml", paths["user_settings"])
    if model_item:
        items.append(model_item)

    sessions = user / "sessions"
    if sessions.is_dir():
        count = sum(1 for _ in sessions.rglob("*.jsonl"))
        items.append(_item("history", f"Codex 会话历史（{count} 条）", sessions, "skip",
                           detail="请在下方逐条预览并选择可导入的文本会话"))
    history_file = user / "history.jsonl"
    if history_file.is_file():
        items.append(_item("history", "Codex 命令历史（history.jsonl）", history_file, "skip",
                           detail="Codex 输入命令历史不是会话转录，不导入"))

    items.sort(key=lambda item: _KIND_ORDER.index(item["kind"]))
    return items, _codex_roots(home)


def _openclaw_roots(home: Path) -> list[Path]:
    root = home / ".openclaw"
    return [root / "openclaw.json", root / "workspace", root / "agents"]


def _scan_openclaw(home: Path, ws: Path | None,
                   paths: dict[str, Path]) -> tuple[list[dict[str, Any]], list[Path]]:
    root = home / ".openclaw"
    items: list[dict[str, Any]] = []
    config_path = root / "openclaw.json"
    config = _load_json(config_path)
    existing_servers = _atlas_servers(paths["config_toml"])
    servers: Any = {}
    if isinstance(config, dict):
        servers = config.get("mcpServers")
        if not isinstance(servers, dict):
            tools = config.get("tools") if isinstance(config.get("tools"), dict) else {}
            servers = tools.get("servers") if isinstance(tools.get("servers"), dict) else tools.get("mcp", {}).get("servers", {}) if isinstance(tools.get("mcp"), dict) else {}
    if isinstance(servers, dict):
        for name, raw in servers.items():
            if not isinstance(raw, dict) or not (raw.get("command") or raw.get("url")):
                continue
            entry = _canonical_mcp(raw)
            if name in existing_servers:
                same = _servers_equal(_canonical_mcp(existing_servers[name]), entry)
                items.append(_item("mcp", name, config_path, "skip", conflict=not same,
                                   detail="Atlas 已有内容一致的同名服务器" if same else "Atlas 已有同名但配置不同的服务器，默认跳过"))
            else:
                items.append(_item("mcp", name, config_path, "import", detail=_mcp_detail(entry)))

    if ws is not None:
        for source in (root / "workspace" / "AGENTS.md", root / "workspace" / "SOUL.md",
                       root / "workspace" / "USER.md", root / "AGENTS.md"):
            item = _rules_item(source, f"OpenClaw {source.name}", ws)
            if item:
                items.append(item)
    items.extend(_scan_skill_dirs(root / "skills", "OpenClaw", paths["skills"]))
    items.extend(_scan_md_files("agents", root / "agents", "OpenClaw", paths["agents"]))
    sessions = root / "agents"
    if sessions.is_dir():
        count = sum(1 for path in sessions.glob("*/sessions/*.jsonl") if path.is_file())
        if count:
            items.append(_item("history", f"OpenClaw 会话历史（{count} 条）", sessions, "skip",
                               detail="请在下方逐条预览后选择导入；源会话文件只读"))
    items.sort(key=lambda item: _KIND_ORDER.index(item["kind"]))
    return items, _openclaw_roots(home)


# ---------------------------------------------------------------------------
# Read-only transcript discovery for the dedicated external-history API
# ---------------------------------------------------------------------------

def _history_roots(source: str) -> tuple[Path, ...]:
    if source == "claude":
        config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
        configured = Path(config_dir).expanduser() if config_dir else Path.home() / ".claude"
        if not configured.is_absolute():
            configured = Path.home() / ".claude"
        return (configured / "projects",)
    if source == "codex":
        codex_home = os.environ.get("CODEX_HOME")
        home = Path(codex_home).expanduser() if codex_home else Path.home() / ".codex"
        return home / "sessions", home / "archived_sessions"
    if source == "openclaw":
        openclaw_home = os.environ.get("OPENCLAW_HOME")
        root = Path(openclaw_home).expanduser() if openclaw_home else Path.home() / ".openclaw"
        return (root / "agents",)
    raise ValueError(f"source must be one of {SOURCES}: got {source!r}")


def _is_history_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


def _history_files(
    root: Path, source: str, *, cutoff: float | None = None,
) -> tuple[list[tuple[Path, int, float]], int, bool]:
    """Return recent regular JSONL files strictly beneath the recognized root."""
    if _is_history_link(root) or (
        source == "claude" and _is_history_link(root.parent)
    ) or (
        source == "codex" and not os.environ.get("CODEX_HOME") and _is_history_link(root.parent)
    ):
        return [], 0, False
    try:
        resolved_root = root.resolve(strict=True)
    except OSError:
        return [], 0, False
    if not resolved_root.is_dir():
        return [], 0, False

    candidates: list[tuple[Path, int, float]] = []
    discovered = 0
    reached_cap = False
    visited_dirs = {resolved_root}
    for current, dirnames, filenames in os.walk(resolved_root, topdown=True, followlinks=False):
        base = Path(current)
        safe_dirs: list[str] = []
        for name in sorted(dirnames):
            child = base / name
            if name.lower() in {"subagents", "tool-results"} or _is_history_link(child):
                continue
            try:
                resolved_child = child.resolve(strict=True)
                resolved_child.relative_to(resolved_root)
            except (OSError, ValueError):
                continue
            if resolved_child in visited_dirs:
                continue
            visited_dirs.add(resolved_child)
            safe_dirs.append(name)
        dirnames[:] = safe_dirs
        for filename in filenames:
            if not filename.lower().endswith(".jsonl"):
                continue
            path = base / filename
            try:
                if _is_history_link(path):
                    continue
                stat = path.stat()
                path.resolve(strict=True).relative_to(resolved_root)
            except (OSError, ValueError):
                continue
            if not path.is_file():
                continue
            if cutoff is not None and stat.st_mtime < cutoff:
                continue
            discovered += 1
            candidates.append((path, stat.st_size, stat.st_mtime))
            if discovered >= _HISTORY_MAX_DISCOVERED:
                reached_cap = True
                break
        if reached_cap:
            break

    candidates.sort(key=lambda item: (-item[2], item[0].as_posix()))
    return candidates[:_HISTORY_MAX_RESULTS], discovered, reached_cap or discovered > _HISTORY_MAX_RESULTS


def _text_from_blocks(value: Any, *, codex: bool = False) -> str:
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, list):
        return ""
    allowed = {"text", "input_text", "output_text"} if codex else {"text"}
    parts = [
        str(block.get("text") or "")
        for block in value
        if isinstance(block, dict) and block.get("type") in allowed
        and isinstance(block.get("text"), str)
    ]
    return "\n".join(part for part in parts if part.strip()).strip()


def _timestamp(value: Any) -> str | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(value, UTC).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str) and value.strip():
        raw = value.strip()
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return parsed.astimezone(UTC).isoformat() if parsed.tzinfo else parsed.replace(tzinfo=UTC).isoformat()
        except ValueError:
            return None
    return None


def _append_transcript_message(
    messages: list[dict[str, str]], source: str, session_key: str, role: Any,
    content: Any, timestamp_value: Any, source_id: Any, occurrences: dict[str, int],
    sequence: int,
) -> None:
    if role not in {"user", "assistant"}:
        return
    text = _text_from_blocks(content, codex=source != "claude")
    if not text:
        return
    timestamp = _timestamp(timestamp_value)
    identity = str(source_id or "")
    basis = identity or f"{role}\0{timestamp or ''}\0{text}"
    occurrence = occurrences.get(basis, 0)
    occurrences[basis] = occurrence + 1
    message_key = hashlib.sha256(
        f"{session_key}\0{basis}\0{occurrence}".encode("utf-8", errors="replace")
    ).hexdigest()
    message: dict[str, str] = {
        "role": str(role), "content": text,
        "external_message_key": message_key,
        "_sequence": str(sequence),
    }
    if timestamp:
        message["timestamp"] = timestamp
    messages.append(message)


def _parse_history_file(source: str, root: Path, path: Path, size: int, modified: float) -> dict[str, Any] | None:
    if size < 0 or size > _HISTORY_MAX_FILE_BYTES:
        return None
    try:
        resolved_root = root.resolve(strict=True)
        resolved_path = path.resolve(strict=True)
        relative = resolved_path.relative_to(resolved_root).as_posix()
        file_stat = resolved_path.stat()
        if _is_history_link(path) or file_stat.st_size != size or size > _HISTORY_MAX_FILE_BYTES:
            return None
    except (OSError, ValueError):
        return None
    session_key = hashlib.sha256(f"{source}\0{root.name}\0{relative}".encode("utf-8")).hexdigest()
    messages: list[dict[str, str]] = []
    codex_user_fallbacks: list[tuple[Any, Any, Any]] = []
    occurrences: dict[str, int] = {}
    title = ""
    records = 0
    try:
        with resolved_path.open("r", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                records += 1
                if records > _HISTORY_MAX_RECORDS:
                    return None
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                if source == "claude":
                    record_type = row.get("type")
                    if record_type in {"custom-title", "summary"} and not title:
                        title = str(row.get("customTitle") or row.get("summary") or "").strip()
                    if record_type not in {"user", "assistant"}:
                        continue
                    if row.get("isMeta") or row.get("isSidechain") or row.get("isCompactSummary"):
                        continue
                    if row.get("isVisibleInTranscript") is False:
                        continue
                    message = row.get("message")
                    if not isinstance(message, dict):
                        continue
                    _append_transcript_message(
                        messages, source, session_key, record_type,
                        message.get("content"), row.get("timestamp") or message.get("timestamp"),
                        row.get("uuid") or message.get("id"), occurrences, records,
                    )
                elif source == "codex":
                    row_type = row.get("type")
                    payload = row.get("payload")
                    if not isinstance(payload, dict):
                        continue
                    if row_type == "session_meta":
                        title = title or str(payload.get("title") or "").strip()
                        continue
                    if row_type == "response_item" and payload.get("type") == "message":
                        channel = str(payload.get("channel") or "").lower()
                        phase = str(payload.get("phase") or "").lower()
                        if channel in {"analysis", "reasoning", "justify"} or phase in {"analysis", "commentary"}:
                            continue
                        _append_transcript_message(
                            messages, source, session_key, payload.get("role"),
                            payload.get("content"), payload.get("timestamp") or row.get("timestamp"),
                            payload.get("id") or row.get("id"), occurrences, records,
                        )
                    elif row_type == "event_msg" and payload.get("type") == "user_message":
                        # Newer rollouts also mirror user turns in event_msg. Use
                        # this only when no response_item user message exists.
                        fallback = payload.get("message")
                        if isinstance(fallback, str) and fallback.strip():
                            codex_user_fallbacks.append((
                                fallback, payload.get("timestamp") or row.get("timestamp"),
                                payload.get("id") or row.get("id"), records,
                            ))
                else:
                    row_type = str(row.get("type") or "")
                    if row_type in {"session", "session_meta", "metadata"}:
                        title = title or str(row.get("title") or row.get("label") or "").strip()
                        continue
                    message = row.get("message") if isinstance(row.get("message"), dict) else row
                    role = message.get("role")
                    if role not in {"user", "assistant"}:
                        continue
                    if message.get("isMeta") or message.get("isSidechain") or message.get("isCompactSummary"):
                        continue
                    _append_transcript_message(
                        messages, source, session_key, role,
                        message.get("content", message.get("text")),
                        row.get("timestamp") or message.get("timestamp"),
                        row.get("id") or message.get("id"), occurrences, records,
                    )
    except OSError:
        return None

    if source == "codex" and not any(item["role"] == "user" for item in messages):
        for content, timestamp_value, source_id, sequence in codex_user_fallbacks:
            _append_transcript_message(
                messages, source, session_key, "user", content,
                timestamp_value, source_id, occurrences, sequence,
            )
        messages.sort(key=lambda item: int(item.get("_sequence") or 0))
    for message in messages:
        message.pop("_sequence", None)
    if not messages:
        return None

    first_user = next((item["content"] for item in messages if item["role"] == "user"), "")
    last_assistant = next((item["content"] for item in reversed(messages) if item["role"] == "assistant"), "")
    if not title:
        title = first_user or f"{source.title()} 会话"
    title = re.sub(r"\s+", " ", title).strip()[:120] or f"{source.title()} 会话"
    preview_parts = []
    if first_user:
        preview_parts.append(f"用户：{first_user}")
    if last_assistant:
        preview_parts.append(f"助手：{last_assistant}")
    preview = "\n".join(preview_parts) or first_user or last_assistant
    if len(preview) > _HISTORY_PREVIEW_CHARS:
        preview = preview[:_HISTORY_PREVIEW_CHARS].rstrip() + "…"
    try:
        modified_at = datetime.fromtimestamp(modified, UTC).isoformat()
    except (OverflowError, OSError, ValueError):
        modified_at = ""
    return {
        "key": session_key, "title": title, "modified_at": modified_at,
        "message_count": len(messages), "preview": preview, "messages": messages,
    }


def _history_index() -> dict[str, Any]:
    try:
        raw = json.loads(_HISTORY_INDEX_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"version": 1, "sessions": {}, "jsonl": {}}
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("外部会话导入索引无法读取；为避免重复导入，未继续操作") from exc
    if not isinstance(raw, dict) or raw.get("version") != 1 or not isinstance(raw.get("sessions"), dict):
        raise ValueError("外部会话导入索引格式未知；为避免重复导入，未继续操作")
    jsonl = raw.get("jsonl", {})
    if not isinstance(jsonl, dict):
        jsonl = {}
    return {"version": 1, "sessions": raw["sessions"], "jsonl": jsonl}


def _save_history_index(index: Mapping[str, Any]) -> None:
    target = _HISTORY_INDEX_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".external-history-", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(index, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, target)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def load_external_history(
    source: str, *, max_age_days: int | None = None,
) -> dict[str, Any]:
    """Scan recognized local history roots and return summaries plus import data.

    This helper is local-only: callers cannot supply an arbitrary root or file
    path. The `messages` member is for the import route and must not be exposed
    as part of the list response.
    """
    if max_age_days is not None and (
        isinstance(max_age_days, bool) or max_age_days not in {7, 30, 90}
    ):
        raise ValueError("max_age_days must be 7, 30, 90, or None")
    cutoff = (
        datetime.now(UTC).timestamp() - max_age_days * 24 * 60 * 60
        if max_age_days is not None else None
    )
    roots = _history_roots(source)
    files: list[tuple[Path, Path, int, float]] = []
    discovered = 0
    truncated = False
    for root in roots:
        root_files, root_discovered, root_truncated = _history_files(root, source, cutoff=cutoff)
        files.extend((root, path, size, modified) for path, size, modified in root_files)
        discovered += root_discovered
        truncated = truncated or root_truncated
    files.sort(key=lambda item: (-item[3], item[1].as_posix()))
    files = files[:_HISTORY_MAX_RESULTS]
    sessions = []
    unreadable = 0
    for root, path, size, modified in files:
        session = _parse_history_file(source, root, path, size, modified)
        if session is None:
            unreadable += 1
            continue
        sessions.append(session)
    index = _history_index()["sessions"]
    for session in sessions:
        receipt = index.get(session["key"])
        session["imported"] = bool(isinstance(receipt, dict) and receipt.get("completed"))
    return {
        "source": source,
        "sessions": sessions,
        "total_files": discovered,
        "omitted_files": max(0, discovered - len(files)) + unreadable,
        "truncated": truncated or discovered > len(files),
    }


def list_external_history(source: str, max_age_days: int | None = None) -> dict[str, Any]:
    result = load_external_history(source, max_age_days=max_age_days)
    return {
        key: value for key, value in result.items()
        if key != "sessions"
    } | {
        "sessions": [
            {key: value for key, value in session.items() if key != "messages"}
            for session in result["sessions"]
        ],
    }


def _atlas_servers(config_path: Path) -> dict[str, Any]:
    data = _load_toml(config_path)
    servers = (data or {}).get("tools", {}).get("servers", {}) if isinstance(data, dict) else {}
    return servers if isinstance(servers, dict) else {}


def _rules_item(path: Path, label: str, ws: Path | None) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    if ws is None:
        return _item("rules", label, path, "skip", detail="未指定 workspace，无法合并到 AGENTS.md")
    target = ws / "AGENTS.md"
    if not target.exists():
        return _item("rules", label, path, "import",
                     detail="将创建 workspace 的 AGENTS.md 并写入规则段落")
    source_text = path.read_text(encoding="utf-8")
    missing = _missing_paragraphs(target.read_text(encoding="utf-8"), source_text)
    if not missing:
        return _item("rules", label, path, "skip", detail="规则段落已全部存在于 AGENTS.md")
    return _item("rules", label, path, "merge",
                 detail=f"向 AGENTS.md 追加 {len(missing)} 个段落，原内容保留")


def _scan_skill_dirs(root: Path, scope: str, atlas_skills: Path) -> list[dict[str, Any]]:
    if not root.is_dir():
        return []
    items = []
    for skill_md in sorted(root.rglob("SKILL.md"), key=lambda item: item.as_posix().casefold()):
        source_dir = skill_md.parent
        rel = source_dir.relative_to(root).as_posix()
        target = atlas_skills / Path(*PurePosixPath(rel).parts)
        if target.is_dir() and _sha_dir(target) == _sha_dir(source_dir):
            items.append(_item("skills", rel, source_dir, "skip",
                               detail=f"Atlas 技能目录已有相同副本（{scope}）"))
        elif target.is_dir():
            items.append(_item("skills", rel, source_dir, "skip", conflict=True,
                               detail="Atlas 技能目录已有同名但内容不同的技能，默认跳过"
                                      f"（{scope}）"))
        else:
            items.append(_item("skills", rel, source_dir, "import",
                               detail=f"复制为 Atlas 技能副本（{scope}，"
                                      f"Claude 目录仍被 Atlas 直读）"))
    return items


def _scan_md_files(kind: str, root: Path, scope: str, atlas_dir: Path) -> list[dict[str, Any]]:
    if not root.is_dir():
        return []
    label = "命令" if kind == "commands" else "子 Agent"
    items = []
    files = sorted(root.rglob("*.md"), key=lambda item: item.as_posix().casefold())
    for path in files:
        rel = path.relative_to(root).with_suffix("").as_posix()
        target = atlas_dir / Path(*PurePosixPath(rel).parts)
        target = target.with_suffix(".md")
        if target.is_file() and _sha_file(target) == _sha_file(path):
            items.append(_item(kind, rel, path, "skip",
                               detail=f"Atlas {label}目录已有相同文件（{scope}）"))
        elif target.is_file():
            items.append(_item(kind, rel, path, "skip", conflict=True,
                               detail=f"Atlas {label}目录已有同名但内容不同的文件，"
                                      f"默认跳过（{scope}）"))
        else:
            items.append(_item(kind, rel, path, "import",
                               detail=f"复制到 Atlas {label}目录（{scope}）"))
    return items


def _model_prefs_item(source: str, path: Path, settings_path: Path) -> dict[str, Any] | None:
    if source == "claude":
        data = _load_json(path)
        value = data.get("model") if isinstance(data, dict) else None
    else:
        data = _load_toml(path)
        value = data.get("model") if isinstance(data, dict) else None
    if not isinstance(value, str) or not value.strip():
        return None
    current = load_user_settings(settings_path).get("selected_model")
    if current == value:
        return _item("model_prefs", "默认模型", path, "skip", detail=f"Atlas 默认模型已是 {value}")
    if current:
        return _item("model_prefs", "默认模型", path, "skip", conflict=True,
                     detail=f"将覆盖 Atlas 现有默认模型 {current}，默认跳过")
    return _item("model_prefs", "默认模型", path, "import",
                 detail=f"写入 Atlas 设置 selected_model={value}")


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def import_external(source: str, items: Sequence[dict], *, workspace: Path | None = None,
                    atlas_home: Path | None = None,
                    source_home: Path | None = None) -> dict:
    """Import the user-selected manifest items. Only Atlas-side files change.

    Returns ``{"imported", "skipped", "report"}`` with a short Chinese report.
    """
    if source not in SOURCES:
        raise ValueError(f"source must be one of {SOURCES}: got {source!r}")
    home = _source_home(source_home)
    ws = Path(workspace).expanduser() if workspace else None
    paths = _atlas_layout(atlas_home)

    imported: list[tuple[str, str]] = []
    skipped: list[tuple[str, str]] = []
    written_servers: set[str] = set()

    for raw in items:
        item = dict(raw)
        kind = str(item.get("kind") or "")
        name = str(item.get("name") or "")
        ok, note = _import_one(source, item, paths, home, ws, written_servers)
        (imported if ok else skipped).append((kind, name) if ok else (kind, note or name))

    lines: list[str] = []
    if imported:
        by_kind: dict[str, list[str]] = {}
        for kind, name in imported:
            by_kind.setdefault(kind, []).append(name)
        summary = "；".join(
            f"{_KIND_LABELS[kind]} {len(names)} 个"
            f"（{'、'.join(names[:5])}{'等' if len(names) > 5 else ''}）"
            for kind, names in sorted(by_kind.items(), key=lambda pair: _KIND_ORDER.index(pair[0]))
        )
        lines.append(f"已导入 {len(imported)} 项：{summary}")
    if skipped:
        reasons = Counter(note for _kind, note in skipped)
        reason_text = "；".join(
        f"{reason}（{count} 个）" for reason, count in reasons.most_common()
    )
        lines.append(f"跳过 {len(skipped)} 项：{reason_text}")
    if not lines:
        lines.append("没有可导入的条目")
    return {"imported": len(imported), "skipped": len(skipped), "report": "\n".join(lines)}


def _import_one(source: str, item: dict[str, Any], paths: dict[str, Path],
                home: Path, ws: Path | None, written_servers: set[str]) -> tuple[bool, str]:
    kind = str(item.get("kind") or "")
    name = str(item.get("name") or "")
    action = str(item.get("action") or "skip")
    path = Path(item["path"]) if item.get("path") else None

    if kind == "history":
        return False, "只读历史，不导入"
    if action == "skip":
        if item.get("conflict"):
            return False, "同名冲突，默认保留 Atlas 版本"
        return False, "按选择跳过"

    if kind == "mcp":
        return _import_mcp(source, name, path, item, paths, written_servers)
    if kind == "hooks":
        return _import_hooks(path, paths)
    if kind == "rules":
        return _import_rules(path, ws)
    if kind == "skills":
        return _import_copy_dir(name, path, paths["skills"], bool(item.get("conflict")))
    if kind == "commands":
        return _import_copy_file(name, path, paths["commands"])
    if kind == "agents":
        if source == "codex":
            return False, "Atlas 直接读取 ~/.codex/agents，导入会重复"
        return _import_copy_file(name, path, paths["agents"])
    if kind == "model_prefs":
        return _import_model_prefs(source, home, item, paths)
    return False, "未知条目类型"


def _import_mcp(source: str, name: str, path: Path | None, item: dict[str, Any],
                paths: dict[str, Path], written_servers: set[str]) -> tuple[bool, str]:
    if not name or name in written_servers:
        return False, "MCP 名称缺失或本批已导入同名服务器"
    if path is None:
        return False, "缺少源配置路径"
    raw = _read_source_mcp(source, path, name)
    if raw is None:
        return False, "源 MCP 配置已不可读"
    entry = _canonical_mcp(raw)
    entry["env"] = _protect_mcp_env(source, path, name, entry.get("env", {}))

    config_path = paths["config_toml"]
    text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    try:
        parsed = tomllib.loads(text) if text.strip() else {}
    except tomllib.TOMLDecodeError:
        return False, "atlas.toml 解析失败，未写入"
    existing = (parsed.get("tools") or {}).get("servers") or {}
    if name in existing:
        if _servers_equal(_canonical_mcp(existing[name]), entry):
            return False, "内容一致，跳过"
        if not item.get("conflict"):
            return False, "Atlas 同名服务器配置已变化，跳过"
        text = _remove_server_table(text, name)

    if (parsed.get("tools") or {}).get("auto_start"):
        text = _extend_auto_start(text, [name])
    text = (text.rstrip("\n") + "\n\n" if text.strip() else "") + _server_block(name, entry) + "\n"
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return False, "生成的 atlas.toml 无法解析，未写入"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(text, encoding="utf-8")
    written_servers.add(name)
    return True, ""


def _import_hooks(path: Path | None, paths: dict[str, Path]) -> tuple[bool, str]:
    if path is None:
        return False, "缺少源配置路径"
    data = _load_json(path)
    entries = _hook_entries(parse_claude_hooks(data)) if isinstance(data, dict) else []
    if not entries:
        return False, "无可映射到 Atlas 事件的 hooks"
    store = HookStore(paths["hooks_toml"])
    existing = store.list()
    have = {(hook.get("event"), hook.get("command")) for hook in existing}
    fresh = [entry for entry in entries if (entry["event"], entry["command"]) not in have]
    if not fresh:
        return False, "hooks 已存在，内容一致"
    store.save(existing + fresh)
    return True, ""


def _import_rules(path: Path | None, ws: Path | None) -> tuple[bool, str]:
    if ws is None:
        return False, "未指定 workspace，无法合并规则"
    if path is None or not path.is_file():
        return False, "源规则文件不可读"
    status = _merge_markdown(ws / "AGENTS.md", path.read_text(encoding="utf-8"))
    if status == "identical":
        return False, "内容一致，跳过"
    return True, ""


def _safe_rel(name: str) -> PurePosixPath | None:
    rel = PurePosixPath(name)
    if not name or ".." in rel.parts or rel.is_absolute():
        return None
    return rel


def _import_copy_dir(name: str, path: Path | None, atlas_dir: Path,
                     conflict: bool) -> tuple[bool, str]:
    rel = _safe_rel(name)
    if rel is None or path is None or not path.is_dir():
        return False, "源技能目录不可读或名称非法"
    target = atlas_dir / Path(*rel.parts)
    if target.is_dir():
        if _sha_dir(target) == _sha_dir(path):
            return False, "内容一致，跳过"
        if not conflict:
            return False, "Atlas 侧已有不同内容，跳过"
        shutil.rmtree(target)  # user explicitly forced import over the conflict
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(path, target)
    return True, ""


def _import_copy_file(name: str, path: Path | None, atlas_dir: Path) -> tuple[bool, str]:
    rel = _safe_rel(name)
    if rel is None or path is None or not path.is_file():
        return False, "源文件不可读或名称非法"
    target = atlas_dir / Path(*rel.parts)
    target = target.with_suffix(".md")
    if target.is_file():
        if _sha_file(target) == _sha_file(path):
            return False, "内容一致，跳过"
        return False, "Atlas 侧已有不同内容，跳过"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, target)
    return True, ""


def _import_model_prefs(source: str, home: Path, item: dict[str, Any],
                        paths: dict[str, Path]) -> tuple[bool, str]:
    if source == "claude":
        path = home / ".claude" / "settings.json"
    else:
        path = home / ".codex" / "config.toml"
    value = None
    data = _load_json(path) if source == "claude" else _load_toml(path)
    if isinstance(data, dict):
        value = data.get("model")
    if not isinstance(value, str) or not value.strip():
        return False, "源默认模型配置不可读"
    settings = load_user_settings(paths["user_settings"])
    if settings.get("selected_model") == value:
        return False, "内容一致，跳过"
    if settings.get("selected_model") and not item.get("conflict"):
        return False, "Atlas 已有不同默认模型，跳过"
    settings["selected_model"] = value
    save_user_settings(settings, paths["user_settings"])
    return True, ""

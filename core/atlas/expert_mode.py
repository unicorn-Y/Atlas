"""专家模式：开着时，在普通配置之上额外加载用户自己的一整套内容。

内容放在一个独立的目录（默认 ``~/.atlas-expert``），它本身是一个单独的 git 仓库
（默认 ``expert.repo``），和 Atlas 源码互不影响::

    prompts/<名字>.md            追加到系统提示词末尾
    skills/<名字>/SKILL.md       额外的技能
    plugins/<名字>/...           额外的插件（和普通插件同格式）
    tools/<编号>/tool.json       额外的自定义工具（和普通自定义工具同格式）
    mcp/<名字>.json              额外的 MCP 服务器（字段同 [tools.servers.x]）
    config.toml                  配置覆盖层，和 atlas.toml 同结构，深度合并

仓库里的每一项都可以单独「安装 / 卸载」：卸载只是本机不加载，文件仍在仓库里。
装了哪些记在本机 ``data/user-settings.json``（不跟仓库同步）；从界面新建的项自动装上，
从仓库拉下来的新项默认不装。开关和装卸都即时生效，不用重启。

日志只记数量和名字，不记内容。
"""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import socket
import subprocess
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any

from atlas import config as _config

_SETTING_KEY = "expert_mode"
_INSTALLED_KEY = "expert_installed"
DEFAULT_REPO = "https://github.com/unicorn-Y/atlas-expert.git"
KINDS = ("prompts", "skills", "plugins", "tools", "mcp")
_NAME = re.compile(r"[^\\/:*?\"<>|\x00-\x1f]{1,64}\Z")
_TOOL_ID = re.compile(r"[a-z0-9-]{1,64}\Z")
_SKILL_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")  # 和技能索引的要求一致
_SKILL_PRIORITY = 70  # 高于内置/插件：同名时专家里的那份生效


# ---------------------------------------------------------------------------
# 位置与开关
# ---------------------------------------------------------------------------

def _section(raw: dict[str, Any] | None) -> dict[str, Any]:
    if raw is None:
        raw = _config.get_config().base_raw
    value = raw.get("expert", {})
    return value if isinstance(value, dict) else {}


def pack_dir(raw: dict[str, Any] | None = None) -> Path:
    configured = str(_section(raw).get("dir") or "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".atlas-expert"


def repo_url(raw: dict[str, Any] | None = None) -> str:
    value = _section(raw).get("repo", DEFAULT_REPO)
    return str(value or "").strip()


def _legacy_config_path() -> Path:
    return _config.CONFIG_PATH.parent / "expert.toml"


def _legacy_instructions_path() -> Path:
    return _config.CONFIG_PATH.parent / "expert-instructions.md"


def is_enabled() -> bool:
    return bool(_config.load_user_settings().get(_SETTING_KEY, False))


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError):
        return ""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


# ---------------------------------------------------------------------------
# 安装状态（本机）
# ---------------------------------------------------------------------------

def installed() -> dict[str, list[str]]:
    stored = _config.load_user_settings().get(_INSTALLED_KEY, {})
    stored = stored if isinstance(stored, dict) else {}
    return {kind: sorted({str(n) for n in stored.get(kind, []) if isinstance(n, str)}) for kind in KINDS}


def _save_installed(state: dict[str, list[str]]) -> None:
    settings = _config.load_user_settings()
    settings[_INSTALLED_KEY] = {kind: sorted(set(state.get(kind, []))) for kind in KINDS}
    _config.save_user_settings(settings)


def set_installed(kind: str, name: str, value: bool) -> None:
    _check_kind(kind)
    state = installed()
    names = set(state[kind])
    (names.add if value else names.discard)(name)
    state[kind] = sorted(names)
    _save_installed(state)
    _config.reload_config()


# ---------------------------------------------------------------------------
# 仓库里的各项
# ---------------------------------------------------------------------------

def _check_kind(kind: str) -> None:
    if kind not in KINDS:
        raise ValueError(f"不认识的类别：{kind}")


def _check_name(kind: str, name: str) -> None:
    if not _NAME.fullmatch(name) or name.strip() != name or name.startswith(".") or name in {".", ".."}:
        raise ValueError("名字不能为空、不能以点开头，也不能含有 \\ / : * ? \" < > |")
    if kind == "tools" and not _TOOL_ID.fullmatch(name):
        raise ValueError("工具编号只能用小写英文字母、数字和连字符。")
    if kind == "skills" and not _SKILL_NAME.fullmatch(name):
        raise ValueError("技能名只能用小写英文字母、数字和连字符（如 my-skill），中文说明写在 description 里。")


def _item_path(kind: str, name: str, root: Path | None = None) -> Path:
    """一项在仓库里的位置：单文件类是文件本身，其余是它的文件夹。"""
    base = (root or pack_dir()) / kind
    if kind == "prompts":
        return base / f"{name}.md"
    if kind == "mcp":
        return base / f"{name}.json"
    return base / name


def _main_file(kind: str, name: str, root: Path | None = None) -> Path | None:
    """界面里直接编辑的那个文件；插件没有固定主文件时返回 None（只能开文件夹改）。"""
    path = _item_path(kind, name, root)
    if kind in ("prompts", "mcp"):
        return path
    if kind == "skills":
        return path / "SKILL.md"
    if kind == "tools":
        return path / "tool.json"
    for candidate in (path / ".claude-plugin" / "plugin.json", path / "plugin.json"):
        if candidate.is_file():
            return candidate
    return None


def _scan(kind: str, root: Path) -> list[str]:
    base = root / kind
    if not base.is_dir():
        return []
    names: list[str] = []
    for child in base.iterdir():
        if child.name.startswith("."):
            continue
        if kind == "prompts" and child.is_file() and child.suffix.lower() == ".md":
            names.append(child.stem)
        elif kind == "mcp" and child.is_file() and child.suffix.lower() == ".json":
            names.append(child.stem)
        elif kind == "skills" and (child / "SKILL.md").is_file():
            names.append(child.name)
        elif kind == "tools" and (child / "tool.json").is_file():
            names.append(child.name)
        elif kind == "plugins" and child.is_dir():
            names.append(child.name)
    return sorted(names, key=str.casefold)


def _describe(kind: str, name: str, root: Path) -> str:
    """列表里显示的一行说明：从各自的格式里取 description，取不到就空着。"""
    main = _main_file(kind, name, root)
    text = _read(main) if main else ""
    if not text:
        return ""
    try:
        if kind in ("tools", "mcp", "plugins"):
            data = json.loads(text)
            return str(data.get("description") or data.get("name") or "")[:160] if isinstance(data, dict) else ""
        if kind == "skills":
            match = re.search(r"^description:\s*(.+)$", text, re.MULTILINE)
            return match.group(1).strip().strip("\"'")[:160] if match else ""
    except ValueError:
        return ""
    first = next((line.strip("# ").strip() for line in text.splitlines() if line.strip()), "")
    return first[:160]


def list_items() -> dict[str, list[dict[str, Any]]]:
    root = pack_dir()
    state = installed()
    return {
        kind: [
            {"name": name, "installed": name in state[kind], "description": _describe(kind, name, root),
             "editable": _main_file(kind, name, root) is not None}
            for name in _scan(kind, root)
        ]
        for kind in KINDS
    }


def _template(kind: str, name: str) -> str:
    if kind == "skills":
        return f"---\nname: {name}\ndescription: 一句话说明什么时候用这个技能\n---\n\n# {name}\n\n"
    if kind == "tools":
        return json.dumps({
            "id": name, "name": name, "description": "这个工具做什么",
            "command": ["python", "run.py"],
            "input_schema": {"type": "object", "properties": {}},
            "timeout_s": 30, "enabled": True,
        }, ensure_ascii=False, indent=2) + "\n"
    if kind == "mcp":
        return json.dumps({"transport": "stdio", "command": "npx", "args": [], "env": {}},
                          ensure_ascii=False, indent=2) + "\n"
    if kind == "plugins":
        return json.dumps({"name": name, "version": "0.1.0", "description": ""},
                          ensure_ascii=False, indent=2) + "\n"
    return ""


def _validate(kind: str, name: str, text: str) -> None:
    if kind in ("tools", "mcp", "plugins"):
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise ValueError(f"JSON 写法有错：{exc}") from None
        if not isinstance(data, dict):
            raise ValueError("内容必须是一个 JSON 对象。")
        if kind == "tools" and data.get("id") != name:
            raise ValueError(f"tool.json 里的 id 必须和编号一致（{name}）。")


def read_item(kind: str, name: str) -> dict[str, Any]:
    _check_kind(kind)
    _check_name(kind, name)
    main = _main_file(kind, name)
    return {"kind": kind, "name": name, "path": str(_item_path(kind, name)),
            "file": str(main) if main else "", "text": _read(main) if main else ""}


def create_item(kind: str, name: str, text: str | None = None) -> None:
    _check_kind(kind)
    _check_name(kind, name)
    if _item_path(kind, name).exists():
        raise FileExistsError(f"已经有叫「{name}」的了。")
    body = _template(kind, name) if text is None else text
    _validate(kind, name, body)
    if kind == "plugins":
        _write(_item_path(kind, name) / ".claude-plugin" / "plugin.json", body)
    else:
        main = _main_file(kind, name)
        assert main is not None
        _write(main, body)
    set_installed(kind, name, True)
    _config.log.info("expert_mode.item_created", kind=kind, name=name)


def save_item(kind: str, name: str, text: str) -> None:
    _check_kind(kind)
    _check_name(kind, name)
    main = _main_file(kind, name)
    if main is None or not _item_path(kind, name).exists():
        raise FileNotFoundError(name)
    _validate(kind, name, text)
    _write(main, text)
    _config.reload_config()


def delete_item(kind: str, name: str) -> None:
    """从仓库里删掉（同步后远端也没了，但 git 历史里还找得回）。"""
    _check_kind(kind)
    _check_name(kind, name)
    path = _item_path(kind, name)
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()
    set_installed(kind, name, False)
    _config.log.info("expert_mode.item_deleted", kind=kind, name=name)


# ---------------------------------------------------------------------------
# 叠加到普通配置 / 提示词上
# ---------------------------------------------------------------------------

def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _overlay_text(raw: dict[str, Any] | None = None) -> str:
    text = _read(pack_dir(raw) / "config.toml")
    return text if text.strip() else _read(_legacy_config_path())


def _mcp_servers(raw: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    root = pack_dir(raw)
    servers: dict[str, dict[str, Any]] = {}
    for name in installed()["mcp"]:
        try:
            data = json.loads(_read(_item_path("mcp", name, root)) or "null")
        except ValueError:
            _config.log.warning("expert_mode.mcp_invalid", name=name)
            continue
        if isinstance(data, dict):
            servers[name] = {**data, "enabled": True}
    return servers


def apply_overlay(data: dict[str, Any]) -> dict[str, Any]:
    """普通配置 → 专家模式开着时叠上 config.toml 和已装 MCP 的结果；关着时原样返回。"""
    if not is_enabled():
        return data
    merged = data
    text = _overlay_text(data)
    if text.strip():
        try:
            merged = deep_merge(merged, tomllib.loads(text))
        except tomllib.TOMLDecodeError:
            _config.log.warning("expert_mode.overlay_invalid")
    servers = _mcp_servers(data)
    if servers:
        merged = deep_merge(merged, {"tools": {"servers": servers}})
        tools = merged.setdefault("tools", {})
        auto_start = list(tools.get("auto_start", []) or [])
        if auto_start:  # 非空表示「只启动这些」，要把专家的也加进去
            tools["auto_start"] = auto_start + [n for n in servers if n not in auto_start]
    return merged


def instructions() -> str:
    """专家模式开着时追加到系统提示词的内容：已装的提示词按名字顺序拼起来。"""
    if not is_enabled():
        return ""
    root = pack_dir()
    parts = [_read(_item_path("prompts", name, root)).strip() for name in installed()["prompts"]]
    legacy = _read(_legacy_instructions_path()).strip()
    return "\n\n".join(filter(None, [legacy, *parts]))


def set_enabled(enabled: bool) -> None:
    settings = _config.load_user_settings()
    settings[_SETTING_KEY] = bool(enabled)
    _config.save_user_settings(settings)
    _config.reload_config()
    _config.log.info("expert_mode.toggled", enabled=bool(enabled))


def save_overlay(text: str) -> None:
    if text.strip():
        tomllib.loads(text)  # 写坏了直接报错，不落盘
    _write(pack_dir() / "config.toml", text)
    _config.reload_config()


# ---------------------------------------------------------------------------
# 即时生效：把已装的技能 / 工具 / 插件 / MCP 接到正在运行的 Atlas 上
# ---------------------------------------------------------------------------

_applied_mcp: set[str] = set()


def runtime_selection() -> dict[str, list[Path]]:
    if not is_enabled():
        return {kind: [] for kind in KINDS}
    root = pack_dir()
    state = installed()
    return {
        kind: [p for p in (_item_path(kind, n, root) for n in state[kind]) if p.exists()]
        for kind in KINDS
    }


def prime_runtime(services: Any) -> None:
    """启动时、技能扫描和插件加载之前调用：只登记来源，扫描和加载交给正常启动流程。"""
    selection = runtime_selection()
    if getattr(services, "skill_mgr", None) is not None:
        from atlas.skills import SkillSource

        for path in selection["skills"]:
            services.skill_mgr.register_skill_source(
                SkillSource(f"expert:{path.name}", path, _SKILL_PRIORITY, layout="single"))
    if getattr(services, "custom_tools", None) is not None:
        services.custom_tools.extra_dirs = list(selection["tools"])
    if getattr(services, "plugin_runtime", None) is not None:
        services.plugin_runtime.extra_roots = list(selection["plugins"])


async def apply_runtime() -> dict[str, int]:
    """开关、装卸、保存后调用：不重启就让变化生效。拿不到运行中的服务时静默跳过。"""
    import atlas.server as server

    selection = runtime_selection()

    skill_mgr = getattr(server, "skill_mgr", None)
    if skill_mgr is not None:
        from atlas.skills import SkillSource

        skill_mgr.replace_skill_sources("expert:", [
            SkillSource(f"expert:{path.name}", path, _SKILL_PRIORITY, layout="single")
            for path in selection["skills"]
        ])

    custom_tools = getattr(server, "custom_tools", None)
    if custom_tools is not None:
        custom_tools.extra_dirs = list(selection["tools"])

    plugin_runtime = getattr(server, "plugin_runtime", None)
    if plugin_runtime is not None and (plugin_runtime.extra_roots or selection["plugins"]):
        plugin_runtime.extra_roots = list(selection["plugins"])
        from atlas.api.run_drive import _reload_extensions

        try:
            await _reload_extensions()
        except Exception:  # noqa: BLE001 — 插件出错不能拖垮开关本身
            _config.log.exception("expert_mode.plugins_reload_failed")

    await _apply_mcp(server)

    counts = {kind: len(paths) for kind, paths in selection.items()}
    _config.log.info("expert_mode.applied", enabled=is_enabled(), **counts)
    return counts


async def _apply_mcp(server: Any) -> None:
    global _applied_mcp
    wanted = _mcp_servers() if is_enabled() else {}
    mcp_client = getattr(server, "mcp_client", None)
    removed = _applied_mcp - set(wanted)
    if mcp_client is not None:
        from atlas.tools.mcp_client import MCPServerConfig

        for name in removed:
            tool_names = {t.qualified_name for t in mcp_client.get_server_tools(name)}
            await mcp_client.disconnect_server(name)
            try:
                import asyncio

                from atlas.engine.hermes_runtime import HermesRuntime

                await asyncio.to_thread(HermesRuntime.unregister_atlas_mcp_server, name, tool_names)
            except Exception:  # noqa: BLE001
                _config.log.warning("expert_mode.mcp_unregister_failed", name=name)
        for name, spec in wanted.items():
            if name in mcp_client.get_server_names():
                continue
            try:
                await mcp_client._connect_server(MCPServerConfig(
                    name=name, transport=str(spec.get("transport", spec.get("type", "stdio"))),
                    command=spec.get("command"), args=[str(a) for a in spec.get("args", [])],
                    env={str(k): str(v) for k, v in (spec.get("env") or {}).items()},
                    cwd=spec.get("cwd"), url=spec.get("url"), enabled=True,
                ))
            except Exception:  # noqa: BLE001
                _config.log.warning("expert_mode.mcp_connect_failed", name=name)
    _applied_mcp = set(wanted)


# ---------------------------------------------------------------------------
# 仓库同步
# ---------------------------------------------------------------------------

def _git(*args: str, check: bool = True, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    result = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args], cwd=cwd or pack_dir(), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=180, env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if check and result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip() or f"git {args[0]} 失败")
    return result


def _migrate_legacy(root: Path) -> None:
    """把旧版 config/expert*.{toml,md} 搬进仓库，只搬一次。"""
    legacy_text = _read(_legacy_instructions_path())
    if legacy_text.strip() and not (root / "prompts" / "附加说明.md").exists():
        _write(root / "prompts" / "附加说明.md", legacy_text)
        state = installed()
        state["prompts"] = sorted({*state["prompts"], "附加说明"})
        _save_installed(state)
    legacy_config = _read(_legacy_config_path())
    if legacy_config.strip() and not (root / "config.toml").exists():
        _write(root / "config.toml", legacy_config)
    for path in (_legacy_instructions_path(), _legacy_config_path()):
        if path.exists():
            path.replace(path.with_name(path.name + ".migrated"))


def ensure_pack() -> dict[str, Any]:
    """目录不在就按配置的仓库克隆下来；没配仓库就建个本地仓库。失败不抛，返回原因。"""
    root = pack_dir()
    url = repo_url()
    message = ""
    try:
        if not (root / ".git").exists():
            if url and (not root.exists() or not any(root.iterdir())):
                root.parent.mkdir(parents=True, exist_ok=True)
                _git("clone", url, str(root), cwd=root.parent)
                message = "已从仓库克隆"
            else:
                root.mkdir(parents=True, exist_ok=True)
                _git("init", "-b", "main")
                if url:
                    _git("remote", "add", "origin", url)
                message = "已建好本地仓库"
        for kind in KINDS:
            (root / kind).mkdir(parents=True, exist_ok=True)
        _migrate_legacy(root)
    except Exception as exc:  # noqa: BLE001
        message = f"准备专家目录失败：{exc}"
        _config.log.warning("expert_mode.ensure_failed", error=str(exc)[:300])
    return {"message": message}


def _identity() -> list[str]:
    name = _git("config", "user.name", check=False).stdout.strip()
    email = _git("config", "user.email", check=False).stdout.strip()
    return [] if name and email else ["-c", "user.name=Atlas", "-c", "user.email=atlas@localhost"]


def git_status() -> dict[str, Any]:
    root = pack_dir()
    if not (root / ".git").exists():
        return {"ready": False, "changes": 0, "ahead": 0, "behind": 0, "remote": repo_url()}
    changes = len([line for line in _git("status", "--porcelain", check=False).stdout.splitlines() if line.strip()])
    remote = _git("remote", "get-url", "origin", check=False).stdout.strip()
    ahead = behind = 0
    counts = _git("rev-list", "--left-right", "--count", "HEAD...origin/main", check=False)
    if counts.returncode == 0 and counts.stdout.split():
        ahead, behind = (int(x) for x in counts.stdout.split()[:2])
    last = _git("log", "-1", "--format=%cd", "--date=format:%Y-%m-%d %H:%M", check=False).stdout.strip()
    return {"ready": True, "changes": changes, "ahead": ahead, "behind": behind, "remote": remote, "last_commit": last}


def sync(prefer: str | None = None) -> dict[str, Any]:
    """提交本机改动 → 拉远端 → 推上去。

    两边改了同一处时默认不动，返回冲突文件让用户选；``prefer`` 为 ``"local"``
    或 ``"remote"`` 时按选的那边解决后再推。
    """
    ensure_pack()
    root = pack_dir()
    if not (root / ".git").exists():
        raise RuntimeError("专家目录还不是 git 仓库。")
    _git("add", "-A")
    if _git("status", "--porcelain").stdout.strip():
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        _git(*_identity(), "commit", "-q", "-m", f"同步：{socket.gethostname()} {stamp}")
    if not _git("remote", check=False).stdout.strip():
        return {"status": "local_only", "message": "没有配置远端仓库，只在本机提交了。"}
    _git("fetch", "origin")
    has_remote = _git("rev-parse", "--verify", "--quiet", "origin/main", check=False).returncode == 0
    has_local = _git("rev-parse", "--verify", "--quiet", "HEAD", check=False).returncode == 0
    if has_remote and not has_local:
        _git("checkout", "-B", "main", "origin/main")
    elif has_remote:
        strategy = {"local": ["-X", "theirs"], "remote": ["-X", "ours"]}.get(prefer or "", [])
        rebase = _git(*_identity(), "rebase", *strategy, "origin/main", check=False)
        if rebase.returncode != 0:
            conflicts = [line for line in _git("diff", "--name-only", "--diff-filter=U", check=False).stdout.splitlines() if line]
            _git("rebase", "--abort", check=False)
            if conflicts:
                return {"status": "conflict", "files": conflicts,
                        "message": "本机和仓库都改了同样的文件，选一边保留后再同步。"}
            raise RuntimeError((rebase.stderr or rebase.stdout).strip())
    if _git("rev-parse", "--verify", "--quiet", "HEAD", check=False).returncode == 0:
        _git("push", "-u", "origin", "HEAD:main")
    _config.reload_config()
    _config.log.info("expert_mode.synced")
    return {"status": "ok", "message": "已同步"}


def open_folder(kind: str = "", name: str = "") -> str:
    if kind:
        _check_kind(kind)
    if name:
        _check_name(kind, name)
    path =_item_path(kind, name) if kind and name else (pack_dir() / kind if kind else pack_dir())
    if not path.exists():
        path = pack_dir()
    target = path if path.is_dir() else path.parent
    if hasattr(os, "startfile"):
        os.startfile(target)  # type: ignore[attr-defined]
    return str(target)


# ---------------------------------------------------------------------------
# 给界面的总览
# ---------------------------------------------------------------------------

def status() -> dict[str, Any]:
    text = _overlay_text()
    try:
        keys = sorted(tomllib.loads(text)) if text.strip() else []
        error = ""
    except tomllib.TOMLDecodeError as exc:
        keys, error = [], str(exc)
    return {
        "enabled": is_enabled(),
        "dir": str(pack_dir()),
        "repo": repo_url(),
        "items": list_items(),
        "config_text": text,
        "overlay_sections": keys,
        "config_error": error,
        "git": git_status(),
    }

"""工作台挂件的文件夹、清单（agent.json）和隔离环境。"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from atlas.config import DATA_ROOT

MODES = ("acp", "terminal", "command")
PERMISSIONS = ("ask", "allow")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

# 子进程不能继承的主体变量：后端口令、数据目录、Hermes、Python 虚拟环境。
_STRIP_PREFIXES = ("ATLAS_", "HERMES_", "AGENT_BROWSER_")
_STRIP_KEYS = {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "PYTHONSAFEPATH"}

# isolate_config 打开时，把常见 agent 的配置目录指到挂件自己的 home/。
_CONFIG_DIR_VARS = {
    "CLAUDE_CONFIG_DIR": "claude",
    "CODEX_HOME": "codex",
    "GEMINI_CLI_HOME": "gemini",
    "QWEN_HOME": "qwen",
    "XDG_CONFIG_HOME": "xdg/config",
    "XDG_DATA_HOME": "xdg/data",
    "XDG_STATE_HOME": "xdg/state",
}


def workbench_root() -> Path:
    return DATA_ROOT / "data" / "workbench"


def agents_root() -> Path:
    return workbench_root() / "agents"


@dataclass
class AgentManifest:
    id: str
    name: str
    mode: str = "acp"
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    description: str = ""
    version: str = ""
    source: str = "custom"
    icon: str = ""
    repository: str = ""
    isolate_config: bool = False
    permission: str = "ask"
    enabled: bool = True
    cwd: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentManifest:
        known = {name for name in cls.__dataclass_fields__}
        manifest = cls(**{key: value for key, value in data.items() if key in known})
        manifest.validate()
        return manifest

    def validate(self) -> None:
        if not _ID_RE.match(self.id or ""):
            raise ValueError("挂件 id 只能用小写字母、数字、点、横线和下划线")
        if not (self.name or "").strip():
            raise ValueError("挂件需要一个名字")
        if self.mode not in MODES:
            raise ValueError(f"mode 只能是 {', '.join(MODES)}")
        if self.permission not in PERMISSIONS:
            raise ValueError("permission 只能是 ask 或 allow")
        if not (self.command or "").strip():
            raise ValueError("需要填启动命令")
        if not isinstance(self.args, list) or not all(isinstance(a, str) for a in self.args):
            raise ValueError("args 必须是字符串列表")
        if not isinstance(self.env, dict):
            raise ValueError("env 必须是键值对")
        self.env = {str(k): str(v) for k, v in self.env.items()}
        if self.mode == "command" and not any("{prompt}" in a for a in self.args):
            raise ValueError("一次性命令模式的参数里要有 {prompt}，任务会填到这里")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class WorkbenchStore:
    """读写挂件文件夹。所有路径都在 ``agents_root()`` 之下。"""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or agents_root()

    def agent_dir(self, agent_id: str) -> Path:
        if not _ID_RE.match(agent_id or ""):
            raise KeyError(agent_id)
        return self.root / agent_id

    def list(self) -> list[AgentManifest]:
        if not self.root.is_dir():
            return []
        items: list[AgentManifest] = []
        for child in sorted(self.root.iterdir()):
            manifest_path = child / "agent.json"
            if not manifest_path.is_file():
                continue
            try:
                items.append(AgentManifest.from_dict(json.loads(manifest_path.read_text(encoding="utf-8"))))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
        return items

    def get(self, agent_id: str) -> AgentManifest:
        path = self.agent_dir(agent_id) / "agent.json"
        if not path.is_file():
            raise KeyError(agent_id)
        return AgentManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def save(self, manifest: AgentManifest, *, create: bool = False) -> AgentManifest:
        manifest.validate()
        folder = self.agent_dir(manifest.id)
        if create and (folder / "agent.json").exists():
            raise FileExistsError(manifest.id)
        if not create and not (folder / "agent.json").exists():
            raise KeyError(manifest.id)
        now = time.time()
        manifest.created_at = manifest.created_at or now
        manifest.updated_at = now
        for sub in ("workspace", "home", "sessions"):
            (folder / sub).mkdir(parents=True, exist_ok=True)
        temporary = folder / "agent.json.tmp"
        temporary.write_text(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(folder / "agent.json")
        return manifest

    def delete(self, agent_id: str) -> None:
        folder = self.agent_dir(agent_id)
        if not (folder / "agent.json").exists():
            raise KeyError(agent_id)
        shutil.rmtree(folder)

    def unique_id(self, base: str) -> str:
        slug = re.sub(r"[^a-z0-9._-]+", "-", base.lower()).strip("-._")[:56] or "agent"
        candidate, n = slug, 2
        while (self.root / candidate).exists():
            candidate, n = f"{slug}-{n}", n + 1
        return candidate

    # -- runtime paths ---------------------------------------------------
    def workspace(self, manifest: AgentManifest) -> Path:
        if manifest.cwd:
            path = Path(manifest.cwd).expanduser()
            if path.is_dir():
                return path.resolve()
        path = self.agent_dir(manifest.id) / "workspace"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def sessions_dir(self, agent_id: str) -> Path:
        path = self.agent_dir(agent_id) / "sessions"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def environment(self, manifest: AgentManifest) -> dict[str, str]:
        """主体环境去掉 Atlas 专属变量，再叠上挂件自己的。"""
        env = {
            key: value for key, value in os.environ.items()
            if key not in _STRIP_KEYS and not key.upper().startswith(_STRIP_PREFIXES)
        }
        folder = self.agent_dir(manifest.id)
        home = folder / "home"
        if manifest.isolate_config:
            for var, sub in _CONFIG_DIR_VARS.items():
                target = home / sub
                target.mkdir(parents=True, exist_ok=True)
                env[var] = str(target)
        bin_dir = folder / "bin"
        if bin_dir.is_dir():
            env["PATH"] = os.pathsep.join([str(bin_dir), env.get("PATH", "")])
        replacements = {"{home}": str(home), "{workspace}": str(self.workspace(manifest)), "{agent_dir}": str(folder)}
        for key, value in manifest.env.items():
            for marker, real in replacements.items():
                value = value.replace(marker, real)
            env[key] = value
        env["ATLAS_WORKBENCH_AGENT"] = manifest.id
        return env

    def argv(self, manifest: AgentManifest, prompt: str | None = None) -> list[str]:
        """可执行的命令行：解析 .cmd/.bat、npx 走 Atlas 自带 Node、bin/ 下的相对命令。"""
        folder = self.agent_dir(manifest.id)
        command = manifest.command
        args = [a.replace("{prompt}", prompt) if prompt is not None else a for a in manifest.args]
        args = [a.replace("{agent_dir}", str(folder)).replace("{workspace}", str(self.workspace(manifest))) for a in args]
        local = (folder / command).resolve() if command.startswith(("./", ".\\", "bin/", "bin\\")) else None
        if local and local.exists():
            command = str(local)
        basename = Path(command).name.lower().removesuffix(".cmd").removesuffix(".exe")
        if basename in {"node", "npm", "npx"}:
            from atlas.tools.mcp_client import _resolve_stdio_command

            command, args = _resolve_stdio_command(command, args)
            return [command, *args]
        executable = shutil.which(command, path=self.environment(manifest).get("PATH")) or command
        if os.name == "nt" and executable.lower().endswith((".cmd", ".bat")):
            return ["cmd.exe", "/d", "/c", "call", executable, *args]
        return [executable, *args]

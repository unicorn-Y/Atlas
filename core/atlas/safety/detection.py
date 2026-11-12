"""Decide which tool calls are dangerous enough for the safety reviewer.

Command text goes through Hermes' detector (``atlas_detection``, ported verbatim apart from the
Atlas paths). Atlas adds what a shell detector cannot see: file-tool and MCP writes outside the
work folder or into credential/config files, Windows whole-drive deletes as a floor, and a narrow
pass for clearing regenerable build folders inside the work folder.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Any, Iterable

from atlas.safety import atlas_detection as _h

# Shown in Settings → Safety; the detector itself carries ~100 finer-grained rules.
RULES = {
    "destructive_command": "删除、格式化、强制结束进程、停服务、改注册表等破坏性命令",
    "git_history": "git reset --hard、强制推送、git clean 等会丢失代码的操作",
    "remote_code": "下载后直接执行的脚本（curl | sh、iwr | iex）",
    "credentials": "读取或改写密钥、SSH、浏览器和 Atlas 自己的配置",
    "outside_workspace": "删除或覆盖工作目录以外的文件",
    "system": "关机重启、磁盘和引导、系统目录",
}

_COMMAND_KEYS = ("command", "cmd", "script", "shell_command", "code")
_PATH_KEYS = ("path", "paths", "destination", "target", "file_path", "filepath", "dest",
              "output_path", "source", "directory", "dir")
_FILE_WRITE_ACTIONS = {"write", "append", "delete", "move", "copy", "mkdir"}

# Windows floors Hermes (POSIX-first) does not carry. Recoverable mistakes stay with the reviewer;
# these cannot be undone by a checkpoint.
_WINDOWS_FLOORS = (
    (re.compile(r"\bformat-volume\b|\bclear-disk\b|\bformat(?:\.com)?\s+[a-z]:", re.I), "格式化或清空磁盘"),
    (re.compile(r"\breg(?:\.exe)?\s+delete\s+hklm\\(?:system|software)\b", re.I), "删除系统注册表"),
    (re.compile(r"\bvssadmin\b[^\n]*\bdelete\s+shadows\b|\bwbadmin\b[^\n]*\bdelete\b", re.I), "删除系统备份"),
    (re.compile(r"\bbcdedit\b[^\n]*\s/(?:set|delete)\b", re.I), "修改系统引导"),
    (re.compile(r"(?:^|[;&|(]\s*|\s)(?:stop-computer|restart-computer)\b", re.I), "关机或重启"),
    (re.compile(
        r"(?:\b(?:remove-item|ri|rm|rmdir|rd|del|erase)\b[^\n;|&]*?)\s[\"']?"
        r"(?:[a-z]:\\?(?:\*)?|[a-z]:\\users(?:\\[^\\\s\"';|&]+)?\\?(?:\*)?|\$home\\?|~\\?|%userprofile%\\?)[\"']?(?=\s|$|;|\|)",
        re.I), "递归删除整个磁盘或整个用户目录"),
)

_SENSITIVE_PATH = re.compile(
    r"(?:^|[\\/])(?:\.ssh|\.aws|\.gnupg|\.kube|\.docker|\.config[\\/]gh)(?:[\\/]|$)"
    r"|(?:^|[\\/])\.env(?:\.[\w.-]+)?$|(?:^|[\\/])(?:\.netrc|\.pgpass|\.npmrc|\.pypirc|\.git-credentials)$"
    r"|(?:^|[\\/])(?:atlas\.toml|safety\.json)$|\.(?:pem|key|p12|pfx|kdbx)$"
    r"|[\\/]appdata[\\/](?:local|roaming)[\\/](?:google[\\/]chrome|microsoft[\\/]edge|mozilla)[\\/]",
    re.I)

# Folders every build tool recreates; deleting them inside the work folder is routine.
_REGENERABLE = {"node_modules", "dist", "build", "out", ".next", ".nuxt", ".turbo", ".cache",
                "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "target", "coverage"}
_DELETE_VERBS = {"rm", "rmdir", "rd", "del", "erase", "remove-item", "ri"}
# PowerShell accepts any unambiguous prefix of -Recurse / -Force and the ri / rm / del aliases,
# which Hermes' Remove-Item rule (full parameter names) does not see.
_PS_RECURSIVE_DELETE = re.compile(
    r"(?:^|[;&|(]\s*)(?:remove-item|ri|rm|del|erase|rmdir|rd)\b[^\n;|&]*\s"
    r"-(?:r(?:e(?:c(?:u(?:r(?:s(?:e)?)?)?)?)?)?|fo(?:r(?:c(?:e)?)?)?)\b",
    re.I)
_PS_POLICY = re.compile(r"\bset-executionpolicy\b", re.I)

# Hermes flags every `python -c` / `node -e` as opaque. Atlas runs FULL_ACCESS without prompts, so it
# looks inside instead: only payloads that delete files or embed a dangerous command go to the reviewer.
_INLINE_EXEC = "script execution via -e/-c flag"
_CODE_DELETE = re.compile(
    r"\b(?:shutil\.rmtree|os\.(?:remove|unlink|rmdir|removedirs)|send2trash)\s*\("
    r"|\.(?:unlink|rmdir)\s*\("
    r"|\.(?:rm|rmdir|unlink)(?:Sync)?\s*\(|\brimraf\b"
    r"|\bRemove-Item\b|\[System\.IO\.(?:File|Directory)\]::Delete",
    re.I)
_INLINE_FLAGS = {"-c", "-e", "--eval", "-p", "--print", "-command", "/c"}


def _inline_payloads(command: str) -> list[str]:
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return []
    return [tokens[i + 1] for i, token in enumerate(tokens[:-1]) if token.lower() in _INLINE_FLAGS]


def _code_findings(code: str) -> list[str]:
    found = []
    if _CODE_DELETE.search(code):
        found.append("代码里有删除文件或目录的操作")
    for literal in re.findall(r"""(["'])((?:(?!\1).){4,})\1""", code):
        dangerous, _key, description = _h.detect_dangerous_command(literal[1])
        if dangerous and description != _INLINE_EXEC:
            found.append(_zh(str(description)))
    return found


@dataclass
class Assessment:
    reasons: list[str] = field(default_factory=list)
    floor: str | None = None

    @property
    def dangerous(self) -> bool:
        return bool(self.reasons or self.floor)


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str) and value.strip():
        yield value
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                yield item


def commands_of(tool: str, arguments: dict[str, Any]) -> list[str]:
    """Shell text a tool call will run (or, for execute_code, source text to scan)."""
    if tool == "local_exec" or (tool == "local_process" and not arguments.get("command")):
        parts = [*_strings(arguments.get("executable")), *_strings(arguments.get("args"))]
        return [shlex.join(parts)] if parts else []
    found: list[str] = []
    for key in _COMMAND_KEYS:
        found.extend(_strings(arguments.get(key)))
    return found


def write_targets(tool: str, arguments: dict[str, Any], *, write_capable_mcp: bool) -> list[str]:
    """Paths a tool call creates, overwrites, moves or deletes."""
    if tool == "local_file":
        action = arguments.get("action")
        if action not in _FILE_WRITE_ACTIONS:
            return []
        keys = ("path", "destination") if action in {"move", "copy"} else ("path",)
        if action == "copy":
            keys = ("destination",)
        return [item for key in keys for item in _strings(arguments.get(key))]
    if tool in {"local_edit", "create_document", "create_spreadsheet", "create_presentation"}:
        return list(_strings(arguments.get("path")))
    if write_capable_mcp:
        return [item for key in _PATH_KEYS for item in _strings(arguments.get(key))]
    return []


def _resolve(raw: str, workspace: str | None) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute() and workspace and not workspace.startswith("ssh://"):
        path = Path(workspace) / path
    try:
        return path.resolve()
    except OSError:
        return path.absolute()


def _inside(path: Path, roots: Iterable[str]) -> bool:
    for root in roots:
        if not root or root.startswith("ssh://"):
            continue
        try:
            base = Path(root).expanduser().resolve()
        except OSError:
            continue
        if path == base or base in path.parents:
            return True
    return False


def _is_regenerable_cleanup(command: str, workspace: str | None) -> bool:
    """One plain delete command whose every operand is a build folder inside the work folder.

    Anything compound (``;``, ``&&``, ``|``, redirects, substitutions) is never exempt, so a
    stray ``echo node_modules`` cannot launder another delete.
    """
    if not workspace or workspace.startswith("ssh://") or re.search(r"[;&|<>`\n]|\$\(", command):
        return False
    try:
        tokens = shlex.split(command, posix=False)
    except ValueError:
        return False
    if not tokens or tokens[0].lower() not in _DELETE_VERBS:
        return False
    # PowerShell lists operands with commas: `Remove-Item -Recurse node_modules, dist`.
    operands = [part.strip("\"'") for t in tokens[1:] if not re.match(r"^(?:-|/)[a-z]", t, re.I)
                for part in t.split(",") if part.strip("\"'")]
    if not operands:
        return False
    for operand in operands:
        if operand.startswith("-"):
            return False
        name = PureWindowsPath(operand).name or Path(operand).name
        if name.lower() not in _REGENERABLE:
            return False
        if not _inside(_resolve(operand, workspace), [workspace]):
            return False
    return True


def _zh(description: str) -> str:
    text = description.lower()
    for words, label in (
        (("git",), "可能丢失代码或改写远端历史的 git 操作"),
        (("pipe remote", "remote content", "remote script", "iex", "invoke-expression"), "下载后直接执行的脚本"),
        (("ssh", "secret", "credential", "env", "config", "netrc", "atlas"), "读取或改写密钥、凭据或配置"),
        (("shutdown", "reboot", "boot", "init ", "poweroff"), "关机、重启或修改引导"),
        (("format", "disk", "block device", "mkfs", "dd "), "格式化或直接写磁盘"),
        (("kill", "service", "process"), "强制结束进程或停止服务"),
        (("registry",), "修改注册表"),
        (("sql",), "删除数据库数据"),
        (("delete", "remove", "rm ", "recursive"), "删除文件或目录"),
        (("chmod", "chown", "acl", "everyone"), "大范围修改文件权限"),
    ):
        if any(word in text for word in words):
            return f"{label}（{description}）"
    return description


def assess(
    tool: str, arguments: dict[str, Any], *, workspace: str | None,
    allowed_roots: Iterable[str] = (), write_capable_mcp: bool = False,
) -> Assessment:
    """Danger findings for one write-capable tool call (read-only calls never reach here)."""
    result = Assessment()
    roots = [item for item in [workspace, *allowed_roots] if item]
    if tool == "execute_code":
        for code in _strings(arguments.get("code")):
            result.reasons.extend(_code_findings(code))
        result.reasons = list(dict.fromkeys(result.reasons))
        return result
    for command in commands_of(tool, arguments):
        hard, description = _h.detect_hardline_command(command)
        if hard:
            result.floor = _zh(str(description))
            return result
        for pattern, label in _WINDOWS_FLOORS:
            if pattern.search(command):
                result.floor = label
                return result
        if _is_regenerable_cleanup(command, workspace):
            continue
        dangerous, _key, description = _h.detect_dangerous_command(command)
        if dangerous and description == _INLINE_EXEC:
            payloads = _inline_payloads(command)
            if payloads:
                for payload in payloads:
                    result.reasons.extend(_code_findings(payload))
            else:  # could not isolate the payload: stay with Hermes' verdict
                result.reasons.append(_zh(str(description)))
        elif dangerous:
            result.reasons.append(_zh(str(description)))
        elif _PS_RECURSIVE_DELETE.search(command):
            result.reasons.append("删除文件或目录（PowerShell recursive/forced delete）")
        elif _PS_POLICY.search(command):
            result.reasons.append("放宽 PowerShell 执行策略（Set-ExecutionPolicy）")
    for raw in write_targets(tool, arguments, write_capable_mcp=write_capable_mcp):
        resolved = _resolve(raw, workspace)
        if _SENSITIVE_PATH.search(str(resolved)) or _SENSITIVE_PATH.search(raw):
            result.reasons.append(f"改写密钥、凭据或配置文件：{raw}")
        elif roots and not _inside(resolved, roots):
            result.reasons.append(f"写入或删除工作目录以外的文件：{raw}")
    result.reasons = list(dict.fromkeys(result.reasons))
    return result


def detect_danger(command: str) -> list[str]:
    """Compatibility helper: findings for a bare command string."""
    found = assess("local_shell", {"command": command}, workspace=None)
    return [found.floor] if found.floor else found.reasons

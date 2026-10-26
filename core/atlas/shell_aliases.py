"""Create and revoke small, user-owned shell functions for launching Atlas chat."""

from __future__ import annotations

import os
from pathlib import Path
import re
import shlex

SUPPORTED_SHELLS = ("powershell", "bash", "zsh")
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def default_profile(shell: str) -> Path:
    """Return the conventional per-user startup file for a supported shell."""
    if shell == "powershell":
        documents = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Documents"
        return documents / "PowerShell" / "Microsoft.PowerShell_profile.ps1"
    if shell == "bash":
        return Path.home() / ".bashrc"
    if shell == "zsh":
        return Path.home() / ".zshrc"
    raise ValueError(f"不支持的 shell: {shell}")


def _quote_powershell(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _markers(name: str) -> tuple[str, str]:
    return f"# >>> atlas alias: {name} >>>", f"# <<< atlas alias: {name} <<<"


def _block(name: str, shell: str, workspace: str, arguments: list[str]) -> str:
    start, end = _markers(name)
    if shell == "powershell":
        command = " ".join(_quote_powershell(item) for item in arguments)
        invoke = "& atlas chat" + (f" {command}" if command else "") + " @args"
        body = (
            f"function {name} {{\n"
            f"  Push-Location -LiteralPath {_quote_powershell(workspace)}\n"
            f"  try {{ {invoke} }} finally {{ Pop-Location }}\n"
            "}"
        )
    else:
        command = " ".join(shlex.quote(item) for item in arguments)
        invoke = "atlas chat" + (f" {command}" if command else "") + ' "$@"'
        body = f"{name}() {{ (cd -- {shlex.quote(workspace)} && {invoke}); }}"
    return f"{start}\n{body}\n{end}"


def _read_profile(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _remove_block(text: str, name: str) -> tuple[str, bool]:
    start, end = _markers(name)
    pattern = re.compile(r"(?ms)^" + re.escape(start) + r"\r?\n.*?^" + re.escape(end) + r"\r?\n?")
    updated, count = pattern.subn("", text)
    return updated, count > 0


def add_alias(
    name: str,
    shell: str,
    workspace: str | Path,
    arguments: list[str] | tuple[str, ...] = (),
    profile: str | Path | None = None,
) -> Path:
    """Add or replace one marked alias block and return the profile path."""
    if not _NAME.fullmatch(name):
        raise ValueError("别名名称只能以字母或下划线开头，并包含字母、数字或下划线")
    if shell not in SUPPORTED_SHELLS:
        raise ValueError(f"shell 必须是 {'|'.join(SUPPORTED_SHELLS)} 之一")
    root = Path(workspace).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"工作区不是现有目录: {root}")
    target = Path(profile).expanduser() if profile else default_profile(shell)
    text = _read_profile(target)
    text, _ = _remove_block(text, name)
    block = _block(name, shell, str(root), list(arguments))
    separator = "" if not text or text.endswith("\n") else "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text + separator + block + "\n", encoding="utf-8", newline="\n")
    return target


def remove_alias(name: str, shell: str, profile: str | Path | None = None) -> tuple[Path, bool]:
    """Remove only the matching generated block; preserve all other profile content."""
    if not _NAME.fullmatch(name):
        raise ValueError("别名名称只能以字母或下划线开头，并包含字母、数字或下划线")
    if shell not in SUPPORTED_SHELLS:
        raise ValueError(f"shell 必须是 {'|'.join(SUPPORTED_SHELLS)} 之一")
    target = Path(profile).expanduser() if profile else default_profile(shell)
    text = _read_profile(target)
    updated, removed = _remove_block(text, name)
    if removed:
        target.write_text(updated, encoding="utf-8", newline="\n")
    return target, removed


def list_aliases(shell: str, profile: str | Path | None = None) -> list[str]:
    """List Atlas alias names owned by the generated marker format."""
    if shell not in SUPPORTED_SHELLS:
        raise ValueError(f"shell 必须是 {'|'.join(SUPPORTED_SHELLS)} 之一")
    target = Path(profile).expanduser() if profile else default_profile(shell)
    pattern = re.compile(r"(?m)^# >>> atlas alias: ([A-Za-z_][A-Za-z0-9_]*) >>>$")
    return sorted(set(pattern.findall(_read_profile(target))))

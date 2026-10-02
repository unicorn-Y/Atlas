"""Binary discovery and Chinese missing-server hints for LSP.

Atlas never installs language servers on its own (contract: no ``install.py`` port).
``find_binary`` only probes what is already there — a config override or PATH — and
``missing_server_hint`` turns a miss into a one-line Chinese hint carrying the install
command, so the operator can enable the server themselves.
"""
from __future__ import annotations

import os
import shutil
from typing import Dict, Optional, Sequence

# One short hint per well-known server id: names the language, the install command
# (npm / pip / go / manual download), and the "restart Atlas" tail.  Keys must stay in
# sync with the server ids in atlas.lsp.servers.
_HINTS: Dict[str, str] = {
    "pyright":
        "未找到 Python 语言服务 pyright：请运行 npm install -g pyright（或 pip install pyright）安装，重启 Atlas 即可自动启用。",
    "typescript":
        "未找到 TypeScript 语言服务 typescript-language-server：请运行 npm install -g typescript-language-server typescript 安装，重启 Atlas 即可自动启用。",
    "gopls":
        "未找到 Go 语言服务 gopls：请运行 go install golang.org/x/tools/gopls@latest 安装，重启 Atlas 即可自动启用。",
    "rust-analyzer":
        "未找到 Rust 语言服务 rust-analyzer：请从 GitHub Releases（https://github.com/rust-lang/rust-analyzer/releases）下载对应平台版本手动安装，重启 Atlas 即可自动启用。",
    "clangd":
        "未找到 C/C++ 语言服务 clangd：请安装 LLVM/Clang 工具链（https://clangd.llvm.org/installation，如 scoop install clangd 或 apt install clangd），重启 Atlas 即可自动启用。",
    "bash-language-server":
        "未找到 Shell 语言服务 bash-language-server：请运行 npm install -g bash-language-server 安装，重启 Atlas 即可自动启用。",
    "yaml-language-server":
        "未找到 YAML 语言服务 yaml-language-server：请运行 npm install -g yaml-language-server 安装，重启 Atlas 即可自动启用。",
    "lua-language-server":
        "未找到 Lua 语言服务 lua-language-server：请从 GitHub Releases（https://github.com/LuaLS/lua-language-server/releases）下载对应平台版本手动安装，重启 Atlas 即可自动启用。",
    "intelephense":
        "未找到 PHP 语言服务 intelephense：请运行 npm install -g intelephense 安装，重启 Atlas 即可自动启用。",
    "dockerfile-ls":
        "未找到 Dockerfile 语言服务 dockerfile-ls：请运行 npm install -g dockerfile-language-server-nodejs 安装，重启 Atlas 即可自动启用。",
    "terraform-ls":
        "未找到 Terraform 语言服务 terraform-ls：请从 HashiCorp 官网（https://developer.hashicorp.com/terraform/install）下载 terraform-ls 手动安装，重启 Atlas 即可自动启用。",
    "powershell":
        "未找到 PowerShell 语言服务：请从 https://github.com/PowerShell/PowerShellEditorServices/releases 下载 release zip 并解压安装，重启 Atlas 即可自动启用。",
}


def find_binary(ctx_binary_override: Optional[Sequence[str]], which: Sequence[str]) -> Optional[str]:
    """Resolve a server binary: ``ctx_binary_override[0]`` when it exists on disk, else the first
    ``which`` name found on PATH; ``None`` when nothing resolves.  Never installs anything."""
    if ctx_binary_override and ctx_binary_override[0] and os.path.exists(ctx_binary_override[0]):
        return ctx_binary_override[0]
    for name in which:
        found = shutil.which(name)
        if found:
            return found
    return None


def missing_server_hint(server_id: str, language: str = "") -> str:
    """One-line Chinese hint for a missing server binary; ``language`` (e.g. "Python") is used as
    the display label when present.  Unknown server ids get the generic template."""
    hint = _HINTS.get(server_id)
    if hint is not None:
        return hint
    label = f"{language}语言服务 {server_id}" if language else f"语言服务 {server_id}"
    return f"未找到{label}：请安装后重启 Atlas 即可自动启用。"


def handles_hint(server_id: str) -> bool:
    """True iff ``server_id`` has a dedicated entry in the built-in hint table (test stubs)."""
    return server_id in _HINTS


__all__ = ["find_binary", "missing_server_hint", "handles_hint"]

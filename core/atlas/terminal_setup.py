"""Install and remove Atlas shell prompt and Shift+Enter integration snippets."""
from __future__ import annotations

import os
from pathlib import Path
import platform

_START = "# >>> Atlas terminal integration >>>"
_END = "# <<< Atlas terminal integration <<<"


def detect_shell(environment: dict[str, str] | None = None) -> str:
    env = environment if environment is not None else os.environ
    override = str(env.get("ATLAS_TERMINAL_SHELL") or "").strip().lower()
    if override in {"powershell", "bash", "zsh", "fish"}:
        return override
    shell_path = str(env.get("SHELL") or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
    if shell_path in {"bash", "zsh", "fish"}:
        return shell_path
    if env.get("FISH_VERSION"):
        return "fish"
    if env.get("ZSH_VERSION"):
        return "zsh"
    if env.get("BASH_VERSION"):
        return "bash"
    if env.get("PSModulePath") or env.get("PSExecutionPolicyPreference"):
        return "powershell"
    if platform.system() == "Windows":
        return "unsupported"
    return "unknown"


def profile_path(shell: str, home: Path | None = None) -> Path:
    root = (home or Path.home()).expanduser()
    if shell == "powershell":
        documents = Path(os.environ.get("USERPROFILE", str(root))) / "Documents"
        if "PSModulePath" in os.environ and "WindowsPowerShell" in os.environ["PSModulePath"]:
            return documents / "WindowsPowerShell" / "Microsoft.PowerShell_profile.ps1"
        return documents / "PowerShell" / "Microsoft.PowerShell_profile.ps1"
    if shell == "bash":
        return root / ".bashrc"
    if shell == "zsh":
        return root / ".zshrc"
    if shell == "fish":
        return root / ".config" / "fish" / "config.fish"
    raise ValueError(f"unsupported shell: {shell}")


def integration_block(shell: str) -> str:
    bodies = {
        "powershell": r'''# Atlas sets an environment marker for child CLI sessions.
$env:ATLAS_SHELL_INTEGRATION = '1'
if (Get-Module -ListAvailable -Name PSReadLine) {
    Set-PSReadLineKeyHandler -Chord Shift+Enter -Function AddLine -ErrorAction SilentlyContinue
}
if (-not (Test-Path Function:\global:AtlasOriginalPrompt)) {
    $global:AtlasOriginalPrompt = (Get-Item Function:\prompt).ScriptBlock
    function global:prompt {
        [Console]::Write("`e]133;A`a")
        $value = & $global:AtlasOriginalPrompt
        [Console]::Write("`e]133;B`a")
        $value
    }
}''',
        "bash": r'''export ATLAS_SHELL_INTEGRATION=1
if [[ -n "${PS1:-}" ]]; then
  PS1="\[\e]133;B\a\]${PS1}"
fi
bind '"\e[13;2u": "\C-v\n"' 2>/dev/null || true
__atlas_prompt_mark() { printf '\033]133;A\007'; }
PROMPT_COMMAND="${PROMPT_COMMAND:+${PROMPT_COMMAND};}__atlas_prompt_mark"''',
        "zsh": r'''export ATLAS_SHELL_INTEGRATION=1
autoload -Uz add-zsh-hook
function __atlas_precmd_mark() { printf '\033]133;A\007' }
function __atlas_preexec_mark() { printf '\033]133;C\007' }
add-zsh-hook precmd __atlas_precmd_mark
add-zsh-hook preexec __atlas_preexec_mark
function __atlas_shift_enter() { LBUFFER+=$'\n' }
zle -N __atlas_shift_enter
bindkey '^[[13;2u' __atlas_shift_enter''',
        "fish": r'''set -gx ATLAS_SHELL_INTEGRATION 1
function __atlas_prompt_mark --on-event fish_prompt
    printf '\e]133;A\a'
end
bind '\e\[13\;2u' 'commandline -i \n' ''',
    }
    if shell not in bodies:
        raise ValueError(f"unsupported shell: {shell}")
    return f"{_START}\n{bodies[shell]}\n{_END}"


def install_integration(path: Path, shell: str) -> bool:
    target = path.expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    existing = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
    block = integration_block(shell)
    if _START in existing and _END in existing:
        start = existing.index(_START)
        end = existing.index(_END, start) + len(_END)
        updated = existing[:start] + block + existing[end:]
        changed = updated != existing
    else:
        separator = "" if not existing or existing.endswith("\n") else "\n"
        updated = existing + separator + block + "\n"
        changed = True
    if changed:
        target.write_text(updated, encoding="utf-8", newline="\n")
    return changed


def remove_integration(path: Path) -> bool:
    target = path.expanduser()
    if not target.exists():
        return False
    existing = target.read_text(encoding="utf-8", errors="replace")
    if _START not in existing or _END not in existing:
        return False
    start = existing.index(_START)
    end = existing.index(_END, start) + len(_END)
    updated = existing[:start] + existing[end:]
    if updated.startswith("\n") and start == 0:
        updated = updated[1:]
    target.write_text(updated, encoding="utf-8", newline="\n")
    return True


def integration_installed(path: Path) -> bool:
    if not path.exists():
        return False
    content = path.read_text(encoding="utf-8", errors="replace")
    return _START in content and _END in content

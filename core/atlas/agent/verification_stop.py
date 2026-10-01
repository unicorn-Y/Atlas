# Policy adapted from NousResearch/hermes-agent@663362680b6ffa4fbffeb58f6682564239a1953b:
# agent/verification_stop.py (MIT, (c) Nous Research); evidence comes from Atlas tool events.
"""Classify changed paths and tool invocations for the verification-before-stop nudge."""

from __future__ import annotations

from pathlib import PurePath

_PROSE = {".md", ".markdown", ".mdx", ".rst", ".txt", ".text", ".adoc", ".log", ".csv"}


def requires_verification(path: str) -> bool:
    value = PurePath(path)
    return value.suffix.lower() not in _PROSE and value.name.lower() not in {
        "license", "licence", "notice", "changelog",
    }


def is_verification_command(tool: str, arguments: dict) -> bool:
    if tool == "run_checks":
        return True
    command = " ".join(str(arguments.get(key, "")) for key in ("command", "script", "code")).lower()
    return any(marker in command for marker in (
        "pytest", "unittest", "npm test", "pnpm test", "yarn test", "cargo test",
        "npm run build", "pnpm build", "ruff check", "mypy ", "tsc --noemit",
    ))

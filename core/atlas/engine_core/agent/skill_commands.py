"""Read-only skill scaffold markers needed for SessionDB previews and search."""

from __future__ import annotations

import re
from typing import Any, Optional

_SKILL_INVOCATION_PREFIX = "[IMPORTANT: The user has invoked the "
_AUTO_LOAD_PREFIX = '[IMPORTANT: The "'
_SKILL_NAME_RE = re.compile(re.escape(_SKILL_INVOCATION_PREFIX) + r'"([^"]*)"')
_SINGLE_SKILL_INSTRUCTION = "The user has provided the following instruction alongside the skill invocation: "
_SINGLE_SKILL_MARKER = "The full skill content is loaded below.]"
_BUNDLE_USER_INSTRUCTION = "\nUser instruction: "
_BUNDLE_MARKER = " skill bundle,"
SKILL_SCAFFOLD_SQL_LIKE = _SKILL_INVOCATION_PREFIX + "%"
AUTO_LOAD_SCAFFOLD_SQL_LIKE = _AUTO_LOAD_PREFIX + "%"
SKILL_EXCERPT_JOINT = "\x1e"


def describe_skill_invocation(content: Any, separator: str = " — ") -> Optional[str]:
    if not isinstance(content, str):
        return None
    if not content.startswith(_SKILL_INVOCATION_PREFIX):
        return None
    match = _SKILL_NAME_RE.match(content)
    name = (match.group(1) if match else "").strip()
    label = name if name.startswith("/") else f"/{name}"
    instruction = None
    if _BUNDLE_MARKER in content:
        index = content.find(_BUNDLE_USER_INSTRUCTION)
        if index >= 0:
            instruction = content[index + len(_BUNDLE_USER_INSTRUCTION):]
    else:
        index = content.find(_SINGLE_SKILL_INSTRUCTION)
        if index >= 0:
            instruction = content[index + len(_SINGLE_SKILL_INSTRUCTION):]
    if instruction is not None:
        instruction = " ".join(instruction.split(SKILL_EXCERPT_JOINT)[0].split())
        if instruction:
            return f"{label}{separator}{instruction}" if name else instruction
    return label if name else None



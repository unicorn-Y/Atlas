"""Build bounded model-history attachments after context compaction."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from atlas.engine.read_dedupe import post_compaction_read_paths


def restore_post_compaction_context(
    runtime: Any,
    *,
    modified_files: Iterable[str],
    plan_todo_messages: Sequence[Mapping[str, Any]],
    active_skills: Sequence[Mapping[str, str]],
    max_files: int,
    max_tokens_per_file: int,
    total_file_tokens: int,
    max_tokens_per_skill: int,
    total_skill_tokens: int,
    token_counter: Callable[[str], int] | None = None,
) -> list[dict[str, Any]]:
    """Return raw plan/todo messages plus bounded file, reminder, and skill messages.

    The result is shaped for direct append to the model conversation history, e.g.
    ``messages.extend(restore_post_compaction_context(...))``. `plan_todo_messages`
    must be the original preserved message dictionaries, and `active_skills` must
    come from the current run's loaded skill instructions.
    """
    count_tokens = token_counter or _approx_tokens
    messages = [dict(message) for message in plan_todo_messages]
    workspace = str(getattr(runtime, "workspace", "") or "")
    # Do not accidentally resolve a remote relative path against the local process CWD.
    modified = (
        [] if workspace.startswith("ssh://") else _normalized_paths(modified_files, workspace)
    )
    modified_keys = {path.casefold() for path in modified}
    read_paths = _normalized_paths(post_compaction_read_paths(runtime), workspace)

    restored = 0
    used_tokens = 0
    for path in modified:
        if restored >= max(0, max_files):
            break
        try:
            content = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        available = min(max_tokens_per_file, total_file_tokens - used_tokens)
        if available <= 0:
            break
        attachment = f"最近修改的文件（磁盘当前内容）：{path}\n{content}"
        if count_tokens(attachment) > available:
            attachment = _truncate_to_tokens(attachment, available, count_tokens)
        if not attachment:
            continue
        used_tokens += count_tokens(attachment)
        restored += 1
        messages.append(
            {
                "role": "system",
                "content": attachment,
                "restored_file": path,
            }
        )

    reminders = [path for path in read_paths if path.casefold() not in modified_keys]
    if reminders:
        listing = "\n".join(f"- {path}" for path in reminders)
        messages.append(
            {
                "role": "system",
                "content": ("压缩前读过以下文件；内容未重新附上，需要时请重新读取：\n" + listing),
            }
        )

    skill_tokens = 0
    for skill in active_skills:
        name = str(skill.get("name") or "skill")
        body = str(skill.get("content") or "")
        if not body:
            continue
        available = min(max_tokens_per_skill, total_skill_tokens - skill_tokens)
        if available <= 0:
            break
        attachment = f"当前已加载技能：{name}\n{body}"
        if count_tokens(attachment) > available:
            attachment = _truncate_to_tokens(attachment, available, count_tokens)
        if not attachment:
            continue
        skill_tokens += count_tokens(attachment)
        messages.append({"role": "system", "content": attachment})
    return messages


def _normalized_paths(paths: Iterable[str], workspace: str) -> list[str]:
    root = (
        Path(workspace).expanduser() if workspace and not workspace.startswith("ssh://") else None
    )
    unique: dict[str, str] = {}
    for raw in paths:
        if not raw:
            continue
        path = Path(raw).expanduser()
        if not path.is_absolute() and root is not None:
            path = root / path
        try:
            normalized = str(path.resolve())
        except OSError:
            normalized = str(path.absolute())
        unique.setdefault(normalized.casefold(), normalized)
    return list(unique.values())


def _approx_tokens(text: str) -> int:
    return math.ceil(len(text) / 4)


def _truncate_to_tokens(text: str, budget: int, count_tokens: Callable[[str], int]) -> str:
    if budget <= 0:
        return ""
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if count_tokens(text[:middle]) <= budget:
            low = middle
        else:
            high = middle - 1
    return text[:low]

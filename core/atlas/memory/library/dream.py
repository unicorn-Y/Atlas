"""Daily project-memory consolidation in three small, retryable phases."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

from .store import NOW, SRC_DREAM, SRC_EDITED, SRC_SAID, THINGS, Entry, new_id, safe_name

log = structlog.get_logger(__name__)
_SECTIONS = ("现在状态", "定下的决定", "没做完", "来龙去脉")
_DEADLINE = re.compile(r"(?<!\d)(20\d\d-\d\d-\d\d)(?!\d)")


def _checkpoint(path: Path) -> str:
    try:
        return str(json.loads(path.read_text(encoding="utf-8")).get("checkpoint") or "")
    except (OSError, ValueError, TypeError):
        return ""


def _episode_groups(
    library: Any, checkpoint: str, processed_ids: set[str] | None = None
) -> dict[str, list[Entry]]:
    groups: dict[str, list[Entry]] = {}
    for rel in library.store.pages():
        if not rel.startswith("经历/"):
            continue
        for entry in library.store.read(rel).current:
            if not entry.at or (
                entry.at <= checkpoint and entry.id in (processed_ids or set())
            ):
                continue
            candidates = [*entry.trigger]
            if not candidates:
                for file in entry.files:
                    parts = Path(file.replace("\\", "/")).parts
                    if parts:
                        candidates.append(parts[1] if len(parts) > 1 else parts[0])
            seen = set()
            for candidate in candidates:
                name = safe_name(str(candidate).strip())
                if len(name) < 2 or name.casefold() in seen:
                    continue
                seen.add(name.casefold())
                groups.setdefault(name, []).append(entry)
    output = {}
    for name, entries in groups.items():
        distinct_days = {e.at[:10] for e in entries}
        explicitly_named = any(name.casefold() in e.text.casefold() for e in entries)
        if len(distinct_days) >= 3 or explicitly_named:
            output[name] = entries
    return output


async def _write_project(
    library: Any, model_mgr: Any, name: str, entries: list[Entry]
) -> tuple[dict[str, list[str]], str]:
    if model_mgr is None or getattr(model_mgr, "model_router", None) is None:
        raise RuntimeError("没有可用的记忆整理模型")
    model_id = library._model_id(model_mgr)
    path = f"{THINGS}/{safe_name(name)}.md"
    existing = (
        (library.store.root / path).read_text(encoding="utf-8")
        if (library.store.root / path).exists()
        else ""
    )
    records = []
    for e in entries:
        records.append(
            {
                "id": e.id,
                "at": e.at,
                "text": e.text,
                "outcome": e.outcome,
                "decisions": e.decisions,
                "files": e.files,
                "commands": e.commands,
                "facts": e.facts,
                "open_items": e.open_items,
                "steps": e.steps,
                "verified": e.verified,
            }
        )
    prompt = [
        {
            "role": "system",
            "content": (
                "你负责整理项目记忆。只根据输入内容写四个 Markdown 标题："
                + "、".join(_SECTIONS)
                + "。每条用 - 开头；不要编造。保留已有页面中 src 为「你说的」或「你改的」的行原样，"
                "不要删除或改写它们。只返回这四段，不要其他文字。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {"project": name, "existing_page": existing, "new_episodes": records},
                ensure_ascii=False,
            ),
        },
    ]
    result = await asyncio.wait_for(
        model_mgr.model_router.complete_for(
            model_id, "memory_library", prompt, max_tokens=2000, temperature=0.1
        ),
        timeout=float(library._cfg("writer_timeout_seconds", 90)),
    )
    text = str(getattr(result, "text", "") or "")
    sections = {section: [] for section in _SECTIONS}
    current = None
    for line in text.splitlines():
        heading = re.match(r"^#{1,3}\s*(.+?)\s*$", line)
        if heading:
            current = heading.group(1).strip()
            if current == "现在":
                current = "现在状态"
            elif current == "历史":
                current = "来龙去脉"
            if current not in sections:
                current = None
            continue
        if current and line.strip().startswith("-"):
            value = re.sub(r"^\s*[-*]\s+", "", line).strip()
            if value:
                sections[current].append(value[:400])
    if not any(sections.values()):
        raise RuntimeError(f"整理模型未返回项目段落：{name}")
    return sections, existing


def _old_owner_lines(text: str) -> dict[str, list[str]]:
    result = {section: [] for section in _SECTIONS}
    current = None
    for line in text.splitlines():
        heading = re.match(r"^#{1,3}\s*(.+?)\s*$", line)
        if heading:
            current = heading.group(1).strip()
            if current == "现在":
                current = "现在状态"
            elif current == "历史":
                current = "来龙去脉"
        elif (
            current in result
            and line.strip().startswith(("-", "*"))
            and (SRC_SAID in line or SRC_EDITED in line)
        ):
            result[current].append(line.rstrip())
    return result


async def run_dream(library: Any, model_mgr: Any = None) -> dict[str, Any]:
    library.ready()
    state_path = library.store.root / ".dream-state.json"
    checkpoint = _checkpoint(state_path)
    now = datetime.now().astimezone()
    try:
        processed_ids = set(json.loads(state_path.read_text(encoding="utf-8")).get("processed_ids", []))
    except (OSError, ValueError, TypeError):
        processed_ids = set()
    groups = _episode_groups(library, checkpoint, processed_ids)
    prepared: dict[str, tuple[dict[str, list[str]], str, list[Entry]]] = {}
    try:
        for name, entries in groups.items():
            sections, existing = await _write_project(library, model_mgr, name, entries)
            prepared[name] = (sections, existing, entries)
        written: list[str] = []
        added = changed = 0
        with library.store.lock:
            for name, (sections, existing, entries) in prepared.items():
                source_lines = _old_owner_lines(existing)
                # Model completion may take long enough for a user to edit the page.
                # Merge owner-authored lines from the latest disk version before writing.
                path = f"{THINGS}/{safe_name(name)}.md"
                disk_path = library.store.root / path
                current = disk_path.read_text(encoding="utf-8") if disk_path.exists() else ""
                for heading, lines in _old_owner_lines(current).items():
                    source_lines[heading] = list(dict.fromkeys([*source_lines[heading], *lines]))
                refs = ",".join(dict.fromkeys(e.id for e in entries))
                output = [f"# {name}"]
                for heading in _SECTIONS:
                    output.extend(["", f"## {heading}"])
                    for old in source_lines[heading]:
                        output.append(old)
                    for text in sections[heading]:
                        line = Entry(
                            text=text,
                            id=new_id(),
                            src=SRC_DREAM,
                            at=now.isoformat(timespec="seconds"),
                            ref=refs,
                        ).line()
                        output.append(line)
                        added += 1
                    changed += len(sections[heading]) > 0
                disk_path.parent.mkdir(parents=True, exist_ok=True)
                disk_path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
                written.append(name)
                for item in sections["没做完"]:
                    deadline = _DEADLINE.search(item)
                    if deadline:
                        page = library.store.read(NOW)
                        if not any(e.text == item for e in page.current):
                            page.current.append(
                                Entry(
                                    text=item,
                                    id=new_id(),
                                    src=SRC_DREAM,
                                    at=now.isoformat(timespec="seconds"),
                                    until=deadline.group(1),
                                    ref=refs,
                                )
                            )
                            library.store.write(page)
            library.store.commit("整理：" + "、".join(written))
        if prepared:
            processed_ids.update(
                entry.id for _sections, _existing, entries in prepared.values() for entry in entries
            )
            state_path.write_text(
                json.dumps({"checkpoint": now.isoformat(timespec="seconds"),
                            "processed_ids": sorted(processed_ids)}, ensure_ascii=False),
                encoding="utf-8",
            )
        library.index.sync()
        return {"ok": True, "projects": written, "added": added, "changed": changed, "error": None}
    except Exception as exc:  # noqa: BLE001 - any failed phase must leave the checkpoint unchanged.
        log.warning("memory.library.dream_failed", error=str(exc), error_type=type(exc).__name__)
        return {"ok": False, "projects": [], "added": 0, "changed": 0, "error": str(exc)}


__all__ = ["run_dream"]

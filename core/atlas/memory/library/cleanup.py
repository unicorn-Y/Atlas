"""Preview or remove memory diary blocks written by automated audit sessions."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from . import _skip_reason
from .index import MemoryIndex
from .store import DIARY, EPISODES, MemoryStore


def _run_sessions(runs: Path) -> set[str]:
    sessions: set[str] = set()
    if not runs.exists():
        return sessions
    for path in runs.rglob("*.jsonl"):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("event", event.get("type")) != "run_start":
                continue
            if _skip_reason(str(event.get("workspace") or ""), ""):
                session = str(event.get("session_id") or "")
                if session:
                    sessions.add(session)
    return sessions


def _diary_blocks(text: str) -> list[tuple[str, str]]:
    blocks = []
    current = []
    heading = ""
    for line in text.splitlines():
        if line.startswith("## "):
            if current:
                blocks.append((heading, "\n".join(current)))
            heading, current = line[3:].strip(), [line]
        elif current:
            current.append(line)
    if current:
        blocks.append((heading, "\n".join(current)))
    return blocks


def _session(block: str) -> str:
    match = re.search(r"<!--\s*(\{.*?\})\s*-->", block)
    if not match:
        return ""
    try:
        return str(json.loads(match.group(1)).get("session") or "")
    except ValueError:
        return ""


def cleanup(root: Path, runs: Path, dry_run: bool = False) -> list[str]:
    store = MemoryStore(root)
    session_ids = _run_sessions(runs)
    targets: list[tuple[Path, str, str]] = []
    for rel in store.diary_pages():
        path = root / rel
        text = path.read_text(encoding="utf-8")
        for heading, block in _diary_blocks(text):
            session = _session(block)
            user = re.search(r"^你：(.*)$", block, re.M)
            original = user.group(1).strip() if user else ""
            if session in session_ids or _skip_reason("", original):
                targets.append((path, block, f"{Path(rel).stem} {heading} {session} {original[:40]}"))
    report = ["会删哪些块："]
    report.extend(f"- {label}" for _path, _block, label in targets)
    report.append(f"总数：{len(targets)}")
    if dry_run:
        return report
    replacements: dict[Path, str] = {}
    for path, block, _label in targets:
        original = replacements.get(path, path.read_text(encoding="utf-8"))
        replacements[path] = original.replace(block, "", 1)
    for path, text in replacements.items():
        path.write_text(text.strip() + "\n", encoding="utf-8")
    removed_sessions = {_session(block) for _path, block, _label in targets}
    for rel in store.pages():
        if not rel.startswith(EPISODES + "/"):
            continue
        page = store.read(rel)
        page.current = [entry for entry in page.current if entry.session not in removed_sessions]
        store.write(page)
    store.commit("清理自动测试记录")
    MemoryIndex(store).rebuild()
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--runs", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print("\n".join(cleanup(args.root, args.runs, args.dry_run)))


if __name__ == "__main__":
    main()

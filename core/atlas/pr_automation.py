"""Persistent per-conversation PR links and deterministic gh polling helpers."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any, Callable


def _path() -> Path:
    from atlas.config import DATA_ROOT
    return DATA_ROOT / "data" / "pr-links.json"


class PRLinkStore:
    def _read(self) -> dict[str, Any]:
        try:
            value = json.loads(_path().read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _write(self, value: dict[str, Any]) -> None:
        path = _path(); path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp"); temp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8"); temp.replace(path)

    def get(self, conversation_id: str) -> dict[str, Any] | None:
        value = self._read().get(conversation_id)
        return value if isinstance(value, dict) else None

    def all(self) -> list[dict[str, Any]]:
        return [value for value in self._read().values() if isinstance(value, dict)]

    def link(self, conversation_id: str, *, root: str, pr: str) -> dict[str, Any]:
        if not conversation_id or not root or not pr:
            raise ValueError("conversation id, workspace and PR reference are required")
        state = self._read(); old = state.get(conversation_id, {})
        state[conversation_id] = {**(old if isinstance(old, dict) else {}), "conversation_id": conversation_id, "root": root, "pr": pr,
            "auto_fix": bool((old or {}).get("auto_fix", False)), "interval_seconds": int((old or {}).get("interval_seconds", 180)),
            "max_attempts": int((old or {}).get("max_attempts", 3)), "attempts": (old or {}).get("attempts", {})}
        self._write(state); return state[conversation_id]

    def update(self, conversation_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        state = self._read(); item = state.get(conversation_id)
        if not isinstance(item, dict): raise KeyError("PR is not associated with this conversation")
        allowed = {"auto_fix", "interval_seconds", "max_attempts"}
        if set(changes) - allowed: raise ValueError("unsupported PR settings")
        if "interval_seconds" in changes and not 30 <= int(changes["interval_seconds"]) <= 86400:
            raise ValueError("interval_seconds must be 30..86400")
        if "max_attempts" in changes and not 1 <= int(changes["max_attempts"]) <= 10:
            raise ValueError("max_attempts must be 1..10")
        item.update(changes); self._write(state); return item

    def save(self, conversation_id: str, item: dict[str, Any]) -> None:
        state = self._read(); state[conversation_id] = item; self._write(state)


def _gh(root: str, *args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["gh", *args], cwd=root, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def poll_once(link: dict[str, Any], *, run_fix: Callable[[str, str], Any],
              archive: Callable[[str], Any], save: Callable[[dict[str, Any]], Any] | None = None) -> dict[str, Any]:
    root, pr = str(link["root"]), str(link["pr"])
    view = _gh(root, "pr", "view", pr, "--json", "number,title,url,state,mergeable,reviewDecision,statusCheckRollup")
    if view.returncode: raise RuntimeError(view.stderr.strip() or "gh pr view failed")
    info = json.loads(view.stdout)
    checks_result = _gh(root, "pr", "checks", pr, "--json", "name,state,link")
    checks = json.loads(checks_result.stdout) if checks_result.returncode == 0 else []
    failed = [item for item in checks if str(item.get("state", "")).upper() in {"FAILURE", "CANCELLED", "ERROR"}]
    conflict = str(info.get("mergeable", "")).upper() in {"CONFLICTING", "CONFLICT"}
    if str(info.get("state", "")).upper() in {"MERGED", "CLOSED"}:
        archive(str(link["conversation_id"]))
    if link.get("auto_fix") and (failed or conflict):
        signature = "conflict" if conflict else ",".join(sorted(str(x.get("name")) for x in failed))
        attempts = link.setdefault("attempts", {})
        number = int(attempts.get(signature, 0))
        if number < int(link.get("max_attempts", 3)):
            logs = []
            for check in failed:
                run = _gh(root, "run", "view", str(check.get("link", "")), "--log-failed")
                logs.append(run.stdout[-24000:] if run.returncode == 0 else run.stderr[-2000:])
            instruction = "解决 PR 合并冲突" if conflict else "修复 CI 失败：\n" + "\n".join(logs)
            run_fix(str(link["conversation_id"]), instruction)
            attempts[signature] = number + 1
            if save:
                save(link)
    return {"pr": {key: info.get(key) for key in ("number", "title", "url", "state", "mergeable", "reviewDecision")},
            "checks": checks, "failed": failed, "conflict": conflict}

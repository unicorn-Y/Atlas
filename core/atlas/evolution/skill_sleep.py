"""Nightly skill training for Atlas with microsoft/SkillOpt's SkillOpt-Sleep.

One night = harvest Atlas' own chat sessions (the Hermes session store,
``engine/state.db``) → mine recurring tasks → replay them → propose bounded edits
to one learned skill → keep an edit only if it scores better on held-out real
tasks (SkillOpt's validation gate) → adopt it into
``skills/learned/atlas-learned/SKILL.md``, which Atlas' skill index loads.

SkillOpt ships harvesters for Claude Code / Codex / Cursor / Pi / OpenCode
transcripts only; ``harvest_atlas`` adds Atlas as a source and is swapped in for
the run. Models go through SkillOpt's OpenAI-compatible backend using the same
endpoint and model MemOS is configured with (``data/memos-home/config.yaml``).

Usage: python -m atlas.evolution.skill_sleep [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
import yaml

from atlas.config import DATA_ROOT
from atlas.skills import SKILLS_DIR

log = structlog.get_logger(__name__)

STATE_DB = DATA_ROOT / "engine" / "state.db"
MEMOS_CONFIG = DATA_ROOT / "data" / "memos-home" / "config.yaml"
WORK_DIR = DATA_ROOT / "data" / "skill-sleep"
SKILL_NAME = "atlas-learned"
SKILL_PATH = SKILLS_DIR / "learned" / SKILL_NAME / "SKILL.md"
SESSION_SOURCES = ("desktop", "cli")  # user-facing chats, not cron/subagent sessions
_FEEDBACK = ("不对", "错了", "还是不行", "没用", "重新", "不是这个", "好了", "可以了", "完美", "谢谢",
             "wrong", "still broken", "perfect", "thanks")


def harvest_atlas(state_db: Path = STATE_DB, *, since_iso: str | None = None,
                  limit: int = 0) -> list[Any]:
    """Atlas chat sessions as SkillOpt ``SessionDigest`` rows, newest first."""
    from skillopt_sleep.types import SessionDigest

    if not state_db.exists():
        return []
    since = datetime.fromisoformat(since_iso).timestamp() if since_iso else 0.0
    con = sqlite3.connect(f"file:{state_db}?mode=ro", uri=True)
    try:
        sessions = con.execute(
            f"SELECT id, started_at, ended_at, cwd, git_branch FROM sessions"
            f" WHERE source IN ({','.join('?' * len(SESSION_SOURCES))}) AND started_at >= ?"
            f" ORDER BY started_at DESC{' LIMIT ?' if limit else ''}",
            (*SESSION_SOURCES, since, *((limit,) if limit else ())),
        ).fetchall()
        digests = []
        for session_id, started, ended, cwd, branch in sessions:
            rows = con.execute(
                "SELECT role, content, tool_name FROM messages WHERE session_id = ?"
                " ORDER BY timestamp, id", (session_id,),
            ).fetchall()
            users = [c for r, c, _ in rows if r == "user" and isinstance(c, str) and c.strip()]
            finals = [c for r, c, _ in rows if r == "assistant" and isinstance(c, str) and c.strip()]
            if not users:
                continue
            tools = sorted({t for _, _, t in rows if t})
            digests.append(SessionDigest(
                session_id=str(session_id),
                project=str(cwd or DATA_ROOT),
                git_branch=str(branch or ""),
                started_at=_iso(started),
                ended_at=_iso(ended),
                user_prompts=users,
                assistant_finals=finals,
                tools_used=tools,
                feedback_signals=[u[:120] for u in users if any(f in u for f in _FEEDBACK)],
                n_user_turns=len(users),
                n_assistant_turns=len(finals),
                raw_path=str(state_db),
            ))
        return digests
    finally:
        con.close()


def _iso(ts: Any) -> str:
    return datetime.fromtimestamp(float(ts), UTC).isoformat() if ts else ""


def _model_env() -> dict[str, str]:
    """SkillOpt's OpenAI-compatible backend settings, taken from MemOS' LLM config."""
    llm = (yaml.safe_load(MEMOS_CONFIG.read_text(encoding="utf-8")) or {}).get("llm") or {}
    endpoint = str(llm.get("endpoint") or "").removesuffix("/")
    if not endpoint:
        raise RuntimeError(f"no llm.endpoint in {MEMOS_CONFIG}")
    return {
        "AZURE_OPENAI_AUTH_MODE": "openai_compatible",
        "AZURE_OPENAI_ENDPOINT": endpoint,
        "AZURE_OPENAI_API_KEY": str(llm.get("apiKey") or "none"),
        "model": str(llm.get("model") or ""),
    }


def run(*, dry_run: bool = False) -> dict[str, Any]:
    """Run one SkillOpt-Sleep night over Atlas sessions and return a short summary."""
    from skillopt_sleep import cycle
    from skillopt_sleep.config import load_config

    env = _model_env()
    model = env.pop("model")
    os.environ.update(env)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    SKILL_PATH.parent.mkdir(parents=True, exist_ok=True)
    cfg = load_config(
        backend="azure_openai", model=model,
        invoked_project=str(WORK_DIR), projects="invoked", state_dir=str(WORK_DIR / "state"),
        target_skill_path=str(SKILL_PATH), managed_skill_name=SKILL_NAME,
        evolve_memory=False,      # memory belongs to MemOS; SkillOpt only trains the skill
        auto_adopt=True,          # adopted only when the held-out gate accepts the edit
        gate_mode="on", gate_no_regression=True,
        lookback_hours=24 * 14, max_tasks_per_night=12,
    )
    original = cycle.harvest_for_config
    cycle.harvest_for_config = lambda _cfg, since_iso=None, limit=0: harvest_atlas(
        since_iso=since_iso, limit=limit,
    )
    try:
        outcome = cycle.run_sleep_cycle(cfg, dry_run=dry_run)
    finally:
        cycle.harvest_for_config = original
    report = outcome.report
    summary = {
        "sessions": report.n_sessions, "tasks": report.n_tasks,
        "accepted": bool(report.accepted), "adopted": outcome.adopted,
        "baseline": report.baseline_score, "candidate": report.candidate_score,
        "staging": outcome.staging_dir, "skill": str(SKILL_PATH),
    }
    log.info("skill_sleep.done", **summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="harvest, mine and replay; stage nothing")
    args = parser.parse_args(argv)
    print(json.dumps(run(dry_run=args.dry_run), ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

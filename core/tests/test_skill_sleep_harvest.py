"""Atlas chat sessions become SkillOpt-Sleep digests (no model calls)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("skillopt_sleep")

from atlas.evolution.skill_sleep import harvest_atlas  # noqa: E402


def _state_db(path: Path) -> Path:
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE sessions (id TEXT, source TEXT, started_at REAL, ended_at REAL, cwd TEXT, git_branch TEXT);
        CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT,
                               tool_name TEXT, timestamp REAL);
    """)
    con.executemany("INSERT INTO sessions VALUES (?,?,?,?,?,?)", [
        ("chat", "desktop", 2000, 2100, "D:/proj", "main"),
        ("old", "desktop", 10, 20, "", ""),
        ("cron", "cron", 2000, 2100, "", ""),
        ("empty", "cli", 2000, 2100, "", ""),
    ])
    con.executemany("INSERT INTO messages (session_id, role, content, tool_name, timestamp) VALUES (?,?,?,?,?)", [
        ("chat", "user", "帮我跑一下测试", None, 1),
        ("chat", "assistant", None, "terminal", 2),
        ("chat", "tool", "3 failed", "terminal", 3),
        ("chat", "user", "还是不行，再看看", None, 4),
        ("chat", "assistant", "修好了，全部通过", None, 5),
        ("old", "user", "很久以前", None, 1),
        ("cron", "user", "定时任务", None, 1),
    ])
    con.commit()
    con.close()
    return path


def test_harvest_keeps_recent_user_sessions_only(tmp_path: Path) -> None:
    db = _state_db(tmp_path / "state.db")
    digests = harvest_atlas(db, since_iso="1970-01-01T00:16:40+00:00")  # epoch 1000
    assert [d.session_id for d in digests] == ["chat"]
    chat = digests[0]
    assert chat.user_prompts == ["帮我跑一下测试", "还是不行，再看看"]
    assert chat.assistant_finals == ["修好了，全部通过"]
    assert chat.tools_used == ["terminal"]
    assert chat.feedback_signals == ["还是不行，再看看"]
    assert chat.project == "D:/proj"


def test_missing_store_harvests_nothing(tmp_path: Path) -> None:
    assert harvest_atlas(tmp_path / "nope.db") == []

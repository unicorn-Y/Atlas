"""MemOS 记忆变动追踪：新增 / 修改 / 淡忘 / 删除都能从快照对比中识别出来。"""

import sqlite3

import pytest

from atlas.memory import memos_changes

pytestmark = pytest.mark.unit


def _memos_db(home):
    db = home / "data" / "memos.db"
    db.parent.mkdir(parents=True)
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE traces (id TEXT PRIMARY KEY, user_text TEXT, summary TEXT, value REAL, priority REAL, vec_summary BLOB);"
        "CREATE TABLE skills (id TEXT PRIMARY KEY, name TEXT, status TEXT, eta REAL);"
    )
    return conn


def test_scan_records_add_update_decay_archive_and_delete(tmp_path, monkeypatch):
    monkeypatch.setattr(memos_changes, "DATA_ROOT", tmp_path)  # store lands in tmp_path/data
    monkeypatch.setenv("MEMOS_HOME", str(tmp_path / "memos-home"))
    conn = _memos_db(tmp_path / "memos-home")
    conn.execute("INSERT INTO traces VALUES ('t1', '我住苏州', '住苏州', 0.5, 1.0, x'00')")
    conn.execute("INSERT INTO skills VALUES ('s1', 'tea', 'active', 0.2)")
    conn.commit()
    assert memos_changes.scan() == 2

    conn.execute("UPDATE traces SET summary='常住苏州', priority=0.8 WHERE id='t1'")
    conn.execute("UPDATE skills SET status='retired' WHERE id='s1'")
    conn.commit()
    assert memos_changes.scan() == 2
    conn.execute("UPDATE traces SET priority=0.3 WHERE id='t1'")
    conn.execute("DELETE FROM skills WHERE id='s1'")
    conn.commit()
    assert memos_changes.scan() == 2
    assert memos_changes.scan() == 0  # nothing changed since

    items = memos_changes.list_changes(limit=50)["items"]
    ops = [(i["entity"], i["op"]) for i in reversed(items)]
    assert ops == [("traces", "added"), ("skills", "added"), ("traces", "updated"),
                   ("skills", "archived"), ("traces", "decayed"), ("skills", "removed")]
    updated = next(i for i in items if i["op"] == "updated")
    assert updated["before"]["summary"] == "住苏州" and updated["after"]["summary"] == "常住苏州"
    removed = next(i for i in items if i["op"] == "removed")
    assert removed["before"]["name"] == "tea" and removed["after"] is None
    assert all("vec_summary" not in (i["after"] or {}) for i in items)  # embeddings never tracked

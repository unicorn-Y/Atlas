import json
import sqlite3
from datetime import datetime

from atlas.memory.library import MemoryLibrary, _skip_reason
from atlas.memory.library import extract
from atlas.memory.library.queue import TurnQueue
from atlas.memory.library.store import Entry, EPISODES, ME, Page


def _episode(title="问 dots、Muse 这类 AI 产品", did="直接回答", **kwargs):
    return extract.Episode(title=title, topics=["dots", "Muse"], did=did,
                           outcome=kwargs.pop("outcome", "了解了产品类别"), skip=False, **kwargs)


def test_w1_same_session_updates_one_episode_and_accumulates_steps(tmp_path):
    lib = MemoryLibrary(tmp_path)
    lib.ready()
    now = datetime.now().astimezone()
    first = _episode(did="讨论 dots")
    second = _episode(did="补充 Muse", outcome="识别了两个 AI 产品")
    lib._apply([], "dots", "session-1", "expert", now, episode=first,
               steps=[{"name": "web_search", "ok": True, "note": "找到产品介绍"}], verified=True)
    lib._apply([], "Muse", "session-1", "expert", now, episode=second,
               steps=[{"name": "web_search", "ok": False, "note": "未找到权威来源"}], verified=False)

    page = lib.store.read(f"经历/{now.date().isoformat()}.md")
    assert len(page.current) == 1
    assert "讨论 dots；补充 Muse" in page.current[0].text
    assert [s.split(" ", 1)[0] for s in page.current[0].steps] == ["web_search", "web_search"]
    assert page.current[0].verified is True
    assert page.current[0].trigger == ["dots", "Muse"]


def test_w1_skip_episode_and_missing_episode_preserve_fact_extraction(tmp_path):
    lib = MemoryLibrary(tmp_path)
    lib.ready()
    now = datetime.now().astimezone()
    lib._apply([], "ok", "session-2", "", now,
               episode=extract.Episode("回复 ok", [], "直接回答", "回复 ok", True))
    assert not any(p.startswith("经历/") for p in lib.store.pages())

    proposal = extract.Proposal(op="set", key="user.home_city", value="杭州",
                                 text="住在杭州", quote="我住杭州")
    lib._apply([proposal], "我住杭州", "session-3", "", now, episode=None)
    assert lib.store.read(ME).current[0].text == "住在杭州"


def test_w1_skip_reason_defaults_and_configured_patterns(tmp_path):
    assert _skip_reason(r"D:\Atlas\.tmp\audit-1", "普通请求") == "workspace"
    assert _skip_reason(r"D:\Atlas", "ATLAS_AUDIT 检查") == "text"
    assert _skip_reason(r"D:\Atlas", "[Gemini真实桌面补测] 检查") == "text"
    assert _skip_reason(r"D:\Atlas", "你知道 dots 吗") == ""

    class BadConfig:
        def get(self, key, default):
            if key.endswith("skip_workspace_patterns"):
                return ["["]
            return None

    assert MemoryLibrary(tmp_path, BadConfig())._skip_reason(r"D:\Atlas\.tmp\audit-x", "普通") == "workspace"


def test_w1_legacy_queue_schema_migrates_without_dropping_rows(tmp_path):
    path = tmp_path / ".queue.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE pending(id INTEGER PRIMARY KEY, created TEXT, session TEXT, mode TEXT, user_text TEXT, assistant_text TEXT, stage TEXT NOT NULL DEFAULT 'new', attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT)")
        db.execute("INSERT INTO pending(created, session, user_text) VALUES('2026-10-15T00:00:00+08:00','old','still here')")
    queue = TurnQueue(tmp_path)
    row = queue.pending()[0]
    assert row["user_text"] == "still here"
    assert row["steps"] == "[]"
    assert row["verified"] == 0


def test_w1_forgetting_episode_removes_page_index_and_redacts_diary(tmp_path):
    lib = MemoryLibrary(tmp_path)
    lib.ready()
    now = datetime.now().astimezone()
    lib._apply([], "dots", "session-4", "", now,
               episode=_episode(did="讨论 dots 与 Muse"))
    entry = lib.store.read(f"经历/{now.date().isoformat()}.md").current[0]
    page = lib.store.read(f"{EPISODES}/{now.date().isoformat()}.md")
    page.current.append(Entry(id="other-episode", text="类似内容：讨论 dots 与 Muse",
                              src="经历", session="other-session", at=now.isoformat()))
    lib.store.write(page)
    lib._write_diary(now, "dots", "讨论 dots 与 Muse", "session-4", "")
    lib.index.sync()

    lib.forget_entry(entry.id)

    assert entry.id not in {e.id for rel in lib.store.pages() for e in lib.store.read(rel).current}
    assert entry.id not in {hit["id"] for hit in lib.index.search("dots Muse", kinds=("episode",), include_history=True)}
    assert "讨论 dots" not in (tmp_path / f"{EPISODES}/{now.date().isoformat()}.md").read_text(encoding="utf-8")
    assert "讨论 dots" not in (tmp_path / "日记" / f"{now.date().isoformat()}.md").read_text(encoding="utf-8")


def test_w1_episode_resident_budget_does_not_consume_fact_resident(tmp_path):
    lib = MemoryLibrary(tmp_path)
    lib.ready()
    now = datetime.now().astimezone()
    me = lib.store.read(ME)
    me.current.append(Entry(text="我页保底仍然可见", at=now.isoformat()))
    lib.store.write(me)
    page = Page(path=f"经历/{now.date().isoformat()}.md", title=now.date().isoformat())
    page.current = [Entry(text=f"经历项目{i}-" + "词" * 1000, src="经历",
                          at=now.isoformat(), outcome="处理完成") for i in range(4)]
    lib.store.write(page)

    resident = lib._resident_block()
    episode_section = resident.split("## 最近在聊 / 在做", 1)[1]
    assert len(episode_section) <= 500
    assert "我页保底仍然可见" in resident


def test_w1_episode_parser_returns_episode_without_changing_fact_parse():
    facts, episode = extract.parse_output(json.dumps({
        "facts": [],
        "episode": {"title": "问 dots", "topics": ["dots"], "did": "直接回答",
                    "outcome": "答复", "skip": False},
    }, ensure_ascii=False))
    assert facts == []
    assert episode.title == "问 dots"

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from atlas.memory.library import MemoryLibrary, extract
from atlas.memory.library.embed import embed_texts
from atlas.memory.library.hybrid import merge_scores, mmr_select, temporal_decay
from atlas.memory.library.sources import open_ref
from atlas.memory.library.store import EPISODES, Entry, MemoryStore, Page


def test_episode_lists_merge_deduplicated_and_keep_last_five(tmp_path):
    store = MemoryStore(tmp_path)
    store.ensure()
    first = extract.Episode(
        "做记忆库 W2",
        did="读过模块",
        decisions=["用 SQLite，因已有索引"],
        files=["core/a.py"],
        commands=["pytest -q"],
        facts=["Python 3.14"],
        open_items=["补充 API"],
    )
    extract.apply_episode(
        store,
        first,
        [],
        False,
        "session-1",
        datetime(2026, 10, 1, 8, tzinfo=datetime.now().astimezone().tzinfo),
    )
    second = extract.Episode(
        "做记忆库 W2",
        did="补充 API",
        decisions=["用 SQLite，因已有索引", "第二个决定"],
        files=[f"core/{i}.py" for i in range(6)],
        commands=["pytest -q", "ruff check"],
        facts=["Python 3.14", "20000 条"],
        open_items=["补充 API", "跑主机实测"],
    )
    extract.apply_episode(
        store,
        second,
        [],
        False,
        "session-1",
        datetime(2026, 10, 1, 9, tzinfo=datetime.now().astimezone().tzinfo),
    )
    entry = store.read(f"{EPISODES}/2026-10-01.md").current[0]
    assert entry.decisions == ["用 SQLite，因已有索引", "第二个决定"]
    assert entry.files == [f"core/{i}.py" for i in range(1, 6)]
    assert entry.commands == ["pytest -q", "ruff check"]
    assert entry.facts == ["Python 3.14", "20000 条"]
    assert entry.open_items == ["补充 API", "跑主机实测"]


def test_hybrid_decay_and_mmr_are_deterministic():
    now = datetime(2026, 10, 16, tzinfo=datetime.now().astimezone().tzinfo)
    assert temporal_decay("日记/2026-09-16.md", now - timedelta(days=30), now) == pytest.approx(0.5)
    assert temporal_decay("事/Atlas.md", now - timedelta(days=300), now) == 1
    selected = mmr_select(
        [
            {"id": "a", "score": 1.0, "text": "同一件事的第一条记忆"},
            {"id": "b", "score": 0.99, "text": "同一件事的第一条记忆"},
            {"id": "c", "score": 0.999, "text": "另一件完全不同的事情"},
        ],
        limit=2,
    )
    assert [row["id"] for row in selected] == ["a", "c"]
    merged = merge_scores(
        [
            {
                "id": "same",
                "path": "经历/2026-10-16.md",
                "kind": "episode",
                "text": "提到向量".replace("向量", "topic"),
                "score": 0.8,
            }
        ],
        [
            {
                "id": "same",
                "path": "经历/2026-10-16.md",
                "kind": "episode",
                "text": "向量检索".replace("向量", "topic"),
                "vector_score": 0.9,
            }
        ],
        now=now,
        limit=5,
    )
    assert len(merged) == 1
    assert merged[0]["vector_score"] == pytest.approx(0.9)
    assert merged[0]["text_score"] == pytest.approx(1.0)


def test_open_ref_returns_nearest_user_turn_with_tools_and_truncates(tmp_path, monkeypatch):
    from atlas.engine import session_sync

    stamp = "2026-10-16T10:00:00+08:00"
    messages = [
        {"role": "user", "text": "请改文件", "at": "2026-10-16T09:59:00+08:00"},
        {"role": "assistant", "text": "我会先看", "at": stamp},
        {
            "role": "tool",
            "text": "x" * 3000,
            "at": stamp,
            "tool": {"name": "read_file", "ok": True},
        },
        {"role": "assistant", "text": "已完成", "at": stamp},
        {"role": "user", "text": "另一个问题", "at": "2026-10-16T10:03:00+08:00"},
    ]
    monkeypatch.setattr(session_sync, "read_session_all_messages", lambda *_: messages)
    result = open_ref("session-1@2026-10-16T10:00:00+08:00", root=tmp_path)
    assert result["ok"] is True
    assert [m["role"] for m in result["messages"]] == ["user", "assistant", "tool", "assistant"]
    assert result["truncated"] is True
    assert len(result["messages"][2]["text"]) <= 2000
    assert sum(len(m["text"]) for m in result["messages"]) <= 12000


def test_search_adds_ref_and_raw_only_when_requested(tmp_path, monkeypatch):
    library = MemoryLibrary(tmp_path)
    library.ready()
    page = Page(path="事/Atlas.md", title="Atlas")
    page.current.append(
        Entry(id="fact-1", text="向量搜索使用 fastembed", ref="session-1@2026-10-16T10:00:00+08:00")
    )
    library.store.write(page)
    library.index.sync()
    hits = library.search("向量搜索 fastembed")
    assert hits and hits[0]["ref"].startswith("session-1@")
    dream_page = Page(path="事/Atlas.md", title="Atlas")
    dream_page.current.append(Entry(id="dream-1", text="整理后的项目决定记录", src="整理"))
    library.store.write(dream_page)
    library.index.sync()
    dream_hits = library.search("整理后的项目决定")
    assert any(hit["id"] == "dream-1" and hit["kind"] == "dream" for hit in dream_hits)
    raw = {
        "id": "raw-1",
        "kind": "raw",
        "text": "原文结果",
        "at": "2026-10-16",
        "ref": "session-1@2026-10-16",
    }
    monkeypatch.setattr("atlas.memory.library.sources.search_raw", lambda *_: [raw])
    assert all(hit["kind"] != "raw" for hit in library.search("原文"))
    assert any(hit["kind"] == "raw" for hit in library.search("原文", kinds=("raw",)))


def test_detailed_recall_includes_recent_episode_already_in_resident_context(tmp_path, monkeypatch):
    monkeypatch.setattr("atlas.memory.library.embed.embed_texts", lambda _texts: None)
    library = MemoryLibrary(tmp_path)
    library.ready()
    now = datetime.now().astimezone()
    entry = Entry(
        id="recent-episode",
        text="刚才那个任务修改了样例文件",
        src="经历",
        at=now.isoformat(timespec="seconds"),
        ref=f"session-1@{now.isoformat(timespec='seconds')}",
        session="session-1",
        files=["sample.txt：status=old 改为 status=verified"],
        decisions=["先提交 status 单行修改"],
        commands=["python 验证输出 status=verified"],
        facts=["owner 行未改"],
        open_items=["检查真实配置兼容性"],
    )
    library.store.write(Page(path=f"经历/{now.date().isoformat()}.md", title="episodes",
                             current=[entry]))
    library.index.sync()

    result = library.recall("刚才那个任务改了哪个文件、为什么？")

    assert "sample.txt" in result["relevant"]
    assert "先提交 status 单行修改" in result["relevant"]


def test_embed_unavailable_is_a_nonfatal_keyword_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr("atlas.memory.library.embed._load_model", lambda: None)
    assert embed_texts(["任意文本"]) is None
    library = MemoryLibrary(tmp_path)
    library.ready()
    page = Page(path="事/Atlas.md", title="Atlas")
    page.current.append(Entry(id="lexical", text="关键字仍然能找到这条记录"))
    library.store.write(page)
    hits = library.search("关键字 记录")
    assert hits and hits[0]["id"] == "lexical"


@pytest.mark.asyncio
async def test_dream_checkpoint_advances_only_after_all_projects_succeed(tmp_path, monkeypatch):
    from atlas.memory.library import dream

    library = MemoryLibrary(tmp_path)
    library.ready()
    now = datetime.now().astimezone()
    episode = Entry(
        id="e1",
        text="Atlas：完成接口",
        src="经历",
        at=now.isoformat(),
        trigger=["Atlas"],
        files=["core/atlas/api/x.py"],
    )
    page = Page(path=f"经历/{now.date().isoformat()}.md", title="episodes", current=[episode])
    page.current.append(Entry(id="e2", text="Atlas：完成回归", src="经历",
                              at=(now - timedelta(days=1)).isoformat(), trigger=["Atlas"]))
    library.store.write(page)
    state = tmp_path / ".dream-state.json"
    state.write_text(json.dumps({"checkpoint": "2000-01-01T00:00:00+00:00"}), encoding="utf-8")
    monkeypatch.setattr(
        dream,
        "_write_project",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("model failed")),
    )
    report = await dream.run_dream(library, model_mgr=object())
    assert report["ok"] is False
    assert (
        json.loads(state.read_text(encoding="utf-8"))["checkpoint"] == "2000-01-01T00:00:00+00:00"
    )


@pytest.mark.asyncio
async def test_dream_writes_project_sections_and_advances_checkpoint_after_success(
    tmp_path, monkeypatch
):
    from atlas.memory.library import dream

    library = MemoryLibrary(tmp_path)
    library.ready()
    now = datetime.now().astimezone()
    entry = Entry(
        id="episode-1",
        text="Atlas 记忆库：完成接口",
        src="经历",
        at=now.isoformat(),
        trigger=["Atlas"],
        files=["core/atlas/api/x.py"],
        decisions=["保留接口兼容"],
        open_items=["2026-10-20 前完成验收"],
    )
    page = Page(path=f"经历/{now.date().isoformat()}.md", title="episodes", current=[entry])
    page.current.append(Entry(id="episode-2", text="Atlas 记忆库：回归通过", src="经历",
                              at=(now - timedelta(days=1)).isoformat(), trigger=["Atlas"]))
    library.store.write(page)
    state = tmp_path / ".dream-state.json"
    state.write_text(json.dumps({"checkpoint": "2000-01-01T00:00:00+00:00"}), encoding="utf-8")

    async def write(_library, _model_mgr, _name, _entries):
        return (
            [
                {"action": "add", "target_id": "", "old_text_hash": "",
                 "source_refs": ["episode-1"],
                 "fields": {"section": "现在状态", "text": "接口已落地"},
                 "reason": "跨会话项目状态"},
                {"action": "add", "target_id": "", "old_text_hash": "",
                 "source_refs": ["episode-1"],
                 "fields": {"section": "定下的决定", "text": "使用既有 API"},
                 "reason": "经历中记录的决定"},
                {"action": "add", "target_id": "", "old_text_hash": "",
                 "source_refs": ["episode-1"],
                 "fields": {"section": "没做完", "text": "2026-10-20 前完成验收"},
                 "reason": "经历中记录的未完成事项"},
            ],
            "",
        )

    monkeypatch.setattr(dream, "_write_project", write)
    report = await dream.run_dream(library, model_mgr=object())
    assert report["ok"] is True
    project = (tmp_path / "事" / "Atlas.md").read_text(encoding="utf-8")
    assert "## 现在状态" in project and "## 定下的决定" in project
    assert '"src":"整理"' in project
    assert json.loads(state.read_text(encoding="utf-8"))["checkpoint"] > "2000"
    assert any(e.until == "2026-10-20" for e in library.store.read("现状.md").current)

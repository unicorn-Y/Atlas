from __future__ import annotations

import asyncio
import json
import threading
from types import SimpleNamespace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from atlas.memory.library import MemoryLibrary, extract
from atlas.memory.library.embed import embed_texts
from atlas.memory.library.hybrid import merge_scores, mmr_select, temporal_decay
from atlas.memory.library.sources import open_ref
from atlas.memory.library.store import EPISODES, Entry, MemoryStore, Page
from atlas.memory.library.queue import TurnQueue


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


def test_failed_turn_queue_exposes_detail_and_explicit_retry(tmp_path):
    queue = TurnQueue(tmp_path)
    row_id = queue.insert(created="2026-10-17T10:00:00+08:00", session="s", mode="",
                          user_text="用户输入", assistant_text="回复")
    for attempt in range(3):
        queue.fail(row_id, f"model failure {attempt + 1}")
    assert queue.pending() == []
    failed = queue.failed()
    assert failed[0]["id"] == row_id and failed[0]["last_error"] == "model failure 3"
    assert queue.retry_failed(row_id) == 1
    assert queue.pending()[0]["attempts"] == 0
    assert queue.pending()[0]["last_error"] is None


def test_turn_queue_persists_exact_source_ref_precision(tmp_path):
    queue = TurnQueue(tmp_path)
    row_id = queue.insert(created="2026-10-17T10:00:00+08:00", session="s", mode="",
                          user_text="用户输入", assistant_text="回复", source_ref="atlas://source/v1?x",
                          source_precision="exact")
    row = queue.pending()[0]
    assert row["id"] == row_id
    assert row["source_ref"] == "atlas://source/v1?x"
    assert row["source_precision"] == "exact"


def test_diary_append_is_idempotent_for_pending_queue_row(tmp_path):
    library = MemoryLibrary(tmp_path)
    stamp = datetime(2026, 10, 17, 10, 0, tzinfo=datetime.now().astimezone().tzinfo)
    library._write_diary(stamp, "原话", "回复", "s", "", "", "queue-7")
    library._write_diary(stamp, "原话", "回复", "s", "", "", "queue-7")
    text = (tmp_path / "日记" / "2026-10-17.md").read_text(encoding="utf-8")
    assert text.count("turn_id") == 1
    assert text.count("原话") == 1


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


def test_turn_without_ready_model_keeps_diary_and_pending_queue(tmp_path, monkeypatch):
    async def run():
        library = MemoryLibrary(tmp_path)
        monkeypatch.setattr(library.index, "_schedule_embeddings", lambda: None)
        monkeypatch.setattr(library, "_write_diary", lambda *args: None)
        monkeypatch.setattr("atlas.memory.library._source_ref_for_turn", lambda *_args: "")
        library.schedule_turn(
            user_text="记住这件事",
            assistant_text="收到",
            session="session-no-model",
            model_mgr=None,
        )
        await asyncio.gather(*library._tasks)
        rows = library.queue.pending()
        assert len(rows) == 1
        assert rows[0]["stage"] == "diary_done"
        assert rows[0]["attempts"] == 0

    asyncio.run(run())


def test_embedding_sync_worker_uses_registered_event_loop(tmp_path, monkeypatch):
    async def run():
        index = MemoryLibrary(tmp_path).index
        completed = threading.Event()
        worker_threads: list[str] = []

        def embed_missing():
            worker_threads.append(threading.current_thread().name)
            completed.set()
            index._embedding_state = "ready"
            return 0

        monkeypatch.setattr(index, "embed_missing", embed_missing)
        index.set_event_loop(asyncio.get_running_loop())
        await asyncio.to_thread(index._schedule_embeddings)
        await asyncio.wrap_future(index._embedding_task)
        assert completed.is_set()
        assert worker_threads and worker_threads[0] != threading.current_thread().name
        assert index.embedding_state == "ready"

    asyncio.run(run())


def test_embedding_model_load_retries_after_ten_minutes(tmp_path, monkeypatch):
    import sys

    from atlas import config
    from atlas.memory.library import embed

    clock = iter([100.0, 101.0, 500.0, 801.0])
    monkeypatch.setattr(embed.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(config, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(embed, "_model", None)
    monkeypatch.setattr(embed, "_attempted", False)
    monkeypatch.setattr(embed, "_last_failed_at", None)
    monkeypatch.setattr(embed, "_warned", False)
    attempts = 0
    model = object()

    class TextEmbedding:
        def __init__(self, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise OSError("model files unavailable")
            self.model = model

    monkeypatch.setitem(sys.modules, "fastembed", SimpleNamespace(TextEmbedding=TextEmbedding))
    assert embed._load_model() is None
    assert embed._load_model() is None
    assert attempts == 1
    assert embed._load_model() is embed._model
    assert embed._model is not None
    assert attempts == 2


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
    monkeypatch.setattr(session_sync, "list_session_previews", lambda *_args, **_kwargs: {})
    result = open_ref("session-1@2026-10-16T10:00:00+08:00", root=tmp_path)
    assert result["ok"] is True
    assert [m["role"] for m in result["messages"]] == ["user", "assistant", "tool", "assistant"]
    assert result["truncated"] is True
    assert len(result["messages"][2]["text"]) <= 2000
    assert sum(len(m["text"]) for m in result["messages"]) <= 12000
    assert result["precision"] == "approximate"


def test_open_ref_binds_exact_message_uid_and_missing_uid_never_guesses(tmp_path, monkeypatch):
    from atlas.engine import session_sync
    from atlas.memory.library.source_ref import SourceRef

    messages = [
        {"id": "uid-1", "role": "user", "text": "第一轮", "at": "2026-10-16T10:00:00+08:00"},
        {"id": "uid-assistant", "role": "assistant", "text": "回答", "at": "2026-10-16T10:00:01+08:00"},
        {"id": "uid-2", "role": "user", "text": "第二轮", "at": "2026-10-16T10:00:02+08:00"},
    ]
    monkeypatch.setattr(session_sync, "read_session_all_messages", lambda *_: messages)
    monkeypatch.setattr(session_sync, "list_session_previews", lambda *_args, **_kwargs: {})
    ref = SourceRef("session-1", "uid-2").to_ref()
    opened = open_ref(ref, root=tmp_path)
    assert opened["ok"] and opened["precision"] == "exact"
    assert opened["message_uid"] == "uid-2"
    assert opened["messages"][0]["text"] == "第二轮"
    missing = open_ref(SourceRef("session-1", "deleted-uid").to_ref(), root=tmp_path)
    assert missing["ok"] is False and missing["precision"] == "exact"


def test_schedule_source_ref_requires_matching_sessiondb_user_text(monkeypatch):
    from atlas.engine import session_sync
    from atlas import config
    from atlas.memory.library import _source_ref_for_turn
    from atlas.memory.library.source_ref import SourceRef

    def latest(home, *_args, **_kwargs):
        assert home == config.DATA_ROOT / "engine"
        return {"id": "stable-uid", "content": "本轮原话", "role": "user"}
    monkeypatch.setattr(config, "DATA_ROOT", Path("isolated-atlas-data"))
    monkeypatch.setattr(session_sync, "latest_session_message", latest)
    assert _source_ref_for_turn("session", "本轮原话") == SourceRef("session", "stable-uid").to_ref()
    assert _source_ref_for_turn("session", "另一个时间接近的原话") == ""


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
    library.store.write(
        Page(path=f"经历/{now.date().isoformat()}.md", title="episodes", current=[entry])
    )
    state = tmp_path / ".dream-state.json"
    state.write_text(json.dumps({"checkpoint": "2000-01-01T00:00:00+00:00"}), encoding="utf-8")

    async def write(_library, _model_mgr, _name, _entries):
        return (
            {
                "现在状态": ["接口已落地"],
                "定下的决定": ["使用既有 API"],
                "没做完": ["2026-10-20 前完成验收"],
                "来龙去脉": ["来自经历"],
            },
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


@pytest.mark.asyncio
async def test_dream_does_not_checkpoint_unqualified_episode_and_rechecks_late_ids(tmp_path, monkeypatch):
    from atlas.memory.library import dream

    library = MemoryLibrary(tmp_path)
    library.ready()
    stamp = "2026-10-15T10:00:00+08:00"
    episode = Entry(id="late", text="活动摘要", src="经历", at=stamp, trigger=["Project"])
    library.store.write(Page(path="经历/2026-10-15.md", title="episodes", current=[episode]))
    state = tmp_path / ".dream-state.json"
    state.write_text(json.dumps({"checkpoint": "2000-01-01T00:00:00+00:00"}), encoding="utf-8")
    report = await dream.run_dream(library, model_mgr=object())
    assert report["ok"] is True
    saved = json.loads(state.read_text(encoding="utf-8"))
    assert saved["checkpoint"] == "2000-01-01T00:00:00+00:00"
    assert "late" not in saved.get("processed_ids", [])

    episode.text = "Project 项目明确提及，补充为可归类经历"
    library.store.write(Page(path="经历/2026-10-15.md", title="episodes", current=[episode]))
    async def write(*_args, **_kwargs):
        return ({"现在状态": ["已识别"], "定下的决定": [], "没做完": [], "来龙去脉": []}, "")
    monkeypatch.setattr(dream, "_write_project", write)
    report = await dream.run_dream(library, model_mgr=object())
    assert report["ok"] is True
    assert "Project" in report["projects"]

    late = Entry(id="late-after-checkpoint", text="Project late arrival", src="经历",
                 at="2001-01-01T00:00:00+00:00", trigger=["Project"])
    library.store.write(Page(path="经历/2001-01-01.md", title="episodes", current=[late]))
    restarted = MemoryLibrary(tmp_path)
    restarted.ready()
    report = await dream.run_dream(restarted, model_mgr=object())
    assert report["ok"] is True and "Project" in report["projects"]
    saved = json.loads(state.read_text(encoding="utf-8"))
    assert "Project\x1flate-after-checkpoint" in saved["processed_ids"]


@pytest.mark.asyncio
async def test_dream_preserves_owner_edit_made_during_model_call(tmp_path, monkeypatch):
    from atlas.memory.library import dream

    library = MemoryLibrary(tmp_path)
    library.ready()
    now = datetime.now().astimezone()
    episode = Entry(id="e", text="Atlas 项目明确提及", src="经历", at=now.isoformat(), trigger=["Atlas"])
    library.store.write(Page(path=f"经历/{now.date().isoformat()}.md", title="episodes", current=[episode]))
    project_path = tmp_path / "事" / "Atlas.md"
    async def write(*_args, **_kwargs):
        project_path.write_text(
            "# Atlas\n\n## 现在状态\n" + Entry(text="人工刚添加的决定", src="你改的").line() + "\n",
            encoding="utf-8",
        )
        return ({"现在状态": ["模型摘要"], "定下的决定": [], "没做完": [], "来龙去脉": []}, "")
    monkeypatch.setattr(dream, "_write_project", write)
    report = await dream.run_dream(library, model_mgr=object())
    assert report["ok"] is True
    assert "人工刚添加的决定" in project_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_timeline_compound_cursor_pages_equal_timestamps_without_gaps(monkeypatch):
    from atlas.api import memory_library_router as router

    entries = [Entry(id=f"id-{i}", text=f"经历 {i}", src="经历", at="2026-10-15T10:00:00+08:00")
               for i in range(4)]
    page = Page(path="经历/2026-10-15.md", title="episodes", current=entries)
    class Store:
        def pages(self):
            return [page.path]
        def read(self, _path):
            return page
    class Library:
        store = Store()
        def ready(self):
            return None
    monkeypatch.setattr(router, "_lib", lambda: Library())
    monkeypatch.setattr(router, "_run", lambda fn, *args: asyncio.sleep(0, result=fn(*args)))
    first = await router.timeline(limit=2)
    second = await router.timeline(before=first["next"], limit=2)
    ids = [row["id"] for row in first["items"] + second["items"]]
    assert len(ids) == len(set(ids)) == 4
    assert second["next"] is None


@pytest.mark.asyncio
async def test_search_filters_and_paginates_beyond_first_thousand(monkeypatch):
    from atlas.api import memory_library_router as router

    candidates = [
        {"id": str(i), "kind": "fact", "path": "事/Atlas.md", "text": "match",
         "src": "你说的", "at": "2026-10-17T10:00:00+08:00", "score": 1.0}
        for i in range(1205)
    ]
    class Index:
        def _schedule_embeddings(self):
            return None
    class Library:
        index = Index()
        def search(self, _q, limit, _history, _kinds):
            assert limit == 100000
            return candidates
    monkeypatch.setattr(router, "_lib", lambda: Library())
    async def run(fn, *args):
        return fn(*args)
    monkeypatch.setattr(router, "_run", run)
    result = await router.search(q="match", src="你说的", from_="", to="", project="Atlas",
                                 kinds="memory", limit=20, offset=1180)
    assert result["total"] == 1205
    assert len(result["items"]) == 20
    assert result["items"][0]["id"] == "1180"


@pytest.mark.asyncio
async def test_startup_schedules_bounded_pending_drain_after_model_ready(monkeypatch):
    from atlas import server
    from atlas.api import memory_library_router as router

    drained = []
    class Library:
        _tasks = set()
        class Queue:
            @staticmethod
            def count():
                return 1
        queue = Queue()
        async def _drain(self, model_mgr):
            drained.append(model_mgr)
    library = Library()
    model_mgr = SimpleNamespace(model_router=object())
    monkeypatch.setattr(server, "model_mgr", model_mgr)
    monkeypatch.setattr(router, "get_library", lambda: library)
    monkeypatch.setattr(router, "_dream_task", asyncio.get_running_loop().create_future())
    await router.start_dream_scheduler()
    await asyncio.gather(*list(library._tasks))
    assert drained == [model_mgr]

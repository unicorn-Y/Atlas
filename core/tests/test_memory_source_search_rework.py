from datetime import UTC, datetime

import pytest

from atlas import config
from atlas.memory.library import _source_ref_for_turn, sources
from atlas.memory.library.source_ref import SourceRef


def test_source_ref_uses_supplied_uid_for_repeated_text_and_never_guesses(monkeypatch, tmp_path):
    def evidence(home, session, uid):
        assert home == config.DATA_ROOT / "engine"
        assert session == "session"
        return {"message_uid": uid, "role": "user"} if uid in {"turn-1", "turn-2"} else None

    monkeypatch.setattr(config, "DATA_ROOT", tmp_path)
    monkeypatch.setattr("atlas.engine.session_sync.session_message_evidence", evidence)
    ref_1 = SourceRef("session", "turn-1").to_ref()
    ref_2 = SourceRef("session", "turn-2").to_ref()
    assert _source_ref_for_turn("session", "相同原话", "turn-1") == ref_1
    assert _source_ref_for_turn("session", "相同原话", "turn-2") == ref_2
    assert _source_ref_for_turn("session", "相同原话") == ""
    assert _source_ref_for_turn("session", "相同原话", "missing") == ""


def test_raw_search_pages_past_first_sessiondb_page(monkeypatch, tmp_path):
    offsets = []

    def page(_home, _query, *, limit, offset):
        offsets.append(offset)
        return [{"id": f"uid-{i}", "conversation_id": "s", "content": "raw",
                 "created_at": "2026-10-17T10:00:00+00:00"}
                for i in range(offset, min(offset + limit, 60))]

    monkeypatch.setattr(config, "DATA_ROOT", tmp_path)
    monkeypatch.setattr("atlas.engine.session_sync.search_session_messages", page)
    hits = sources.search_raw("raw", limit=60)
    assert len(hits) == 60
    assert offsets == [0, 50]
    assert hits[59]["ref"].endswith("uid-59")


def test_forget_excludes_exact_source_from_memory_but_preserves_raw_and_other_uid(monkeypatch, tmp_path):
    from atlas.memory.library import MemoryLibrary
    from atlas.memory.library.extract import Episode, apply_episode
    from atlas.memory.library.store import Entry, Page

    monkeypatch.setattr("atlas.memory.library.embed.embed_texts", lambda _texts: None)
    library = MemoryLibrary(tmp_path)
    library.ready()
    ref1 = SourceRef("session", "turn-1").to_ref()
    ref2 = SourceRef("session", "turn-2").to_ref()
    page = Page(path="事/Atlas.md", title="Atlas",
                current=[Entry(id="forgotten", text="same words", ref=ref1),
                         Entry(id="other-source", text="same words", ref=ref2)])
    library.store.write(page)
    library.store.write(Page(path="我.md", title="关于你", current=[
        Entry(id="resident-forgotten", text="resident fact", ref=ref1),
        Entry(id="resident-other", text="other UID fact", ref=ref2),
    ]))
    library.index.sync()
    monkeypatch.setattr("atlas.memory.library._SINGLETON", library)
    monkeypatch.setattr(config, "DATA_ROOT", tmp_path)
    monkeypatch.setattr("atlas.engine.session_sync.search_session_messages", lambda *_a, **_kw: [
        {"id": "turn-1", "conversation_id": "session", "content": "same words"},
        {"id": "turn-2", "conversation_id": "session", "content": "same words"},
    ])

    report = library.forget_entry("forgotten")
    assert report["source_excluded"] is True
    recall = library.index.search("same words", kinds=("fact",), limit=10)
    assert "forgotten" not in {row["id"] for row in recall}
    assert "other-source" in {row["id"] for row in recall}
    resident = library._resident_block()
    assert "resident fact" not in resident
    assert "other UID fact" in resident
    assert len(sources.search_raw("same words", limit=10)) == 1
    assert sources.search_raw("same words", limit=10)[0]["ref"] == ref2
    from atlas.engine import session_sync
    monkeypatch.setattr(session_sync, "read_session_all_messages", lambda *_: [
        {"id": "turn-1", "role": "user", "text": "same words"},
    ])
    monkeypatch.setattr(session_sync, "list_session_previews", lambda *_a, **_kw: {})
    assert sources.open_ref(ref1, root=tmp_path)["ok"] is True

    episode = Episode(title="same words", did="same words")
    now = datetime.now().astimezone()
    assert not apply_episode(library.store, episode, [], False, "session", now, ref=ref1)
    assert apply_episode(library.store, episode, [], False, "session", now, ref=ref2)
    assert "session" in ref1 and library.store.source_tombstoned(ref1)


def test_forget_without_exact_source_reports_source_exclusion_gap(tmp_path):
    from atlas.memory.library import MemoryLibrary
    from atlas.memory.library.store import Entry, Page

    library = MemoryLibrary(tmp_path)
    library.ready()
    page = Page(path="事/Atlas.md", title="Atlas", current=[Entry(id="no-ref", text="derived only")])
    library.store.write(page)
    report = library.forget_entry("no-ref")
    assert report["source_excluded"] is False
    assert any("UID" in item for item in report["not_covered"])


@pytest.mark.asyncio
async def test_browse_search_uses_exact_paged_index_contract(monkeypatch):
    from atlas.api import memory_library_router as router

    class Index:
        def _schedule_embeddings(self):
            return None

    class Library:
        index = Index()
        def browse_search(self, query, *, offset, limit, include_history, kinds,
                          sources, from_date, to_date, project):
            assert (query, offset, limit, include_history, kinds) == (
                "needle", 120000, 20, False, ("fact", "dream", "episode", "diary"),
            )
            assert (sources, from_date, to_date, project) == ({"你说的"}, "2026-01-01", "", "Atlas")
            return {"total": 120001, "items": [{"id": "120000", "kind": "fact",
                "path": "事/Atlas.md", "text": "needle", "src": "你说的",
                "at": "2026-10-17", "ref": "", "score": 0.5}]}

        def search(self, *_args, **_kwargs):
            raise AssertionError("browse route must not materialize the capped search result list")

    monkeypatch.setattr(router, "_lib", lambda: Library())
    async def run(fn, *args, **kwargs):
        return fn(*args, **kwargs)
    monkeypatch.setattr(router, "_run", run)
    result = await router.search(q="needle", src="你说的", from_="2026-01-01", to="",
                                 project="Atlas", kinds="memory", limit=20, offset=120000)
    assert result["total"] == 120001
    assert result["items"][0]["id"] == "120000"


def test_browse_index_scans_past_100k_and_counts_filtered_rows(tmp_path, monkeypatch):
    from atlas.memory.library import MemoryLibrary

    monkeypatch.setattr("atlas.memory.library.embed.embed_texts", lambda _texts: None)
    library = MemoryLibrary(tmp_path)
    library.ready()
    with library.index._lock:
        db = library.index._conn()
        row = {"path": "事/Atlas.md", "kind": "fact", "bucket": "current",
               "text": "needle search result", "key": "", "src": "你说的",
               "at": "2026-10-17", "until": "", "quote": "", "mode": "", "ref": "",
               "importance": 5, "trigger": "", "origin_class": "owner", "observed_at": ""}
        for number in range(100_005):
            library.index._insert(db, {**row, "id": f"item-{number:06d}"})
        db.commit()

    result = library.index.browse_search(
        "needle", offset=100_000, limit=5, kinds=("fact",), include_history=False,
        sources={"你说的"}, from_date="", to_date="", project="Atlas",
        now=datetime(2026, 10, 17, tzinfo=UTC),
    )
    assert result["total"] == 100_005
    assert [row["id"] for row in result["items"]] == [
        "item-100000", "item-100001", "item-100002", "item-100003", "item-100004",
    ]


def test_browse_keyword_normalization_uses_unfiltered_candidates(tmp_path, monkeypatch):
    from atlas.memory.library import MemoryLibrary
    from atlas.memory.library.hybrid import merge_scores

    monkeypatch.setattr("atlas.memory.library.embed.embed_texts", lambda _texts: None)
    library = MemoryLibrary(tmp_path)
    library.ready()
    with library.index._lock:
        db = library.index._conn()
        rows = [
            {"id": "included", "path": "事/Atlas.md", "kind": "fact", "bucket": "current",
             "text": "needle", "key": "", "src": "你说的", "at": "2026-10-17", "until": "",
             "quote": "", "mode": "", "ref": "", "importance": 5, "trigger": "",
             "origin_class": "owner", "observed_at": ""},
            {"id": "filtered-high-score", "path": "事/Other.md", "kind": "fact",
             "bucket": "current", "text": "needle alpha beta", "key": "", "src": "它自己",
             "at": "2026-10-17", "until": "", "quote": "", "mode": "", "ref": "",
             "importance": 10, "trigger": "", "origin_class": "agent", "observed_at": ""},
        ]
        for row in rows:
            library.index._insert(db, row)
        db.commit()

    keyword = library.index._keyword_search(
        "needle alpha beta", limit=10, kinds=("fact",), now=datetime(2026, 10, 17, tzinfo=UTC),
    )
    baseline = merge_scores(keyword, [], now=datetime(2026, 10, 17, tzinfo=UTC), limit=10)
    expected = next(row["score"] for row in baseline if row["id"] == "included")
    result = library.index.browse_search(
        "needle alpha beta", offset=0, limit=10, kinds=("fact",), include_history=False,
        sources={"你说的"}, from_date="", to_date="", project="Atlas",
        now=datetime(2026, 10, 17, tzinfo=UTC),
    )
    assert result["total"] == 1
    assert result["items"][0]["id"] == "included"
    assert result["items"][0]["score"] == pytest.approx(expected)

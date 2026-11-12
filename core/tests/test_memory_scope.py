import hashlib
import sqlite3
from types import SimpleNamespace

from atlas.memory.library import MemoryLibrary
from atlas.memory.library.index import MemoryIndex
from atlas.memory.library.store import Entry, MemoryStore, Page


def test_index_migrates_legacy_items_to_global_scope(tmp_path):
    store = MemoryStore(tmp_path)
    store.ensure()
    path = tmp_path / ".index.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE items (
            rowid INTEGER PRIMARY KEY, id TEXT NOT NULL, path TEXT NOT NULL,
            kind TEXT NOT NULL, bucket TEXT NOT NULL, text TEXT NOT NULL,
            key TEXT, src TEXT, at TEXT, until TEXT, quote TEXT, mode TEXT,
            ref TEXT, importance INTEGER NOT NULL DEFAULT 5, trigger TEXT,
            tokens TEXT NOT NULL, origin_class TEXT NOT NULL,
            observed_at TEXT)""")
        db.execute("""INSERT INTO items(id,path,kind,bucket,text,tokens,origin_class) VALUES
                    ('legacy','我.md','fact','current','legacy row','legacy row','owner')""")

    index = MemoryIndex(store)
    rows = index._conn().execute("PRAGMA table_info(items)").fetchall()
    assert "scope" in {row[1] for row in rows}
    row = index._conn().execute("SELECT scope FROM items WHERE id='legacy'").fetchone()
    assert row[0] == "global"


def test_memory_search_isolates_project_scopes_and_includes_global(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_TEST_DISABLE_MEMORY_EMBEDDINGS", "1")
    library = MemoryLibrary(tmp_path)
    library.ready()
    for path, scope, text in (
        ("我.md", "global", "aurora shared note"),
        ("项目/a.md", "project:A", "aurora alpha secret"),
        ("项目/b.md", "project:B", "aurora beta secret"),
    ):
        page = library.store.read(path)
        page.current.append(Entry(id=scope, text=text, scope=scope))
        library.store.write(page)
    library.index.sync()

    a_hits = library.index.search("aurora", scope=None, project_scope="project:A")
    b_hits = library.index.search("aurora", scope=None, project_scope="project:B")
    assert {hit["scope"] for hit in a_hits} == {"global", "project:A"}
    assert {hit["scope"] for hit in b_hits} == {"global", "project:B"}
    assert {hit["id"] for hit in a_hits}.isdisjoint({"project:B"})
    assert {hit["id"] for hit in b_hits}.isdisjoint({"project:A"})


def test_memory_library_search_resolves_current_project_scope(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_TEST_DISABLE_MEMORY_EMBEDDINGS", "1")
    library = MemoryLibrary(tmp_path)
    library.ready()
    project_root = r"C:\Projects\alpha"
    project_scope = "project:" + hashlib.sha256(project_root.casefold().encode("utf-8")).hexdigest()[:16]
    for path, scope, text in (
        ("我.md", "global", "comet shared note"),
        ("项目/alpha.md", project_scope, "comet alpha note"),
        ("项目/beta.md", "project:beta", "comet beta note"),
    ):
        page = library.store.read(path)
        page.current.append(Entry(id=scope, text=text, scope=scope))
        library.store.write(page)
    library.index.sync()
    monkeypatch.setattr(
        "atlas.memory.library.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(stdout=project_root + "\n"),
    )

    hits = library.search("comet", workspace=r"C:\Projects\alpha")
    assert {hit["id"] for hit in hits} == {"global", project_scope}


def test_explicit_scope_also_filters_raw_search_results(tmp_path, monkeypatch):
    library = MemoryLibrary(tmp_path)
    library.ready()
    monkeypatch.setattr(
        "atlas.memory.library.sources.search_raw",
        lambda _query, _limit: [
            {"id": "global-raw", "scope": "global", "text": "raw result"},
            {"id": "other-project-raw", "scope": "project:B", "text": "raw result"},
            {"id": "this-project-raw", "scope": "project:A", "text": "raw result"},
        ],
    )

    hits = library.index.search("raw", kinds=("raw",), scope="project:A")
    assert {hit["id"] for hit in hits} == {"this-project-raw"}


def test_entry_scope_round_trips_in_markdown_meta():
    entry = Entry(text="project memory", scope="project:alpha")
    restored = Entry.parse(entry.line())
    assert restored is not None
    assert restored.scope == "project:alpha"


def test_agent_scope_write_is_indexed_and_searchable(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_TEST_DISABLE_MEMORY_EMBEDDINGS", "1")
    library = MemoryLibrary(tmp_path)
    library._turn_source_ref = lambda *_args: "ref-1"
    result = library.agent_memory_write("agent-a", "agent scoped memory", session="s1")
    hits = library.index.search("scoped memory", scope=result["scope"])
    assert len(hits) == 1
    assert hits[0]["scope"] == result["scope"]

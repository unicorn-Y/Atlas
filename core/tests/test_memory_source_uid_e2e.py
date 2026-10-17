"""FIND-5 end-to-end: the durable user row's UID survives write -> read -> SourceRef.

Runs against a real SessionDB in a temp dir (no kernel stream needed): a turn is
appended exactly the way ``AtlasKernel.run`` appends it, read back exactly the way
the kernel reads it, and the resulting identity is fed to the memory library.
Two turns of the same text must produce two different SourceRefs.
"""

import asyncio
import tempfile
from pathlib import Path

import pytest

from atlas.engine.session_sync import append_session_message, read_session_model_messages
from atlas.memory.library import MemoryLibrary
from atlas.memory.library.source_ref import SourceRef

SESSION = "session-find5-e2e"


@pytest.fixture()
def home(tmp_path):
    return tmp_path / "engine"


def _append_turn(home, text):
    """Mirror AtlasKernel.run: one durable user row per turn, uid kept."""
    return append_session_message(home, SESSION, "user", text, {"kernel_run_id": "r1"})


def _adopt_from_transcript(home, text):
    """Mirror the kernel's recovery branch: read rows, take the newest matching uid."""
    rows = read_session_model_messages(home, SESSION)
    pending_user = bool(rows) and rows[-1].get("role") == "user" \
        and str(rows[-1].get("content") or "") == text
    assert pending_user, "the transcript must end with this turn's user row"
    return next((
        str(row.get("message_uid") or "") for row in reversed(rows)
        if row.get("role") == "user" and row.get("message_uid")
        and str(row.get("content") or "") == text
    ), "")


def test_repeated_text_gets_distinct_durable_uids(home):
    first_uid = _append_turn(home, "继续")
    second_uid = _append_turn(home, "继续")

    assert first_uid, "append_session_message must return the durable uid"
    assert second_uid, "append_session_message must return the durable uid"
    assert first_uid != second_uid, "two turns must be two distinct SessionDB rows"

    rows = read_session_model_messages(home, SESSION)
    assert [r.get("message_uid") for r in rows if r.get("role") == "user"] == [
        first_uid, second_uid,
    ], "the transcript must expose both rows' identities in order"


def test_recovery_branch_returns_the_trailing_turns_uid(home):
    first_uid = _append_turn(home, "继续")
    second_uid = _append_turn(home, "继续")

    recovered = _adopt_from_transcript(home, "继续")
    assert recovered == second_uid, \
        "recovery must adopt the current turn's row, not the earlier identical one"
    assert recovered != first_uid


def test_library_stores_the_real_uid_after_write_read(home, tmp_path, monkeypatch):
    first_uid = _append_turn(home, "继续")
    second_uid = _append_turn(home, "继续")

    # ``_source_ref_for_turn`` resolves the session store from ``atlas.config.DATA_ROOT``
    # as ``DATA_ROOT / "engine"``; ``home`` IS that engine dir, so point DATA_ROOT at
    # its parent and the real SessionDB lookup runs unpatched.
    import atlas.config as atlas_config

    monkeypatch.setattr(atlas_config, "DATA_ROOT", home.parent, raising=False)

    library = MemoryLibrary(tmp_path / "library")
    monkeypatch.setattr(library.index, "_schedule_embeddings", lambda: None)
    monkeypatch.setattr(library, "_write_diary", lambda *args: None)

    async def run(uid):
        library.schedule_turn(
            user_text="继续", assistant_text="收到", session=SESSION,
            model_mgr=None, message_uid=uid,
        )
        await asyncio.gather(*library._tasks)
        return library.queue.pending()

    first_rows = asyncio.run(run(first_uid))
    second_rows = asyncio.run(run(second_uid))

    assert first_rows[0]["source_ref"] == SourceRef(SESSION, first_uid).to_ref()
    assert second_rows[-1]["source_ref"] == SourceRef(SESSION, second_uid).to_ref()
    assert first_rows[0]["source_ref"] != second_rows[-1]["source_ref"]


def test_missing_uid_is_recorded_as_missing_not_guessed(home, tmp_path, monkeypatch):
    _append_turn(home, "继续")

    import atlas.config as atlas_config

    monkeypatch.setattr(atlas_config, "DATA_ROOT", home.parent, raising=False)

    library = MemoryLibrary(tmp_path / "library2")
    monkeypatch.setattr(library.index, "_schedule_embeddings", lambda: None)
    monkeypatch.setattr(library, "_write_diary", lambda *args: None)

    async def run():
        library.schedule_turn(
            user_text="继续", assistant_text="收到", session=SESSION,
            model_mgr=None, message_uid="",
        )
        await asyncio.gather(*library._tasks)
        return library.queue.pending()

    rows = asyncio.run(run())
    assert rows[0]["source_precision"] == "missing"
    assert rows[0]["source_ref"] == ""

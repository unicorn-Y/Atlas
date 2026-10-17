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


def _adopt_from_transcript(home, text, run_id, request_uid=""):
    """Mirror the kernel's adoption branch: ask the real helper, never a text scan."""
    from atlas.kernel.loop import _reusable_user_uid

    rows = read_session_model_messages(home, SESSION)
    history = [{"role": r.get("role"), "content": r.get("content"),
                "message_uid": r.get("message_uid"),
                "display_metadata": r.get("display_metadata")} for r in rows]
    return _reusable_user_uid(history, text, run_id, request_uid)


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

    # Both rows were written under kernel_run_id "r1"; a run resuming as "r1" may adopt the
    # trailing row (its own pre-write), and gets the newest identity, not the earlier one.
    recovered = _adopt_from_transcript(home, "继续", "r1")
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


# --- BLOCK-4: an interrupted turn's leftover user row must never be adopted ---------


def test_interrupted_turn_does_not_donate_its_uid_to_the_next_turn(home, tmp_path, monkeypatch):
    """Turn A dies after its user row is durable; turn B repeats the text in a new run.

    BLOCK-4: the old rule (trailing role+text match, then a reverse scan for any user row
    with equal text) adopted A's uid for B, so B's memories were stamped with A's message
    identity. Runs against a real SessionDB.
    """
    from atlas.kernel.loop import _reusable_user_uid

    interrupted_uid = append_session_message(
        home, SESSION, "user", "继续", {"kernel_run_id": "run-A"},
    )
    # Turn A never produced an assistant row: the transcript still ends with its user row,
    # exactly like a turn that failed during generation.
    rows = read_session_model_messages(home, SESSION)
    history = [{"role": r.get("role"), "content": r.get("content"),
                "message_uid": r.get("message_uid"),
                "display_metadata": r.get("display_metadata")} for r in rows]
    assert history[-1]["role"] == "user" and history[-1]["content"] == "继续"

    adopted = _reusable_user_uid(history, "继续", "run-B")
    assert adopted == "", "turn B must not inherit the interrupted turn's uid"

    new_uid = append_session_message(home, SESSION, "user", "继续", {"kernel_run_id": "run-B"})
    assert new_uid and new_uid != interrupted_uid
    after = read_session_model_messages(home, SESSION)
    user_uids = [r.get("message_uid") for r in after if r.get("role") == "user"]
    assert user_uids == [interrupted_uid, new_uid], "turn B must own a durable row of its own"
    assert after[-1].get("message_uid") == new_uid

    # And the memory library, fed B's real uid, must store B's identity — not A's.
    import atlas.config as atlas_config

    monkeypatch.setattr(atlas_config, "DATA_ROOT", home.parent, raising=False)
    library = MemoryLibrary(tmp_path / "library-b")
    monkeypatch.setattr(library.index, "_schedule_embeddings", lambda: None)
    monkeypatch.setattr(library, "_write_diary", lambda *args: None)

    async def run():
        library.schedule_turn(
            user_text="继续", assistant_text="收到", session=SESSION,
            model_mgr=None, message_uid=new_uid,
        )
        await asyncio.gather(*library._tasks)
        return library.queue.pending()

    stored = asyncio.run(run())
    assert stored[0]["source_precision"] == "exact"
    assert stored[0]["source_ref"] == SourceRef(SESSION, new_uid).to_ref()
    assert stored[0]["source_ref"] != SourceRef(SESSION, interrupted_uid).to_ref()


def test_current_run_row_is_still_reused(home):
    """The pre-written-current-turn path must keep working when ownership is proven."""
    from atlas.kernel.loop import _reusable_user_uid

    uid = append_session_message(home, SESSION, "user", "继续", {"kernel_run_id": "run-C"})
    rows = read_session_model_messages(home, SESSION)
    history = [{"role": r.get("role"), "content": r.get("content"),
                "message_uid": r.get("message_uid"),
                "display_metadata": r.get("display_metadata")} for r in rows]

    assert _reusable_user_uid(history, "继续", "run-C") == uid, \
        "a row carrying this run's kernel_run_id is provably ours"
    assert _reusable_user_uid(history, "继续", "run-D", request_uid=uid) == uid, \
        "an explicitly supplied uid is provable ownership too"
    assert _reusable_user_uid(history, "别的文本", "run-C") == "", \
        "text mismatch is still a new turn"


"""FIND-5: a turn's SourceRef must ride the durable message UID, never a text guess.

The kernel mints the user row for the turn; these tests pin both halves of that
contract: the identity travels out on ``hermes.result``, and the library stores
exactly that identity (or ``missing`` when there is none) instead of attaching a
repeated phrase like "继续" to whichever user row happens to be newest.
"""

import asyncio
import inspect

import pytest

from atlas.memory.library import MemoryLibrary
from atlas.memory.library.source_ref import SourceRef

SESSION = "session-find5"


def _run_schedule(library, user_text, message_uid):
    async def run():
        library.schedule_turn(
            user_text=user_text,
            assistant_text="收到",
            session=SESSION,
            model_mgr=None,
            message_uid=message_uid,
        )
        await asyncio.gather(*library._tasks)
        return library.queue.pending()

    return asyncio.run(run())


def _library(tmp_path, monkeypatch):
    library = MemoryLibrary(tmp_path)
    monkeypatch.setattr(library.index, "_schedule_embeddings", lambda: None)
    monkeypatch.setattr(library, "_write_diary", lambda *args: None)
    return library


@pytest.mark.parametrize(
    ("message_uid", "expected_precision"),
    [("turn-1", "exact"), ("turn-2", "exact"), ("", "missing"), ("not-in-sessiondb", "missing")],
)
def test_repeated_user_text_keeps_the_supplied_uid(
    tmp_path, monkeypatch, message_uid, expected_precision,
):
    """Two turns of the same text must not collapse onto one SourceRef."""
    library = _library(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "atlas.engine.session_sync.session_message_evidence",
        lambda _home, _session, uid: (
            {"message_uid": uid, "role": "user"} if uid in {"turn-1", "turn-2"} else None
        ),
    )

    rows = _run_schedule(library, "继续", message_uid)

    assert len(rows) == 1
    assert rows[0]["user_text"] == "继续"
    assert rows[0]["source_precision"] == expected_precision
    if expected_precision == "exact":
        assert rows[0]["source_ref"] == SourceRef(SESSION, message_uid).to_ref()
    else:
        assert rows[0]["source_ref"] == ""


def test_same_text_successive_turns_store_distinct_refs(tmp_path, monkeypatch):
    library = _library(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "atlas.engine.session_sync.session_message_evidence",
        lambda _home, _session, uid: (
            {"message_uid": uid, "role": "user"} if uid in {"turn-1", "turn-2"} else None
        ),
    )

    first = _run_schedule(library, "继续", "turn-1")
    second = _run_schedule(library, "继续", "turn-2")

    # ``pending()`` reports the whole undrained queue, so the second call returns
    # the first turn's row too; the new row is the tail.
    assert len(second) == len(first) + 1
    assert first[-1]["source_ref"] == SourceRef(SESSION, "turn-1").to_ref()
    assert second[-1]["source_ref"] == SourceRef(SESSION, "turn-2").to_ref()
    assert first[-1]["source_ref"] != second[-1]["source_ref"]


def test_kernel_result_carries_the_minted_user_message_uid():
    """The kernel must hand the turn's durable id to the finalizer, which must use it."""
    from atlas.agent.run_phases import _schedule_library_write
    from atlas.kernel.loop import AtlasKernel, KernelRequest

    assert "message_uid" in inspect.getsource(KernelRequest), \
        "KernelRequest must carry the turn's user message uid"

    kernel_source = inspect.getsource(AtlasKernel.run)
    assert "user_message_uid = await persist_async(" in kernel_source, \
        "the kernel must keep the uid returned by the durable user-row insert"
    assert '"user_message_uid": user_message_uid' in kernel_source, \
        "the kernel must report the uid on hermes.result"

    assert "message_uid=state.request.message_uid" in inspect.getsource(_schedule_library_write), \
        "the library write must receive the turn's uid, not derive it from text"


def test_finalizer_receives_the_uid_from_the_kernel_result(monkeypatch):
    """A kernel-reported uid reaches schedule_turn unchanged."""
    from atlas.agent import run_phases

    captured = {}

    class Library:
        def schedule_turn(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("atlas.memory.library.get_library", lambda: Library())

    state = run_phases._RunState(
        request=run_phases.RunRequest(message="继续", conversation_id=SESSION),
        callbacks=None,
        message="继续",
    )
    state.runtime = type("Runtime", (), {"verification_passed": False})()
    state.request.message_uid = "turn-2"

    run_phases._schedule_library_write(None, state, "收到")

    assert captured["message_uid"] == "turn-2"
    assert captured["session"] == SESSION

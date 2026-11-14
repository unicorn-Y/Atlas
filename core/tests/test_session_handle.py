"""SessionHandle lifecycle (DSH S5 parity): read/append/flush/close + single writer."""
from __future__ import annotations

import asyncio
import os
import time

import pytest

from atlas.engine.session_handle import (
    SessionHandle,
    SessionHandleUnavailable,
    acquire_run_turn_lease,
    hold_turn_lease,
    open_session_handle,
    release_run_turn_lease,
    turn_lease_holder,
)
from atlas.engine.session_sync import read_session_model_messages
from atlas.engine.state.atlas_state import SessionDB
from atlas.engine.state.atlas_state_errors import SessionTurnLeaseLostError
from atlas.engine.state.atlas_state_pidns import holder_namespace_token

pytestmark = pytest.mark.unit


def _owner(tag: str) -> str:
    return f"pid={os.getpid()}{holder_namespace_token()}:test={tag}"


def test_handle_lifecycle_read_append_flush_close(tmp_path):
    with open_session_handle(tmp_path, "s", _owner("lifecycle")) as handle:
        handle.append_message("user", "handle written")
        seq = handle.append_event("probe/lifecycle", {"marker": "S5"})
        assert handle.flush() is True
        events = handle.read_events()
        assert [event["event_type"] for event in events][-1] == "probe/lifecycle"
        assert events[-1]["payload"]["marker"] == "S5"
        assert seq > 0
        messages = read_session_model_messages(tmp_path, "s")
        assert messages[-1]["content"] == "handle written"
    # close released the lease: a successor admits immediately
    with open_session_handle(tmp_path, "s", _owner("successor")) as second:
        assert second.lease_expires_at() is not None


def test_handle_open_fails_closed_while_elsewhere_holds(tmp_path):
    with SessionDB(db_path=tmp_path / "state.db") as db:
        db.ensure_session("s", "api_server")
        first = SessionHandle.open(db, "s", _owner("first"))
        with pytest.raises(SessionHandleUnavailable):
            SessionHandle.open(db, "s", _owner("second"))
        assert SessionHandle.acquire(db, "s", _owner("second")) is None
        first.close()
        successor = SessionHandle.acquire(db, "s", _owner("second"))
        assert successor is not None
        successor.close()


def test_fenced_append_refuses_after_lease_lost(tmp_path):
    with SessionDB(db_path=tmp_path / "state.db") as db:
        db.ensure_session("s", "api_server")
        handle = SessionHandle.open(db, "s", _owner("writer"))
        handle.append_message("user", "while owned")
        # Simulate losing the lease without going through the handle.
        db._write_sql("DELETE FROM session_turn_leases WHERE conversation_id = ?", ("s",))
        with pytest.raises(SessionTurnLeaseLostError):
            handle.append_message("user", "must be refused")
        with pytest.raises(SessionTurnLeaseLostError):
            db.append_message("s", "user", content="unfenced writer also refused", turn_lease_holder=_owner("writer"))
        handle.close()


def test_live_owner_retains_expired_lease_and_refresh(tmp_path):
    holder = _owner("live")
    with SessionDB(db_path=tmp_path / "state.db") as db:
        db.ensure_session("s", "api_server")
        handle = SessionHandle.open(db, "s", holder, ttl_seconds=300.0)
        # A stalled heartbeat must not hand the lease to a contender while the
        # owner process is verifiably alive: force the stamp into the past.
        db._write_sql("UPDATE session_turn_leases SET expires_at = ?", (time.time() - 100_000,))
        assert db.try_acquire_session_turn_lease("s", _owner("contender")) is False
        assert handle.refresh() is True
        assert handle.lease_expires_at() > time.time()
        handle.close()
        assert db.try_acquire_session_turn_lease("s", _owner("contender")) is True


def test_turn_lease_holder_is_pid_checkable():
    holder = turn_lease_holder("run-xyz")
    assert holder.startswith(f"pid={os.getpid()}")
    assert ":run=run-xyz" in holder


def test_acquire_run_turn_lease_holds_and_releases(tmp_path):
    handle = acquire_run_turn_lease("conv-lease", "run-1", home=tmp_path / "engine")
    assert handle is not None
    with SessionDB(db_path=tmp_path / "engine" / "state.db") as db:
        db.ensure_session("conv-lease", "api_server")
        assert db.try_acquire_session_turn_lease("conv-lease", _owner("other")) is False
    release_run_turn_lease(handle)
    with SessionDB(db_path=tmp_path / "engine" / "state.db") as db:
        assert db.try_acquire_session_turn_lease("conv-lease", _owner("other")) is True


def test_acquire_run_turn_lease_fail_open_without_conversation(tmp_path):
    assert acquire_run_turn_lease("", "run-1", home=tmp_path / "engine") is None


class _Request:
    def __init__(self, conversation_id: str, *, ephemeral: bool = False):
        self.conversation_id = conversation_id
        self.run_id = "run-lease-1"
        self.ephemeral = ephemeral


@pytest.mark.asyncio
async def test_hold_turn_lease_holds_for_run_and_releases(tmp_path, monkeypatch):
    import atlas.config as config

    monkeypatch.setattr(config, "DATA_ROOT", tmp_path)
    async with hold_turn_lease(_Request("conv-run"), ttl_seconds=300.0) as handle:
        assert handle is not None
        with SessionDB(db_path=config.DATA_ROOT / "engine" / "state.db") as db:
            db.ensure_session("conv-run", "api_server")
            assert db.try_acquire_session_turn_lease("conv-run", _owner("contender")) is False
    with SessionDB(db_path=config.DATA_ROOT / "engine" / "state.db") as db:
        assert db.session_turn_lease_expires_at("conv-run", handle.holder) is None


@pytest.mark.asyncio
async def test_hold_turn_lease_skips_ephemeral_and_empty(tmp_path, monkeypatch):
    from atlas.config import DATA_ROOT

    monkeypatch.setattr("atlas.config.DATA_ROOT", tmp_path)
    async with hold_turn_lease(_Request("", ephemeral=True)) as handle:
        assert handle is None


@pytest.mark.asyncio
async def test_hold_turn_lease_refreshes_across_long_holds(tmp_path, monkeypatch):
    from atlas.config import DATA_ROOT

    monkeypatch.setattr("atlas.config.DATA_ROOT", tmp_path)
    async with hold_turn_lease(_Request("conv-refresh"), ttl_seconds=1.0,
                               refresh_interval=0.05) as handle:
        assert handle is not None
        first = handle.lease_expires_at()
        await asyncio.sleep(0.25)
        second = handle.lease_expires_at()
        assert second is not None and first is not None
        assert second >= first  # refresher kept extending the stamp

from __future__ import annotations

import base64
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from atlas.engine.session_sync import (
    SessionAttachmentIntegrityError,
    append_session_event,
    append_session_message,
    get_file_observation,
    persist_session_attachments,
    read_session_events,
    read_session_model_messages,
    record_file_observation,
)
from atlas.engine.state.atlas_state import SessionDB
from atlas.tools.local_execution import LocalExecutionRuntime
from atlas.engine.kernel.loop import AtlasKernel, KernelRequest


pytestmark = pytest.mark.unit


def _session(home, session_id: str) -> None:
    with SessionDB(db_path=home / "state.db") as db:
        db.ensure_session(session_id, "api_server")


def test_reader_persists_interrupted_closer_without_rewriting_transcript(tmp_path):
    home = tmp_path / "engine"
    home.mkdir()
    _session(home, "turn-session")
    append_session_event(home, "turn-session", "turn/start", {"turn_id": "turn-1"})

    first = read_session_events(home, "turn-session")
    second = read_session_events(home, "turn-session")

    assert first[-1]["event_type"] == "turn/end"
    assert first[-1]["payload"] == {
        "turn_id": "turn-1", "reason": "interrupted", "synthetic": True,
    }
    assert second[-1] == first[-1]
    with SessionDB(db_path=home / "state.db") as db:
        assert len(db.list_session_events("turn-session")) == 2
        assert db.get_messages("turn-session", limit=10) == []


def test_image_attachment_is_content_addressed_and_verified_on_read(tmp_path):
    home = tmp_path / "engine"
    home.mkdir()
    _session(home, "image-session")
    image = b"image bytes"
    url = "data:image/png;base64," + base64.b64encode(image).decode("ascii")
    stored = persist_session_attachments(home, "image-session", [
        {"type": "text", "text": "what is this?"},
        {"type": "image_url", "image_url": {"url": url}},
    ])
    ref = stored[1]["image_url"]["url"]
    assert ref == "atlas-attachment://" + hashlib.sha256(image).hexdigest()
    append_session_message(home, "image-session", "user", stored)

    assert read_session_model_messages(home, "image-session")[0]["content"][1]["image_url"]["url"] == url

    digest = ref.removeprefix("atlas-attachment://")
    blob = home / "attachments" / digest[:2] / digest
    blob.write_bytes(b"corrupt")
    with pytest.raises(SessionAttachmentIntegrityError, match="integrity"):
        read_session_model_messages(home, "image-session")


@pytest.mark.asyncio
async def test_kernel_fails_closed_when_session_attachment_integrity_fails(tmp_path, monkeypatch):
    home = tmp_path / "engine"
    home.mkdir()
    _session(home, "corrupt-image-session")

    def corrupt_history(*_args, **_kwargs):
        raise SessionAttachmentIntegrityError("durable image attachment failed integrity verification")

    monkeypatch.setattr("atlas.engine.session_sync.read_session_model_messages", corrupt_history)
    monkeypatch.setattr("atlas.run_checkpoints.require_checkpoint", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("atlas.logs.append_run_event", lambda *_args, **_kwargs: None)
    with SessionDB(db_path=home / "state.db") as db:
        original_messages = db.get_messages("corrupt-image-session")
    with SessionDB(db_path=home / "state.db") as db:
        original_messages = db.get_messages("corrupt-image-session")
    kernel = AtlasKernel(data_dir=tmp_path)
    kernel._run_hook = AsyncMock(return_value=None)
    request = KernelRequest(
        agent=SimpleNamespace(_model_mgr=SimpleNamespace(current_model="test-model")),
        runtime=SimpleNamespace(run_id="corrupt-image-run", model="test-model"),
        message="continue", conversation_id="corrupt-image-session",
    )

    events = [event async for event in kernel.run(request)]

    errors = [event for event in events if event.get("type") == "error"]
    assert errors
    assert errors[-1]["category"] == "invalid_history"
    assert "attachment failed integrity" in errors[-1]["detail"]
    with SessionDB(db_path=home / "state.db") as db:
        assert db.get_messages("corrupt-image-session") == original_messages
    with SessionDB(db_path=home / "state.db") as db:
        assert db.get_messages("corrupt-image-session") == original_messages


def test_file_observations_are_scoped_by_session_and_path(tmp_path):
    home = tmp_path / "engine"
    home.mkdir()
    _session(home, "session-a")
    token = {"exists": True, "sha256": "abc"}
    record_file_observation(home, "session-a", "C:/project/a.py", token)
    record_file_observation(home, "session-a", "C:/project/missing.py", {"exists": False})

    assert get_file_observation(home, "session-a", "C:/project/a.py") == token
    assert get_file_observation(home, "session-b", "C:/project/a.py") is None
    assert get_file_observation(home, "session-a", "C:/project/b.py") is None
    assert get_file_observation(home, "session-a", "C:/project/missing.py") == {"exists": False}


@pytest.mark.asyncio
async def test_local_edit_rejects_file_changed_since_session_read(tmp_path):
    target = tmp_path / "observed.py"
    target.write_text("before", encoding="utf-8")
    runtime = LocalExecutionRuntime()
    identity = {"_atlas_conversation_id": "observation-session"}

    read = await runtime.call_tool("local_file", {
        **identity, "action": "read", "path": str(target),
    })
    assert read["data"]["content"] == "before"
    target.write_text("changed externally", encoding="utf-8")
    restarted_runtime = LocalExecutionRuntime()
    edited = await restarted_runtime.call_tool("local_edit", {
        **identity, "path": str(target), "old_string": "changed externally",
        "new_string": "overwritten",
    })

    assert edited["is_error"] is True
    assert "changed since this session observed it" in edited["data"]["error"]
    assert target.read_text(encoding="utf-8") == "changed externally"

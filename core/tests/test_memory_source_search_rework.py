from atlas import config
from atlas.memory.library import _source_ref_for_turn
from atlas.memory.library.source_ref import SourceRef
from atlas.memory.library import sources


def test_source_ref_uses_supplied_uid_for_repeated_text_and_never_guesses(monkeypatch, tmp_path):
    def evidence(home, session, uid):
        assert home == config.DATA_ROOT / "engine"
        assert session == "session"
        return {"message_uid": uid, "role": "user"} if uid in {"turn-1", "turn-2"} else None

    monkeypatch.setattr(config, "DATA_ROOT", tmp_path)
    monkeypatch.setattr("atlas.engine.session_sync.session_message_evidence", evidence)
    assert _source_ref_for_turn("session", "相同原话", "turn-1") == SourceRef("session", "turn-1").to_ref()
    assert _source_ref_for_turn("session", "相同原话", "turn-2") == SourceRef("session", "turn-2").to_ref()
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

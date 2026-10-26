from __future__ import annotations

import asyncio

from atlas.api import conversations_router


def test_session_labels_and_unread_are_queryable_in_sqlite(tmp_path, monkeypatch):
    from atlas import config

    monkeypatch.setattr(config, "DATA_ROOT", tmp_path)
    metadata = {
        "atlas.sidebar.labels": {"c-1": ["custom-blue", "urgent"], "c-2": ["urgent"]},
        "atlas.sidebar.label-definitions": [
            {"id": "custom-blue", "name": "蓝色自定义", "color": "#123456"},
            {"id": "urgent", "name": "紧急", "color": "#ff0000"},
        ],
        "atlas.sidebar.unread": ["c-1"],
        "atlas.sidebar.order": ["c-2", "c-1"],
        "atlas.sidebar.custom-groups": [{"id": "g1", "name": "项目一"}],
        "atlas.sidebar.custom-members": {"c-1": "g1"},
    }
    conversations_router._write_ui_metadata(metadata)

    restored, sessions = conversations_router._read_ui_metadata()
    assert restored == metadata
    assert sessions["c-1"] == {"labels": ["custom-blue", "urgent"], "unread": True}
    assert sessions["c-2"] == {"labels": ["urgent"], "unread": False}

    result = asyncio.run(conversations_router.query_conversation_metadata(label="urgent", unread=True))
    assert result == {"conversations": {"c-1": {"labels": ["custom-blue", "urgent"], "unread": True}}, "count": 1}

    conversations_router._write_ui_metadata({**metadata, "atlas.sidebar.labels": {"c-2": ["urgent"]}, "atlas.sidebar.unread": []})
    _restored, sessions = conversations_router._read_ui_metadata()
    assert sessions["c-1"] == {"labels": [], "unread": False}

from __future__ import annotations

import asyncio
import pytest

from atlas.api.app_services import AppServices
from atlas.api import shares_router
from atlas.api.shares_router import ImportShareRequest
from atlas.sharing import ConversationShareStore, shared_page_html


def test_hosted_share_password_retention_revoke_and_import_deep_link(tmp_path):
    store = ConversationShareStore(tmp_path / "shares.db")
    created = store.create(conversation_id="conversation-1", title="检查报告", base_url="https://atlas.example/proxy",
                          messages=[{"role": "user", "content": "请检查", "created_at": "2026-10-25T10:00:00Z"}],
                          password="tea&coffee", retention_days=7)
    token = created["url"].rsplit("/", 1)[-1]
    assert created["password_protected"] and created["url"].startswith("https://atlas.example/proxy/api/shared/")
    assert store.read(token, allow_locked=True)["messages"] == []
    with pytest.raises(PermissionError):
        store.read(token, "wrong")
    share = store.read(token, "tea&coffee")
    assert share and share["messages"][0]["content"] == "请检查"
    page = shared_page_html(created["url"], {**share, "token": token})
    assert 'type="password"' in page and f"atlas://share/{token}" in page and "只读分享" in page
    assert store.revoke(created["id"])
    assert store.read(token, "tea&coffee") is None


def test_import_share_fetches_snapshot_and_creates_separate_local_transcript(monkeypatch):
    imported: list[tuple[str, str, dict]] = []
    transcript_rows: list[dict] = []

    class Memory:
        async def create_conversation(self, title):
            imported.append(("conversation", title, {})); return "new-local-id"
        async def update_conversation(self, conversation_id, **kwargs):
            imported.append((conversation_id, "metadata", kwargs))

    class Response:
        status_code = 200
        def json(self):
            return {"title": "共有记录", "messages": [
                {"role": "user", "content": "问题"}, {"role": "assistant", "content": "答案"},
            ]}

    class Client:
        def __init__(self, **_kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): return None
        async def post(self, url, *, json):
            assert url == "https://atlas.example/api/shared/abcdefghijklmnopqrstuvwxyz123456/export"
            assert json == {"password": ""}
            return Response()

    monkeypatch.setattr(shares_router.httpx, "AsyncClient", Client)
    from atlas.engine import session_sync
    monkeypatch.setattr(session_sync, "append_session_messages", lambda _home, _id, rows: transcript_rows.extend(rows))
    result = asyncio.run(shares_router.import_shared_conversation(
        ImportShareRequest(share_url="https://atlas.example/api/shared/abcdefghijklmnopqrstuvwxyz123456"),
        AppServices(memory=Memory()),
    ))
    assert result == {"conversation_id": "new-local-id", "title": "分享：共有记录", "messages": 2}
    assert imported[0] == ("conversation", "分享：共有记录", {})
    assert [row["content"] for row in transcript_rows] == ["问题", "答案"]
    assert all(row["display_metadata"]["imported_from_share"] for row in transcript_rows)

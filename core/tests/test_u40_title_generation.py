from __future__ import annotations

import asyncio
from types import SimpleNamespace

from atlas.api import conversations_router


def test_title_proposal_uses_first_user_goal_and_does_not_save(tmp_path, monkeypatch):
    from atlas import config
    from atlas.engine import session_sync

    monkeypatch.setattr(config, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(session_sync, "read_session_all_messages", lambda *_: [
        {"role": "user", "content": "请整理我的项目并补上测试，API key=super-secret-value"},
        {"role": "assistant", "content": "后续对话不应被用作标题目标。"},
    ])
    conversation = {"id": "c-1", "title": "原有标题"}
    captured = {}

    class Memory:
        async def get_conversation(self, conversation_id):
            return conversation if conversation_id == "c-1" else None

    class Router:
        async def resolve(self, model, purpose):
            captured["route"] = (model, purpose)
            return object()

        async def complete(self, _route, **kwargs):
            captured["messages"] = kwargs["messages"]
            return SimpleNamespace(text='"整理项目并补齐测试"')

    services = SimpleNamespace(memory=Memory(), model_mgr=SimpleNamespace(
        current_model="test-model", model_router=Router(),
    ))
    result = asyncio.run(conversations_router.suggest_conversation_title(services, "c-1"))
    assert result == {"conversation_id": "c-1", "title": "整理项目并补齐测试", "model": "test-model"}
    assert captured["route"] == ("test-model", "prompt_enhance")
    prompt = captured["messages"][1]["content"]
    assert "补上测试" in prompt
    assert "super-secret-value" not in prompt
    assert conversation["title"] == "原有标题"

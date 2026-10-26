"""Interface level checks for Atlas U4 features. Requires ATLAS_ROOT and a configured model key."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from atlas.api import u4_router
from atlas.api.conversations_router import get_conversation_stats
from atlas.agent.tool_catalog import model_facing_tools
from atlas.usage_pricing import estimate_cost


def check_price_matching() -> None:
    assert estimate_cost(
        "openai/deepseek-v4.1-flash", input_tokens=1_000_000, output_tokens=0,
    ) is not None
    assert estimate_cost(
        "custom-route", native_model="deepseek-v4.1-flash",
        input_tokens=1_000_000, output_tokens=0,
    ) is not None


def check_chatgpt_import_sample() -> None:
    sample = [{"title": "小样例", "mapping": {
        "u": {"id": "u", "message": {"author": {"role": "user"}, "create_time": 1, "content": {"parts": ["你好"]}}},
        "a": {"id": "a", "message": {"author": {"role": "assistant"}, "create_time": 2, "content": {"parts": ["你好！"]}}},
    }}]
    converted = u4_router.normalize_chatgpt_conversations(sample)
    assert converted[0]["messages"] == [
        {"role": "user", "content": "你好"}, {"role": "assistant", "content": "你好！"},
    ]


def check_tool_catalog() -> None:
    agent = SimpleNamespace(
        _mcp=None, _custom_tools=None, _local_execution=None, _computer_use=None,
        _web=None, _projects=None, _skills=None, _memory=None, _delegation=None,
    )
    names = {item["function"]["name"] for item in model_facing_tools(agent)}
    assert {"propose_settings_change", "ask_advisor"}.issubset(names)


async def check_service_contracts() -> None:
    with tempfile.TemporaryDirectory(prefix="atlas-u4-check-") as temp:
        root = Path(temp)
        with patch.object(u4_router, "_path", return_value=root / "u4.json"):
            model_mgr = SimpleNamespace(selected="", select=lambda value: setattr(model_mgr, "selected", value))
            services = SimpleNamespace(model_mgr=model_mgr, usage_ledger=None)
            proposal = u4_router.create_settings_proposal(
                key="model", old_value="old", new_value="deepseek-v4.1-flash", reason="check",
            )
            resolved = await u4_router.resolve_proposal(proposal["id"], {"approve": True}, services)
            assert resolved["status"] == "approved" and model_mgr.selected == "deepseek-v4.1-flash"

            saved = await u4_router.save_preset({"label": "u4-check", "env": {"U4_CHECK": "1"}}, services)
            loaded = await u4_router.get_presets(services)
            assert any(item["id"] == saved["id"] for item in loaded["presets"])
            await u4_router.delete_preset(saved["id"], services)

            imported_memory = SimpleNamespace(create_conversation=lambda title: asyncio.sleep(0, result=f"id-{title}"))
            with patch("atlas.config.DATA_ROOT", root), patch("atlas.engine.session_sync.append_session_message") as append:
                imported = await u4_router.import_chatgpt({"conversations": [{
                    "title": "小样例", "mapping": {
                        "u": {"id": "u", "message": {"author": {"role": "user"}, "create_time": 1, "content": {"parts": ["你好"]}}},
                        "a": {"id": "a", "message": {"author": {"role": "assistant"}, "create_time": 2, "content": {"parts": ["你好！"]}}},
                    },
                }]}, SimpleNamespace(memory=imported_memory))
            assert imported["imported"] == 1 and append.call_count == 2

            report_services = SimpleNamespace(
                usage_ledger=None,
                memory=SimpleNamespace(
                    list_conversations=lambda limit=None: asyncio.sleep(0, result=[]),
                ),
            )
            with patch("atlas.config.DATA_ROOT", root):
                report = await u4_router.get_insights(report_services, 7)
            assert "使用习惯报告" in report["markdown"] and (root / report["path"]).is_file()

            memory = SimpleNamespace(get_conversation=lambda _id: asyncio.sleep(0, result={"id": _id}))
            ledger = SimpleNamespace(query=lambda **_kwargs: asyncio.sleep(0, result={"rows": [{
                "key": "u4-check-conversation", "runs": 2, "input_tokens": 40,
                "output_tokens": 12, "cached_input_tokens": 10,
                "cache_hit_rate": 0.25, "est_cost": 0.00002,
            }]}))
            stats_services = SimpleNamespace(memory=memory, usage_ledger=ledger)
            with patch("atlas.engine.session_sync.read_session_all_messages", return_value=[
                {"role": "user", "created_at": "2026-10-24T10:00:00+00:00"},
                {"role": "assistant", "created_at": "2026-10-24T10:03:00+00:00"},
            ]), patch("atlas.config.DATA_ROOT", root):
                stats = await get_conversation_stats(stats_services, "u4-check-conversation")
            assert stats["input_tokens"] == 40 and stats["est_cost"] == 0.00002

    assert u4_router.push_event_enabled({"mobile_push": {
        "enabled": True, "events": {"completion": True, "approval": False},
    }}, "completion")
    assert not u4_router.push_event_enabled({"mobile_push": {
        "enabled": True, "events": {"completion": True, "approval": False},
    }}, "approval")


async def check_live_advisor() -> None:
    from atlas.models import ModelManager
    from real_model_check import AttemptResult, retry_real_model_check_async

    router = ModelManager().model_router

    async def attempt(prompt: str, attempt_number: int) -> AttemptResult:
        del attempt_number
        response = await router.complete_for(
            "deepseek-v4.1-flash", "advisor", [{"role": "user", "content": prompt}],
            max_tokens=40, temperature=0,
        )
        answer = str(response.text or "")
        return AttemptResult(bool(answer.strip()), answer=answer, detail="advisor returned an empty answer")

    await retry_real_model_check_async(
        "U4 advisor route", "Reply with exactly: U4 advisor reachable", attempt,
    )


async def main() -> None:
    check_price_matching()
    check_chatgpt_import_sample()
    check_tool_catalog()
    await check_service_contracts()
    await check_live_advisor()
    print("U4 CHECK PASS")


if __name__ == "__main__":
    asyncio.run(main())

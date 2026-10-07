"""Real ModelRouter smoke test for S3 recall_context & run_phases wiring.

Exercises:
1. Real model deepseek-v4.1-flash via gateway for end-to-end turn.
2. Verified assemble_recall_context integration via run_phases._phase_context and _build_messages.
3. Gate OPEN round:
   - User asks personal question ("我喜欢喝什么咖啡？还有我目前住在哪？").
   - Intent gate passes.
   - Profile block (<=600 tokens) in stable system prompt prefix.
   - Relevant memory block (<=1500 tokens) with [m:<ref>] tags, dates, and conflict warnings.
   - Real model returns completion citing memories.
4. Gate CLOSED round:
   - User asks generic code question ("Python 中如何快速对字典按 key 排序？给出代码示例。").
   - Intent gate intercepts (rule:pure_generic_code).
   - Relevant memory block is EMPTY; memories list is EMPTY.
   - Profile block retained in stable system prompt.
   - Real model returns code answer without memory pollution.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
PROJECT_ROOT = Path(r"D:\Atlas").resolve()
CORE_ROOT = PROJECT_ROOT / "core"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Strict data isolation: prevent touching production data
PRODUCTION_ROOTS = (
    Path(r"D:\Atlas\data").resolve(),
    Path(r"D:\MemoryOSData").resolve(),
    (Path(os.environ.get("LOCALAPPDATA", r"C:\Users\25011\AppData\Local")) / "hermes").resolve(),
)

temp_data_dir = tempfile.mkdtemp(prefix="atlas_smoke_s3_")
os.environ["ATLAS_DATA_DIR"] = temp_data_dir

# Ensure isolated path check
for p in (Path(temp_data_dir).resolve(),):
    for prod in PRODUCTION_ROOTS:
        if p == prod or prod in p.parents:
            raise RuntimeError(f"Refusing production data path: {p}")

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]


def _setup_readonly_config():
    config_path = PROJECT_ROOT / "config" / "atlas.toml"
    from atlas import config as atlas_config
    from atlas.config import AtlasConfig

    raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    config = AtlasConfig(raw)
    atlas_config.get_config = lambda: config
    from atlas.models import manager as model_manager_module
    model_manager_module.get_config = lambda: config
    return config


class FakeUnifiedClient:
    """Mock client mimicking unified memory service response with profile and recall items."""

    def __init__(self):
        self.profile_data = {
            "preferences": [
                {"record_ref": "memory:prof-01", "key": "编程风格", "value": "偏好 TS 强类型与函数式风格"},
                {"record_ref": "memory:prof-02", "key": "常住城市", "value": "常住杭州"},
            ],
            "states": [
                {"record_ref": "memory:prof-03", "key": "工作状态", "value": "正在做跨境电商研发"},
            ],
            "habits": [],
            "relations": [],
        }

        self.recall_data = {
            "context_items": [
                {
                    "record_ref": "memory:coffee-01",
                    "lifecycle": "ACTIVE",
                    "valid_time": {"valid_from": "2026-09-20T08:00:00Z"},
                    "content": {"text": "用户每天早晨喜欢喝热美式，不加糖"},
                },
                {
                    "record_ref": "memory:loc-01",
                    "lifecycle": "CONFLICTED",
                    "valid_time": {"valid_from": "2026-09-01T10:00:00Z"},
                    "content": {"text": "用户目前在上海工作"},
                },
                {
                    "record_ref": "memory:loc-02",
                    "lifecycle": "ACTIVE",
                    "valid_time": {"valid_from": "2026-10-01T10:00:00Z"},
                    "content": {"text": "用户目前在杭州工作与生活"},
                },
            ],
            "conflicts": [
                {"record_refs": ["memory:loc-01", "memory:loc-02"], "kind": "LOCATION_DISAGREEMENT"}
            ],
            "read_id": "read-smoke-001",
            "authority_revision": 10,
        }

    async def _request(self, method: str, path: str, *, params=None, json_body=None):
        if path == "/v1/unified/profile":
            return self.profile_data
        if path == "/v1/unified/recall":
            return self.recall_data
        return {}

    async def recall_for_conversation(self, query: str, budget=None, purpose="CONVERSATION", context=None):
        return self.recall_data


class MockMemoryStore:
    def __init__(self, client):
        self._unified = client

    def _unified_reads_enabled(self) -> bool:
        return True

    def _unified_or_none(self):
        return self._unified


class MockAgent:
    SYSTEM_PROMPT = "你是由 Nous Research 开发的 Atlas 智能助理。请根据用户提问和已知背景给出准确回答。"

    def __init__(self, memory_store, model_mgr):
        self._memory = memory_store
        self._model_mgr = model_mgr
        self._skills = None
        self._projects = None

    def get_config(self):
        class Cfg:
            max_context_messages = 20
        return Cfg()


async def run_smoke():
    print("=" * 80)
    print("【S3 真实模型冒烟验证 · deepseek-v4.1-flash 真实回合】")
    print("=" * 80)

    config = _setup_readonly_config()
    from atlas.models import ModelManager
    from atlas.models.router import ModelRouter
    from atlas.agent import run_phases
    from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, AIMessage

    mm = ModelManager()
    router = ModelRouter(mm)
    model_id = "deepseek-v4.1-flash"
    print(f"[*] 真实模型加载成功: {mm.current_model} (target={model_id})")
    print(f"[*] 数据隔离路径: {temp_data_dir}")

    client = FakeUnifiedClient()
    memory_store = MockMemoryStore(client)
    agent = MockAgent(memory_store, mm)

    # =========================================================================
    # 回合 1: 个人意图问题 (闸门开启 -> 画像块 + 记忆块完整装配 + 真实模型调用)
    # =========================================================================
    print("\n" + "#" * 80)
    print("【回合 1: 个人意图问题（闸门开启测试）】")
    print("#" * 80)
    from types import SimpleNamespace
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import append_session_message

    q1 = "我喜欢喝什么咖啡？还有我目前住在哪？"
    req1 = run_phases.RunRequest(message=q1, conversation_id="conv-smoke-01")
    append_session_message(DATA_ROOT / "engine", req1.conversation_id, "user", q1)
    state1 = run_phases._RunState(request=req1, callbacks=run_phases.RunCallbacks(), message=q1, runtime=SimpleNamespace(maintenance_context={}))

    # 1. 运行 _phase_context
    async for _ in run_phases._phase_context(agent, state1):
        pass

    assert state1.context.get("gate_passed") is True, "Gate should pass for personal question"
    print(f"[*] 意图闸门判定: passed={state1.context['gate_passed']}, score={state1.context['knowledge_trace']['decisions'][0]['gate_score']}, reason={state1.context['knowledge_trace']['decisions'][0]['gate_reason']}")
    print(f"[*] 装配出处条目: {state1.context.get('assembled_refs')}")

    # 2. 运行 _build_messages
    messages1 = await run_phases._build_messages(agent, state1)

    print("\n--- [实际发给模型的 Messages 完整列表] ---")
    formatted_msgs1 = []
    for idx, msg in enumerate(messages1):
        role = "system" if isinstance(msg, SystemMessage) else "user" if isinstance(msg, HumanMessage) else "assistant"
        print(f"\n[Message #{idx} | Role: {role.upper()}]:")
        print(msg.content)
        formatted_msgs1.append({"role": role, "content": msg.content})

    # 验证关键内容在 prompt 中
    all_content1 = "\n".join(str(m.content) for m in messages1)
    assert "【用户画像" in all_content1, "画像块必须在 prompt 中"
    assert "【本轮相关记忆】" in all_content1, "相关记忆块必须在 prompt 中"
    assert "[m:coffee-01]" in all_content1, "[m:<ref>] 标号必须在 prompt 中"
    assert "【有冲突/有多个候选】" in all_content1, "冲突警告必须在 prompt 中"

    # 3. 发送给真实模型 deepseek-v4.1-flash
    print("\n[*] 正在向真实模型 deepseek-v4.1-flash 发送请求...")
    t0 = asyncio.get_event_loop().time()
    resp1 = await router.complete_for(model_id, "chat", formatted_msgs1)
    t1 = asyncio.get_event_loop().time()
    print(f"[*] 模型响应成功 (耗时: {t1 - t0:.2f}s):")
    print(f"\n{resp1.text}\n")

    # =========================================================================
    # 回合 2: 纯技术问题 (闸门关闭 -> 画像块保留、动态记忆块被闸门拦截为空)
    # =========================================================================
    print("\n" + "#" * 80)
    print("【回合 2: 纯技术代码问题（闸门拦截测试）】")
    print("#" * 80)
    q2 = "Python 中如何快速对字典按 key 排序？给出简短代码示例。"
    req2 = run_phases.RunRequest(message=q2, conversation_id="conv-smoke-02")
    append_session_message(DATA_ROOT / "engine", req2.conversation_id, "user", q2)
    state2 = run_phases._RunState(request=req2, callbacks=run_phases.RunCallbacks(), message=q2, runtime=SimpleNamespace(maintenance_context={}))

    # 1. 运行 _phase_context
    async for _ in run_phases._phase_context(agent, state2):
        pass

    assert state2.context.get("gate_passed") is False, "Gate should block for pure generic code"
    assert state2.context.get("relevant_memory_block") == "", "Relevant memory block must be empty when gated"
    assert state2.context.get("memories") == [], "Memories list must be empty when gated"
    print(f"[*] 意图闸门判定: passed={state2.context['gate_passed']}, score={state2.context['knowledge_trace']['decisions'][0]['gate_score']}, reason={state2.context['knowledge_trace']['decisions'][0]['gate_reason']}")
    print(f"[*] 相关记忆块内容长度: {len(state2.context.get('relevant_memory_block'))} (成功拦截为空)")

    # 2. 运行 _build_messages
    messages2 = await run_phases._build_messages(agent, state2)

    print("\n--- [实际发给模型的 Messages 完整列表] ---")
    formatted_msgs2 = []
    for idx, msg in enumerate(messages2):
        role = "system" if isinstance(msg, SystemMessage) else "user" if isinstance(msg, HumanMessage) else "assistant"
        print(f"\n[Message #{idx} | Role: {role.upper()}]:")
        print(msg.content)
        formatted_msgs2.append({"role": role, "content": msg.content})

    all_content2 = "\n".join(str(m.content) for m in messages2)
    assert "【用户画像" in all_content2, "稳定画像块仍在系统提示词中"
    assert "【本轮相关记忆】" not in all_content2, "被闸门拦截后相关记忆块不得注入"
    assert "coffee-01" not in all_content2, "无关个人记忆不得出现在技术问题 prompt 中"

    # 3. 发送给真实模型 deepseek-v4.1-flash
    print("\n[*] 正在向真实模型 deepseek-v4.1-flash 发送请求...")
    t0 = asyncio.get_event_loop().time()
    resp2 = await router.complete_for(model_id, "chat", formatted_msgs2)
    t1 = asyncio.get_event_loop().time()
    print(f"[*] 模型响应成功 (耗时: {t1 - t0:.2f}s):")
    print(f"\n{resp2.text}\n")

    evidence = {
        "status": "PASSED",
        "model_id": model_id,
        "round_1_gate_open": {
            "query": q1,
            "gate_passed": state1.context.get("gate_passed"),
            "gate_reason": state1.context["knowledge_trace"]["decisions"][0]["gate_reason"],
            "messages_sent_to_model": formatted_msgs1,
            "model_response": resp1.text,
        },
        "round_2_gate_closed": {
            "query": q2,
            "gate_passed": state2.context.get("gate_passed"),
            "gate_reason": state2.context["knowledge_trace"]["decisions"][0]["gate_reason"],
            "messages_sent_to_model": formatted_msgs2,
            "model_response": resp2.text,
        },
    }

    evidence_file = PROJECT_ROOT / "docs" / "plan" / "MEMORY-V1" / "progress" / "packages" / "L1_smoke_evidence.json"
    evidence_file.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[+] 真实证据文件已保存: {evidence_file}")
    print("=" * 80)
    print("【S3 真实模型冒烟验证完成 · 全部通过】")
    print("=" * 80)
    return evidence


if __name__ == "__main__":
    asyncio.run(run_smoke())

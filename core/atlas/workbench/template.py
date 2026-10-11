"""「我的 agent」模板：一个最小的 ACP agent，Python 写，填自己的逻辑就能挂到工作台。"""

from __future__ import annotations

import sys

from atlas.workbench.store import AgentManifest, WorkbenchStore

TEMPLATE = '''"""{name} —— 挂在 Atlas 工作台上的自定义 agent（ACP 协议，标准输入输出通信）。

改 handle() 就是改它的本事。模型地址、密钥、模型名在工作台里这个挂件的「环境变量」里填，
和 Atlas 主体的配置互不相干：
    MODEL_BASE_URL   OpenAI 兼容地址，例如 https://api.example.com/v1
    MODEL_API_KEY    密钥
    MODEL_NAME       模型名
    SYSTEM_PROMPT    （可选）它的人设 / 专门要干的事
文档：https://agentclientprotocol.com  Python SDK：https://github.com/agentclientprotocol/python-sdk
"""

import asyncio
import os
import uuid

import httpx
from acp import PROTOCOL_VERSION, run_agent, text_block, update_agent_message
from acp.interfaces import Agent, Client
from acp.schema import AgentCapabilities, Implementation, InitializeResponse, NewSessionResponse, PromptResponse


class MyAgent(Agent):
    def __init__(self) -> None:
        self.client: Client | None = None
        self.history: dict[str, list[dict]] = {{}}

    def on_connect(self, conn: Client) -> None:
        self.client = conn

    async def initialize(self, protocol_version, client_capabilities=None, client_info=None, **kwargs):
        return InitializeResponse(
            protocol_version=PROTOCOL_VERSION,
            agent_capabilities=AgentCapabilities(),
            agent_info=Implementation(name="{id}", title="{name}", version="0.1.0"),
        )

    async def new_session(self, cwd, mcp_servers=None, **kwargs):
        session_id = uuid.uuid4().hex
        system = os.environ.get("SYSTEM_PROMPT", "你是一个专门干一件事的助手，回答简洁。")
        self.history[session_id] = [{{"role": "system", "content": system}}]
        return NewSessionResponse(session_id=session_id)

    async def prompt(self, prompt, session_id, **kwargs):
        text = "".join(getattr(block, "text", "") for block in prompt)
        reply = await self.handle(session_id, text)
        await self.client.session_update(session_id=session_id, update=update_agent_message(text_block(reply)))
        return PromptResponse(stop_reason="end_turn")

    async def cancel(self, session_id, **kwargs):
        return None

    async def handle(self, session_id: str, text: str) -> str:
        """收到一条任务，返回回复。在这里写你自己的逻辑。"""
        messages = self.history.setdefault(session_id, [])
        messages.append({{"role": "user", "content": text}})
        base = os.environ.get("MODEL_BASE_URL", "").rstrip("/")
        if not base:
            return f"（模板 agent）收到：{{text}}\\n\\n在工作台里给我配上 MODEL_BASE_URL / MODEL_API_KEY / MODEL_NAME 就能真正回答了。"
        async with httpx.AsyncClient(timeout=300) as http:
            response = await http.post(
                f"{{base}}/chat/completions",
                headers={{"Authorization": f"Bearer {{os.environ.get('MODEL_API_KEY', '')}}"}},
                json={{"model": os.environ.get("MODEL_NAME", ""), "messages": messages}},
            )
            response.raise_for_status()
            reply = response.json()["choices"][0]["message"]["content"]
        messages.append({{"role": "assistant", "content": reply}})
        return reply


if __name__ == "__main__":
    asyncio.run(run_agent(MyAgent()))
'''


def create_template_agent(store: WorkbenchStore, name: str) -> AgentManifest:
    agent_id = store.unique_id(name if name.isascii() else "my-agent")
    manifest = AgentManifest(
        id=agent_id, name=name, mode="acp", command=sys.executable,
        args=["{agent_dir}/agent.py"], source="template",
        description="自己写的 agent：改它文件夹里的 agent.py",
        env={"MODEL_BASE_URL": "", "MODEL_API_KEY": "", "MODEL_NAME": "", "SYSTEM_PROMPT": ""},
    )
    store.save(manifest, create=True)
    (store.agent_dir(agent_id) / "agent.py").write_text(
        TEMPLATE.format(id=agent_id, name=name.replace('"', "'")), encoding="utf-8",
    )
    return manifest

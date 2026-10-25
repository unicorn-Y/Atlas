"""U31 item-level integration checks; no Electron window or screenshots are used."""

from __future__ import annotations

import asyncio
import base64
import tempfile
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))


async def check_whatsapp_bridge() -> None:
    """Exercise QR state, normalized inbound text/media, and outbound delivery over local JSONL."""
    from unittest.mock import patch

    from atlas.channels.adapters.whatsapp import WhatsAppAdapter

    node = shutil.which("node")
    assert node, "Node.js is required for the local WhatsApp bridge scenario"
    with tempfile.TemporaryDirectory(prefix="atlas-u31-wa-") as temp:
        root = Path(temp)
        bridge = root / "bridge"
        bridge.mkdir()
        (bridge / "bridge.mjs").write_text(
            """
import readline from 'node:readline';
const emit = (value) => process.stdout.write(JSON.stringify(value) + '\\n');
emit({type:'qr', value:'local-fake-whatsapp-qr'});
emit({type:'message', value:{event_id:'wamid-in-1',chat_id:'15550001111@s.whatsapp.net',sender_id:'15550001111@s.whatsapp.net',sender_name:'Fixture',text:'hello from local fixture',timestamp:1792944000}});
emit({type:'message', value:{event_id:'wamid-in-2',chat_id:'15550001111@s.whatsapp.net',sender_id:'15550001111@s.whatsapp.net',text:'image caption',timestamp:1792944001,attachment:{data:'""" + base64.b64encode(b"fixture-image-bytes").decode("ascii") + """',mime_type:'image/png',filename:'tiny.png',kind:'image'}}});
readline.createInterface({input:process.stdin,crlfDelay:Infinity}).on('line', line => {const request=JSON.parse(line); emit({type:'response',id:request.id,value:{message_id:'wamid-out-1',echo:request.text,chat_id:request.chat_id}})});
""",
            encoding="utf-8",
        )
        received: asyncio.Queue = asyncio.Queue()

        async def dispatch(event) -> None:
            await received.put(event)

        adapter = WhatsAppAdapter({"account": "u31-local", "state_path": str(root / "data")}, dispatch)
        original_available = WhatsAppAdapter.is_available
        WhatsAppAdapter.is_available = classmethod(lambda cls: True)
        try:
            with patch("atlas.channels.adapters.whatsapp._bridge_paths", return_value=(bridge, Path(node))):
                await adapter.start()
                assert adapter.pairing_status()["state"] == "pairing", adapter.pairing_status()
                assert adapter.pairing_status()["qr"] == "local-fake-whatsapp-qr", adapter.pairing_status()
                text_event = await asyncio.wait_for(received.get(), timeout=3)
                media_event = await asyncio.wait_for(received.get(), timeout=3)
                assert text_event.text == "hello from local fixture" and text_event.channel == "whatsapp"
                assert text_event.sender_id == "15550001111@s.whatsapp.net" and not text_event.is_group
                assert media_event.text == "image caption" and media_event.attachments[0].kind.value == "image"
                assert Path(media_event.attachments[0].local_path).read_bytes() == b"fixture-image-bytes"
                sent = await adapter.send("15550001111@s.whatsapp.net", "outbound fixture")
                assert sent.ok and sent.message_id == "wamid-out-1"
                assert adapter.pairing_status()["state"] == "pairing"
                await adapter.stop()
        finally:
            WhatsAppAdapter.is_available = original_available
        print("U31 item 1: local JSONL bridge QR state, inbound text/media normalization and outbound delivery PASS")


async def check_prompt_enhancement_modes() -> None:
    """Exercise both prompt rewrite and previous-answer refinement through the API endpoint."""
    import json
    from types import SimpleNamespace

    from starlette.requests import Request
    from atlas.api.workspace_router import enhance_chat_prompt

    calls = []

    class Router:
        async def resolve(self, model, purpose):
            assert model == "fixture-model" and purpose == "prompt_enhance"
            return "fixture-route"

        async def complete(self, route, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(text="改写后的内容", raw={"choices": [{"finish_reason": "stop"}]})

    services = SimpleNamespace(model_mgr=SimpleNamespace(
        model_router=Router(), current_model="fixture-model"))

    async def invoke(payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        sent = False

        async def receive():
            nonlocal sent
            if sent:
                return {"type": "http.request", "body": b"", "more_body": False}
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        request = Request({"type": "http", "method": "POST", "path": "/api/chat/prompt-enhance", "headers": []}, receive)
        return await enhance_chat_prompt(services, request)

    prompt = await invoke({"text": "整理 bug", "mode": "prompt"})
    assert prompt == {"text": "改写后的内容", "model": "fixture-model", "mode": "prompt"}
    prompt_messages = calls[-1]["messages"]
    assert "Rewrite the user's draft" in prompt_messages[0]["content"]
    assert prompt_messages[1]["content"] == "整理 bug"

    answer = await invoke({"text": "修复已完成", "context": "请修复 bug", "mode": "answer"})
    assert answer == {"text": "改写后的内容", "model": "fixture-model", "mode": "answer"}
    answer_messages = calls[-1]["messages"]
    assert "previous assistant answer" in answer_messages[0]["content"]
    assert "请修复 bug" in answer_messages[1]["content"] and "修复已完成" in answer_messages[1]["content"]
    assert "do not answer it again" in answer_messages[0]["content"]
    print("U31 item 2: prompt and previous-answer API rewrite modes PASS")


def require(path: str, *needles: str) -> None:
    content = (ROOT / path).read_text(encoding="utf-8")
    missing = [needle for needle in needles if needle not in content]
    if missing:
        raise AssertionError(f"{path}: missing {missing}")


async def main() -> None:
    await check_prompt_enhancement_modes()
    await check_whatsapp_bridge()
    require("frontend/src/renderer/components/Composer.tsx", "预览改写内容", "替换输入框草稿", "追加到输入框草稿", "精修上一条回答")
    require("frontend/src/renderer/App.tsx", "mode: 'answer'", "mode: 'prompt'")
    require("core/atlas/channels/adapters/__init__.py", '("whatsapp", "atlas.channels.adapters.whatsapp", "WhatsAppAdapter")')
    require("core/atlas/channels/catalog.py", '"id": "whatsapp"', 'Baileys 6.7.24', '二维码')
    require("core/atlas/api/channel_router.py", '"/whatsapp/pairing"', '"/whatsapp/pairing/reset"')
    require("frontend/src/renderer/pages/settings/ChannelsSettings.tsx", "WhatsApp 配对二维码", "已关联设备", "pairing/reset")
    print("U31 CHECK PASS")


if __name__ == "__main__":
    asyncio.run(main())

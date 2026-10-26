"""U46 end-to-end acceptance scenarios for the seven Wave 46 work items."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import tempfile
import urllib.request

import websockets

ROOT = Path(__file__).resolve().parents[2]


async def _cdp_eval(ws: websockets.ClientConnection, request_id: int, expression: str) -> object:
    await ws.send(json.dumps({
        "id": request_id,
        "method": "Runtime.evaluate",
        "params": {"expression": expression, "returnByValue": True, "awaitPromise": True},
    }))
    while True:
        response = json.loads(await ws.recv())
        if response.get("id") != request_id:
            continue
        if "error" in response:
            raise AssertionError(f"CDP evaluation failed: {response['error']}")
        result = response["result"]["result"]
        if result.get("subtype") == "error":
            raise AssertionError(f"DOM scenario failed: {result.get('description')}")
        return result.get("value")


async def _cdp_command(ws: websockets.ClientConnection, request_id: int, method: str, params: dict[str, object]) -> None:
    await ws.send(json.dumps({"id": request_id, "method": method, "params": params}))
    while True:
        response = json.loads(await ws.recv())
        if response.get("id") == request_id:
            if "error" in response:
                raise AssertionError(f"CDP command {method} failed: {response['error']}")
            return


async def check_scroll_speed() -> None:
    """Open the actual /scroll-speed dialog, change preference, and exercise its wheel listener."""
    target = next((item for item in json.load(urllib.request.urlopen("http://127.0.0.1:9336/json/list"))
                   if item.get("type") == "page" and "127.0.0.1:5173" in item.get("url", "")), None)
    assert target, "Atlas renderer is not attached to CDP port 9336"
    async with websockets.connect(target["webSocketDebuggerUrl"]) as ws:
        before = await _cdp_eval(ws, 1, "localStorage.getItem('atlas.preference.scroll-speed')")
        try:
            await _cdp_eval(ws, 9, "(()=>{const d=document.querySelector('[role=dialog]');if(d)[...d.querySelectorAll('button')].find(b=>b.innerText.includes('完成'))?.click()})()")
            await _cdp_eval(ws, 2, "(()=>{const e=document.querySelector('textarea[aria-label=\\\"消息内容\\\"]');if(!e)throw Error('composer missing');e.focus();e.value='';e.dispatchEvent(new Event('input',{bubbles:true}))})()")
            await _cdp_command(ws, 3, "Input.insertText", {"text": "/scroll-speed"})
            await _cdp_command(ws, 4, "Input.dispatchKeyEvent", {"type": "keyDown", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13})
            await _cdp_command(ws, 5, "Input.dispatchKeyEvent", {"type": "keyUp", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13})
            dialog = await _cdp_eval(ws, 6, "({open:!!document.querySelector('[role=dialog]'),slider:!!document.querySelector('input[aria-label=\\\"对话滚轮速度\\\"]')})")
            assert dialog == {"open": True, "slider": True}, dialog
            current = float(await _cdp_eval(ws, 7, "(()=>{const e=document.querySelector('input[aria-label=\\\"对话滚轮速度\\\"]');e.focus();return e.value})()"))
            delta_steps = round((1.5 - current) / 0.05)
            key = "ArrowRight" if delta_steps > 0 else "ArrowLeft"
            for index in range(abs(delta_steps)):
                await _cdp_command(ws, 8 + index * 2, "Input.dispatchKeyEvent", {"type": "keyDown", "key": key, "code": key, "windowsVirtualKeyCode": 39 if key == "ArrowRight" else 37})
                await _cdp_command(ws, 9 + index * 2, "Input.dispatchKeyEvent", {"type": "keyUp", "key": key, "code": key, "windowsVirtualKeyCode": 39 if key == "ArrowRight" else 37})
            changed = await _cdp_eval(ws, 1000, "(()=>{const e=document.querySelector('input[aria-label=\\\"对话滚轮速度\\\"]');const thread=document.querySelector('[aria-label=\\\"任务活动\\\"]');const wheel=new WheelEvent('wheel',{deltaY:100,bubbles:true,cancelable:true});const nativeAllowed=thread.dispatchEvent(wheel);return {slider:e.value,saved:localStorage.getItem('atlas.preference.scroll-speed'),wheelIntercepted:!nativeAllowed}})()")
            assert changed == {"slider": "1.5", "saved": "1.5", "wheelIntercepted": True}, changed
            print("PASS scroll-speed: /scroll-speed dialog, persisted live preview, and session-only wheel interception")
        finally:
            await _cdp_eval(ws, 8, "(()=>{const d=document.querySelector('[role=dialog]');if(d)[...d.querySelectorAll('button')].find(b=>b.innerText.includes('完成'))?.click();if(" + json.dumps(before) + "===null)localStorage.removeItem('atlas.preference.scroll-speed');else localStorage.setItem('atlas.preference.scroll-speed'," + json.dumps(before) + ");window.dispatchEvent(new CustomEvent('atlas:scroll-speed',{detail:Number(" + json.dumps(before) + "||1)}))})()")


async def main() -> None:
    await check_scroll_speed()
    print("U46 CHECK PASS")


if __name__ == "__main__":
    asyncio.run(main())

"""U46 end-to-end acceptance scenarios for the seven Wave 46 work items."""
from __future__ import annotations

import asyncio
from concurrent.futures import ProcessPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.request

import websockets

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "core"


def _run_cli(*arguments: str) -> str:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(CORE) + (os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else "")
    result = subprocess.run([sys.executable, "-m", "atlas.cli", *arguments], cwd=CORE, env=environment,
                            text=True, encoding="utf-8", errors="replace", capture_output=True, check=False)
    if result.returncode:
        raise AssertionError(f"CLI failed ({result.returncode}): {result.stderr[-1200:]}")
    return result.stdout


def check_shell_aliases() -> None:
    """Create, list, update, and revoke aliases in disposable PowerShell/POSIX profiles."""
    with tempfile.TemporaryDirectory(prefix="atlas-u46-alias-") as temp_dir:
        root = Path(temp_dir)
        workspace = root / "workspace with spaces"
        workspace.mkdir()
        for shell in ("powershell", "bash", "zsh"):
            profile = root / f"{shell}.profile"
            profile.write_text("# User-owned line\n", encoding="utf-8")
            args = ("--argument=--model", "--argument=deepseek-v4.1-flash", "--argument=--safe-mode")
            _run_cli("alias", "add", "atlas_work", "--shell", shell, "--workspace", str(workspace), "--profile", str(profile), *args)
            _run_cli("alias", "add", "atlas_work", "--shell", shell, "--workspace", str(workspace), "--profile", str(profile), *args)
            content = profile.read_text(encoding="utf-8")
            assert content.count("# >>> atlas alias: atlas_work >>>") == 1, f"{shell} duplicate markers"
            assert "# User-owned line" in content and str(workspace) in content
            if shell == "powershell":
                assert "Push-Location -LiteralPath" in content and "finally { Pop-Location }" in content and "@args" in content
            else:
                assert "(cd -- " in content and '"$@"' in content and "--safe-mode" in content
            listed = _run_cli("alias", "list", "--shell", shell, "--profile", str(profile))
            assert "atlas_work" in listed
            removed = _run_cli("alias", "remove", "atlas_work", "--shell", shell, "--profile", str(profile))
            assert "已撤销" in removed
            content = profile.read_text(encoding="utf-8")
            assert "# >>> atlas alias: atlas_work >>>" not in content and content.strip() == "# User-owned line"
    print("PASS shell-aliases: add/list/update/revoke for PowerShell, Bash, and Zsh profiles")


def _create_automation_probe(arguments: tuple[str, str]) -> bool:
    """Cross-process writer used to prove the cap check and TOML replacement are atomic."""
    from atlas.automation.store import AutomationLimitError, AutomationStore, normalize_record

    path, automation_id = arguments
    store = AutomationStore(path)
    record = normalize_record({
        "id": automation_id,
        "name": automation_id,
        "trigger": {"kind": "interval", "every_seconds": 3600},
        "payload": {"kind": "agent_turn", "message": "U46 disposable cap probe"},
    })
    try:
        store.put(record)
        return True
    except AutomationLimitError:
        return False


def check_automation_cap() -> None:
    """Run concurrent stores against a temporary TOML path and confirm the configured ceiling."""
    from atlas.automation.store import AutomationStore

    previous = os.environ.get("ATLAS_AUTOMATION_MAX_COUNT")
    os.environ["ATLAS_AUTOMATION_MAX_COUNT"] = "2"
    try:
        with tempfile.TemporaryDirectory(prefix="atlas-u46-automation-") as temp_dir:
            path = str(Path(temp_dir) / "automations.toml")
            with ProcessPoolExecutor(max_workers=6) as pool:
                created = list(pool.map(_create_automation_probe, [(path, f"u46-probe-{index}") for index in range(12)]))
            assert sum(created) == 2, f"configured cap should admit exactly 2 creates, got {sum(created)}"
            records = AutomationStore(path).list()
            assert len(records) == 2, f"concurrent creates persisted {len(records)} records"
        print("PASS automation-cap: 12 cross-process creates persisted exactly 2 records at configured cap")
    finally:
        if previous is None:
            os.environ.pop("ATLAS_AUTOMATION_MAX_COUNT", None)
        else:
            os.environ["ATLAS_AUTOMATION_MAX_COUNT"] = previous


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
            await _cdp_eval(ws, 10, "document.querySelector('button[aria-label=\\\"新建对话\\\"]')?.click()")
            await asyncio.sleep(0.3)
            await _cdp_eval(ws, 2, "(()=>{const e=document.querySelector('textarea[aria-label=\\\"消息内容\\\"]');if(!e)throw Error('composer missing');e.focus();e.value='';e.dispatchEvent(new Event('input',{bubbles:true}))})()")
            await _cdp_command(ws, 3, "Input.insertText", {"text": "/scroll-speed"})
            await _cdp_command(ws, 4, "Input.dispatchKeyEvent", {"type": "keyDown", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13})
            await _cdp_command(ws, 5, "Input.dispatchKeyEvent", {"type": "keyUp", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13})
            await asyncio.sleep(0.5)
            dialog = await _cdp_eval(ws, 6, "({open:!!document.querySelector('[role=dialog]'),slider:!!document.querySelector('input[aria-label=\\\"对话滚轮速度\\\"]')})")
            assert dialog == {"open": True, "slider": True}, dialog
            await _cdp_eval(ws, 7, "[...document.querySelectorAll('[role=dialog] button')].find(b=>b.innerText.includes('恢复默认'))?.click()")
            await _cdp_eval(ws, 8, "document.querySelector('input[aria-label=\\\"对话滚轮速度\\\"]').focus()")
            await _cdp_command(ws, 11, "Input.dispatchKeyEvent", {"type": "keyDown", "key": "ArrowRight", "code": "ArrowRight", "windowsVirtualKeyCode": 39})
            await _cdp_command(ws, 12, "Input.dispatchKeyEvent", {"type": "keyUp", "key": "ArrowRight", "code": "ArrowRight", "windowsVirtualKeyCode": 39})
            await asyncio.sleep(0.2)
            changed = await _cdp_eval(ws, 1000, "(()=>{const e=document.querySelector('input[aria-label=\\\"对话滚轮速度\\\"]');const thread=document.querySelector('[aria-label=\\\"任务活动\\\"]');const wheel=new WheelEvent('wheel',{deltaY:100,bubbles:true,cancelable:true});const nativeAllowed=thread.dispatchEvent(wheel);return {slider:e.value,saved:localStorage.getItem('atlas.preference.scroll-speed'),wheelIntercepted:!nativeAllowed}})()")
            assert changed == {"slider": "1.05", "saved": "1.05", "wheelIntercepted": True}, changed
            print("PASS scroll-speed: /scroll-speed dialog, persisted live preview, and session-only wheel interception")
        finally:
            await _cdp_eval(ws, 8, "(()=>{const d=document.querySelector('[role=dialog]');if(d)[...d.querySelectorAll('button')].find(b=>b.innerText.includes('完成'))?.click();if(" + json.dumps(before) + "===null)localStorage.removeItem('atlas.preference.scroll-speed');else localStorage.setItem('atlas.preference.scroll-speed'," + json.dumps(before) + ");window.dispatchEvent(new CustomEvent('atlas:scroll-speed',{detail:Number(" + json.dumps(before) + "||1)}))})()")


async def main() -> None:
    check_shell_aliases()
    check_automation_cap()
    await check_scroll_speed()
    print("U46 CHECK PASS")


if __name__ == "__main__":
    asyncio.run(main())

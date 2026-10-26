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
from urllib.parse import quote, urlencode

import websockets

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "core"


def _run_cli(*arguments: str, timeout: float = 60) -> str:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(CORE) + (os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else "")
    result = subprocess.run([sys.executable, "-m", "atlas.cli", *arguments], cwd=CORE, env=environment,
                            text=True, encoding="utf-8", errors="replace", capture_output=True, check=False,
                            timeout=timeout)
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


def check_cli_tui_modes() -> None:
    """Drive both interactive input modes with /exit and a disposable data root."""
    with tempfile.TemporaryDirectory(prefix="atlas-u46-chat-") as temp_dir:
        environment = os.environ.copy()
        environment["ATLAS_DATA_DIR"] = temp_dir
        environment["PYTHONPATH"] = str(CORE) + (os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else "")
        outputs: dict[str, str] = {}
        for mode in ("--tui", "--cli"):
            result = subprocess.run(
                [sys.executable, "-m", "atlas.cli", "chat", mode], cwd=CORE, env=environment,
                input="/exit\n", text=True, encoding="utf-8", errors="replace", capture_output=True,
                check=False, timeout=60,
            )
            assert result.returncode == 0, f"atlas chat {mode} failed: {result.stderr[-1200:]}"
            outputs[mode] = result.stdout
        assert "Terminal mode: TUI (Rich)" in outputs["--tui"]
        assert "Terminal mode: CLI (plain text)" in outputs["--cli"]
        assert "You:" in outputs["--cli"] and "[bold" not in outputs["--cli"] and "\x1b[" not in outputs["--cli"]
    help_text = _run_cli("moa", "--help")
    assert "--sample-model" in help_text and "--parallelism" in help_text and "-p, --print" in help_text
    print("PASS cli-modes: --tui and --cli accept an interactive /exit; CLI output stays plain; moa --print help is wired")


async def check_moa_pipeline() -> None:
    """Check bounded concurrent sampling with a fake router, then use configured DeepSeek routes."""
    from types import SimpleNamespace
    from atlas.cli import _moa_pipeline

    class FakeRouter:
        def __init__(self) -> None:
            self.active = 0
            self.max_active = 0
            self.calls: list[str] = []

        async def complete_for(self, model: str, purpose: str, messages: list[dict], **kwargs):
            assert purpose == "moa" and "max_tokens" in kwargs
            self.calls.append(model)
            if "Synthesize" in messages[0]["content"]:
                return SimpleNamespace(text="combined answer")
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            await asyncio.sleep(0.05)
            self.active -= 1
            return SimpleNamespace(text=f"sample from {model}")

    class FakeModelManager:
        model_router = FakeRouter()

        @staticmethod
        def list_models():
            return [{"id": name, "litellm_model": name} for name in
                    ("deepseek-v4.1-flash", "deepseek-v3", "deepseek-r1")]

    fake = FakeModelManager()
    simulated = await _moa_pipeline(
        "Compare two approaches.", ["deepseek-v3", "deepseek-r1"], "deepseek-v4.1-flash", fake, max_parallel=2,
    )
    assert simulated["answer"] == "combined answer" and len(simulated["samples"]) == 2
    assert fake.model_router.max_active == 2 and len(fake.model_router.calls) == 3, fake.model_router.calls

    live = _run_cli(
        "moa", "--print", "用一句话说明 MoA 的作用，包含并行采样与合成。",
        "--sample-model", "deepseek-v3", "--sample-model", "deepseek-r1",
        "--model", "deepseek-v4.1-flash", "--max-references", "2", "--parallelism", "2",
        "--output-format", "json", timeout=300,
    )
    result = json.loads(live)
    assert result["synthesis_model"] == "deepseek-v4.1-flash" and result["answer"].strip()
    assert len(result["samples"]) == 2 and any(item.get("text") for item in result["samples"]), result
    print("PASS moa: fake router confirms concurrent 2-model sampling then synthesis; real DeepSeek CLI request returns JSON answer")


def check_workspace_treemap_api() -> None:
    """Exercise the live workspace scanner, size totals, ignores, and small-repo output."""
    with tempfile.TemporaryDirectory(prefix="atlas-u46-treemap-") as temp_dir:
        root = Path(temp_dir)
        (root / "src").mkdir()
        (root / "docs").mkdir()
        (root / "node_modules" / "ignored").mkdir(parents=True)
        (root / ".git").mkdir()
        (root / "src" / "main.py").write_bytes(b"print('atlas')\n")
        (root / "docs" / "readme.md").write_bytes(b"hello treemap\n")
        (root / "node_modules" / "ignored" / "package.json").write_bytes(b"must not appear")
        (root / ".git" / "config").write_bytes(b"must not appear")
        url = "http://127.0.0.1:8765/api/workspace/treemap?" + urlencode({"root": str(root)})
        result = json.load(urllib.request.urlopen(url, timeout=10))
        by_path = {item["path"]: item["size"] for item in result["files"]}
        expected = {"src/main.py": len(b"print('atlas')\n"), "docs/readme.md": len(b"hello treemap\n")}
        assert by_path == expected, f"tree scan paths/sizes mismatch: {by_path}"
        assert result["file_count"] == 2 and result["total_bytes"] == sum(expected.values()) and not result["truncated"], result
    print("PASS workspace-treemap: live API reports exact sizes and excludes .git/node_modules")


def _api_json(path: str, *, method: str = "GET", payload: dict | None = None) -> dict:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"http://127.0.0.1:8765{path}", data=body, method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise AssertionError(f"Atlas API {method} {path} returned HTTP {error.code}: {detail[:1200]}") from error


async def check_plugin_capability_projection() -> None:
    """Install a disabled, inert local fixture and inspect its real Settings projection."""
    name = "u46-capability-probe"
    existing = await asyncio.to_thread(_api_json, "/api/plugins")
    assert all(plugin.get("name") != name for plugin in existing.get("plugins", [])), f"reserved probe already exists: {name}"
    with tempfile.TemporaryDirectory(prefix="atlas-u46-plugin-") as temp_dir:
        root = Path(temp_dir) / name
        (root / "skills" / "daily").mkdir(parents=True)
        (root / "commands").mkdir()
        (root / "agents").mkdir()
        (root / "hooks").mkdir()
        (root / "output-styles").mkdir()
        (root / "skills" / "daily" / "SKILL.md").write_text(
            "---\nname: daily\ndescription: Summarize a day's work.\n---\nPrompt body.", encoding="utf-8")
        (root / "commands" / "ship.md").write_text(
            "---\nname: ship\ndescription: Prepare a release.\n---\nPrompt body.", encoding="utf-8")
        (root / "agents" / "reviewer.md").write_text(
            "---\nname: reviewer\ndescription: Reviews a change set.\n---\nAgent body.", encoding="utf-8")
        (root / "hooks" / "hooks.json").write_text(json.dumps({"hooks": {
            "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo inert-u46"}]}],
        }}), encoding="utf-8")
        (root / "output-styles" / "brief.md").write_text("brief style", encoding="utf-8")
        (root / ".mcp.json").write_text(json.dumps({"mcpServers": {
            "remote-docs": {"url": "https://u46-secret:never-display@mcp.example.invalid/rpc", "description": "Remote docs server"},
        }}), encoding="utf-8")
        manifest = {
            "name": name, "version": "1.0.0", "description": "U46 capability projection fixture",
            "defaultEnabled": False, "skills": "./skills", "commands": "./commands",
            "agents": "./agents", "hooks": "./hooks/hooks.json",
            "tools": {"file-reader": {"description": "Metadata-only file reader declaration", "tools": ["local_file.read"]}},
            "permissions": {"tools": ["local_file.read", "shell.run"], "network": ["https://docs.example.invalid"]},
            "outputStyles": ["./output-styles/brief.md"],
            "lspServers": {"sample-lsp": {"description": "Metadata-only language server declaration"}},
        }
        (root / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        installed = False
        try:
            result = await asyncio.to_thread(_api_json, "/api/plugins/install-local", method="POST", payload={"path": str(root)})
            installed = True
            assert result.get("name") == name, result
            body = await asyncio.to_thread(_api_json, "/api/plugins")
            plugin = next((item for item in body.get("plugins", []) if item.get("name") == name), None)
            assert plugin, body
            groups = {group["kind"]: group for group in plugin.get("capability_groups", [])}
            expected = {"skill", "command", "agent", "hook", "mcp", "tool", "output-style", "lsp-server"}
            assert set(groups) == expected, groups
            assert groups["skill"]["items"][0]["description"] == "Summarize a day's work."
            assert groups["command"]["items"][0]["loaded"] is False
            assert groups["tool"]["items"][0]["execution"] == "metadata-only"
            assert groups["output-style"]["items"][0]["execution"] == "metadata-only"
            assert groups["lsp-server"]["items"][0]["execution"] == "metadata-only"
            assert groups["mcp"]["items"][0]["network_access"] == "远程端点 mcp.example.invalid"
            assert "u46-secret" not in json.dumps(plugin, ensure_ascii=False)

            target = next((item for item in json.load(urllib.request.urlopen("http://127.0.0.1:9336/json/list"))
                           if item.get("type") == "page" and "127.0.0.1:5173" in item.get("url", "")), None)
            assert target, "Atlas renderer is not attached to CDP port 9336"
            async with websockets.connect(target["webSocketDebuggerUrl"]) as ws:
                await _cdp_eval(ws, 200, "document.querySelector('button[aria-label=\\\"设置\\\"]')?.click()")
                await asyncio.sleep(0.4)
                await _cdp_eval(ws, 201, "(()=>{const item=[...document.querySelectorAll('[aria-label=\\\"设置分类\\\"] button')].find(b=>b.innerText.includes('插件与导入'));if(!item)throw Error('设置里找不到插件与导入');item.click()})()")
                row_found = False
                for attempt in range(20):
                    await asyncio.sleep(0.5)
                    row_found = await _cdp_eval(ws, 202 + attempt, "[...document.querySelectorAll('[aria-label=\\\"插件管理\\\"] li')].some(li=>li.querySelector('strong')?.innerText==='" + name + "')")
                    if row_found:
                        break
                assert row_found, f"UI did not load installed fixture {name}"
                shown = await _cdp_eval(ws, 230, "(()=>{const li=[...document.querySelectorAll('[aria-label=\\\"插件管理\\\"] li')].find(row=>row.querySelector('strong')?.innerText==='" + name + "');li?.querySelector('details summary')?.click();return {groups:[...li.querySelectorAll('[aria-label$=\\\"贡献\\\"]')].map(x=>x.innerText),text:li?.innerText,body:document.body.innerText}})()")
                for label in ("技能", "命令", "Agent", "Hook", "MCP", "工具声明", "输出样式", "语言服务"):
                    assert any(group.startswith(label) for group in shown["groups"]), {"missing": label, **shown}
                assert "Metadata-only file reader declaration" in shown["text"]
                assert "metadata-only · 不执行" in shown["text"]
                assert "local_file.read" in shown["text"] and "docs.example.invalid" in shown["text"]
                assert "审批要求" in shown["text"] and "未加载" in shown["text"]
                assert "u46-secret" not in shown["body"]
                await _cdp_eval(ws, 231, "document.querySelector('button[aria-label=\\\"关闭设置\\\"]')?.click()")
            print("PASS plugin-capabilities: normalized 8 groups, sources/descriptions/load state/risk shown; metadata-only and MCP URL credentials stay inert/private")
        finally:
            if installed:
                await asyncio.to_thread(_api_json, f"/api/plugins/{quote(name)}", method="DELETE")


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


async def check_window_title() -> None:
    """Use the renderer slash command and checkbox to update both title preference and document title."""
    target = next((item for item in json.load(urllib.request.urlopen("http://127.0.0.1:9336/json/list"))
                   if item.get("type") == "page" and "127.0.0.1:5173" in item.get("url", "")), None)
    assert target, "Atlas renderer is not attached to CDP port 9336"
    async with websockets.connect(target["webSocketDebuggerUrl"]) as ws:
        before = await _cdp_eval(ws, 1, "localStorage.getItem('atlas.preference.window-title-fields')")
        original = (before.split(",") if isinstance(before, str) else ["conversation", "status"])
        try:
            await _cdp_eval(ws, 2, "(()=>{const d=document.querySelector('[role=dialog]');if(d)[...d.querySelectorAll('button')].find(b=>b.innerText.includes('完成'))?.click();const e=document.querySelector('textarea[aria-label=\\\"消息内容\\\"]');e.focus();e.value='';e.dispatchEvent(new Event('input',{bubbles:true}))})()")
            await _cdp_command(ws, 3, "Input.insertText", {"text": "/window-title"})
            await _cdp_command(ws, 4, "Input.dispatchKeyEvent", {"type": "keyDown", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13})
            await _cdp_command(ws, 5, "Input.dispatchKeyEvent", {"type": "keyUp", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13})
            dialog = await _cdp_eval(ws, 6, "({open:!!document.querySelector('[role=dialog]'),labels:[...document.querySelectorAll('[role=dialog] label')].map(x=>x.innerText.trim())})")
            assert dialog["open"] and dialog["labels"] == ["会话标题", "当前模型", "工作目录", "运行状态"], dialog
            old_title = await _cdp_eval(ws, 7, "document.title")
            await _cdp_eval(ws, 8, "[...document.querySelectorAll('[role=dialog] label')].find(x=>x.innerText.includes('当前模型'))?.querySelector('input')?.click()")
            await asyncio.sleep(0.2)
            changed = await _cdp_eval(ws, 9, "({title:document.title,fields:localStorage.getItem('atlas.preference.window-title-fields'),ipc:typeof window.atlasDesktop?.setWindowTitle,tooLong:document.title.length>160})")
            assert changed["ipc"] == "function" and not changed["tooLong"] and changed["title"] != old_title, changed
            assert ("model" in (changed["fields"] or "")) != ("model" in original), changed
            print("PASS window-title: field picker updates persisted selection, renderer title, and main-process IPC bridge")
        finally:
            await _cdp_eval(ws, 10, "(()=>{const l=[...document.querySelectorAll('[role=dialog] label')].find(x=>x.innerText.includes('当前模型'));if(l){const checked=l.querySelector('input')?.checked;const wanted=" + json.dumps("model" in original) + ";if(checked!==wanted)l.querySelector('input')?.click()}const pref=" + json.dumps(before) + ";if(pref===null)localStorage.removeItem('atlas.preference.window-title-fields');else localStorage.setItem('atlas.preference.window-title-fields',pref);const d=document.querySelector('[role=dialog]');if(d)[...d.querySelectorAll('button')].find(b=>b.innerText.includes('完成'))?.click()})()")


async def check_workspace_treemap_ui() -> None:
    """Open the actual Inspector tree-map tab, zoom a directory, and open a selected file in Files."""
    target = next((item for item in json.load(urllib.request.urlopen("http://127.0.0.1:9336/json/list"))
                   if item.get("type") == "page" and "127.0.0.1:5173" in item.get("url", "")), None)
    assert target, "Atlas renderer is not attached to CDP port 9336"
    async with websockets.connect(target["webSocketDebuggerUrl"]) as ws:
        draft_workspace = await _cdp_eval(ws, 100, "localStorage.getItem('atlas.conversations.draft-workspace')")
        default_workspace = await _cdp_eval(ws, 103, "localStorage.getItem('atlas.preference.default-workspace')")
        try:
            await _cdp_eval(ws, 110, "document.querySelector('button[aria-label=\\\"新建对话\\\"]')?.click()")
            await asyncio.sleep(1.0)
            await _cdp_eval(ws, 101, "(()=>{const d=document.querySelector('[role=dialog]');if(d)[...d.querySelectorAll('button')].find(b=>b.innerText.includes('完成'))?.click();const e=document.querySelector('textarea[aria-label=\\\"消息内容\\\"]');if(e){e.focus();e.value='';e.dispatchEvent(new Event('input',{bubbles:true}))}})()")
            await _cdp_command(ws, 102, "Input.insertText", {"text": "/treemap"})
            await _cdp_command(ws, 104, "Input.dispatchKeyEvent", {"type": "keyDown", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13})
            await _cdp_command(ws, 105, "Input.dispatchKeyEvent", {"type": "keyUp", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13})
            await asyncio.sleep(0.5)
            initial = {}
            for attempt in range(20):
                await asyncio.sleep(0.5)
                initial = await _cdp_eval(ws, 5 + attempt, "({panel:!!document.querySelector('[data-repo-treemap]'),title:document.querySelector('[data-repo-treemap] h2')?.innerText,workspace:document.querySelector('[data-repo-treemap] header p')?.innerText,summary:document.querySelector('[data-repo-treemap] p')?.innerText,loading:!![...document.querySelectorAll('[data-repo-treemap] [role=status]')].find(x=>x.innerText.includes('正在统计')),error:document.querySelector('[data-repo-treemap] [role=alert]')?.innerText,tree:document.querySelector('[aria-label=\\\"文件矩形树图\\\"]')?.innerText,dirs:[...document.querySelectorAll('[data-repo-treemap] button[aria-label^=\\\"打开目录 \\\"]')].map(b=>b.getAttribute('aria-label')).slice(0,5),input:document.querySelector('textarea[aria-label=\\\"消息内容\\\"]')?.value,inspector:document.querySelector('button[aria-label=\\\"切换任务面板\\\"]')?.getAttribute('aria-pressed'),tail:document.body.innerText.slice(-250)})")
                if initial.get("panel") and not initial.get("loading"):
                    break
            assert initial["panel"] and initial["title"] == "仓库文件树图", initial
            if initial.get("workspace") == "请选择本地工作区":
                await _cdp_eval(ws, 106, "Object.defineProperty(window.atlasDesktop,'selectDirectory',{configurable:true,value:async()=> 'C:\\\\engine-reg'})")
                await _cdp_eval(ws, 107, "[...document.querySelectorAll('[data-repo-treemap] button')].find(b=>b.innerText.includes('选择工作区'))?.click()")
                await asyncio.sleep(0.8)
                for attempt in range(20):
                    await asyncio.sleep(0.5)
                    initial = await _cdp_eval(ws, 108 + attempt, "({workspace:document.querySelector('[data-repo-treemap] header p')?.innerText,loading:!![...document.querySelectorAll('[data-repo-treemap] [role=status]')].find(x=>x.innerText.includes('正在统计')),dirs:[...document.querySelectorAll('[data-repo-treemap] button[aria-label^=\\\"打开目录 \\\"]')].map(b=>b.getAttribute('aria-label')).slice(0,5),error:document.querySelector('[data-repo-treemap] [role=alert]')?.innerText})")
                    if initial.get("workspace") != "请选择本地工作区" and not initial.get("loading"):
                        break
            assert initial["dirs"], f"current Atlas workspace has no directory tiles: {initial}"
            directory_button = "[data-repo-treemap] button[aria-label^=\"" + initial["dirs"][0].split("，")[0] + "\"]"
            await _cdp_eval(ws, 6, "document.querySelector(" + json.dumps(directory_button) + ")?.click()")
            zoom = await _cdp_eval(ws, 7, "document.querySelector('[aria-label=\\\"树图缩放层级\\\"]')?.innerText")
            assert zoom and zoom.count("/") >= 1, f"directory zoom did not update breadcrumbs: {zoom}"
            file_button = await _cdp_eval(ws, 8, "document.querySelector('[data-repo-treemap] button[aria-label^=\\\"打开文件 \\\"]')?.getAttribute('aria-label')")
            assert file_button, "zoomed directory has no file tile"
            file_path = file_button.removeprefix("打开文件 ").split("，")[0]
            file_prefix = file_button.split("，")[0]
            await _cdp_eval(ws, 9, "(()=>{const prefix=" + json.dumps(file_prefix) + ";[...document.querySelectorAll('[data-repo-treemap] button')].find(b=>b.getAttribute('aria-label')?.startsWith(prefix))?.click()})()")
            await asyncio.sleep(0.7)
            opened = await _cdp_eval(ws, 10, "({active:[...document.querySelectorAll('[role=tab][aria-selected=true]')].map(x=>x.innerText),fileRequest:document.body.innerText.includes(" + json.dumps(Path(file_path).name) + ")})")
            assert any("文件" in item for item in opened["active"]) and opened["fileRequest"], {"file": file_path, **opened}
            print(f"PASS workspace-treemap UI: root → {zoom} → FilesPanel opened {file_path}")
        finally:
            await _cdp_eval(ws, 11, "(()=>{const key='atlas.conversations.draft-workspace';const value=" + json.dumps(draft_workspace) + ";if(value===null)localStorage.removeItem(key);else localStorage.setItem(key,value);const pref=" + json.dumps(default_workspace) + ";if(pref===null)localStorage.removeItem('atlas.preference.default-workspace');else localStorage.setItem('atlas.preference.default-workspace',pref)})()")
            await _cdp_command(ws, 108, "Page.reload", {"ignoreCache": True})
            await asyncio.sleep(2)


async def main() -> None:
    check_shell_aliases()
    check_automation_cap()
    check_workspace_treemap_api()
    await check_scroll_speed()
    await check_window_title()
    await check_workspace_treemap_ui()
    await check_plugin_capability_projection()
    check_cli_tui_modes()
    await check_moa_pipeline()
    print("U46 CHECK PASS")


if __name__ == "__main__":
    asyncio.run(main())

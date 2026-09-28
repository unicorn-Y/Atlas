"""Opt-in normal-Agent browser acceptance through Playwright MCP."""

from __future__ import annotations

import ast
import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.mark.skipif(
    os.environ.get("ATLAS_P18X_RUN_AGENT_BROWSER_E2E") != "1",
    reason="set ATLAS_P18X_RUN_AGENT_BROWSER_E2E=1 to run normal-Agent browser acceptance",
)
async def test_normal_agent_reads_local_facts_and_completes_playwright_form(tmp_path: Path) -> None:
    from atlas.agent import AgentOrchestrator
    from atlas.memory import MemoryStore
    from atlas.models import ModelManager
    from atlas.tools.local_execution import LocalExecutionRuntime
    from atlas.tools.mcp_client import MCPClient

    provider = _DeterministicProvider()
    page = _FormFixture()
    source = tmp_path / "contact.txt"
    source.write_text("Name: Atlas Acceptance\nEmail: atlas@example.test\n", encoding="utf-8")
    provider.source_path = str(source)
    provider.page_url = page.url
    mcp = MCPClient()
    local = LocalExecutionRuntime()
    memory = MemoryStore(db_path=tmp_path / "agent-memory.db")
    config = _MCPConfig()
    try:
        manager_settings = {
            "gateway_base_url": provider.base_url,
            "api_key": "atlas-local-provider",
        }
        with patch("atlas.tools.mcp_client.get_config", return_value=config):
            await mcp.start()
        assert any(
            item.qualified_name == "playwright__browser_navigate"
            for item in mcp.list_tools()
        )
        await memory.init()
        with patch("atlas.models.load_user_settings", return_value=manager_settings):
            manager = ModelManager(default_model="gpt-4o-mini")
        agent = AgentOrchestrator(manager, memory, mcp_client=mcp, local_execution=local)

        events = [event async for event in agent.run(
            f"Complete the local form at {page.url}. Read source facts from {source}. "
            "Report the submitted result."
            , "agent-browser-acceptance",
        )]

        calls = [event["name"] for event in events if event["type"] == "tool_call"]
        assert "local_file" in calls
        assert "playwright__browser_navigate" in calls
        assert "playwright__browser_snapshot" in calls
        assert "playwright__browser_fill_form" in calls
        assert "playwright__browser_click" in calls
        assert any(
            event["type"] == "chunk" and "AGENT_BROWSER_E2E_OK" in event["content"]
            for event in events
        )
        assert provider.selected_tools == [
            "local_file", "playwright__browser_navigate", "playwright__browser_snapshot",
            "playwright__browser_fill_form", "playwright__browser_click",
            "playwright__browser_snapshot",
        ]
        assert page.submission == "Atlas Acceptance|atlas@example.test"
    finally:
        await mcp.stop()
        await local.shutdown()
        await memory.close()
        page.close()
        provider.close()


class _MCPConfig:
    def get(self, key: str, default=None):
        return {
            "tools.servers": {
                "playwright": {
                    "transport": "stdio",
                    "command": "npx",
                    "args": ["-y", "@playwright/mcp@0.0.45", "--headless", "--browser", "chrome"],
                },
            },
            "tools.auto_start": ["playwright"],
        }.get(key, default)


class _FormFixture:
    def __init__(self) -> None:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                body = b"""<!doctype html><html><body>
<form id="contact"><label>Full name<input name="name"></label>
<label>Email<input name="email" type="email"></label>
<button type="submit">Submit</button></form><output id="result"></output>
<script>document.querySelector('#contact').addEventListener('submit', event => {
event.preventDefault(); const data = new FormData(event.target);
fetch('/', {method:'POST', body:new URLSearchParams(data)}).then(r => r.text())
.then(text => document.querySelector('#result').textContent = text);
});</script></body></html>"""
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:
                from urllib.parse import parse_qs

                form = parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
                owner.submission = f"{form.get('name', [''])[0]}|{form.get('email', [''])[0]}"
                result = f"Submitted {owner.submission}".encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(result)))
                self.end_headers()
                self.wfile.write(result)

            def log_message(self, *_args) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/"
        self.submission = ""

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class _DeterministicProvider:
    def __init__(self) -> None:
        self.selected_tools: list[str] = []
        self.source_path = ""
        self.page_url = ""
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                messages = body.get("messages", [])
                tools = {
                    item["function"]["name"]: item["function"]
                    for item in body.get("tools", [])
                }
                calls = [
                    call["function"]["name"]
                    for message in messages if message.get("role") == "assistant"
                    for call in message.get("tool_calls", [])
                ]
                tool_content = "\n".join(
                    str(message.get("content", ""))
                    for message in messages if message.get("role") == "tool"
                )
                if "local_file" not in calls:
                    name = "local_file"
                    arguments = {"action": "read", "path": owner.source_path}
                elif "playwright__browser_navigate" not in calls:
                    name = "playwright__browser_navigate"
                    arguments = {"url": owner.page_url}
                elif calls.count("playwright__browser_snapshot") == 0:
                    name = "playwright__browser_snapshot"
                    arguments = {}
                elif "playwright__browser_fill_form" not in calls:
                    name = "playwright__browser_fill_form"
                    arguments = {"fields": self._fields(tool_content)}
                elif "playwright__browser_click" not in calls:
                    name = "playwright__browser_click"
                    submit_ref = self._ref(tool_content, 'button "Submit"')
                    arguments = {"element": "Submit button", "ref": submit_ref}
                elif calls.count("playwright__browser_snapshot") == 1:
                    name = "playwright__browser_snapshot"
                    arguments = {}
                else:
                    if "Submitted Atlas Acceptance|atlas@example.test" not in tool_content:
                        raise AssertionError(
                            f"DOM did not show the accepted submission: {tool_content}"
                        )
                    name = ""
                    arguments = {}

                if name:
                    name = self._available(name, tools)
                    owner.selected_tools.append(name)
                    chunks = [{
                        "delta": {"tool_calls": [{
                            "index": 0, "id": f"call-{len(owner.selected_tools)}",
                            "type": "function", "function": {
                                "name": name, "arguments": json.dumps(arguments),
                            },
                        }]},
                        "finish_reason": "tool_calls",
                    }]
                else:
                    chunks = [{
                        "delta": {
                            "content": "AGENT_BROWSER_E2E_OK: submitted form result verified."
                        },
                        "finish_reason": "stop",
                    }]
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                for chunk in chunks:
                    value = {
                        "id": "chatcmpl-atlas-browser-e2e", "object": "chat.completion.chunk",
                        "created": 0, "model": "gpt-4o-mini",
                        "choices": [{"index": 0, **chunk}],
                    }
                    self.wfile.write(f"data: {json.dumps(value)}\n\n".encode())
                    self.wfile.flush()
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
                self.close_connection = True

            @staticmethod
            def _available(name: str, tools: dict[str, dict]) -> str:
                if name in tools:
                    return name
                raise AssertionError(f"Normal Agent did not expose expected tool {name!r}")

            @staticmethod
            def _ref(text: str, accessible_name: str) -> str:
                match = re.search(re.escape(accessible_name) + r"[^\n]*\[ref=([^\]]+)\]", text)
                if not match:
                    raise AssertionError(
                        f"Playwright snapshot did not contain {accessible_name!r}: {text}"
                    )
                return match.group(1)

            @classmethod
            def _fields(cls, text: str) -> list[dict[str, str]]:
                facts = ""
                first_line = text.splitlines()[0] if text else ""
                try:
                    decoded = ast.literal_eval(first_line)
                except (SyntaxError, ValueError):
                    decoded = {}
                if isinstance(decoded, dict) and isinstance(decoded.get("content"), str):
                    facts = decoded["content"]
                name_match = re.search(r'textbox "Full name"[^\n]*\[ref=([^\]]+)\]', text)
                email_match = re.search(r'textbox "Email"[^\n]*\[ref=([^\]]+)\]', text)
                name_value = re.search(r"Name: ([^\r\n]+)", facts)
                email_value = re.search(r"Email: ([^\r\n]+)", facts)
                if not all((name_match, email_match, name_value, email_value)):
                    raise AssertionError(f"Snapshot or local source facts missing: {text}")
                return [
                    {
                        "name": "Full name", "type": "textbox",
                        "ref": name_match.group(1), "value": name_value.group(1),
                    },
                    {
                        "name": "Email", "type": "textbox",
                        "ref": email_match.group(1), "value": email_value.group(1),
                    },
                ]

            def log_message(self, *_args) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}/v1"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

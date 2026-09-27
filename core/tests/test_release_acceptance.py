"""Opt-in clean-user release acceptance through the packaged Electron product."""

from __future__ import annotations

import csv
import ctypes
import http.server
import json
import os
import shutil
import socket
import subprocess
import threading
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any

import httpx
import pytest
from websockets.sync.client import connect


@pytest.mark.skipif(
    os.environ.get("ATLAS_P17A_RUN_RELEASE_ACCEPTANCE") != "1",
    reason="set ATLAS_P17A_RUN_RELEASE_ACCEPTANCE=1 to run packaged desktop acceptance",
)
def test_clean_packaged_daily_usability_twice(tmp_path: Path) -> None:
    resources = Path(
        os.environ.get(
            "ATLAS_P17A_RESOURCES_DIR",
            Path(__file__).parents[1]
            / "frontend"
            / "windows-release"
            / "win-unpacked"
            / "resources"
            / "atlas",
        )
    )
    executable = resources.parents[1] / "Atlas.exe"
    node_dir = resources / "runtime" / "node"
    backend = resources / "backend" / "atlas_backend.exe"
    assert executable.is_file(), executable
    assert backend.is_file(), backend
    assert (node_dir / "node.exe").is_file(), node_dir

    provider = _LocalOpenAIProvider()
    shared_npm_cache = tmp_path / "clean-npm-cache"
    try:
        for iteration in range(1, 3):
            _run_clean_user_flow(
                resources=resources,
                executable=executable,
                node_dir=node_dir,
                runtime_dir=tmp_path / f"clean-user-{iteration}",
                npm_cache=shared_npm_cache,
                provider=provider,
                iteration=iteration,
            )
    finally:
        provider.close()


@pytest.mark.skipif(
    os.environ.get("ATLAS_P17B_RUN_INSTALLER_ACCEPTANCE") != "1",
    reason="set ATLAS_P17B_RUN_INSTALLER_ACCEPTANCE=1 to run NSIS install lifecycle acceptance",
)
def test_nsis_install_uninstall_reinstall_acceptance(tmp_path: Path) -> None:
    repository = Path(__file__).parents[2]
    installer = Path(
        os.environ.get(
            "ATLAS_P17B_INSTALLER",
            repository / "frontend" / "windows-release" / "Atlas-0.1.0-Setup.exe",
        )
    )
    assert installer.is_file(), f"NSIS installer is missing: {installer}"

    install_dir = Path(
        os.environ.get("ATLAS_P17B_INSTALL_DIR", f"D:\\P17B-{os.getpid():x}")
    )
    runtime_dir = tmp_path / "isolated-user"
    npm_cache = tmp_path / "isolated-npm-cache"
    assert not install_dir.exists(), f"isolated install target already exists: {install_dir}"
    install_dir.mkdir()
    _install_nsis(installer, install_dir)
    executable, resources, node_dir = _installed_paths(install_dir)
    _assert_installed_paths_are_self_contained(repository, resources)

    provider = _LocalOpenAIProvider()
    try:
        _run_clean_user_flow(
            resources=resources,
            executable=executable,
            node_dir=node_dir,
            runtime_dir=runtime_dir,
            npm_cache=npm_cache,
            provider=provider,
            iteration=1,
        )

        data_dir = runtime_dir / "atlas-data"
        profile_dir = runtime_dir / "windows-profile"
        user_data_before = _snapshot_files(data_dir, profile_dir)
        assert user_data_before, "NSIS-installed Atlas produced no persistent user data"
        _uninstall_nsis(install_dir)
        assert _snapshot_files(data_dir, profile_dir) == user_data_before, (
            "NSIS uninstall changed or removed isolated user data"
        )

        install_dir.mkdir(exist_ok=True)
        _install_nsis(installer, install_dir)
        executable, resources, node_dir = _installed_paths(install_dir)
        _assert_installed_paths_are_self_contained(repository, resources)
        _verify_reinstalled_user_state(
            executable=executable,
            resources=resources,
            node_dir=node_dir,
            runtime_dir=runtime_dir,
            npm_cache=npm_cache,
        )
        _uninstall_nsis(install_dir)
    finally:
        provider.close()


def _install_nsis(installer: Path, install_dir: Path) -> None:
    subprocess.run(
        [str(installer), "/S", f"/D={install_dir}"],
        check=True,
        timeout=240,
    )


def _uninstall_nsis(install_dir: Path) -> None:
    uninstaller = install_dir / "Uninstall Atlas.exe"
    assert uninstaller.is_file(), f"NSIS uninstaller is missing: {uninstaller}"
    subprocess.run([str(uninstaller), "/S"], check=True, timeout=180)
    deadline = time.monotonic() + 120
    while (
        install_dir.exists()
        and any(install_dir.iterdir())
        and time.monotonic() < deadline
    ):
        time.sleep(0.5)
    remaining_files = (
        [
            str(item.relative_to(install_dir))
            for item in install_dir.rglob("*")
            if item.is_file()
        ]
        if install_dir.exists()
        else []
    )
    allowed_metadata = {"uninstall atlas.exe", "unins000.dat"}
    unexpected_files = [
        name for name in remaining_files if Path(name).name.casefold() not in allowed_metadata
    ]
    assert not unexpected_files, (
        f"NSIS uninstall left application files in the isolated install directory: "
        f"{unexpected_files[:12]}"
    )


def _installed_paths(install_dir: Path) -> tuple[Path, Path, Path]:
    executable = install_dir / "Atlas.exe"
    resources = install_dir / "resources" / "atlas"
    node_dir = resources / "runtime" / "node"
    assert executable.is_file(), f"installed Atlas executable is missing: {executable}"
    assert (resources / "backend" / "atlas_backend.exe").is_file()
    assert (node_dir / "node.exe").is_file()
    return executable, resources, node_dir


def _assert_installed_paths_are_self_contained(repository: Path, resources: Path) -> None:
    expected = [
        resources / "backend" / "atlas_backend.exe",
        resources / "runtime" / "node" / "node.exe",
    ]
    for path in expected:
        assert path.is_file() and path.is_relative_to(resources), (
            f"installed resource does not resolve inside the installation: {path}"
        )
    root_text = str(repository).replace("/", "\\").casefold()
    for relative in ("config/atlas.example.toml", "runtime/node/node-runtime.json"):
        text = (resources / relative).read_text(encoding="utf-8").casefold()
        assert root_text not in text, (
            f"installed metadata references the development checkout: {relative}"
        )
    forbidden_names = {"atlas.toml", ".env", "user-settings.json"}
    forbidden_suffixes = {".db", ".db-journal", ".log"}
    for item in resources.rglob("*"):
        if item.is_file():
            assert item.name.casefold() not in forbidden_names, (
                f"user configuration or secret file was packaged: {item.relative_to(resources)}"
            )
            assert item.suffix.casefold() not in forbidden_suffixes, (
                f"user database/log was packaged: {item.relative_to(resources)}"
            )


def _snapshot_files(*roots: Path) -> dict[str, int]:
    snapshot: dict[str, int] = {}
    for root in roots:
        if root.exists():
            for item in root.rglob("*"):
                if item.is_file():
                    snapshot[str(item)] = item.stat().st_size
    return snapshot


def _verify_reinstalled_user_state(
    *,
    executable: Path,
    resources: Path,
    node_dir: Path,
    runtime_dir: Path,
    npm_cache: Path,
) -> None:
    profile = runtime_dir / "windows-profile"
    env = os.environ.copy()
    env["PATH"] = _without_system_node(env.get("PATH", ""))
    port = _free_port()
    debug_port = _free_port()
    env.update(
        {
            "APPDATA": str(profile / "roaming"),
            "LOCALAPPDATA": str(profile / "local"),
            "ATLAS_ROOT": str(resources),
            "ATLAS_DATA_DIR": str(runtime_dir / "atlas-data"),
            "ATLAS_NODE_RUNTIME_DIR": str(node_dir),
            "ATLAS_NODE_RUNTIME_REQUIRED": "1",
            "ATLAS_PORT": str(port),
            "ATLAS_SCHEDULER_ENABLED": "false",
            "ATLAS_DEBUG_BACKEND": "1",
            "npm_config_cache": str(npm_cache),
            "npm_config_yes": "true",
        }
    )
    for name in ("ATLAS_API_BASE", "ATLAS_API_KEY", "ATLAS_API_BASE_URL", "VITE_API_BASE_URL"):
        env.pop(name, None)
    env.pop("VITE_DEV_SERVER_URL", None)
    baseline_node_pids = _process_pids("node.exe")
    baseline_backend_pids = _process_pids("atlas_backend.exe")
    process = subprocess.Popen(
        [str(executable), f"--remote-debugging-port={debug_port}", "--remote-allow-origins=*"],
        cwd=runtime_dir,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    try:
        base_url = f"http://127.0.0.1:{port}"
        _wait_for_health(base_url, process, runtime_dir / "atlas-desktop.log")
        with httpx.Client(trust_env=False, timeout=10) as http:
            config = http.get(f"{base_url}/api/settings/configuration").json()
            assert config["api_key_configured"] is True
            assert config["current"] == "gpt-4o-mini"
            assert "p17a-local-secret-1" not in json.dumps(config)
            conversations = http.get(f"{base_url}/api/conversations").json()
            assert any(
                "P17A_FIRST_TURN_DONE" in str(item)
                for item in [
                    http.get(f"{base_url}/api/conversations/{row['id']}/messages").json()
                    for row in conversations
                ]
            ), "conversation history was not available after reinstall"
    finally:
        if process.poll() is None:
            _close_packaged_app(
                process,
                debug_port,
                f"http://127.0.0.1:{port}",
                baseline_node_pids,
                baseline_backend_pids,
            )


class _LocalOpenAIProvider:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.responses_sent = 0
        self.skill_context_seen: list[bool] = []
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.requests.append(body)
                messages = body.get("messages", [])
                user_message = next(
                    (
                        str(item.get("content", ""))
                        for item in reversed(messages)
                        if item.get("role") == "user"
                    ),
                    "",
                )
                tool_messages = [item for item in messages if item.get("role") == "tool"]
                available_tools = body.get("tools", [])
                has_read_file = any(
                    item.get("function", {}).get("name") == "filesystem__read_file"
                    for item in available_tools
                )
                if "P17A_READ_FILE" in user_message and has_read_file and not tool_messages:
                    tool = next(
                        item["function"]["name"]
                        for item in available_tools
                        if item["function"]["name"] == "filesystem__read_file"
                    )
                    chunks: list[dict[str, Any]] = [
                        {
                            "tool_call": {
                                "id": "p17a-read-file",
                                "name": tool,
                                "arguments": json.dumps({"path": owner.allowed_file}),
                            },
                        },
                        {"content": None, "finish_reason": "tool_calls"},
                    ]
                elif "P17A_READ_FILE" in user_message and tool_messages:
                    system_text = "\n".join(
                        str(item.get("content", ""))
                        for item in messages
                        if item.get("role") == "system"
                    )
                    has_skill = "简洁优先" in system_text and "coding-discipline" in system_text
                    owner.skill_context_seen.append(has_skill)
                    marker = owner.allowed_marker if has_skill else "P17A_SKILL_CONTEXT_MISSING"
                    chunks = [
                        {"content": "P17A_MCP_SKILL_"},
                        {"content": f"{marker}_OK"},
                        {"content": None, "finish_reason": "stop"},
                    ]
                else:
                    marker = (
                        "P17A_FIRST_TURN_DONE"
                        if "P17A_FIRST_TURN" in user_message
                        else "P17A_SECOND_TURN_DONE"
                    )
                    chunks = [
                        {"content": "P17A_STREAM_"},
                        {"content": marker},
                        {"content": None, "finish_reason": "stop"},
                    ]

                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                for chunk in chunks:
                    delta: dict[str, Any] = {}
                    if "content" in chunk:
                        delta["content"] = chunk["content"]
                    if "tool_call" in chunk:
                        call = chunk["tool_call"]
                        delta["tool_calls"] = [
                            {
                                "index": 0,
                                "id": call["id"],
                                "type": "function",
                                "function": {"name": call["name"], "arguments": call["arguments"]},
                            }
                        ]
                    value = {
                        "id": "chatcmpl-p17a-acceptance",
                        "object": "chat.completion.chunk",
                        "created": 0,
                        "model": "gpt-4o-mini",
                        "choices": [
                            {
                                "index": 0,
                                "delta": delta,
                                "finish_reason": chunk.get("finish_reason"),
                            }
                        ],
                    }
                    self.wfile.write(f"data: {json.dumps(value)}\n\n".encode())
                    self.wfile.flush()
                    time.sleep(0.12)
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
                owner.responses_sent += 1
                self.close_connection = True

            def log_message(self, format: str, *args: object) -> None:
                return

        self.allowed_file = ""
        self.allowed_marker = ""
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}/v1"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class _DevTools:
    def __init__(self, endpoint: str) -> None:
        self.socket = connect(endpoint, open_timeout=10, close_timeout=5)
        self.next_id = 1

    def evaluate(self, expression: str) -> Any:
        result = self.command(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        if "exceptionDetails" in result:
            raise AssertionError(result["exceptionDetails"])
        return result.get("result", {}).get("value")

    def command(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        command_id = self.next_id
        self.next_id += 1
        self.socket.send(
            json.dumps(
                {
                    "id": command_id,
                    "method": method,
                    "params": params,
                }
            )
        )
        while True:
            message = json.loads(self.socket.recv(timeout=15))
            if message.get("id") != command_id:
                continue
            return message.get("result", {})

    def close(self) -> None:
        self.socket.close()


def _run_clean_user_flow(
    *,
    resources: Path,
    executable: Path,
    node_dir: Path,
    runtime_dir: Path,
    npm_cache: Path,
    provider: _LocalOpenAIProvider,
    iteration: int,
) -> None:
    data_dir = runtime_dir / "atlas-data"
    profile = runtime_dir / "windows-profile"
    for directory in (data_dir, profile / "roaming", profile / "local", runtime_dir / "allowed"):
        directory.mkdir(parents=True)
    marker = f"P17A_FILESYSTEM_MARKER_{iteration}"
    allowed_file = runtime_dir / "allowed" / "readme.txt"
    allowed_file.write_text(marker, encoding="utf-8")
    provider.allowed_file = str(allowed_file)
    provider.allowed_marker = marker

    port = _free_port()
    debug_port = _free_port()
    baseline_node_pids = _process_pids("node.exe")
    baseline_backend_pids = _process_pids("atlas_backend.exe")
    env = os.environ.copy()
    env["PATH"] = _without_system_node(env.get("PATH", ""))
    env.update(
        {
            "APPDATA": str(profile / "roaming"),
            "LOCALAPPDATA": str(profile / "local"),
            "ATLAS_ROOT": str(resources),
            "ATLAS_DATA_DIR": str(data_dir),
            "ATLAS_NODE_RUNTIME_DIR": str(node_dir),
            "ATLAS_NODE_RUNTIME_REQUIRED": "1",
            "ATLAS_PORT": str(port),
            "ATLAS_SCHEDULER_ENABLED": "false",
            "ATLAS_DEBUG_BACKEND": "1",
            "npm_config_cache": str(npm_cache),
            "npm_config_yes": "true",
        }
    )
    env.pop("ATLAS_API_BASE", None)
    env.pop("ATLAS_API_KEY", None)
    env.pop("ATLAS_API_BASE_URL", None)
    env.pop("VITE_API_BASE_URL", None)
    env.pop("VITE_DEV_SERVER_URL", None)
    assert shutil.which("node", path=env["PATH"]) is None

    log_path = runtime_dir / "atlas-desktop.log"
    process: subprocess.Popen[bytes] | None = None
    devtools: _DevTools | None = None
    conversation_id = ""
    with log_path.open("wb") as log_file:
        process = subprocess.Popen(
            [str(executable), f"--remote-debugging-port={debug_port}", "--remote-allow-origins=*"],
            cwd=runtime_dir,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        base_url = f"http://127.0.0.1:{port}"
        try:
            _wait_for_health(base_url, process, log_path)
            target = _wait_for_devtools_target(debug_port, process, log_path)
            devtools = _DevTools(target)
            desktop_api_base = devtools.evaluate("window.atlasDesktop?.apiBaseUrl ?? null")
            bridge_info = devtools.evaluate(
                "JSON.stringify({ type: typeof window.atlasDesktop, "
                "keys: Object.keys(window.atlasDesktop ?? {}), "
                "platform: window.atlasDesktop?.platform })"
            )
            assert desktop_api_base == base_url, (
                "packaged renderer API base did not use its isolated backend: "
                f"{desktop_api_base}; desktop bridge: {bridge_info}"
            )
            _wait_dom(
                devtools, "document.body.innerText.includes('首次设置')", "first-run Settings"
            )
            assert devtools.evaluate("document.body.innerText.includes('Atlas 后端已连接')")

            _set_value(devtools, "input[type='url']", provider.base_url)
            _set_value(devtools, "input[type='password']", f"p17a-local-secret-{iteration}")
            _click_button(devtools, "保存 API 配置")
            with httpx.Client(trust_env=False) as http:
                config = _wait_for_configuration(http, base_url, provider.base_url)
                assert config["api_key_configured"] is True
                assert f"p17a-local-secret-{iteration}" not in json.dumps(config)

            _click_button(devtools, "gpt-4o-mini")
            _wait_http_json(
                base_url,
                "/api/settings/configuration",
                lambda value: value.get("current") == "gpt-4o-mini",
            )
            _click_button(devtools, "返回对话")
            before_new_conversation = _wait_http_json(
                base_url, "/api/conversations", lambda value: isinstance(value, list)
            )
            _wait_dom(
                devtools,
                "!document.querySelector('aside button[aria-label=\"新建对话\"]').disabled",
                "new conversation control ready",
            )
            _click_selector(devtools, 'aside button[aria-label="新建对话"]')
            _wait_http_json(
                base_url,
                "/api/conversations",
                lambda value: any(
                    item["id"] not in {old["id"] for old in before_new_conversation}
                    for item in value
                ),
            )
            _wait_dom(
                devtools,
                "document.querySelector('textarea[placeholder^=\"继续告诉 Atlas\"]') !== null",
                "chat composer",
            )
            _send_message(devtools, "P17A_FIRST_TURN")
            try:
                _wait_dom(
                    devtools,
                    "document.body.innerText.includes('P17A_STREAM_')",
                    "first streamed chunk",
                )
            except AssertionError as exc:
                raise AssertionError(
                    f"{exc}; deterministic provider requests: {len(provider.requests)}"
                ) from exc
            _wait_dom(
                devtools,
                "document.body.innerText.includes('P17A_FIRST_TURN_DONE')",
                "first completed turn",
            )
            try:
                _wait_dom(
                    devtools,
                    "document.body.innerText.includes('completed')",
                    "terminal run completion",
                )
            except AssertionError as exc:
                raise AssertionError(
                    f"{exc}; deterministic provider requests={len(provider.requests)}, "
                    f"responses_sent={provider.responses_sent}"
                ) from exc

            with httpx.Client(trust_env=False) as http:
                conversations = _wait_http_json(
                    base_url, "/api/conversations", lambda value: bool(value)
                )
                conversation_id = conversations[0]["id"]
                assert any(item["id"] == conversation_id for item in conversations)
                messages = _wait_http_json(
                    base_url,
                    f"/api/conversations/{conversation_id}/messages",
                    lambda value: len(value) >= 2,
                )
                assert [item["role"] for item in messages] == ["user", "assistant"]
                assert "P17A_FIRST_TURN_DONE" in messages[-1]["content"]

            _click_selector(devtools, 'aside button[aria-label="新建对话"]')
            _wait_dom(
                devtools,
                "document.body.innerText.includes('New conversation')",
                "switch to another conversation",
            )
            first_title = "P17A_FIRST_TURN"
            _click_button(devtools, first_title)
            _wait_dom(
                devtools,
                "document.body.innerText.includes('P17A_FIRST_TURN_DONE')",
                "reopen conversation history",
            )
            devtools.close()
            devtools = None
            _close_packaged_app(
                process,
                debug_port,
                base_url,
                baseline_node_pids,
                baseline_backend_pids,
            )
            process = None

        finally:
            if devtools is not None:
                devtools.close()
            if process is not None and process.poll() is None:
                _emergency_stop(process)

    process = subprocess.Popen(
        [str(executable), f"--remote-debugging-port={debug_port}", "--remote-allow-origins=*"],
        cwd=runtime_dir,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    devtools = None
    try:
        _wait_for_health(base_url, process, log_path)
        target = _wait_for_devtools_target(debug_port, process, log_path)
        devtools = _DevTools(target)
        _wait_dom(
            devtools,
            "document.querySelector('textarea[placeholder^=\"继续告诉 Atlas\"]') !== null",
            "relaunch chat",
        )
        with httpx.Client(trust_env=False) as http:
            config = http.get(f"{base_url}/api/settings/configuration", timeout=10).json()
            assert config["gateway_base_url"] == provider.base_url
            assert config["api_key_configured"] is True
            assert config["current"] == "gpt-4o-mini"
            assert f"p17a-local-secret-{iteration}" not in json.dumps(config)
            conversations = http.get(f"{base_url}/api/conversations", timeout=10).json()
            assert any(item["id"] == conversation_id for item in conversations)
            messages = http.get(
                f"{base_url}/api/conversations/{conversation_id}/messages", timeout=10
            ).json()
            assert any(item["content"] == "P17A_FIRST_TURN" for item in messages)
            assert any("P17A_FIRST_TURN_DONE" in item["content"] for item in messages)
            assert any(
                item["name"] == "coding-discipline"
                for item in http.get(f"{base_url}/api/skills", timeout=10).json()["skills"]
            )
            registry = http.get(f"{base_url}/api/skill-registry", timeout=10).json()
            assert any(item["name"] == "coding-discipline" for item in registry["skills"])

        _click_button(devtools, first_title)
        _wait_dom(
            devtools,
            "document.body.innerText.includes('P17A_FIRST_TURN_DONE')",
            "restored conversation in renderer",
        )
        _send_message(devtools, "P17A_SECOND_TURN")
        _wait_dom(
            devtools, "document.body.innerText.includes('P17A_STREAM_')", "second streamed chunk"
        )
        _wait_dom(
            devtools,
            "document.body.innerText.includes('P17A_SECOND_TURN_DONE')",
            "second turn after restart",
        )

        allowed_dir = runtime_dir / "allowed"
        with httpx.Client(trust_env=False, timeout=90) as http:
            report = http.get(f"{base_url}/api/runtime/dependency-check", timeout=15).json()
            assert report["node"]["source"] == "bundled", report
            assert report["node"]["version"] == "v22.23.3", report
            assert report["node"]["system"]["available"] is False, report
            added = http.post(
                f"{base_url}/api/mcp/servers",
                json={
                    "name": "filesystem",
                    "transport": "stdio",
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-filesystem", str(allowed_dir)],
                },
            )
            assert added.status_code == 200, added.text
            tools = http.get(f"{base_url}/api/tools", timeout=15).json()["tools"]
            assert any(tool["name"] == "filesystem__read_file" for tool in tools)
            servers = http.get(f"{base_url}/api/runtime/dependency-check", timeout=15).json()[
                "mcp_servers"
            ]
            filesystem = next(item for item in servers if item["name"] == "filesystem")
            assert filesystem["connected"] and filesystem["tool_discovery"] == "complete"
            skill = http.get(
                f"{base_url}/api/skills/coding-discipline/dependencies", timeout=10
            ).json()
            assert skill["read_only"] and skill["can_activate"] and skill["blocking"] == []

        _click_button(devtools, "技能发现")
        _set_value(devtools, "input[aria-label='任务或技能搜索']", "coding-discipline")
        _wait_dom(
            devtools,
            "[...document.querySelectorAll('button')].some(button => "
            "button.innerText.includes('搜索技能') && !button.disabled)",
            "Skill search ready",
        )
        _click_button(devtools, "搜索技能")
        _wait_dom(
            devtools,
            "document.body.innerText.includes('coding-discipline')",
            "local Skill discovery result",
        )
        _click_button(devtools, "coding-discipline")
        _wait_dom(
            devtools, "document.body.innerText.includes('无声明依赖。')", "visible Skill preflight"
        )
        _click_button(devtools, "打开本地技能")
        _wait_dom(
            devtools,
            "document.body.innerText.includes('简洁优先')",
            "registry-activated Skill content",
        )
        if devtools.evaluate(
            "[...document.querySelectorAll('button')].some(button => "
            "button.innerText.includes('应用到后续 Agent 对话'))"
        ):
            _click_button(devtools, "应用到后续 Agent 对话")
        else:
            assert devtools.evaluate(
                "[...document.querySelectorAll('button')].some(button => "
                "button.innerText.includes('从后续对话移除此技能'))"
            ), (
                "Skill activation controls missing: "
                f"{devtools.evaluate('document.body.innerText.slice(-1200)')}"
            )
        _wait_dom(
            devtools,
            "document.body.innerText.includes('此技能会在后续运行时由 Registry 重新校验并应用。')",
            "visible active Skill state",
        )
        _click_button(devtools, "对话")
        _send_message(
            devtools,
            f"P17A_READ_FILE 请按 coding-discipline 指引读取文件并简短说明依据："
            f"{provider.allowed_marker} {provider.allowed_file}",
        )
        _wait_dom(
            devtools,
            "document.body.innerText.includes('P17A_MCP_SKILL_')",
            "Agent MCP plus active Skill response",
        )
        _wait_dom(
            devtools,
            "document.body.innerText.includes('filesystem__read_file')",
            "renderer ToolCard",
        )
        assert provider.skill_context_seen and all(provider.skill_context_seen)
        messages = _wait_http_json(
            base_url,
            f"/api/conversations/{conversation_id}/messages",
            lambda value: any("P17A_MCP_SKILL_" in item["content"] for item in value),
        )
        assert any("P17A_MCP_SKILL_" in item["content"] for item in messages)

    finally:
        if devtools is not None:
            devtools.close()
        if process.poll() is None:
            _close_packaged_app(
                process,
                debug_port,
                base_url,
                baseline_node_pids,
                baseline_backend_pids,
            )


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _without_system_node(path: str) -> str:
    entries = [
        item
        for item in path.split(os.pathsep)
        if not item
        or not any(
            (Path(item.strip('"')) / name).is_file() for name in ("node.exe", "node.cmd", "node")
        )
    ]
    return os.pathsep.join(entries)


def _wait_for_health(base_url: str, process: subprocess.Popen[bytes], log_path: Path) -> None:
    deadline = time.monotonic() + 60
    with httpx.Client(trust_env=False) as http:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                break
            try:
                response = http.get(f"{base_url}/api/health", timeout=1)
                if response.status_code == 200 and response.json().get("status") == "ok":
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.25)
    detail = (
        log_path.read_text(encoding="utf-8", errors="replace")[-5000:] if log_path.exists() else ""
    )
    raise AssertionError(f"packaged Atlas did not become healthy\n{detail}")


def _wait_for_devtools_target(
    port: int,
    process: subprocess.Popen[bytes],
    log_path: Path,
) -> str:
    deadline = time.monotonic() + 45
    url = f"http://127.0.0.1:{port}/json/list"
    with httpx.Client(trust_env=False) as http:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                break
            try:
                targets = http.get(url, timeout=1).json()
                page = next((item for item in targets if item.get("type") == "page"), None)
                if page and page.get("webSocketDebuggerUrl"):
                    return page["webSocketDebuggerUrl"]
            except (httpx.HTTPError, ValueError):
                pass
            time.sleep(0.25)
    detail = (
        log_path.read_text(encoding="utf-8", errors="replace")[-5000:] if log_path.exists() else ""
    )
    raise AssertionError(f"packaged Electron renderer DevTools did not become ready\n{detail}")


def _wait_dom(devtools: _DevTools, expression: str, description: str, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if devtools.evaluate(expression):
            return
        time.sleep(0.15)
    body_text = devtools.evaluate("document.body?.innerText.slice(0, 3000) ?? ''")
    raise AssertionError(
        f"renderer condition timed out: {description}; current page text: {body_text}"
    )


def _set_value(devtools: _DevTools, selector: str, value: str) -> None:
    expression = (
        "(() => { const element = document.querySelector(" + json.dumps(selector) + ");"
        "if (!element) return false; const setter = "
        "Object.getOwnPropertyDescriptor(Object.getPrototypeOf(element), 'value')?.set;"
        "if (!setter) return false; setter.call(element, " + json.dumps(value) + ");"
        "element.dispatchEvent(new Event('input', { bubbles: true }));"
        "element.dispatchEvent(new Event('change', { bubbles: true })); return true; })()"
    )
    assert devtools.evaluate(expression), f"renderer input not found: {selector}"


def _click_button(devtools: _DevTools, text: str) -> None:
    expression = (
        "(() => { const button = [...document.querySelectorAll('button')].find(item => "
        "item.innerText.trim().includes(" + json.dumps(text) + "));"
        "if (!button || button.disabled) return false; button.click(); return true; })()"
    )
    assert devtools.evaluate(expression), f"renderer button not found or disabled: {text}"


def _click_selector(devtools: _DevTools, selector: str) -> None:
    expression = (
        "(() => { const element = document.querySelector(" + json.dumps(selector) + ");"
        "if (!element) return false; element.click(); return true; })()"
    )
    assert devtools.evaluate(expression), f"renderer element not found: {selector}"


def _send_message(devtools: _DevTools, message: str) -> None:
    assert devtools.evaluate(
        "(() => { const input = document.querySelector("
        "'textarea[placeholder^=\\\"继续告诉 Atlas\\\"]'); "
        "if (!input) return false; input.focus(); return true; })()"
    ), "renderer composer was not available"
    devtools.command("Input.insertText", {"text": message})
    state = devtools.evaluate(
        "JSON.stringify({ value: document.querySelector("
        "'textarea[placeholder^=\\\"继续告诉 Atlas\\\"]')?.value, "
        "disabled: document.querySelector('button[aria-label=\\\"发送消息\\\"]')?.disabled })"
    )
    assert (
        state
        and json.loads(state).get("value") == message
        and not json.loads(state).get("disabled")
    ), f"renderer composer did not accept message text: {state}"
    devtools.command(
        "Input.dispatchKeyEvent",
        {"type": "keyDown", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13},
    )
    devtools.command(
        "Input.dispatchKeyEvent",
        {"type": "keyUp", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13},
    )
    remaining_text = devtools.evaluate(
        "document.querySelector('textarea[placeholder^=\\\"继续告诉 Atlas\\\"]')?.value ?? null"
    )
    assert remaining_text == "", (
        f"renderer submit did not consume the composer text: {remaining_text!r}"
    )


def _wait_for_configuration(
    http: httpx.Client,
    base_url: str,
    expected_provider: str,
) -> dict[str, Any]:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        response = http.get(f"{base_url}/api/settings/configuration", timeout=5)
        if response.status_code == 200:
            value = response.json()
            if (
                value.get("api_key_configured")
                and value.get("gateway_base_url") == expected_provider
            ):
                return value
        time.sleep(0.2)
    raise AssertionError("provider configuration was not saved through Settings")


def _wait_http_json(base_url: str, path: str, predicate: Any) -> Any:
    deadline = time.monotonic() + 20
    with httpx.Client(trust_env=False) as http:
        while time.monotonic() < deadline:
            try:
                response = http.get(base_url + path, timeout=2)
            except httpx.TimeoutException:
                time.sleep(0.2)
                continue
            if response.status_code == 200:
                value = response.json()
                if predicate(value):
                    return value
            time.sleep(0.2)
    raise AssertionError(f"product API state did not become ready: GET {path}")


def _process_pids(name: str) -> set[str]:
    result = subprocess.run(
        ["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV", "/NH"],
        check=True,
        capture_output=True,
        text=True,
    )
    return {
        row[1]
        for row in csv.reader(result.stdout.splitlines())
        if len(row) > 1 and row[0].casefold() == name.casefold()
    }


def _close_packaged_app(
    process: subprocess.Popen[bytes],
    debug_port: int,
    base_url: str,
    baseline_node_pids: set[str],
    baseline_backend_pids: set[str],
) -> None:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    windows: list[int] = []
    enum_windows_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def collect_window(hwnd: int, _lparam: int) -> bool:
        owner_pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
        if owner_pid.value == process.pid and user32.IsWindowVisible(hwnd):
            windows.append(hwnd)
        return True

    callback = enum_windows_proc(collect_window)
    if not user32.EnumWindows(callback, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    assert windows, f"packaged Electron has no visible window for PID {process.pid}"
    for hwnd in windows:
        if not user32.PostMessageW(hwnd, 0x0010, 0, 0):  # WM_CLOSE
            raise ctypes.WinError(ctypes.get_last_error())
    process.wait(timeout=45)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            with httpx.Client(trust_env=False) as http:
                http.get(f"{base_url}/api/health", timeout=0.5)
        except httpx.HTTPError:
            break
        time.sleep(0.25)
    assert process.returncode == 0, f"graceful Electron exit returned {process.returncode}"
    node_deadline = time.monotonic() + 15
    current_node_pids = _process_pids("node.exe")
    while current_node_pids != baseline_node_pids and time.monotonic() < node_deadline:
        time.sleep(0.25)
        current_node_pids = _process_pids("node.exe")
    assert _process_pids("node.exe") == baseline_node_pids, (
        f"Atlas left bundled Node/MCP process IDs after shutdown: "
        f"{sorted(current_node_pids - baseline_node_pids)}"
    )
    assert _process_pids("atlas_backend.exe") == baseline_backend_pids, (
        "Atlas left its packaged backend after shutdown"
    )


def _emergency_stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    subprocess.run(
        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
        check=False,
        capture_output=True,
        timeout=15,
    )
    process.wait(timeout=10)

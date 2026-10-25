"""U23 local scenario checks; never starts Electron or captures the desktop."""
from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path
import sys
import tempfile
import textwrap
import urllib.parse

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sdk" / "python"))
sys.path.insert(0, str(ROOT / "core"))

from atlas_sdk import AppServer  # noqa: E402
from atlas.api import cloud_documents_router as cloud  # noqa: E402


def check_window_and_capture_contracts() -> None:
    main = (ROOT / "frontend/src/main/electron.ts").read_text(encoding="utf-8")
    preload = (ROOT / "frontend/src/preload/index.cts").read_text(encoding="utf-8")
    app = (ROOT / "frontend/src/renderer/App.tsx").read_text(encoding="utf-8")
    composer = (ROOT / "frontend/src/renderer/components/Composer.tsx").read_text(encoding="utf-8")
    assert "新建窗口" in main and "新会话并在新窗口打开" in main
    assert "openNewWindow" in preload and "openNewSessionWindow" in preload
    assert "newSession" in app and "新会话并在新窗口打开" in app
    assert "types: ['window']" in main and "screenshot:capture-window" in main
    assert "listCaptureWindows" in preload and "listRecentScreenshots" in preload
    assert "删除缓存" in composer and "添加所选" in composer and "截取活动窗口" in composer


def check_app_server_sdk() -> None:
    mock_server = r'''
import json, sys
for line in sys.stdin:
    request = json.loads(line)
    method, params, request_id = request.get("method"), request.get("params", {}), request.get("id")
    if method == "initialize":
        result = {"protocolVersion": 1, "serverInfo": {"name": "mock", "version": "1"}, "capabilities": {}}
    elif method == "tools/list":
        result = {"tools": [{"type": "function", "function": {"name": "read_file"}}]}
    elif method == "session/start":
        result = {"session_id": "session-1", "conversation_id": "conversation-1", "workspace": params["workspace"]}
    elif method == "session/prompt":
        print(json.dumps({"jsonrpc":"2.0", "method":"session/event", "params":{"session_id":params["session_id"], "event":{"type":"chunk", "content":"ok"}}}), flush=True)
        result = {"session_id": params["session_id"], "text": "ok", "status": "completed"}
    elif method == "session/close":
        result = {"closed": True}
    else:
        print(json.dumps({"jsonrpc":"2.0", "id":request_id, "error":{"code":-32601,"message":"unknown"}}), flush=True)
        continue
    print(json.dumps({"jsonrpc":"2.0", "id":request_id, "result":result}), flush=True)
'''
    with tempfile.TemporaryDirectory(prefix="atlas-u23-sdk-") as temporary:
        script = Path(temporary) / "mock_app_server.py"
        script.write_text(textwrap.dedent(mock_server), encoding="utf-8")
        observed: list[dict[str, object]] = []
        with AppServer([sys.executable, str(script)], workspace=temporary) as client:
            tools = client.list_tools()
            session = client.new_session()
            result = client.prompt(session.session_id, "Reply ok", on_event=observed.append)
            client.close_session(session.session_id)
        assert tools[0]["function"]["name"] == "read_file"
        assert session.conversation_id == "conversation-1" and result.text == "ok" and result.status == "completed"
        assert observed == [{"type": "chunk", "content": "ok"}]


def check_live_app_server_model() -> None:
    if os.environ.get("U23_SKIP_LIVE_MODEL") == "1":
        return
    # The checked-out worktree supplies code, while the active Atlas data root
    # supplies the model route and local credentials. Keep those roots explicit
    # so this scenario behaves the same from a detached worktree.
    configured_root = Path(os.environ.get("ATLAS_U23_DATA_ROOT", r"C:\engine-reg\atlas-work")).resolve()
    env = {**os.environ, "ATLAS_ROOT": str(configured_root), "ATLAS_DATA_DIR": str(configured_root),
           "PYTHONPATH": str(ROOT / "core") + os.pathsep + os.environ.get("PYTHONPATH", "")}
    stage = "launch"
    diagnostic = ""
    try:
        with AppServer([sys.executable, "-m", "atlas.cli"], workspace=ROOT, env=env) as client:
            stage = "start-session"
            session = client.new_session()
            stage = "prompt"
            result = client.prompt(session.session_id, "只回复：U23_APP_SERVER_OK。不要调用任何工具。")
            if result.status != "completed" or "U23_APP_SERVER_OK" not in result.text:
                diagnostic = (
                    f"model response mismatch: status={result.status!r}, "
                    f"chars={len(result.text)}, marker_present={'U23_APP_SERVER_OK' in result.text}"
                )
                raise AssertionError("live model response mismatch")
            client.close_session(session.session_id)
    except Exception as exc:
        # Never include protocol payloads, response text, command lines or config values.
        detail = diagnostic or f"error_type={type(exc).__name__}"
        raise RuntimeError(f"live app-server model scenario failed at {stage}: {detail}") from None


async def check_cloud_imports() -> None:
    original_client, original_access = cloud.httpx.AsyncClient, cloud._access_token
    def google(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/drive/v3/files":
            body = {"files": [{"id": "d1", "name": "Roadmap", "mimeType": "application/vnd.google-apps.document", "modifiedTime": "2026-10-25T12:00:00Z"}]}
        elif path == "/drive/v3/files/d1":
            body = {"id": "d1", "name": "Roadmap", "mimeType": "application/vnd.google-apps.document", "webViewLink": "https://drive.google.com/open?id=d1"}
        elif path == "/drive/v3/files/d1/export":
            return httpx.Response(200, text="milestone alpha", request=request)
        elif path == "/gmail/v1/users/me/messages":
            body = {"messages": [{"id": "m1"}]}
        elif path == "/gmail/v1/users/me/messages/m1" and request.url.params.get("format") == "metadata":
            body = {"id": "m1", "snippet": "Meeting notes", "payload": {"headers": [{"name":"Subject", "value":"Planning"}, {"name":"From", "value":"dev@example.test"}, {"name":"Date", "value":"Sun, 25 Oct 2026 12:00:00 +0000"}]}}
        elif path == "/gmail/v1/users/me/messages/m1":
            encoded = base64.urlsafe_b64encode(b"ship it").decode().rstrip("=")
            body = {"id":"m1", "snippet":"fallback", "payload":{"headers":[{"name":"Subject","value":"Planning"}], "mimeType":"text/plain", "body":{"data":encoded}}}
        else:
            return httpx.Response(404, json={"error":"not found"}, request=request)
        return httpx.Response(200, json=body, request=request)

    class FakeClient:
        def __init__(self, *args: object, **kwargs: object):
            self.client = original_client(transport=httpx.MockTransport(google), **kwargs)
        async def __aenter__(self):
            return await self.client.__aenter__()
        async def __aexit__(self, *args: object):
            return await self.client.__aexit__(*args)

    cloud.httpx.AsyncClient = FakeClient  # type: ignore[assignment]
    async def fake_access() -> str:
        return "local-fake-token"
    cloud._access_token = fake_access
    try:
        drive = await cloud.google_items(source="drive", q="Roadmap")
        drive_import = await cloud.import_google_item("drive", "d1")
        gmail = await cloud.google_items(source="gmail", q="Planning")
        gmail_import = await cloud.import_google_item("gmail", "m1")
        assert drive["items"][0]["name"] == "Roadmap" and drive_import["content"] == "milestone alpha"
        assert drive_import["source_url"].endswith("id=d1")
        assert gmail["items"][0]["from"] == "dev@example.test" and "ship it" in gmail_import["content"]
    finally:
        cloud.httpx.AsyncClient = original_client  # type: ignore[assignment]
        cloud._access_token = original_access


async def check_google_oauth_loopback() -> None:
    original_client, original_id, original_token_path = cloud.httpx.AsyncClient, cloud._client_id, cloud._TOKEN_PATH
    with tempfile.TemporaryDirectory(prefix="atlas-u23-google-") as temporary:
        cloud._TOKEN_PATH = Path(temporary) / "google.json"
        cloud._client_id = lambda: "1234567890-desktop.apps.googleusercontent.com"

        def fake_google(request: httpx.Request) -> httpx.Response:
            if request.url.host == "oauth2.googleapis.com" and request.url.path == "/token":
                return httpx.Response(200, json={"access_token":"mock-access", "refresh_token":"mock-refresh", "expires_in":3600}, request=request)
            if request.url.host == "gmail.googleapis.com" and request.url.path == "/gmail/v1/users/me/profile":
                return httpx.Response(200, json={"emailAddress":"test@example.invalid"}, request=request)
            return httpx.Response(404, json={}, request=request)

        class FakeClient:
            def __init__(self, *args: object, **kwargs: object):
                self.client = original_client(transport=httpx.MockTransport(fake_google), **kwargs)
            async def __aenter__(self):
                return await self.client.__aenter__()
            async def __aexit__(self, *args: object):
                return await self.client.__aexit__(*args)

        cloud.httpx.AsyncClient = FakeClient  # type: ignore[assignment]
        try:
            result = await cloud.google_authorize()
            params = urllib.parse.parse_qs(urllib.parse.urlsplit(result["authorization_url"]).query)
            assert "code_challenge" in params and params["code_challenge_method"] == ["S256"]
            redirect_uri = params["redirect_uri"][0]
            async with original_client(timeout=5) as browser:
                response = await browser.get(redirect_uri, params={"code":"local-fake-code", "state":params["state"][0]})
            assert response.status_code == 200
            for _ in range(30):
                if (await cloud.google_status())["connected"]:
                    break
                await asyncio.sleep(0.05)
            status = await cloud.google_status()
            assert status["connected"] and json.loads(cloud._TOKEN_PATH.read_text(encoding="utf-8"))["refresh_token"] == "mock-refresh"
        finally:
            cloud.httpx.AsyncClient = original_client  # type: ignore[assignment]
            cloud._client_id = original_id
            cloud._TOKEN_PATH = original_token_path


def main() -> None:
    check_window_and_capture_contracts()
    check_app_server_sdk()
    check_live_app_server_model()
    asyncio.run(check_cloud_imports())
    asyncio.run(check_google_oauth_loopback())
    print("U23 CHECK PASS")


if __name__ == "__main__":
    main()

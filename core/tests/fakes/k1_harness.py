"""K1 daily-path harness: real Atlas HTTP/WS backend + scripted fake model.

Reuses the C1 isolated-backend launcher (one fresh ``atlas.server`` subprocess
per test on an ephemeral port, isolated ``ATLAS_DATA_DIR``/``HERMES_HOME``,
scheduler off) so the daily scenarios drive the real server, runtime, tools and
event protocol. Only the LLM provider is fake and loopback-only.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest_asyncio

from tests.fakes.fake_llm_provider import FakeLLMServer, Text, write_hermes_home
from tests.test_c1_websocket_acceptance import IsolatedBackend

TOKEN = "c1-isolated-token"
TERMINAL_EVENTS = {"run.completed", "run.failed", "run.cancelled"}


@pytest_asyncio.fixture
async def k1_backend(tmp_path):
    (tmp_path / "workspace").mkdir()
    with FakeLLMServer() as fake:
        server = IsolatedBackend(tmp_path, fake)
        try:
            await server.ready()
            # Auxiliary calls (task planner, compression summaries, judges) must
            # never eat a scripted main turn; answer the planner with a valid
            # plan object and everything else with a generic summary.
            def default_aux(record):
                body = json.dumps(record, ensure_ascii=False)
                if "goal and subtasks" in body:
                    return Text('{"goal":"finish the requested task","subtasks":'
                                '[{"id":"step-1","title":"complete the requested task",'
                                '"verification":"the requested task is done"}]}')
                return Text("Fake summary of the earlier conversation.")

            fake._aux = default_aux
            yield server
        finally:
            await server.close()


class RestartableBackend(IsolatedBackend):
    """Same isolated launcher, tolerant of an already-populated data directory.

    Used by the restart scenario: the first instance is an ordinary
    :class:`IsolatedBackend`; the "restarted" instance points at a copy of the
    first instance's ``atlas`` data dir, which already exists.
    """

    def __init__(self, root, fake):
        data = root / "atlas"
        data.mkdir(parents=True, exist_ok=True)
        self._init_common(root, fake, data)

    def _init_common(self, root, fake, data):
        # Mirror of IsolatedBackend.__init__ with exist_ok-tolerant directory
        # creation; kept local so the shared C1 test module stays untouched.
        import socket as _socket

        with _socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        assert self.port != 8765
        self.url = f"http://127.0.0.1:{self.port}"
        self.events = []
        config = data / "config/atlas.toml"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(
            '[models]\ndefault="fake-model"\n'
            f'[models.gateway]\nbase_url="{fake.base_url}"\napi_key="sk-fake-e2e"\n'
            '[[models.custom]]\nid="fake-model"\nname="Fake fixture"\nprovider="openai"\n'
            'litellm_model="openai/fake-model"\nmax_output_tokens=512\n'
            '[agent]\nengine="hermes"\nverify_before_stop=false\n'
            '[tools]\nauto_start=[]\n[tools.servers]\n'
            '[scheduler]\nenabled=false\n', encoding="utf-8")
        write_hermes_home(
            data / "engine", fake.base_url,
            extra_config="auxiliary:\n  title_generation:\n    model_upgrade_enabled: false\n")
        env = dict(os.environ)
        secret_markers = ("API_KEY", "ACCESS_KEY", "SECRET", "TOKEN", "PASSWORD", "PASSWD",
                          "CREDENTIAL", "AUTH")
        for key in list(env):
            upper_key = key.upper()
            if (any(marker in upper_key for marker in secret_markers)
                    or upper_key.startswith("HERMES_SESSION_")
                    or upper_key.endswith("_PROXY")):
                env.pop(key, None)
        for key in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "TMPDIR"):
            directory = root / key.lower()
            directory.mkdir(exist_ok=True)
            env[key] = str(directory)
        env.update(ATLAS_DATA_DIR=str(data), HERMES_HOME=str(data / "engine"),
                   ATLAS_SCHEDULER_ENABLED="false", ATLAS_API_TOKEN="c1-isolated-token",
                   ATLAS_API_KEY="sk-fake-e2e", ATLAS_API_BASE=fake.base_url,
                   NO_PROXY="127.0.0.1,localhost", HERMES_TEST_MODE="1")
        env.update(OPENAI_API_BASE=fake.base_url, OPENAI_BASE_URL=fake.base_url,
                   OPENAI_API_KEY="sk-fake-e2e")
        for key in list(env):
            if key.upper().endswith("_PROXY"):
                env.pop(key, None)
        for key in ("HERMES_SCRATCH_DIR",):
            env.pop(key, None)
        launch_root = root / "backend-cwd"
        launch_root.mkdir(exist_ok=True)
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
        self.log = (root / "backend.log").open("w", encoding="utf-8")
        self.process = subprocess.Popen([
            sys.executable, "-m", "uvicorn", "atlas.server:app", "--host", "127.0.0.1",
            "--port", str(self.port),
        ], cwd=launch_root, env=env, stdout=self.log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        self.http = httpx.AsyncClient(base_url=self.url, headers={
            "x-atlas-api-token": "c1-isolated-token"}, timeout=30)


def last_user_text(record: dict[str, Any]) -> str:
    """Text of the last user message in a recorded provider request body."""
    messages = record["body"].get("messages", [])
    last = next((m for m in reversed(messages) if m.get("role") == "user"), {})
    return str(last.get("content", ""))


async def ws_run(
    backend: IsolatedBackend,
    content: str,
    *,
    conversation: str | None = None,
    model: str | None = "fake-model",
    workspace: str | None = None,
    respond: Any = None,
    keep_reading: Any = None,
    timeout: float = 120,
    **options: Any,
) -> tuple[str, list[dict[str, Any]]]:
    """Send ``run.start`` over the real WebSocket and collect envelopes.

    Collects until a terminal event (and, when ``keep_reading(events)`` is
    given, until it returns True — for events that may trail the run, such as
    ``process.completed`` from background terminals). Returns
    ``(conversation_id, events)``.
    """
    from websockets.asyncio.client import connect

    conversation = conversation or await backend.conversation()
    run_id = uuid.uuid4().hex
    start: dict[str, Any] = {"type": "run.start", "run_id": run_id, "content": content,
        "conversation_id": conversation,
        "workspace": str(workspace or backend.root / "workspace")}
    if model is not None:
        start["model"] = model
    start.update(options)
    events: list[dict[str, Any]] = []
    async with connect(backend.url.replace("http", "ws", 1) + "/ws/chat",
                       additional_headers={"x-atlas-api-token": TOKEN}, max_size=8_000_000) as ws:
        await ws.send(json.dumps(start))
        async with asyncio.timeout(timeout):
            while True:
                event = json.loads(await ws.recv())
                events.append(event)
                if respond:
                    await respond(ws, event)
                if (event.get("run_id") == run_id and event.get("event") in TERMINAL_EVENTS
                        and (keep_reading is None or keep_reading(events))):
                    break
    return conversation, events

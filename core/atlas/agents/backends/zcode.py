"""ZCode's supported non-interactive prompt interface."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from atlas.runtime.backends import AgentEvent, AgentSession


class ZCodeBackend:
    """Run one isolated ZCode CLI prompt per Atlas Agent turn."""

    name = "zcode"

    def __init__(self, executable: str | None = None) -> None:
        self.executable = executable or shutil.which("zcode") or "zcode"
        self._sessions: dict[str, dict[str, Any]] = {}

    def _command(self, session: AgentSession, prompt: str) -> list[str]:
        executable = self.executable
        if os.name == "nt" and executable.lower().endswith((".cmd", ".bat")):
            shim = Path(executable).read_text(encoding="utf-8", errors="replace")
            match = re.search(r'(?im)^\s*node\s+"([^"]+\.cjs)"\s+%\*', shim)
            node = shutil.which("node")
            if not match or not node:
                raise RuntimeError("Cannot resolve the installed ZCode CLI JavaScript entry point")
            executable, script = node, match.group(1)
            return [
                executable, script, "--prompt", prompt, "--cwd", session.cwd or str(Path.cwd()),
                "--mode", "yolo", "--no-color",
            ]
        return [
            executable, "--prompt", prompt, "--cwd", session.cwd or str(Path.cwd()),
            "--mode", "yolo", "--no-color",
        ]

    async def start_session(self, cwd: str | None = None) -> AgentSession:
        session = AgentSession(id=str(uuid.uuid4()), cwd=str(Path(cwd or Path.cwd()).resolve()))
        self._sessions[session.id] = {"events": asyncio.Queue(), "process": None}
        return session

    async def send(self, session: AgentSession, prompt: str) -> None:
        state = self._sessions[session.id]
        if state["process"] is not None and state["process"].returncode is None:
            raise RuntimeError("zcode already has an active prompt")
        state["events"] = asyncio.Queue()
        process = await asyncio.create_subprocess_exec(
            *self._command(session, prompt),
            cwd=session.cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        state["process"] = process

        async def read(stream: asyncio.StreamReader | None, event_type: str) -> None:
            if stream is None:
                return
            while line := await stream.readline():
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    await state["events"].put(
                        AgentEvent(event_type, {"backend": self.name, "text": text})
                    )

        async def collect() -> None:
            await asyncio.gather(read(process.stdout, "text"), read(process.stderr, "progress"))
            code = await process.wait()
            await state["events"].put(
                AgentEvent("done" if code == 0 else "error", {"exit_code": code})
            )
            await state["events"].put(None)

        state["collector"] = asyncio.create_task(collect())

    async def stream_events(self, session: AgentSession) -> AsyncIterator[AgentEvent]:
        state = self._sessions[session.id]
        while True:
            event = await state["events"].get()
            if event is None:
                break
            yield event

    async def cancel(self, session: AgentSession) -> None:
        state = self._sessions.get(session.id)
        process = state and state.get("process")
        if process and process.returncode is None:
            process.terminate()
            await process.wait()

    async def resume(self, session_id: str, cwd: str | None = None) -> AgentSession:
        raise NotImplementedError("ZCode CLI mode starts isolated prompt sessions")

    async def close(self, session: AgentSession) -> None:
        state = self._sessions.get(session.id)
        if not state:
            return
        await self.cancel(session)
        self._sessions.pop(session.id, None)
        collector = state.get("collector")
        if collector:
            await asyncio.gather(collector, return_exceptions=True)


def create() -> ZCodeBackend:
    return ZCodeBackend()

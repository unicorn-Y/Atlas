"""Thin async subprocess/session bridge for external Agent CLIs."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from atlas.runtime.backends import AgentEvent, AgentSession


@dataclass
class _ProcessSession:
    session: AgentSession
    process: asyncio.subprocess.Process
    events: asyncio.Queue[AgentEvent | None]
    readers: list[asyncio.Task[None]]


class ExternalProcessAdapter:
    """Own a CLI process and normalize its stdout/stderr into Agent events."""

    def __init__(
        self,
        name: str,
        command: str,
        args: list[str] | None = None,
        *,
        protocol: str = "text",
    ) -> None:
        self.name = name
        self.command = command
        self.args = list(args or [])
        self.protocol = protocol
        self._sessions: dict[str, _ProcessSession] = {}

    async def start_session(self, cwd: str | None = None) -> AgentSession:
        working = str(Path(cwd).resolve()) if cwd else None
        process = await asyncio.create_subprocess_exec(
            self.command,
            *self.args,
            cwd=working,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=os.environ.copy(),
        )
        session = AgentSession(id=str(uuid.uuid4()), cwd=working)
        state = _ProcessSession(session, process, asyncio.Queue(), [])
        self._sessions[session.id] = state
        state.readers = [
            asyncio.create_task(self._read_stream(state, process.stdout, "text")),
            asyncio.create_task(self._read_stream(state, process.stderr, "progress")),
        ]
        return session

    async def _read_stream(
        self,
        state: _ProcessSession,
        stream: asyncio.StreamReader | None,
        event_type: str,
    ) -> None:
        if stream is None:
            return
        while line := await stream.readline():
            value = line.decode("utf-8", errors="replace").rstrip()
            if value:
                if event_type == "text" and self.protocol == "pi-rpc":
                    try:
                        message = json.loads(value)
                    except json.JSONDecodeError:
                        await state.events.put(
                            AgentEvent("progress", {"backend": self.name, "text": value})
                        )
                    else:
                        message_type = str(message.get("type", "event"))
                        await state.events.put(
                            AgentEvent(message_type, {"backend": self.name, **message})
                        )
                        if message_type in {"agent_end", "response_error"}:
                            await state.events.put(None)
                else:
                    await state.events.put(
                        AgentEvent(event_type, {"backend": self.name, "text": value})
                    )
        if all(task is asyncio.current_task() or task.done() for task in state.readers):
            await state.events.put(None)

    async def send(self, session: AgentSession, prompt: str) -> None:
        state = self._sessions.get(session.id)
        if not state or state.process.stdin is None or state.process.returncode is not None:
            raise RuntimeError(f"{self.name} session is not running")
        payload = (
            json.dumps({"type": "prompt", "message": prompt}, ensure_ascii=False)
            if self.protocol == "pi-rpc"
            else prompt.replace("\r", " ")
        )
        state.process.stdin.write((payload + "\n").encode("utf-8"))
        await state.process.stdin.drain()

    async def stream_events(self, session: AgentSession) -> AsyncIterator[AgentEvent]:
        state = self._sessions.get(session.id)
        if not state:
            raise KeyError(session.id)
        while True:
            event = await state.events.get()
            if event is None:
                break
            yield event
        if self.protocol == "pi-rpc" and state.process.returncode is None:
            return
        code = await state.process.wait()
        yield AgentEvent("done" if code == 0 else "error", {"exit_code": code})

    async def cancel(self, session: AgentSession) -> None:
        state = self._sessions.get(session.id)
        if state and state.process.returncode is None:
            if self.protocol == "pi-rpc" and state.process.stdin:
                state.process.stdin.write(b'{"type":"abort"}\n')
                await state.process.stdin.drain()
                return
            state.process.terminate()
            try:
                await asyncio.wait_for(state.process.wait(), timeout=3)
            except TimeoutError:
                state.process.kill()
                await state.process.wait()

    async def resume(self, session_id: str, cwd: str | None = None) -> AgentSession:
        raise NotImplementedError(f"{self.name} does not expose generic process resume")

    async def close(self, session: AgentSession) -> None:
        state = self._sessions.get(session.id)
        if not state:
            return
        if self.protocol == "pi-rpc" and state.process.returncode is None and state.process.stdin:
            state.process.stdin.write(b'{"type":"exit"}\n')
            await state.process.stdin.drain()
            try:
                await asyncio.wait_for(state.process.wait(), timeout=2)
            except TimeoutError:
                state.process.terminate()
                await state.process.wait()
        else:
            await self.cancel(session)
        self._sessions.pop(session.id, None)
        for task in state.readers:
            if not task.done():
                task.cancel()
        await asyncio.gather(*state.readers, return_exceptions=True)

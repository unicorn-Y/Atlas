"""Atlas host for launching and controlling the selected external Agents."""

from __future__ import annotations

from typing import Any

from atlas.agents.backends import create_backends
from atlas.runtime.backends import AgentBackend, AgentSession


class AgentBackendHost:
    def __init__(self, backends: dict[str, AgentBackend] | None = None) -> None:
        self.backends = backends if backends is not None else create_backends()
        self.sessions: dict[str, tuple[str, AgentSession]] = {}
        self.smoke_verified: set[str] = set()

    def names(self) -> list[str]:
        return sorted(self.backends)

    def connected_names(self) -> set[str]:
        return {name for name, _session in self.sessions.values()}

    async def start(self, name: str, cwd: str | None = None) -> AgentSession:
        backend = self.backends.get(name)
        if backend is None:
            raise KeyError(name)
        session = await backend.start_session(cwd)
        self.sessions[session.id] = (name, session)
        return session

    async def send(self, session_id: str, prompt: str) -> None:
        name, session = self.sessions[session_id]
        await self.backends[name].send(session, prompt)

    async def events(self, session_id: str) -> Any:
        name, session = self.sessions[session_id]
        async for event in self.backends[name].stream_events(session):
            if event.type in {"done", "agent_end"}:
                self.smoke_verified.add(name)
            yield event

    async def cancel(self, session_id: str) -> None:
        name, session = self.sessions[session_id]
        await self.backends[name].cancel(session)

    async def resume(self, name: str, session_id: str, cwd: str | None = None) -> AgentSession:
        backend = self.backends.get(name)
        if backend is None:
            raise KeyError(name)
        session = await backend.resume(session_id, cwd)
        self.sessions[session.id] = (name, session)
        return session

    async def close(self, session_id: str) -> None:
        name, session = self.sessions.pop(session_id)
        await self.backends[name].close(session)

    async def shutdown(self) -> None:
        for session_id in list(self.sessions):
            try:
                await self.close(session_id)
            except Exception:
                continue

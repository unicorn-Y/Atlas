"""Minimum common contract for native and external Agent backends."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass
class AgentSession:
    """A backend-owned conversation session."""

    id: str
    cwd: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentEvent:
    """Normalized text, tool, progress, completion, and error event."""

    type: str
    data: dict[str, Any]


class AgentBackend(Protocol):
    """Small session surface shared by all supported Agent implementations."""

    name: str

    async def start_session(self, cwd: str | None = None) -> AgentSession: ...

    async def send(self, session: AgentSession, prompt: str) -> None: ...

    def stream_events(self, session: AgentSession) -> AsyncIterator[AgentEvent]: ...

    async def cancel(self, session: AgentSession) -> None: ...

    async def resume(self, session_id: str, cwd: str | None = None) -> AgentSession: ...

    async def close(self, session: AgentSession) -> None: ...


class ACPBackend:
    """ACP client adapter for upstream Agent processes."""

    def __init__(self, name: str, command: str, args: list[str]) -> None:
        self.name = name
        self.command = command
        self.args = args
        self._states: dict[str, Any] = {}

    async def start_session(self, cwd: str | None = None) -> AgentSession:
        import asyncio

        from acp import PROTOCOL_VERSION, spawn_agent_process
        from acp.interfaces import Client

        events: asyncio.Queue[AgentEvent | None] = asyncio.Queue()

        class EventClient(Client):
            async def session_update(self, session_id: str, update: Any, **_kwargs: Any) -> None:
                data = (
                    update.model_dump(mode="json", exclude_none=True)
                    if hasattr(update, "model_dump")
                    else {"value": str(update)}
                )
                await events.put(AgentEvent("update", {"session_id": session_id, "update": data}))

            async def request_permission(
                self, session_id: str, tool_call: Any, options: Any, **_kwargs: Any
            ) -> Any:
                from acp.schema import DeniedOutcome, RequestPermissionResponse

                return RequestPermissionResponse(outcome=DeniedOutcome())

        command, args = self.command, self.args
        if command == "npx":
            from atlas.tools.mcp_client import _resolve_stdio_command

            command, args = _resolve_stdio_command(command, args)
        manager = spawn_agent_process(EventClient(), command, *args, cwd=cwd)
        connection, process = await manager.__aenter__()
        try:
            await connection.initialize(protocol_version=PROTOCOL_VERSION)
            response = await connection.new_session(cwd=cwd or str(Path.cwd()), mcp_servers=[])
        except BaseException:
            await manager.__aexit__(None, None, None)
            raise
        session = AgentSession(
            id=response.session_id,
            cwd=cwd,
            metadata={"acp_session_id": response.session_id},
        )
        self._states[session.id] = {
            "manager": manager,
            "connection": connection,
            "process": process,
            "events": events,
            "prompt_task": None,
        }
        return session

    async def send(self, session: AgentSession, prompt: str) -> None:
        import asyncio

        from acp.schema import TextContentBlock

        state = self._states[session.id]
        if state["prompt_task"] and not state["prompt_task"].done():
            raise RuntimeError(f"{self.name} already has an active prompt")

        async def submit() -> None:
            try:
                await state["connection"].prompt(
                    session_id=session.metadata["acp_session_id"],
                    prompt=[TextContentBlock(type="text", text=prompt)],
                )
                await state["events"].put(AgentEvent("done", {"backend": self.name}))
            except Exception as exc:
                await state["events"].put(
                    AgentEvent("error", {"backend": self.name, "detail": str(exc)})
                )
            finally:
                await state["events"].put(None)

        state["prompt_task"] = asyncio.create_task(submit())

    async def stream_events(self, session: AgentSession) -> AsyncIterator[AgentEvent]:
        state = self._states[session.id]
        while True:
            event = await state["events"].get()
            if event is None:
                break
            yield event

    async def cancel(self, session: AgentSession) -> None:
        state = self._states.get(session.id)
        if state:
            await state["connection"].cancel(session_id=session.metadata["acp_session_id"])

    async def resume(self, session_id: str, cwd: str | None = None) -> AgentSession:
        state = self._states.get(session_id)
        if not state:
            session = await self.start_session(cwd)
            new_state = self._states.pop(session.id)
            try:
                await new_state["connection"].load_session(
                    cwd=cwd or str(Path.cwd()),
                    session_id=session_id,
                    mcp_servers=[],
                )
            except BaseException:
                await new_state["manager"].__aexit__(None, None, None)
                raise
            session.id = session_id
            self._states[session_id] = new_state
            return session
        return AgentSession(id=session_id, cwd=cwd, metadata={"acp_session_id": session_id})

    async def close(self, session: AgentSession) -> None:
        state = self._states.pop(session.id, None)
        if not state:
            return
        task = state["prompt_task"]
        if task and not task.done():
            task.cancel()
        await state["manager"].__aexit__(None, None, None)

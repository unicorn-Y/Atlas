"""Gateway bridge — the Wave-2 dispatcher seam between channels and agent runs.

One inbound :class:`~atlas.channels.contract.MessageEvent` becomes exactly one
agent run and at most two outbound replies (completion / failure — never a
stream), so long tasks do not flood the chat:

    event → session resolution (channel_sessions sqlite map, keyed by the
    ``atlas.persistent_agents.session_key`` grammar) → ``submit_run`` (the
    server's ``_handle_run_start``) → await ``run.task`` → answer via
    ``manager.send`` back to the originating channel/thread.

The bridge owns no agent logic: every server-side capability is an injected
callable (``submit_run`` / ``get_run`` / ``read_answer`` /
``create_conversation`` / ``set_agent_status``), so the module imports neither
``atlas.server`` nor any agent runtime — the server wires real callables during
lifespan and tests inject fakes.

Persistent-agent status projection: ``working`` while the run lives, then
``idle`` (or ``waiting_user`` when the run parks on an approval/trust gate).
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

import structlog

from atlas.channels import ChannelManager
from atlas.channels.contract import MessageEvent
from atlas.persistent_agents import session_key

log = structlog.get_logger()

#: server-side run entry point (``atlas.server._handle_run_start``)
SubmitRun = Callable[[str, dict[str, Any]], Awaitable[None]]
#: run registry lookup (``runtime_mgr.runs.get``)
GetRun = Callable[[str], Any]
#: last assistant message of a conversation
ReadAnswer = Callable[[str], Awaitable[str]]
#: create a fresh conversation for a new session key
CreateConversation = Callable[[str], Awaitable[str]]
#: project persistent-agent status (may be sync or async)
SetAgentStatus = Callable[..., Any]

MAX_REPLY_CHARS = 3500
MAX_FAILURE_CHARS = 800


class SessionMapper:
    """Durable ``channel_sessions`` map: session key → conversation id.

    Shares the gateway's ``channels.sqlite`` (its own table + connection) so a
    restart resumes the same conversations instead of forking new ones. The
    mapping is idempotent: the same session key always resolves to the same
    conversation id once created.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(self._path), check_same_thread=False)
        with self._db:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS channel_sessions ("
                "session_key TEXT PRIMARY KEY, "
                "conversation_id TEXT NOT NULL, "
                "created_at TEXT NOT NULL)"
            )

    def get(self, key: str) -> str | None:
        with self._lock:
            row = self._db.execute(
                "SELECT conversation_id FROM channel_sessions WHERE session_key=?", (key,)
            ).fetchone()
        return str(row[0]) if row else None

    def put(self, key: str, conversation_id: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO channel_sessions(session_key, conversation_id, created_at) "
                "VALUES(?, ?, ?) ON CONFLICT(session_key) DO NOTHING",
                (key, conversation_id, datetime.now(UTC).isoformat()),
            )

    def close(self) -> None:
        with contextlib.suppress(OSError):
            self._db.close()


async def _await_maybe(value: Any) -> None:
    if value is not None and asyncio.iscoroutine(value):
        await value


class GatewayBridge:
    """Dispatch channel events into agent runs and deliver answers back."""

    def __init__(
        self,
        *,
        manager: ChannelManager,
        db_path: str | Path,
        submit_run: SubmitRun,
        get_run: GetRun,
        read_answer: ReadAnswer,
        create_conversation: CreateConversation,
        default_workspace: str | None = None,
        set_agent_status: SetAgentStatus | None = None,
    ) -> None:
        self.manager = manager
        self.sessions = SessionMapper(db_path)
        self._submit_run = submit_run
        self._get_run = get_run
        self._read_answer = read_answer
        self._create_conversation = create_conversation
        self._default_workspace = default_workspace
        self._set_agent_status = set_agent_status

    # -- session lineage ------------------------------------------------------

    def build_session_key(self, event: MessageEvent, agent_id: str | None) -> str:
        """``agent:<id|main>:[channel:[account]:]direct:<chat_id>`` lineage key."""
        return session_key(
            agent_id or "main",
            channel=event.channel or "channel",
            account=event.account or "",
            peer=event.chat_id,
        )

    async def resolve_conversation(self, key: str, event: MessageEvent) -> str | None:
        """Existing conversation for the session key, else create + remember it."""
        known = self.sessions.get(key)
        if known:
            return known
        try:
            conversation_id = await self._create_conversation(key, event)
        except Exception as exc:  # noqa: BLE001 — infra failure: report in-band
            log.error("gateway.conversation_create_failed", session_key=key, error=str(exc))
            return None
        if not conversation_id:
            return None
        self.sessions.put(key, str(conversation_id))
        return str(conversation_id)

    # -- dispatcher seam --------------------------------------------------------

    async def dispatch(self, event: MessageEvent, agent_id: str | None) -> None:
        """``ChannelManager`` dispatcher: one inbound event → one run → one reply.

        Never raises: every failure path answers in-band with a one-line
        summary, so the gateway's retry queue does not replay a permanently
        rejected event forever.
        """
        try:
            await self._dispatch(event, agent_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — last-resort in-band failure reply
            log.error("gateway.dispatch_failed", channel=event.channel,
                      event_id=event.event_id, error=str(exc))
            await self._reply(event, f"任务执行失败：{str(exc)[:MAX_FAILURE_CHARS]}")
            await self._project_status(agent_id, "idle", str(exc))

    async def _dispatch(self, event: MessageEvent, agent_id: str | None) -> None:
        content = str(event.text or "")
        local_paths = [
            attachment.local_path for attachment in (event.attachments or [])
            if getattr(attachment, "local_path", "")
        ]
        if not content.strip() and not local_paths:
            return  # nothing actionable (sticker / reaction / empty ping)
        if local_paths:
            content += "\n\nAttached files stored at:\n" + "\n".join(local_paths)

        session = self.build_session_key(event, agent_id)
        conversation_id = await self.resolve_conversation(session, event)
        if conversation_id is None:
            await self._reply(event, "会话服务未就绪，请稍后再试。")
            return

        data: dict[str, Any] = {
            "run_id": uuid.uuid4().hex,
            "conversation_id": conversation_id,
            "content": content,
            "workspace": None if agent_id else self._default_workspace,
            "source": "channel",
        }
        if agent_id:
            data["agent_id"] = str(agent_id)
        await self._project_status(agent_id, "working")
        await self._submit_run("channel", data)

        run = self._get_run(str(data["run_id"]))
        task = getattr(run, "task", None)
        if run is None or task is None:
            detail = self._failure_detail(run) or "run 未启动"
            log.error("gateway.run_not_started", channel=event.channel, detail=detail)
            await self._reply(event, f"任务未能启动：{detail[:MAX_FAILURE_CHARS]}")
            await self._project_status(agent_id, "idle", detail)
            return
        try:
            await task
        except asyncio.CancelledError:
            await self._reply(event, "任务已停止。")
            await self._project_status(agent_id, "idle")
            return
        except Exception as exc:  # noqa: BLE001 — in-band failure summary
            await self._reply(event, f"任务执行失败：{str(exc)[:MAX_FAILURE_CHARS]}")
            await self._project_status(agent_id, "idle", str(exc))
            return

        run_status = str(getattr(run, "status", "") or "")
        if run_status == "failed":
            detail = self._failure_detail(run) or "未知错误"
            await self._reply(event, f"任务执行失败：{detail[:MAX_FAILURE_CHARS]}")
            await self._project_status(agent_id, "idle", detail)
            return
        if run_status == "cancelled":
            await self._reply(event, "任务已停止。")
            await self._project_status(agent_id, "idle")
            return
        if run_status == "waiting":
            # Parked on an approval/trust gate; nothing to answer yet.
            await self._project_status(agent_id, "waiting_user")
            return
        answer = ""
        try:
            answer = str(await self._read_answer(conversation_id) or "")
        except Exception as exc:  # noqa: BLE001 — still deliver a terminal ack
            log.warning("gateway.answer_read_failed", error=str(exc))
        await self._reply(event, answer or "任务完成。")
        await self._project_status(agent_id, "idle")

    # -- helpers ------------------------------------------------------------------

    async def _reply(self, event: MessageEvent, text: str) -> None:
        body = str(text or "").strip()
        if not body:
            return
        await self.manager.send(
            event.channel,
            event.chat_id,
            body[:MAX_REPLY_CHARS],
            account=event.account or "",
            reply_to=event.thread_id or "",
        )

    async def _project_status(self, agent_id: str | None, status: str, error: str = "") -> None:
        if not agent_id or self._set_agent_status is None:
            return
        try:
            await _await_maybe(self._set_agent_status(agent_id, status, error))
        except Exception as exc:  # noqa: BLE001 — projection must never break a run
            log.debug("gateway.status_projection_failed", agent_id=agent_id, error=str(exc))

    @staticmethod
    def _failure_detail(run: Any) -> str:
        for envelope in reversed(list(getattr(run, "events", None) or [])):
            if envelope.get("event") == "run.failed":
                data = envelope.get("data") or {}
                return str(data.get("detail") or "未知错误")
        return ""


__all__ = ["GatewayBridge", "SessionMapper"]

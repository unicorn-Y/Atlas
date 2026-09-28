"""DBOS-backed durable execution for long-running Atlas tasks.

Durable state remains DBOS-owned: the system database is a local SQLite file
(``data/dbos.sqlite`` by default), so crash/restart recovery works on a plain
Windows single-machine install with no Postgres and no Docker.

Integration contract (kept deliberately thin):

- the server registers one async dispatcher (the existing scheduled-goal
  callback path) and starts the backend;
- every durable agent task is one DBOS workflow whose single step bridges back
  onto the server's event loop, so a crash mid-task leaves a RUNNING workflow
  that DBOS re-executes on the next start (task-level resume);
- when the backend is not started, callers fall back to direct execution.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from atlas.config import get_config

Dispatcher = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def status() -> dict[str, Any]:
    """Dependency probe kept for the existing dbos_status import."""
    try:
        import dbos  # noqa: F401
    except ImportError as exc:
        return {"available": False, "status": "missing_dependency", "error": str(exc)}
    return {
        "available": True,
        "status": "ready",
        "error": None,
    }


class DurableBackend:
    """Own the process-wide DBOS instance and the durable agent-task workflow."""

    def __init__(self, system_db_path: str | Path | None = None) -> None:
        self._system_db_path = Path(
            system_db_path or (get_config().db_path.parent / "dbos.sqlite"),
        )
        self._dispatcher: Dispatcher | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._started = False
        self._start_error: str | None = None
        self._agent_task_workflow: Any = None

    @property
    def started(self) -> bool:
        return self._started

    def status(self) -> dict[str, Any]:
        probe = status()
        return {
            **probe,
            "started": self._started,
            "system_db": str(self._system_db_path),
            "system_db_exists": self._system_db_path.exists(),
            "start_error": self._start_error,
        }

    def set_dispatcher(self, dispatcher: Dispatcher, loop: asyncio.AbstractEventLoop) -> None:
        """Register the callback that durable workflows bridge back into.

        Must be called before :meth:`start` so restart recovery immediately
        finds a live dispatcher.
        """
        self._dispatcher = dispatcher
        self._loop = loop

    def start(self) -> dict[str, Any]:
        if self._started:
            return self.status()
        if self._dispatcher is None or self._loop is None:
            self._start_error = "dispatcher not registered before start"
            return self.status()
        try:
            from dbos import DBOS

            self._system_db_path.parent.mkdir(parents=True, exist_ok=True)
            dbos = DBOS(config={
                "name": "atlas",
                "system_database_url": f"sqlite:///{self._system_db_path.as_posix()}",
                "db_engine_kwargs": {
                    "connect_args": {"timeout": 30},
                },
            })

            @dbos.step()
            async def _agent_task_step(payload: dict[str, Any]) -> dict[str, Any]:
                dispatcher = self._dispatcher
                loop = self._loop
                if dispatcher is None or loop is None:
                    raise RuntimeError("durable dispatcher is not registered")
                # Bridge onto the server's live event loop: in-process runs hop
                # to that loop; restart-recovery hops from DBOS's own loop.
                future = asyncio.run_coroutine_threadsafe(dispatcher(payload), loop)
                return await asyncio.wrap_future(future)

            @dbos.workflow()
            async def _agent_task_workflow(payload: dict[str, Any]) -> dict[str, Any]:
                return await _agent_task_step(payload)

            self._agent_task_workflow = _agent_task_workflow
            DBOS.launch()
            self._started = True
            self._start_error = None
        except Exception as exc:  # durable is best-effort: never block startup
            self._started = False
            self._start_error = str(exc)
        return self.status()

    async def run_agent_task(
        self, payload: dict[str, Any], timeout: float | None = None,
    ) -> dict[str, Any]:
        """Run one agent task as a durable workflow (at-least-once resume)."""
        if not self._started or self._agent_task_workflow is None:
            raise RuntimeError("DurableBackend is not started")
        from dbos import DBOS

        handle = await DBOS.start_workflow_async(self._agent_task_workflow, payload)
        result = await handle.get_result()
        return dict(result)

    def stop(self) -> None:
        if not self._started:
            return
        try:
            from dbos import DBOS

            DBOS.destroy(destroy_registry=True)
        except Exception:
            pass
        self._started = False
        # DBOS replaces the loop's default executor with its own and shuts it
        # down on destroy; restore a plain one so the same process (tests,
        # graceful restarts) keeps a working default executor.
        loop = self._loop
        if loop is not None and not loop.is_closed():

            def _restore_executor() -> None:
                try:
                    loop.set_default_executor(
                        concurrent.futures.ThreadPoolExecutor(),
                    )
                except RuntimeError:
                    pass

            try:
                loop.call_soon_threadsafe(_restore_executor)
            except RuntimeError:
                pass

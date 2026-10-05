"""Regression: a durable scheduler failure must notify and fall back (not NameError).

``run_drive._scheduled_goal`` previously referenced an ``exc`` name it never
bound (``except Exception:`` without ``as exc``), so the failure-notification
path raised ``NameError`` and the direct fallback at the end of the function was
never reached. This pins both behaviours with fakes.
"""

from __future__ import annotations

import pytest

from atlas import server as atlas_server
from atlas.api import run_drive


@pytest.mark.asyncio
async def test_durable_failure_notifies_with_exception_and_falls_back(monkeypatch) -> None:
    class _FailingDurable:
        started = True

        async def run_agent_task(self, payload):  # noqa: ANN001, ANN201 - test fake
            raise RuntimeError("durable backend exploded")

    class _Recorder:
        def __init__(self) -> None:
            self.messages: list[tuple[str, str]] = []

        async def notify(self, title: str, body: str) -> None:
            self.messages.append((title, body))

    recorder = _Recorder()
    fallback_calls: list[tuple[str, str]] = []

    async def _fake_run_scheduled_goal(task_id: str, message: str) -> None:
        fallback_calls.append((task_id, message))

    monkeypatch.setattr(atlas_server, "durable", _FailingDurable())
    monkeypatch.setattr(atlas_server, "notifications", recorder)
    monkeypatch.setattr(atlas_server, "_run_scheduled_goal", _fake_run_scheduled_goal)

    await run_drive._scheduled_goal("task-1", "do the thing")

    # (a) the notification carries the real exception text, not a NameError
    assert len(recorder.messages) == 1, recorder.messages
    title, body = recorder.messages[0]
    assert title == "Atlas task failed"
    assert "durable backend exploded" in body, body
    assert "NameError" not in body

    # (b) the direct fallback still runs after a durable failure
    assert fallback_calls == [("task-1", "do the thing")]

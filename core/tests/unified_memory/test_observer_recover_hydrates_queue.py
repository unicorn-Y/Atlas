"""F3-B 回归：只经「恢复」路径入库的 source 必须能被内存队列看见。

场景 29 的结算卡死根因是结构性的：``_recover_unprocessed_sources`` 把 ACKED 但
无 watermark 的 capture 行直接写进 outbox，**从不**追加到 ``_SessionQueue.entries``；
而 ``_restore_queue`` 对已在本进程 restore 过的 session 直接短路返回内存队列、
不重读 DB。于是这条 source 只在 DB 里有、内存队列里没有 —— ``_start_batch`` 看到
空队列就返回 None，该 session 永远无法结算（连 ``session/close`` 也救不回来）。

修法：``resume``/``add_messages`` 在 restore 之后调用 ``_hydrate_queue_from_outbox``，
按 ``queue_id`` 去重、把内存队列与持久队列收敛一致。本文件钉住这个不变量。
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import atlas.memory.observer as observer_module
from atlas.memory.capture import build_observation
from atlas.memory.observer import MemoryObserver
from atlas.memory.outbox import OperationalOutbox

pytestmark = pytest.mark.fake_provider

SESSION = "session-hydrate"


def _source(
    event_id: str,
    object_id: str,
    text: str,
    *,
    kind: str = "ATLAS_USER_MESSAGE",
    role: str = "USER",
    epistemic: str = "USER_ASSERTED",
) -> dict[str, object]:
    return {
        "text": text,
        "source_event_id": event_id,
        "occurred_at": "2026-10-09T12:00:00+08:00",
        "source_timezone": "Asia/Shanghai",
        "speaker_role": role,
        "source_kind": kind,
        "source_object_id": object_id,
        "source_revision": "1",
        "epistemic_kind": epistemic,
        "provenance": {},
    }


def _answer(evidence: list[str], text: str = "用户交代了一件事。") -> dict[str, object]:
    return {"observations": [{
        "text": text,
        "priority": "HIGH",
        "facet": "FACT",
        "key": "user.misc.note",
        "value": text,
        "entities": ["用户"],
        "valid_from": None,
        "valid_to": None,
        "is_change": False,
        "evidence": evidence,
        "speaker": "USER",
    }]}


class _Router:
    def __init__(self, answers: list[dict[str, object]]) -> None:
        self.answers = answers
        self.calls: list[dict[str, object]] = []

    async def complete_for(self, model_id, purpose, messages, **kwargs):
        self.calls.append({
            "model_id": model_id,
            "purpose": purpose,
            "messages": messages,
            "kwargs": kwargs,
        })
        answer = self.answers.pop(0)
        return SimpleNamespace(
            text=json.dumps(answer, ensure_ascii=False),
            usage={"input_tokens": 10, "output_tokens": 5},
        )


class _Manager:
    current_model = "hydrate-unit-model"

    def __init__(self, router: _Router) -> None:
        self.model_router = router

    def list_models(self):
        return [{"id": self.current_model}]


def _acked_capture(outbox: OperationalOutbox, src: dict[str, object]) -> None:
    """像 capture flush 循环那样：入库 → poll → ack，留下无 watermark 的 ACKED 行。"""

    observation = build_observation(
        source_kind=src["source_kind"],
        source_object_id=src["source_object_id"],
        source_revision=src["source_revision"],
        content={"text": src["text"]},
        speaker_role=src["speaker_role"],
        epistemic_kind=src["epistemic_kind"],
        occurred_at=src["occurred_at"],
        source_timezone=src["source_timezone"],
    )
    assert observation["source_event_id"] == src["source_event_id"]
    outbox.enqueue(observation, context={"memory_subject_id": "subject-1",
                                        "runtime_session_id": SESSION},
                   event_class="TEST")
    for row in outbox.poll_pending(limit=50):
        if str(row["source_event_id"]) == src["source_event_id"]:
            assert outbox.mark_acked(str(row["source_event_id"]))
            return
    raise AssertionError(f"capture row {src['source_event_id']} never became pending")


def _observer(
    monkeypatch, outbox: OperationalOutbox, answers: list[dict[str, object]],
) -> tuple[MemoryObserver, _Router]:
    monkeypatch.setattr(observer_module, "_DAILY_SPENT", {})
    monkeypatch.setattr(observer_module, "_DAILY_RESERVED", {})
    router = _Router(answers)
    observer = MemoryObserver(
        _Manager(router),
        {
            "memory.unified.enabled": True,
            "memory.unified.capture_mode": "enabled",
            "memory.v1.observer_daily_token_budget": 1_000_000,
        },
        outbox=outbox,
        token_counter=len,
        now=lambda: datetime(2100, 1, 1, tzinfo=UTC),
    )
    return observer, router


async def _drain_first_batch(tmp_path, monkeypatch) -> tuple[MemoryObserver, dict[str, object]]:
    """把 session 推进到「队列已清空 + 进程内已 restore」的状态。"""

    outbox = OperationalOutbox(tmp_path / "outbox.sqlite3")
    first = _source("atlas:ATLAS_USER_MESSAGE:m1:1:UPSERT", "m1", "先记一句。")
    second = _source(
        "atlas:ATLAS_ASSISTANT_MESSAGE:m2:1:UPSERT", "m2", "好的，已记下。",
        kind="ATLAS_ASSISTANT_MESSAGE", role="ATLAS", epistemic="OBSERVED",
    )
    _acked_capture(outbox, first)

    observer, router = _observer(monkeypatch, outbox, [
        _answer([first["source_event_id"]]),
        _answer([second["source_event_id"]]),
    ])
    batch = await observer.add_messages(SESSION, [first], session_ended=True)
    assert batch is not None
    assert await observer.ack_batch(batch.batch_id) is None
    assert outbox.observer_queue_sources(SESSION) == []
    return observer, {"outbox": outbox, "first": first, "second": second,
                      "router": router, "batch": batch}


def test_recovered_source_reaches_live_queue_and_batches(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        observer, state = await _drain_first_batch(tmp_path, monkeypatch)
        outbox, second = state["outbox"], state["second"]
        router = state["router"]

        # 迟到的 capture 行只在 outbox 里 ACK，从未直接交给 add_messages —— 真实
        # 运行时它就是被 resume → _recover_unprocessed_sources 捡起来的那条。
        _acked_capture(outbox, second)
        unprocessed = outbox.observer_unprocessed_sources(SESSION)
        assert [str(row["source_event_id"]) for row in unprocessed] == [
            second["source_event_id"]]

        tail = await observer.resume(SESSION, session_ended=True)

        assert tail is not None, "恢复出来的 source 被永久孤立：内存队列始终为空"
        # 它确实被当成 batch 2 的内容送进观察者，而不是被悄悄丢掉。
        assert len(router.calls) == 2
        assert tail.payload["observations"][0]["derived_from"] == [second["source_event_id"]]

        # 结算完成：队列行、待确认批次、未处理 source 全部清空。
        assert await observer.ack_batch(tail.batch_id) is None
        assert outbox.observer_queue_sources(SESSION) == []
        assert outbox.observer_pending_batch(SESSION) is None
        assert outbox.observer_unprocessed_sources(SESSION) == []
        assert observer.pending_sessions() == []

    asyncio.run(scenario())


def test_hydrate_does_not_duplicate_live_entries(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        outbox = OperationalOutbox(tmp_path / "outbox.sqlite3")
        src = _source("atlas:ATLAS_USER_MESSAGE:m9:1:UPSERT", "m9", "你好。")
        _acked_capture(outbox, src)
        observer, _ = _observer(monkeypatch, outbox, [_answer([src["source_event_id"]])])

        batch = await observer.add_messages(SESSION, [src], session_ended=True)
        assert batch is not None
        queue = observer._queues[SESSION]
        before = [str(entry["_observer_queue_id"]) for entry in queue.entries]
        assert before == ["1"]

        await observer.resume(SESSION, session_ended=True)

        after = [str(entry["_observer_queue_id"]) for entry in queue.entries]
        assert after == before, "收敛把已有 entry 重复灌进队列了"
        assert len(observer._outbox.observer_queue_sources(SESSION)) == 1

    asyncio.run(scenario())

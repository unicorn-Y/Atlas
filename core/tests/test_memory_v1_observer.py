from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from atlas.memory.observer import MemoryObserver, _parse_observer_output
from atlas.memory.capture import build_observation
from atlas.memory.outbox import OperationalOutbox, STATE_ACKED
from atlas.memory.observer_prompt import (
    OBSERVER_EXTRACTION_INSTRUCTIONS,
    OBSERVER_QUESTION_RULES,
)


class Config:
    def __init__(self, **values):
        self.values = {
            "memory.unified.enabled": True,
            "memory.unified.capture_mode": "enabled",
            "memory.v1.observer_daily_token_budget": 50_000,
            **values,
        }

    def get(self, key, default=None):
        return self.values.get(key, default)


class Router:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    async def complete_for(self, model_id, purpose, messages, **kwargs):
        self.calls.append((model_id, purpose, messages, kwargs))
        return type("Result", (), {
            "text": json.dumps(self.answer, ensure_ascii=False),
            "usage": {"prompt_tokens": 31, "completion_tokens": 12},
        })()


class ModelManager:
    current_model = "active-model"

    def __init__(self, router):
        self.model_router = router

    def list_models(self):
        return [{"id": "active-model", "litellm_model": "provider/active-model"}]


def source(event_id="atlas:ATLAS_USER_MESSAGE:message-1:1:UPSERT", **updates):
    value = {
        "text": "我住在上海。",
        "source_event_id": event_id,
        "occurred_at": "2026-10-07T12:00:00+08:00",
        "source_timezone": "Asia/Shanghai",
        "speaker_role": "USER",
        "source_kind": "ATLAS_USER_MESSAGE",
        "source_object_id": "message-1",
        "source_revision": "1",
        "epistemic_kind": "USER_ASSERTED",
        "provenance": {},
    }
    value.update(updates)
    return value


def answer(evidence, **updates):
    item = {
        "text": "用户住在上海。",
        "priority": "HIGH",
        "facet": "FACT",
        "key": "user.home_city",
        "value": "上海",
        "entities": ["用户", "上海"],
        "valid_from": "2026-10-07",
        "valid_to": None,
        "is_change": False,
        "evidence": evidence,
        "speaker": "USER",
    }
    item.update(updates)
    return {"observations": [item]}


def make_observer(router, *, config=None, token_counter=None, now=None):
    return MemoryObserver(
        ModelManager(router), config or Config(), token_counter=token_counter, now=now,
    )


def acked_capture(outbox, src, *, context=None):
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
    result = outbox.enqueue(observation, context=context, event_class="TEST")
    assert result["source_event_id"] == src["source_event_id"]
    row = outbox.poll_pending(limit=1)[0]
    assert outbox.mark_acked(row["source_event_id"])
    assert outbox.get(src["source_event_id"])["state"] == STATE_ACKED


def test_end_of_session_flush_builds_derived_batch_from_real_source_ids():
    src = source()
    router = Router(answer([src["source_event_id"]]))
    observer = make_observer(router, token_counter=len)

    batch = asyncio.run(observer.add_messages("session-1", [src], session_ended=True))

    assert batch is not None
    assert router.calls[0][1] == "memory_observe"
    assert router.calls[0][0] == "active-model"
    assert batch.payload["contract_version"] == "UM-WIN-1.0"
    item = batch.payload["observations"][0]
    assert item["source_kind"] == "DERIVED"
    assert item["derived_from"] == [src["source_event_id"]]
    assert item["epistemic_kind"] == "USER_ASSERTED"
    assert item["speaker_role"] == "USER"
    assert item["content"]["change"] is False
    assert "is_change" not in item["content"]


def test_model_cannot_attach_unknown_source_or_promote_external_tool_content_to_user():
    external = source(
        "atlas:ATLAS_TOOL_OBSERVATION:call-7:2:UPSERT",
        text="某网页写着：用户已搬到上海。",
        speaker_role="TOOL",
        source_kind="ATLAS_TOOL_OBSERVATION",
        source_object_id="call-7",
        source_revision="2",
        epistemic_kind="OBSERVED",
        provenance={"tool_name": "browser", "external_content": True},
    )
    router = Router(answer([external["source_event_id"]], speaker="USER"))
    observer = make_observer(router, token_counter=len)

    batch = asyncio.run(observer.add_messages("session-2", [external], session_ended=True))

    assert batch is not None
    item = batch.payload["observations"][0]
    assert item["speaker_role"] == "THIRD_PARTY"
    assert item["epistemic_kind"] == "THIRD_PARTY_ASSERTED"


def test_parser_rejects_invalid_items_individually_and_counts_reasons():
    valid = answer(["source-1"])["observations"][0]
    unknown_facet = {**valid, "facet": "QUESTION", "evidence": ["source-1"]}
    missing_evidence = {key: value for key, value in valid.items() if key != "evidence"}
    forged_evidence = {**valid, "evidence": ["forged-source"]}

    parsed, rejected = _parse_observer_output(
        json.dumps({"observations": [
            valid, unknown_facet, missing_evidence, forged_evidence,
        ]}),
        {"source-1"},
    )

    assert parsed["observations"] == [valid]
    assert rejected == {
        "unknown_facet": 1,
        "missing_evidence": 1,
        "evidence_not_in_batch": 1,
    }


def test_parser_ignores_extra_root_metadata_when_observations_are_valid():
    valid = answer(["source-1"])['observations'][0]

    parsed, rejected = _parse_observer_output(
        json.dumps({"observations": [valid], "note": "provider metadata"}),
        {"source-1"},
    )

    assert parsed["observations"] == [valid]
    assert rejected == {}


def test_model_discards_invalid_evidence_item_without_losing_valid_items():
    src = source()
    valid = answer([src["source_event_id"]])["observations"][0]
    invalid = answer([src["source_event_id"], "atlas:forged:id"])["observations"][0]
    router = Router({"observations": [valid, invalid]})
    observer = make_observer(router, token_counter=len)

    batch = asyncio.run(observer.add_messages("session-2b", [src], session_ended=True))

    assert batch is not None
    assert len(batch.payload["observations"]) == 1
    assert batch.payload["observations"][0]["content"]["text"] == valid["text"]
    assert observer.item_rejected_counts == {"evidence_not_in_batch": 1}


def test_all_invalid_items_complete_as_an_empty_batch():
    src = source()
    item = answer([src["source_event_id"]])["observations"][0]
    router = Router({"observations": [{**item, "facet": "QUESTION"}]})
    observer = make_observer(router, token_counter=len)

    batch = asyncio.run(observer.add_messages("session-2c", [src], session_ended=True))

    assert batch is not None
    assert batch.payload is None
    assert asyncio.run(observer.ack_batch(batch.batch_id)) is None
    assert "session-2c" not in observer._queues


def test_small_exchange_waits_for_threshold_or_end_flush():
    router = Router({"observations": []})
    observer = make_observer(router, token_counter=lambda _text: 1)

    pending = asyncio.run(observer.add_messages("session-3", [source()], session_ended=False))

    assert pending is None
    assert router.calls == []


def test_daily_budget_defers_original_sources_then_flushes_after_reset():
    src = source()
    router = Router(answer([src["source_event_id"]]))
    current = [datetime(2026, 10, 7, tzinfo=timezone.utc)]
    observer = make_observer(
        router,
        config=Config(**{"memory.v1.observer_daily_token_budget": 1}),
        token_counter=lambda _text: 1,
        now=lambda: current[0],
    )

    deferred = asyncio.run(observer.add_messages("session-4", [src], session_ended=True))
    assert deferred is None
    assert not router.calls

    current[0] = datetime(2026, 10, 8, tzinfo=timezone.utc)
    # The added question rule raises the fixed prompt estimate above the old 5,000 cap.
    observer._config.values["memory.v1.observer_daily_token_budget"] = 10_000
    flushed = asyncio.run(observer.add_messages("session-4", [], session_ended=True))

    assert flushed is not None
    assert flushed.payload["observations"][0]["derived_from"] == [src["source_event_id"]]


def test_unparseable_output_does_not_ack_or_drop_queued_source():
    src = source()
    class RawRouter(Router):
        async def complete_for(self, model_id, purpose, messages, **kwargs):
            self.calls.append((model_id, purpose, messages, kwargs))
            return type("Result", (), {
                "text": "{not json", "usage": {"prompt_tokens": 31, "completion_tokens": 12},
            })()

    router = RawRouter(None)
    observer = make_observer(router, token_counter=len)

    with pytest.raises(ValueError, match="failed the S2 JSON schema"):
        asyncio.run(observer.add_messages("session-5", [src], session_ended=True))
    assert "session-5" in observer._queues
    assert observer._queues["session-5"].entries[0]["source_event_id"] == src["source_event_id"]


def test_observer_prompt_distinguishes_questions_from_facts_without_question_facet():
    assert "When the user ASKS about something, mark it as a question/request:" in OBSERVER_EXTRACTION_INSTRUCTIONS
    assert "用户的提问、请求、指令本身不记录；只有提问中透露出的事实才记录。" in OBSERVER_QUESTION_RULES
    assert "条件句或假设" in OBSERVER_QUESTION_RULES
    assert "不证明用户已经计划、决定或承诺" in OBSERVER_QUESTION_RULES
    assert "问句中的查询条件" in OBSERVER_QUESTION_RULES
    assert "不证明用户有该偏好或需求" in OBSERVER_QUESTION_RULES
    assert "question, request, or instruction is not itself a fact to remember" in OBSERVER_QUESTION_RULES
    assert "hypothetical or conditional phrase" in OBSERVER_QUESTION_RULES
    assert "Conditions asked about in a question do not establish personal preferences" in OBSERVER_QUESTION_RULES
    assert "我女儿 6 岁了，她该上几年级？" in OBSERVER_QUESTION_RULES


def test_threshold_flushes_in_capped_batches_without_losing_source_text():
    src = source(text="甲" * 30_000)
    router = Router(answer([src["source_event_id"]]))
    observer = make_observer(router, token_counter=len)

    first = asyncio.run(observer.add_messages("session-6", [src]))
    assert first is not None
    assert first.payload["observations"][0]["derived_from"] == [src["source_event_id"]]
    batches = [first]
    while batches[-1] is not None:
        next_batch = asyncio.run(observer.ack_batch(batches[-1].batch_id))
        if next_batch is None:
            break
        batches.append(next_batch)

    assert len(batches) == 3
    assert len(router.calls) == 3
    assert all(len(call[2][1]["content"].split('"text": "')[1].split('"')[0]) <= 10_000
               for call in router.calls)
    assert "session-6" not in observer._queues


def test_memory_model_precedes_compression_and_current_model(monkeypatch):
    import atlas.config

    monkeypatch.setattr(atlas.config, "load_user_settings", lambda: {
        "memory_model": "memory-choice",
        "compression_model": "compression-choice",
    })
    router = Router({"observations": []})

    class MultiModelManager(ModelManager):
        def list_models(self):
            return [
                {"id": "active-model", "litellm_model": "provider/active-model"},
                {"id": "memory-choice", "litellm_model": "provider/memory-choice"},
                {"id": "compression-choice", "litellm_model": "provider/compression-choice"},
            ]

    observer = MemoryObserver(MultiModelManager(router), Config(), token_counter=len)
    asyncio.run(observer.add_messages("session-7", [source()], session_ended=True))

    assert router.calls[0][0] == "memory-choice"
    assert router.calls[0][1] == "memory_observe"


def test_late_observation_keeps_evidence_time_instead_of_extraction_time():
    src = source(occurred_at="2026-03-21T12:00:00+08:00")
    router = Router(answer([src["source_event_id"]]))
    observer = make_observer(router, token_counter=len)

    batch = asyncio.run(observer.add_messages("session-8", [src], session_ended=True))

    item = batch.payload["observations"][0]
    assert item["occurred_at"] == "2026-03-21T12:00:00+08:00"
    assert item["source_timezone"] == "Asia/Shanghai"


def test_same_session_concurrent_adds_do_not_duplicate_model_extraction():
    src = source()

    class BlockingRouter(Router):
        def __init__(self):
            super().__init__(answer([src["source_event_id"]]))
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def complete_for(self, model_id, purpose, messages, **kwargs):
            self.calls.append((model_id, purpose, messages, kwargs))
            self.started.set()
            await self.release.wait()
            return type("Result", (), {
                "text": json.dumps(self.answer, ensure_ascii=False), "usage": {},
            })()

    async def exercise():
        router = BlockingRouter()
        observer = make_observer(router, token_counter=len)
        first = asyncio.create_task(
            observer.add_messages("session-9", [src], session_ended=True),
        )
        await router.started.wait()
        concurrent = await observer.add_messages("session-9", [src], session_ended=True)
        router.release.set()
        result = await first
        return router, concurrent, result

    router, concurrent, result = asyncio.run(exercise())

    assert len(router.calls) == 1
    assert concurrent is None
    assert result is not None


def test_persistent_outbox_rejects_unacked_sources_and_resumes_saved_http_batch(tmp_path):
    path = tmp_path / "outbox.sqlite3"
    outbox = OperationalOutbox(path)
    src = source()
    router = Router(answer([src["source_event_id"]]))
    observer = MemoryObserver(
        ModelManager(router), Config(), outbox=outbox, token_counter=len,
    )

    with pytest.raises(ValueError, match="not a captured ACKED"):
        asyncio.run(observer.add_messages("session-outbox", [src], session_ended=True))
    assert router.calls == []

    acked_capture(outbox, src)
    batch = asyncio.run(observer.add_messages("session-outbox", [src], session_ended=True))
    assert batch is not None
    assert outbox.observer_pending_sessions() == ["session-outbox"]
    stored = outbox.observer_pending_batch("session-outbox")
    assert stored is not None and stored["batch_id"] == batch.batch_id
    assert stored["raw_output"] == batch.raw_output
    assert outbox.observer_budget_snapshot(datetime.now(timezone.utc).date().isoformat())["spent"] == 43
    outbox.close()

    reopened = OperationalOutbox(path)
    recovery_router = Router({"observations": []})
    recovered = MemoryObserver(
        ModelManager(recovery_router), Config(), outbox=reopened, token_counter=len,
    )
    assert recovered.pending_sessions() == ["session-outbox"]
    resumed = asyncio.run(recovered.resume("session-outbox"))
    assert resumed is not None
    assert resumed.batch_id == batch.batch_id
    assert resumed.raw_output == batch.raw_output
    assert recovery_router.calls == []  # saved result is replayed without another model call

    assert asyncio.run(recovered.ack_batch(resumed.batch_id)) is None
    assert recovered.pending_sessions() == []
    assert reopened.observer_get_batch(resumed.batch_id)["status"] == "ACKED"
    reopened.close()


def test_persistent_daily_budget_survives_observer_restart(tmp_path):
    path = tmp_path / "outbox.sqlite3"
    outbox = OperationalOutbox(path)
    current = datetime(2026, 10, 7, tzinfo=timezone.utc)
    first_source = source("atlas:ATLAS_USER_MESSAGE:budget-1:1:UPSERT",
                          source_object_id="budget-1")
    acked_capture(outbox, first_source)
    first_router = Router(answer([first_source["source_event_id"]]))
    first = MemoryObserver(
        ModelManager(first_router), Config(), outbox=outbox,
        token_counter=len, now=lambda: current,
    )
    batch = asyncio.run(first.add_messages("budget-session-1", [first_source], session_ended=True))
    assert batch is not None
    assert asyncio.run(first.ack_batch(batch.batch_id)) is None
    assert outbox.observer_budget_snapshot("2026-10-07")["spent"] == 43

    second_source = source("atlas:ATLAS_USER_MESSAGE:budget-2:1:UPSERT",
                           source_object_id="budget-2")
    acked_capture(outbox, second_source)
    second_router = Router(answer([second_source["source_event_id"]]))
    second = MemoryObserver(
        ModelManager(second_router),
        Config(**{"memory.v1.observer_daily_token_budget": 43}),
        outbox=outbox, token_counter=len, now=lambda: current,
    )
    deferred = asyncio.run(second.add_messages(
        "budget-session-2", [second_source], session_ended=True,
    ))
    assert deferred is None
    assert second_router.calls == []
    assert second.pending_sessions() == ["budget-session-2"]
    outbox.close()


def test_acked_capture_before_observer_enqueue_is_recovered_by_session_drain(tmp_path):
    outbox = OperationalOutbox(tmp_path / "outbox.sqlite3")
    src = source("atlas:ATLAS_USER_MESSAGE:crash-gap:1:UPSERT",
                 source_object_id="crash-gap")
    acked_capture(outbox, src, context={"runtime_session_id": "session-crash-gap"})
    assert outbox.observer_pending_sessions() == ["session-crash-gap"]

    router = Router(answer([src["source_event_id"]]))
    observer = MemoryObserver(
        ModelManager(router), Config(), outbox=outbox, token_counter=len,
    )
    batch = asyncio.run(observer.resume("session-crash-gap", session_ended=True))

    assert batch is not None
    assert len(router.calls) == 1
    assert outbox.observer_queue_sources("session-crash-gap")[0]["source_event_id"] == src[
        "source_event_id"]
    outbox.close()


def test_session_end_flush_marker_survives_observer_restart(tmp_path):
    path = tmp_path / "outbox.sqlite3"
    session_id = "observer-ended-session"
    outbox = OperationalOutbox(path)
    observer = MemoryObserver(ModelManager(Router("{}")), Config(), outbox=outbox)
    observer.mark_session_ended(session_id)
    outbox.close()

    restored_outbox = OperationalOutbox(path)
    restored = MemoryObserver(
        ModelManager(Router("{}")), Config(), outbox=restored_outbox,
    )
    assert asyncio.run(restored.resume(session_id)) is None
    assert restored_outbox.observer_flush_requested(session_id) is True
    assert restored._queues[session_id].flush_requested is True
    restored_outbox.close()


@pytest.mark.parametrize(
    ("operation", "expected_spent"),
    [("commit", 40), ("release", 0)],
)
def test_daily_reservation_settlement_is_idempotent_across_connections(
    tmp_path, operation, expected_spent,
):
    path = tmp_path / "outbox.sqlite3"
    seed = OperationalOutbox(path)
    assert seed.observer_budget_reserve("2026-10-07", 100, "reservation-1", 80)
    seed.close()

    barrier = Barrier(2)

    def settle():
        box = OperationalOutbox(path)
        try:
            barrier.wait()
            if operation == "commit":
                return box.observer_budget_commit("reservation-1", 40)
            return box.observer_budget_release("reservation-1")
        finally:
            box.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: settle(), range(2)))

    assert sum(results) == 1
    check = OperationalOutbox(path)
    snapshot = check.observer_budget_snapshot("2026-10-07")
    assert snapshot["spent"] == expected_spent
    assert snapshot["reserved"] == 0
    check.close()


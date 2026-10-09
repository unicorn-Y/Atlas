from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import atlas.memory.observer as observer_module
from atlas.memory.observer import (
    MemoryObserver,
    _dominant_language,
    _language_mismatch_indices,
    _SessionQueue,
)
from atlas.memory.observer_prompt import (
    OBSERVER_EXTRACTION_INSTRUCTIONS,
    OBSERVER_OUTPUT_GUIDANCE,
    OBSERVER_QUESTION_RULES,
)
from atlas.memory.reflector import (
    MemoryReflector,
    build_reflector_system_prompt,
)

pytestmark = pytest.mark.fake_provider


def _observation(
    text: str, value: str, evidence: str = "f1-language:user",
) -> dict[str, object]:
    return {
        "text": text,
        "priority": "HIGH",
        "facet": "HABIT",
        "key": "user.exercise.frequency",
        "value": value,
        "entities": ["用户", "跑步"],
        "valid_from": None,
        "valid_to": None,
        "is_change": False,
        "evidence": [evidence],
        "speaker": "USER",
    }


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
        if answer.get("cancel"):
            raise asyncio.CancelledError()
        return SimpleNamespace(
            text=json.dumps(answer["body"], ensure_ascii=False),
            usage=answer.get("usage", {"input_tokens": 10, "output_tokens": 5}),
        )


class _Manager:
    current_model = "f1-language-unit-model"

    def __init__(self, router: _Router) -> None:
        self.model_router = router

    def list_models(self):
        return [{"id": self.current_model}]


def _queue() -> _SessionQueue:
    entries = [
        MemoryObserver._queue_entry({
            "source_event_id": "f1-language:user",
            "text": "我最近开始跑步，每周三次。",
            "speaker_role": "USER",
            "epistemic_kind": "ASSERTED",
            "source_kind": "CHAT",
            "source_object_id": "f1-language-user",
            "source_revision": "1",
        }, "我最近开始跑步，每周三次。"),
        MemoryObserver._queue_entry({
            "source_event_id": "f1-language:assistant",
            "text": "明白，你每周跑步三次。",
            "speaker_role": "ATLAS",
            "epistemic_kind": "INFERRED",
            "source_kind": "CHAT",
            "source_object_id": "f1-language-assistant",
            "source_revision": "1",
        }, "明白，你每周跑步三次。"),
    ]
    return _SessionQueue(entries=entries)


def _mixed_queue() -> _SessionQueue:
    queue = _queue()
    queue.entries.append(MemoryObserver._queue_entry({
        "source_event_id": "f1-language:tool",
        "text": "The PostgreSQL connection failed after a timeout.",
        "speaker_role": "TOOL",
        "epistemic_kind": "OBSERVED",
        "source_kind": "TOOL",
        "source_object_id": "f1-language-tool",
        "source_revision": "1",
    }, "The PostgreSQL connection failed after a timeout."))
    return queue


def _english_answer() -> dict[str, object]:
    return {"observations": [_observation(
        "The user runs three times per week.", "three times per week",
    )]}


def _chinese_answer() -> dict[str, object]:
    return {"observations": [_observation(
        "用户每周跑步三次。", "每周三次",
    )]}


def _make_observer(monkeypatch, answers: list[dict[str, object]]) -> tuple[MemoryObserver, _Router]:
    monkeypatch.setattr(observer_module, "_DAILY_SPENT", {})
    monkeypatch.setattr(observer_module, "_DAILY_RESERVED", {})
    router = _Router(answers)
    observer = MemoryObserver(
        _Manager(router),
        {"memory.v1.observer_daily_token_budget": 1_000_000},
        token_counter=len,
        now=lambda: datetime(2100, 1, 1, tzinfo=UTC),
    )
    return observer, router


def test_language_detector_requires_a_clear_majority() -> None:
    assert _dominant_language("我住在杭州") == "zh"
    assert _dominant_language("I live in Hangzhou") == "en"
    assert _dominant_language("GPT-6 2026") is None


def test_language_check_uses_cited_source_and_keeps_original_names() -> None:
    entries = [
        {"source_event_id": "zh-user", "text": "我喜欢 TypeScript 和 PostgreSQL，也读 John Smith 的书。"},
        {"source_event_id": "en-tool", "text": "The package was released on version 2.3.1."},
    ]
    observations = [
        _observation(
            "用户喜欢 TypeScript 和 PostgreSQL，也读 John Smith 的书。",
            "TypeScript", evidence="zh-user",
        ),
        _observation(
            "The package is version 2.3.1.", "2.3.1", evidence="en-tool",
        ),
        _observation(
            "The user likes TypeScript and PostgreSQL.", "TypeScript", evidence="zh-user",
        ),
    ]

    assert _language_mismatch_indices(observations, entries) == [2]


def test_language_check_flags_english_noun_phrases_without_a_verb() -> None:
    source = [{"source_event_id": "zh-user", "text": "我对花生过敏，目前住在杭州。"}]
    observations = [
        _observation("Peanut allergy.", "Peanut allergy", evidence="zh-user"),
        _observation("Hangzhou resident.", "Hangzhou resident", evidence="zh-user"),
        _observation("用户提到 Peanut allergy。", "花生过敏", evidence="zh-user"),
    ]

    assert _language_mismatch_indices(observations, source) == [0, 1]


def test_observer_retries_language_mismatch_once_and_uses_final_chinese_output(monkeypatch) -> None:
    observer, router = _make_observer(monkeypatch, [
        {"body": _english_answer(), "usage": {"input_tokens": 10, "output_tokens": 5}},
        {"body": _chinese_answer(), "usage": {"input_tokens": 12, "output_tokens": 6}},
    ])

    batch = asyncio.run(observer._start_batch("f1-language-session", _queue(), None))

    assert batch is not None
    assert batch.language_status == "retry_recovered"
    assert batch.language_mismatch_count == 0
    assert batch.payload["observations"][0]["content"]["text"] == "用户每周跑步三次。"
    assert (batch.input_tokens, batch.output_tokens) == (22, 11)
    assert len(router.calls) == 2
    assert all(call["kwargs"]["temperature"] <= 0.1 for call in router.calls)
    assert "Retry this extraction once" in router.calls[1]["messages"][-1]["content"]
    assert "expected" not in router.calls[1]["messages"][-1]["content"].lower()


def test_mixed_sources_keep_retry_language_per_cited_observation(monkeypatch) -> None:
    initial = {
        "observations": [
            _observation("The user runs three times per week.", "three times weekly"),
            {
                **_observation(
                    "The PostgreSQL connection failed after a timeout.",
                    "connection timeout",
                    evidence="f1-language:tool",
                ),
                "speaker": "TOOL",
            },
        ],
    }
    corrected = {
        "observations": [
            _chinese_answer()["observations"][0],
            initial["observations"][1],
        ],
    }
    observer, router = _make_observer(monkeypatch, [
        {"body": initial},
        {"body": corrected},
    ])

    batch = asyncio.run(observer._start_batch("f1-language-session", _mixed_queue(), None))

    assert batch is not None
    assert batch.language_status == "retry_recovered"
    rows = batch.payload["observations"]
    assert rows[0]["content"]["text"] == "用户每周跑步三次。"
    assert rows[1]["content"]["text"] == "The PostgreSQL connection failed after a timeout."
    retry_instruction = router.calls[1]["messages"][-1]["content"]
    assert "Do not force a batch-wide language" in retry_instruction


def test_observer_retains_second_mismatch_and_counts_rows(monkeypatch) -> None:
    observer, router = _make_observer(monkeypatch, [
        {"body": _english_answer()},
        {"body": _english_answer()},
    ])

    batch = asyncio.run(observer._start_batch("f1-language-session", _queue(), None))

    assert batch is not None
    assert batch.language_status == "language_mismatch"
    assert batch.language_mismatch_count == 1
    assert observer.language_mismatch_count == 1
    assert batch.payload["observations"][0]["content"]["text"] == "The user runs three times per week."
    assert len(router.calls) == 2


def test_cancelled_language_retry_releases_its_daily_budget_reservation(monkeypatch) -> None:
    observer, _router = _make_observer(monkeypatch, [
        {"body": _english_answer()},
        {"cancel": True},
    ])

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(observer._start_batch("f1-language-session", _queue(), None))

    assert observer_module._DAILY_RESERVED.get("2100-01-01", 0) == 0
    assert observer_module._DAILY_SPENT.get("2100-01-01", 0) > 0


def test_prompts_keep_mastra_examples_and_add_chinese_language_rules() -> None:
    assert '"I have two kids" → 🔴 (14:30) User stated has two kids' in OBSERVER_EXTRACTION_INSTRUCTIONS
    assert "我对花生过敏" in OBSERVER_EXTRACTION_INSTRUCTIONS
    assert "same language as the source conversation" in OBSERVER_EXTRACTION_INSTRUCTIONS
    assert "🔴 “用户明确说对花生过敏”" in OBSERVER_OUTPUT_GUIDANCE

    prompt = build_reflector_system_prompt()
    assert "NEVER DELETE" in prompt
    assert "dominant language of the cited source records" in prompt
    assert "用户从杭州搬到深圳" in prompt


def test_observer_prompt_distinguishes_authorized_reminders_from_commitments(monkeypatch) -> None:
    observer, router = _make_observer(monkeypatch, [{"body": {"observations": []}}])

    batch = asyncio.run(observer._start_batch("f4-reminder-intent", _queue(), None))

    assert batch is not None
    system_prompt = router.calls[0]["messages"][0]["content"]
    assert "A direct request authorizing Atlas to remind or notify the user" in system_prompt
    assert "is an INTENT" in system_prompt
    assert (
        "Ordinary information questions, immediate help requests, and instructions for work "
        "happening now are not personal facts" in OBSERVER_QUESTION_RULES
    )
    assert (
        "A separately authorized, time-cued future reminder or notification may be recorded "
        "as INTENT" in OBSERVER_QUESTION_RULES
    )
    assert "Do not store ordinary information requests, immediate help requests" in system_prompt
    assert (
        "Only when the USER directly authorizes Atlas to perform a future reminder"
        in system_prompt
    )
    assert "recorded as INTENT" in system_prompt
    assert "without asking Atlas to act" in system_prompt
    assert "is a COMMITMENT" in system_prompt
    assert "hypothetical or information question" in system_prompt


def test_observer_prompt_and_daily_budget_use_configured_local_clock(monkeypatch) -> None:
    monkeypatch.setattr(observer_module, "_DAILY_SPENT", {})
    monkeypatch.setattr(observer_module, "_DAILY_RESERVED", {})
    router = _Router([{"body": _chinese_answer()}])
    observer = MemoryObserver(
        _Manager(router),
        {"user": {"timezone": "America/Los_Angeles"},
         "memory": {"v1": {"observer_daily_token_budget": 1_000_000}}},
        token_counter=len,
        now=lambda: datetime(2100, 1, 1, tzinfo=UTC),
    )

    batch = asyncio.run(observer._start_batch("f4-time-session", _queue(), None))

    assert batch is not None
    system_prompt = router.calls[0]["messages"][0]["content"]
    assert "America/Los_Angeles" in system_prompt
    assert "2099-12-31T16:00:00-08:00" in system_prompt
    assert set(observer_module._DAILY_SPENT) == {"2099-12-31"}


def test_reflector_prompt_and_apply_request_use_user_timezone(monkeypatch) -> None:
    import atlas.config

    monkeypatch.setattr(atlas.config, "load_user_settings", lambda: {})
    router = _Router([{"body": {"operations": []}}])
    config = {"user": {"timezone": "America/Los_Angeles"}}
    def now() -> datetime:
        return datetime(2100, 1, 1, tzinfo=UTC)

    reflector = MemoryReflector(_Manager(router), config=config, now=now)

    asyncio.run(reflector.propose_operations([]))

    system_prompt = router.calls[0]["messages"][0]["content"]
    assert "America/Los_Angeles" in system_prompt
    assert "2099-12-31T16:00:00-08:00" in system_prompt
    assert "local calendar day" in system_prompt

    class _Client:
        def __init__(self):
            self.request = None

        def call(self, method, route, *, json):
            self.request = (method, route, json)
            return {"accepted_count": 1}

    client = _Client()
    result = asyncio.run(reflector.apply_operations(
        "subject", [{"op": "ROLLUP_DAY"}], client=client,
    ))

    assert result["accepted_count"] == 1
    assert client.request[2]["cue_context"] == {
        "current_timezone": "America/Los_Angeles",
    }


def test_reflector_uses_low_temperature_without_changing_model_router(monkeypatch) -> None:
    router = _Router([{"body": {"operations": []}}])
    reflector = MemoryReflector(_Manager(router))

    asyncio.run(reflector._complete_with_retry("f1-language-unit-model", []))

    assert router.calls[0]["purpose"] == "memory_reflect"
    assert router.calls[0]["kwargs"]["temperature"] <= 0.1

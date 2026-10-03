"""heartbeat_respond contract tests: structured parse, legacy tokens, storage."""

from __future__ import annotations

from atlas.heartbeat.outcome import (
    DEFAULT_ACK_MAX_CHARS,
    HEARTBEAT_OUTCOMES,
    HeartbeatOutcome,
    parse_outcome,
    strip_heartbeat_token,
)


class TestStructured:
    def test_full_payload(self):
        outcome = parse_outcome(
            {
                "outcome": "progress",
                "notify": True,
                "summary": "Deploy at 40%",
                "notification_text": "Deploy at 40%, ETA 10m",
                "reason": "watching rollout",
                "priority": "high",
                "next_check": "15m",
                "scratch": "next: watch rollout",
            }
        )
        assert outcome.outcome == "progress"
        assert outcome.notify is True
        assert outcome.summary == "Deploy at 40%"
        assert outcome.notification_text == "Deploy at 40%, ETA 10m"
        assert outcome.reason == "watching rollout"
        assert outcome.priority == "high"
        assert outcome.next_check == "15m"
        assert outcome.scratch == "next: watch rollout"
        assert outcome.source == "structured"
        assert not outcome.silent
        assert outcome.stored

    def test_snake_case_aliases(self):
        outcome = parse_outcome(
            {
                "outcome": "blocked",
                "notify": False,
                "summary": "waiting on CI",
                "notification_text": "blocked on CI",
                "next_check": "30m",
            }
        )
        assert outcome.notification_text == "blocked on CI"
        assert outcome.next_check == "30m"

    def test_notify_false_is_silent(self):
        outcome = parse_outcome(
            {"outcome": "done", "notify": False, "summary": "backup finished"}
        )
        assert outcome.silent
        assert outcome.notification_body() == ""

    def test_no_change_forces_silence_regardless_of_notify(self):
        outcome = parse_outcome(
            {"outcome": "no_change", "notify": True, "summary": "all quiet"}
        )
        assert outcome.silent
        assert outcome.notification_body() == ""
        assert not outcome.stored

    def test_missing_notify_defaults_from_outcome(self):
        assert parse_outcome({"outcome": "blocked", "summary": "x"}).notify is True
        assert parse_outcome({"outcome": "no_change", "summary": "x"}).notify is False

    def test_tool_call_envelope(self):
        outcome = parse_outcome(
            {
                "name": "heartbeat_respond",
                "arguments": {
                    "outcome": "needs_attention",
                    "notify": True,
                    "summary": "disk 95%",
                },
            }
        )
        assert outcome.outcome == "needs_attention"
        assert outcome.notify is True

    def test_json_object_string(self):
        outcome = parse_outcome(
            '{"outcome": "done", "notify": false, "summary": "reindexed"}'
        )
        assert outcome.outcome == "done"
        assert outcome.source == "structured"

    def test_invalid_outcome_falls_back_to_text(self):
        outcome = parse_outcome({"outcome": "banana", "summary": "weird"})
        assert outcome.source == "legacy"

    def test_invalid_priority_dropped(self):
        outcome = parse_outcome(
            {"outcome": "progress", "notify": True, "summary": "s", "priority": "urgent"}
        )
        assert outcome.priority == ""

    def test_scratch_must_be_string(self):
        outcome = parse_outcome(
            {"outcome": "progress", "notify": True, "summary": "s", "scratch": 42}
        )
        assert outcome.scratch is None


class TestLegacyText:
    def test_no_reply_token_only_is_silent(self):
        for text in ("NO_REPLY", "no_reply", "NO_REPLY.", "*NO_REPLY*", "NO_REPLY NO_REPLY"):
            outcome = parse_outcome(text)
            assert outcome.outcome == "no_change", text
            assert outcome.silent
            assert not outcome.stored

    def test_no_reply_embedded_in_prose_is_not_silent(self):
        # Token-only rule: substantive replies ending with NO_REPLY survive.
        outcome = parse_outcome("Everything is fine, NO_REPLY needed here.")
        assert outcome.notify is True
        assert "NO_REPLY" in outcome.summary

    def test_heartbeat_ok_only_is_silent(self):
        outcome = parse_outcome("HEARTBEAT_OK")
        assert outcome.outcome == "no_change"
        assert outcome.silent

    def test_heartbeat_ok_with_short_ack_is_dropped(self):
        outcome = parse_outcome("HEARTBEAT_OK checked the queue, all clear.")
        assert outcome.silent

    def test_heartbeat_ok_with_long_remainder_becomes_alert(self):
        remainder = "x" * (DEFAULT_ACK_MAX_CHARS + 1)
        outcome = parse_outcome(f"HEARTBEAT_OK {remainder}")
        assert outcome.notify is True
        assert outcome.outcome == "needs_attention"
        assert outcome.summary == remainder

    def test_heartbeat_ok_wrapped_in_markup_still_strips(self):
        assert parse_outcome("<b>HEARTBEAT_OK</b>").silent
        assert parse_outcome("**HEARTBEAT_OK**").silent

    def test_long_alert_ending_with_token_keeps_alert(self):
        remainder = "CRITICAL: " + "x" * 320
        outcome = parse_outcome(f"{remainder} HEARTBEAT_OK")
        assert outcome.notify is True
        assert outcome.summary == remainder

    def test_heartbeat_ok_in_middle_is_not_special(self):
        text = "status HEARTBEAT_OK remains red"
        outcome = parse_outcome(text)
        assert outcome.notify is True
        assert outcome.summary == text

    def test_plain_alert_text(self):
        outcome = parse_outcome("Backfill failed twice, needs a look.")
        assert outcome.outcome == "needs_attention"
        assert outcome.notify is True
        assert outcome.summary == "Backfill failed twice, needs a look."
        assert outcome.notification_body() == outcome.summary

    def test_empty_and_none_are_silent(self):
        assert parse_outcome(None).silent
        assert parse_outcome("").silent
        assert parse_outcome("   \n  ").silent

    def test_outcomes_enum_shape(self):
        assert HEARTBEAT_OUTCOMES == (
            "no_change",
            "progress",
            "done",
            "blocked",
            "needs_attention",
        )

    def test_passthrough_heartbeat_outcome_instance(self):
        original = HeartbeatOutcome(outcome="done", notify=True, summary="s")
        assert parse_outcome(original) is original


class TestStripToken:
    def test_returns_none_for_token_only(self):
        assert strip_heartbeat_token("HEARTBEAT_OK") is None
        assert strip_heartbeat_token("") is None
        assert strip_heartbeat_token("   ") is None

    def test_budget_boundary(self):
        assert strip_heartbeat_token(f"HEARTBEAT_OK {'y' * 300}") is None
        assert strip_heartbeat_token(f"HEARTBEAT_OK {'y' * 301}") == "y" * 301

    def test_collapses_whitespace(self):
        # Remainder beyond the ack budget comes back whitespace-collapsed.
        remainder = "line1\n\nline2    spaced " + "x" * 300
        assert strip_heartbeat_token(f"HEARTBEAT_OK {remainder}") == (
            "line1 line2 spaced " + "x" * 300
        )

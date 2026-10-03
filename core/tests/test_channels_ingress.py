"""Ingress queue tests — idempotent enqueue, claim/ack/fail, cross-restart tombstones."""

from __future__ import annotations

import time

from atlas.channels.contract import Attachment, MessageEvent, MessageType
from atlas.channels.ingress import (
    INGRESS_MAX_ATTEMPTS,
    IngressQueue,
    event_from_payload,
    event_to_payload,
)


def make_event(event_id: str = "m1", *, chat_id: str = "100", channel: str = "telegram",
               account: str = "", kind: MessageType = MessageType.TEXT) -> MessageEvent:
    return MessageEvent(
        channel=channel,
        account=account,
        event_id=event_id,
        chat_id=chat_id,
        sender_id="42",
        kind=kind,
        text="你好",
        attachments=(
            [Attachment(kind=MessageType.FILE, filename="a.pdf")]
            if kind is MessageType.FILE
            else []
        ),
    )


def test_enqueue_is_idempotent_on_channel_account_event_id(tmp_path):
    queue = IngressQueue(tmp_path / "inbound.db")
    assert queue.enqueue_inbound(make_event()) is True
    assert queue.enqueue_inbound(make_event()) is False
    assert queue.enqueue_inbound(make_event("m1", account="work")) is True  # other account
    assert queue.enqueue_inbound(make_event("m1", channel="slack")) is True  # other channel
    assert queue.pending_count() == 3
    queue.close()


def test_claim_returns_roundtripped_event(tmp_path):
    queue = IngressQueue(tmp_path / "inbound.db")
    queue.enqueue_inbound(make_event("mfile", kind=MessageType.FILE))
    batch = queue.claim_batch(limit=4, worker_id="w1")
    assert len(batch) == 1
    record = batch[0]
    assert record.event.event_id == "mfile"
    assert record.event.kind is MessageType.FILE
    assert record.event.attachments[0].filename == "a.pdf"
    assert record.claimed_by == "w1"
    assert queue.claim_batch(limit=4, lease_seconds=999) == []  # lease held
    queue.close()


def test_ack_leaves_tombstone_that_blocks_reenqueue(tmp_path):
    queue = IngressQueue(tmp_path / "inbound.db")
    queue.enqueue_inbound(make_event())
    record = queue.claim_batch()[0]
    assert queue.ack(record.id) is True
    assert queue.pending_count() == 0
    assert queue.has_tombstone("telegram", "", "m1") is True
    assert queue.enqueue_inbound(make_event()) is False  # duplicate across restart
    queue.close()


def test_tombstone_ttl_expires(tmp_path):
    queue = IngressQueue(tmp_path / "inbound.db")
    queue.enqueue_inbound(make_event())
    record = queue.claim_batch()[0]
    stale = time.time() - 21 * 60  # older than the 20 min TTL
    assert queue.ack(record.id, now=stale) is True
    assert queue.enqueue_inbound(make_event(), now=time.time()) is True  # pruned on enqueue
    queue.close()


def test_new_instance_same_db_still_sees_tombstones(tmp_path):
    path = tmp_path / "inbound.db"
    first = IngressQueue(path)
    first.enqueue_inbound(make_event())
    record = first.claim_batch()[0]
    first.ack(record.id)
    first.close()
    second = IngressQueue(path)
    assert second.enqueue_inbound(make_event()) is False
    second.close()


def test_fail_requeues_with_backoff_and_respects_available_at(tmp_path):
    queue = IngressQueue(tmp_path / "inbound.db")
    queue.enqueue_inbound(make_event())
    record = queue.claim_batch()[0]
    now = 1000.0
    assert queue.fail(record.id, "boom", now=now) == "retry"
    # 1s ingress backoff after the first failure
    assert queue.claim_batch(now=now + 0.5) == []
    retried = queue.claim_batch(now=now + 1.1)
    assert len(retried) == 1 and retried[0].attempts == 1
    queue.close()


def test_fail_non_retryable_dead_letters_immediately(tmp_path):
    queue = IngressQueue(tmp_path / "inbound.db")
    queue.enqueue_inbound(make_event())
    record = queue.claim_batch()[0]
    assert queue.fail(record.id, "bad payload", retryable=False) == "dead"
    assert queue.pending_count() == 0
    assert queue.enqueue_inbound(make_event()) is False
    queue.close()


def test_fail_exhausts_attempt_budget_then_dead_letters(tmp_path):
    queue = IngressQueue(tmp_path / "inbound.db")
    queue.enqueue_inbound(make_event())
    now = 2000.0
    for attempt in range(INGRESS_MAX_ATTEMPTS):
        batch = queue.claim_batch(now=now)
        assert len(batch) == 1
        outcome = queue.fail(batch[0].id, "still failing", now=now + 5)
        now += 1000  # jump past the exponential backoff each round
        assert outcome == ("retry" if attempt < INGRESS_MAX_ATTEMPTS - 1 else "dead")
    assert queue.pending_count() == 0
    assert queue.has_tombstone("telegram", "", "m1") is True
    queue.close()


def test_lease_expiry_allows_reclaim(tmp_path):
    queue = IngressQueue(tmp_path / "inbound.db")
    queue.enqueue_inbound(make_event())
    assert queue.claim_batch(worker_id="w1", now=100.0)
    # within lease: not claimable; after lease: reclaimed
    assert queue.claim_batch(worker_id="w2", now=110.0) == []
    reclaimed = queue.claim_batch(worker_id="w2", now=100.0 + 301.0)
    assert len(reclaimed) == 1 and reclaimed[0].claimed_by == "w2"
    queue.close()


def test_event_payload_roundtrip_preserves_fields(tmp_path):
    event = make_event("rt")
    rebuilt = event_from_payload(event_to_payload(event))
    assert rebuilt == event

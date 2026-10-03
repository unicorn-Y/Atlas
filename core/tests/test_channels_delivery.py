"""Delivery queue tests — idempotency keys, retry backoff ladder, dead-lettering."""

from __future__ import annotations

from atlas.channels.delivery import (
    RETRY_DELAYS_SECONDS,
    DeliveryQueue,
    idempotency_key,
)


def test_idempotency_key_is_stable_sha256():
    first = idempotency_key("telegram", "100", "你好", account="", reply_to="")
    second = idempotency_key("telegram", "100", "你好", account="", reply_to="")
    assert first == second
    assert len(first) == 64
    assert first != idempotency_key("telegram", "100", "再见")
    assert first != idempotency_key("telegram", "101", "你好")


def test_enqueue_same_logical_message_is_idempotent(tmp_path):
    queue = DeliveryQueue(tmp_path / "out.db")
    key1 = queue.enqueue("telegram", "100", "hello")
    key2 = queue.enqueue("telegram", "100", "hello")
    assert key1 == key2
    assert len(queue.list_pending()) == 1
    explicit = queue.enqueue("telegram", "100", "hello", key="custom-key")
    assert explicit == "custom-key"
    assert len(queue.list_pending()) == 2
    queue.close()


def test_claim_due_marks_sending_and_increments_attempts(tmp_path):
    queue = DeliveryQueue(tmp_path / "out.db")
    queue.enqueue("telegram", "100", "hi")
    claimed = queue.claim_due(worker_id="w1", now=100.0)
    assert len(claimed) == 1 and claimed[0].status == "sending"
    assert claimed[0].attempts == 1
    assert queue.claim_due(worker_id="w2", now=100.5) == []  # lease held
    queue.close()


def test_backoff_sequence_and_dead_letter(tmp_path):
    queue = DeliveryQueue(tmp_path / "out.db")
    key = queue.enqueue("telegram", "100", "hi")
    now = 1000.0
    for expected_delay in RETRY_DELAYS_SECONDS:
        batch = queue.claim_due(now=now)
        assert len(batch) == 1
        outcome = queue.fail(batch[0].id, "transient", retryable=True, now=now)
        assert outcome == "retry"
        row = queue.get(key)
        assert row.status == "pending"
        assert row.next_retry_at == now + expected_delay
        # not claimable before next_retry_at
        assert queue.claim_due(now=now + expected_delay - 1) == []
        now += expected_delay + 1
    # one attempt beyond the budget dead-letters
    batch = queue.claim_due(now=now)
    assert len(batch) == 1
    assert queue.fail(batch[0].id, "still failing", retryable=True, now=now) == "dead"
    assert queue.get(key).status == "dead"
    assert queue.list_pending() == []
    queue.close()


def test_non_retryable_failure_dead_letters_immediately(tmp_path):
    queue = DeliveryQueue(tmp_path / "out.db")
    key = queue.enqueue("telegram", "100", "hi")
    batch = queue.claim_due(now=10.0)
    assert queue.fail(batch[0].id, "forbidden", retryable=False) == "dead"
    assert queue.get(key).status == "dead"
    queue.close()


def test_mark_delivered_sets_status_and_message_id(tmp_path):
    queue = DeliveryQueue(tmp_path / "out.db")
    key = queue.enqueue("telegram", "100", "hi")
    batch = queue.claim_due(now=10.0)
    assert queue.mark_delivered(batch[0].id, message_id="tg-77") is True
    row = queue.get(key)
    assert row.status == "delivered"
    assert row.metadata.get("message_id") == "tg-77"
    assert queue.claim_due(now=11.0) == []
    queue.close()


def test_per_channel_filtering_and_counts(tmp_path):
    queue = DeliveryQueue(tmp_path / "out.db")
    queue.enqueue("telegram", "100", "a")
    queue.enqueue("slack", "200", "b")
    claimed = queue.claim_due(channel="telegram", now=10.0)
    assert [record.channel for record in claimed] == ["telegram"]
    assert queue.counts(channel="telegram") == {"sending": 1}
    assert queue.counts() == {"sending": 1, "pending": 1}
    queue.close()


def test_stale_sending_lease_is_reclaimed(tmp_path):
    queue = DeliveryQueue(tmp_path / "out.db")
    queue.enqueue("telegram", "100", "hi")
    assert queue.claim_due(worker_id="crashed-worker", now=100.0)
    assert queue.claim_due(worker_id="w2", now=150.0) == []
    reclaimed = queue.claim_due(worker_id="w2", now=100.0 + 121.0)
    assert len(reclaimed) == 1 and reclaimed[0].attempts == 2
    queue.close()

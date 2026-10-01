# Ported from NousResearch/hermes-agent@663362680b6ffa4fbffeb58f6682564239a1953b:
# tests/agent/test_error_classifier.py and test_retry_utils.py (MIT, (c) Nous Research).
from types import SimpleNamespace

from atlas.agent.error_classifier import FailoverReason, classify_api_error
from atlas.agent.fallback_cooldown import clear, cool, is_cooling
from atlas.agent.retry_utils import jittered_backoff


def test_error_classification_selects_retry_and_fallback_policy() -> None:
    assert classify_api_error(SimpleNamespace(status_code=429, body="rate limit")).reason == FailoverReason.rate_limit
    assert classify_api_error(SimpleNamespace(status_code=402, body="payment required")).reason == FailoverReason.billing
    assert classify_api_error(SimpleNamespace(status_code=503, body="busy")).should_fallback
    context = classify_api_error(Exception("maximum context length exceeded"))
    assert context.should_compress and not context.should_fallback


def test_retry_backoff_is_bounded_and_cooldown_expires(monkeypatch) -> None:
    assert 1 <= jittered_backoff(1, base_delay=1, max_delay=2, jitter_ratio=0) <= 2
    clear()
    monkeypatch.setattr("atlas.agent.fallback_cooldown.time.monotonic", lambda: 100)
    cool("model-a", 10)
    assert is_cooling("model-a")
    monkeypatch.setattr("atlas.agent.fallback_cooldown.time.monotonic", lambda: 111)
    assert not is_cooling("model-a")

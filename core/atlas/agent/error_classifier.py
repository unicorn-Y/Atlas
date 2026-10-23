# Adapted from NousResearch/hermes-agent@663362680b6ffa4fbffeb58f6682564239a1953b:
# agent/error_classifier.py (MIT, (c) Nous Research); Atlas keeps provider-neutral rules only.
"""Provider-neutral classification for model-call recovery."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class FailoverReason(str, Enum):
    auth = "auth"
    billing = "billing"
    rate_limit = "rate_limit"
    context_overflow = "context_overflow"
    overloaded = "overloaded"
    server_error = "server_error"
    timeout = "timeout"
    network = "network"
    content_blocked = "content_blocked"
    model_not_found = "model_not_found"
    format_error = "format_error"
    unknown = "unknown"


@dataclass(frozen=True)
class ClassifiedError:
    reason: FailoverReason
    status_code: int | None
    retryable: bool
    should_fallback: bool
    should_compress: bool
    message: str


def classify_api_error(error: Exception) -> ClassifiedError:
    status = getattr(error, "status_code", None) or getattr(error, "status", None)
    if status is None:
        status = getattr(getattr(error, "response", None), "status_code", None)
    try:
        status = int(status) if status is not None else None
    except (TypeError, ValueError):
        status = None
    body = getattr(error, "body", None)
    text = " ".join((str(error), str(getattr(error, "message", "")), str(body or ""))).lower()
    if status == 402 or any(value in text for value in (
        "insufficient credits", "insufficient_quota", "billing limit", "billing_not_active",
        "quota exhausted", "payment required",
    )):
        reason, retryable, fallback, compress = FailoverReason.billing, False, True, False
    elif any(value in text for value in ("context length", "context window", "maximum context", "too many tokens")):
        reason, retryable, fallback, compress = FailoverReason.context_overflow, False, False, True
    elif status == 429:
        reason, retryable, fallback, compress = FailoverReason.rate_limit, True, True, False
    elif status in (502, 503, 504, 529):
        reason, retryable, fallback, compress = FailoverReason.overloaded, True, True, False
    elif status is not None and status >= 500:
        reason, retryable, fallback, compress = FailoverReason.server_error, True, True, False
    elif status in (401, 403):
        reason, retryable, fallback, compress = FailoverReason.auth, False, True, False
    elif status == 404:
        reason, retryable, fallback, compress = FailoverReason.model_not_found, False, True, False
    elif any(word in text for word in ("timeout", "timed out")):
        reason, retryable, fallback, compress = FailoverReason.timeout, True, True, False
    elif any(word in text for word in ("connection", "network", "temporarily unavailable")):
        reason, retryable, fallback, compress = FailoverReason.network, True, True, False
    elif any(word in text for word in ("content policy", "safety filter", "content was blocked")):
        reason, retryable, fallback, compress = FailoverReason.content_blocked, False, False, False
    elif status == 400:
        reason, retryable, fallback, compress = FailoverReason.format_error, False, False, False
    else:
        reason, retryable, fallback, compress = FailoverReason.unknown, True, False, False
    return ClassifiedError(reason, status, retryable, fallback, compress, str(error))

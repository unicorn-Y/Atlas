"""OpenTelemetry traces for Atlas runs.

Atlas already emits a rich structured event stream, but that stream is only
visible to a client that is attached. This module exports standard OTLP spans so
an external collector (Jaeger, Tempo, Honeycomb, an OTel Collector) can see the
same work, correlated with the log stream.

Design constraints, in order of importance:

* **Off unless configured.** No endpoint means no provider, no exporter, no
  background thread. Importing this module must stay free.
* **Never breaks a run.** Every entry point swallows its own failures. Telemetry
  that can abort an agent turn is worse than no telemetry.
* **Redaction is shared.** Attribute values pass through the same scrubber the
  logs use, so a secret cannot reach a collector through a span attribute.
* **Trace ids reach the logs.** ``configure_logging`` installs a processor that
  stamps the active ``trace_id``/``span_id`` onto every log line, which is what
  makes "find the trace for this error" a single query.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import structlog

log = structlog.get_logger(__name__)

_TRACER_NAME = "atlas"

_state: dict[str, Any] = {"provider": None, "tracer": None, "endpoint": None}


def endpoint_from_env() -> str | None:
    """Resolve the OTLP endpoint from the environment, or ``None``."""
    for key in ("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "OTEL_EXPORTER_OTLP_ENDPOINT"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return None


def is_enabled() -> bool:
    """True once a real provider is installed."""
    return _state["provider"] is not None


def setup_telemetry(
    endpoint: str | None = None,
    *,
    service_name: str = "atlas",
    force: bool = False,
) -> dict[str, Any]:
    """Install a global tracer provider exporting OTLP/HTTP.

    Returns a status dict; never raises. Calling twice is a no-op unless ``force``.
    """
    if _state["provider"] is not None and not force:
        return {"enabled": True, "endpoint": _state["endpoint"], "already": True}

    resolved = endpoint or endpoint_from_env()
    if not resolved:
        return {"enabled": False, "reason": "no endpoint configured"}

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:
        log.warning("telemetry.unavailable", error=str(exc))
        return {"enabled": False, "reason": f"missing dependency: {exc}"}

    try:
        resource = Resource.create({
            "service.name": service_name,
            "service.version": _version(),
        })
        provider = TracerProvider(resource=resource)
        # A local collector is on the same machine; a batch of 512 with a 5s delay
        # keeps per-turn overhead invisible while bounding loss on hard exit.
        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(endpoint=resolved),
                max_queue_size=2048,
                max_export_batch_size=512,
                schedule_delay_millis=5000,
            )
        )
        trace.set_tracer_provider(provider)
        _state.update(
            provider=provider, tracer=provider.get_tracer(_TRACER_NAME), endpoint=resolved
        )
        log.info("telemetry.enabled", endpoint=resolved)
        return {"enabled": True, "endpoint": resolved}
    except Exception as exc:  # noqa: BLE001 - telemetry must not break startup
        log.warning("telemetry.setup_failed", error=str(exc))
        return {"enabled": False, "reason": str(exc)}


def shutdown() -> None:
    """Flush pending spans. Safe to call when nothing was configured."""
    provider = _state["provider"]
    if provider is None:
        return
    try:
        provider.shutdown()
    except Exception as exc:  # noqa: BLE001
        log.warning("telemetry.shutdown_failed", error=str(exc))
    finally:
        _state.update(provider=None, tracer=None, endpoint=None)


def _version() -> str:
    try:
        from atlas import __version__

        return str(__version__)
    except Exception:  # noqa: BLE001
        return "unknown"


def _scrub_attributes(attributes: dict[str, Any]) -> dict[str, Any]:
    """Redact secret-looking values, and coerce to OTel-safe scalar types.

    Two layers, because either alone leaks:

    * ``is_secret_key`` on the **attribute name** — a span attribute called
      ``api_key`` is a secret regardless of what its value looks like, and
      ``scrub`` is context-based (it needs ``key=value`` in a string), so it
      passes a bare ``sk-...`` straight through.
    * ``scrub`` on every string — catches embedded credentials in free text.
    """
    try:
        from atlas import secrets_store
    except Exception:  # noqa: BLE001
        secrets_store = None  # type: ignore[assignment]

    safe: dict[str, Any] = {}
    for key, value in attributes.items():
        if value is None or isinstance(value, (bool, int, float)):
            safe[key] = value
            continue
        text = value if isinstance(value, str) else str(value)
        if secrets_store is not None:
            if secrets_store.is_secret_key(key):
                safe[key] = secrets_store.mask(text)
                continue
            text = secrets_store.scrub(text)
        safe[key] = text
    return safe


@contextmanager
def span(name: str, attributes: dict[str, Any] | None = None) -> Iterator[Any]:
    """Start a span if telemetry is enabled, otherwise yield ``None``.

    Yields the span so callers can set attributes mid-flight; they must not
    assume it is non-``None``.
    """
    tracer = _state["tracer"]
    if tracer is None:
        yield None
        return
    try:
        with tracer.start_as_current_span(name) as current:
            if attributes:
                for key, value in _scrub_attributes(attributes).items():
                    current.set_attribute(key, value)
            yield current
    except Exception as exc:  # noqa: BLE001 - a span must never abort the caller
        log.debug("telemetry.span_failed", span=name, error=str(exc))
        yield None


def current_ids() -> dict[str, str]:
    """Active ``trace_id``/``span_id`` as hex, or ``{}`` when none."""
    try:
        from opentelemetry import trace

        context = trace.get_current_span().get_span_context()
    except Exception:  # noqa: BLE001
        return {}
    if not context or not context.is_valid:
        return {}
    return {
        "trace_id": format(context.trace_id, "032x"),
        "span_id": format(context.span_id, "016x"),
    }


def trace_log_processor(
    _logger: Any, _method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Structlog processor: stamp trace context onto every log record."""
    ids = current_ids()
    if ids:
        event_dict.update(ids)
    return event_dict


def status() -> dict[str, Any]:
    """Introspection payload describing the current telemetry state."""
    return {
        "enabled": is_enabled(),
        "endpoint": _state["endpoint"],
        "configured_via": (
            "argument" if is_enabled() else ("env" if endpoint_from_env() else None)
        ),
        "env": {
            key: bool(os.environ.get(key))
            for key in ("OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
        },
    }

"""Ordinary-event and session-log OTLP channels are independent (S22)."""

import pytest

from atlas import telemetry

pytestmark = pytest.mark.unit


class _RecordingTracer:
    def __init__(self, label, spans):
        self._label = label
        self._spans = spans

    def start_as_current_span(self, name):
        tracer = self

        class _Current:
            def set_attribute(self, key, value):
                self.key = key

        class _Ctx:
            def __init__(self):
                self.current = _Current()

            def __enter__(self):
                tracer._spans.append((tracer._label, name))
                return self.current

            def __exit__(self, *exc):
                return False

        return _Ctx()


def test_session_spans_route_to_the_independent_channel(monkeypatch):
    spans: list[tuple[str, str]] = []
    monkeypatch.setitem(telemetry._state, "tracer", _RecordingTracer("events", spans))
    monkeypatch.setitem(
        telemetry._state, "session_tracer", _RecordingTracer("session-log", spans)
    )

    with telemetry.span("atlas.session.turn_outline", {"timeline.limit": 5}):
        pass
    with telemetry.span("atlas.run_checkpoint.write"):
        pass
    with telemetry.span("atlas.product"):
        pass

    assert ("session-log", "atlas.session.turn_outline") in spans
    assert ("events", "atlas.run_checkpoint.write") in spans
    assert ("events", "atlas.product") in spans
    # exactly one span reached the session-log channel
    assert [label for label, _name in spans].count("session-log") == 1


def test_setup_builds_two_channels_with_independent_endpoints(monkeypatch):
    exporters: list[str] = []

    class _DummyExporter:
        def __init__(self, endpoint):
            exporters.append(str(endpoint))

    import opentelemetry.exporter.otlp.proto.http.trace_exporter as exporter_module

    monkeypatch.setattr(exporter_module, "OTLPSpanExporter", _DummyExporter)
    try:
        status = telemetry.setup_telemetry(
            "http://127.0.0.1:9/v1/traces",
            session_log_endpoint="http://127.0.0.1:10/v1/traces",
        )
        assert status["enabled"] is True
        assert status["endpoint"] == "http://127.0.0.1:9/v1/traces"
        assert status["session_log_endpoint"] == "http://127.0.0.1:10/v1/traces"
        assert telemetry._state["provider"] is not None
        assert telemetry._state["session_provider"] is not None
        # Two providers = two bounded queues and two worker threads.
        assert telemetry._state["provider"] is not telemetry._state["session_provider"]
        assert exporters == [
            "http://127.0.0.1:9/v1/traces",
            "http://127.0.0.1:10/v1/traces",
        ]
        introspection = telemetry.status()
        assert introspection["channels"]["session-log"]["endpoint"] == \
            "http://127.0.0.1:10/v1/traces"
        assert introspection["channels"]["events"]["endpoint"] == \
            "http://127.0.0.1:9/v1/traces"
    finally:
        telemetry.shutdown()
    assert telemetry._state["provider"] is None
    assert telemetry._state["session_provider"] is None
    assert telemetry._state["session_tracer"] is None


def test_session_log_endpoint_env_overrides_shared_endpoint(monkeypatch):
    exporters: list[str] = []

    class _DummyExporter:
        def __init__(self, endpoint):
            exporters.append(str(endpoint))

    import opentelemetry.exporter.otlp.proto.http.trace_exporter as exporter_module

    monkeypatch.setattr(exporter_module, "OTLPSpanExporter", _DummyExporter)
    monkeypatch.setenv(
        telemetry.SESSION_LOG_ENDPOINT_ENV, "http://127.0.0.1:11/v1/traces"
    )
    try:
        status = telemetry.setup_telemetry("http://127.0.0.1:9/v1/traces")
        assert status["session_log_endpoint"] == "http://127.0.0.1:11/v1/traces"
        assert exporters == [
            "http://127.0.0.1:9/v1/traces",
            "http://127.0.0.1:11/v1/traces",
        ]
    finally:
        telemetry.shutdown()


def test_without_dedicated_endpoint_session_channel_shares_endpoint_only(monkeypatch):
    exporters: list[str] = []

    class _DummyExporter:
        def __init__(self, endpoint):
            exporters.append(str(endpoint))

    import opentelemetry.exporter.otlp.proto.http.trace_exporter as exporter_module

    monkeypatch.setattr(exporter_module, "OTLPSpanExporter", _DummyExporter)
    monkeypatch.delenv(telemetry.SESSION_LOG_ENDPOINT_ENV, raising=False)
    try:
        status = telemetry.setup_telemetry("http://127.0.0.1:9/v1/traces")
        assert status["session_log_endpoint"] == status["endpoint"]
        assert telemetry._state["session_provider"] is not telemetry._state["provider"]
    finally:
        telemetry.shutdown()


def test_shutdown_flushes_both_channels():
    shut_down: list[str] = []

    class _Provider:
        def shutdown(self):
            shut_down.append("ok")

    telemetry._state.update(
        provider=_Provider(), tracer=object(), endpoint="http://x/v1/traces",
        session_provider=_Provider(), session_tracer=object(), session_endpoint="http://y/v1/traces",
    )
    telemetry.shutdown()
    assert shut_down == ["ok", "ok"]
    assert telemetry.is_enabled() is False
    assert telemetry.status()["session_log_endpoint"] is None

"""Caller-selected product events use the existing OTLP exporter."""

from contextlib import contextmanager

import pytest

from atlas import telemetry

pytestmark = pytest.mark.unit


def test_product_event_is_disabled_without_a_tracer(monkeypatch):
    monkeypatch.setitem(telemetry._state, "tracer", None)
    assert telemetry.product_event("composer.sent", {"characters": 12}) is False


def test_product_event_exports_only_selected_scrubbed_attributes(monkeypatch):
    events = []

    class Current:
        def add_event(self, name, attributes):
            events.append((name, attributes))

    class Tracer:
        @contextmanager
        def start_as_current_span(self, name):
            assert name == "atlas.product"
            yield Current()

    monkeypatch.setitem(telemetry._state, "tracer", Tracer())
    secret = "sk-livekey0123456789abcdef"
    assert telemetry.product_event("composer.sent", {"count": 2, "api_key": secret})
    assert events[0][0] == "composer.sent"
    assert set(events[0][1]) == {"count", "api_key"}
    assert events[0][1]["count"] == 2
    assert secret not in str(events)


def test_product_event_exporter_failure_is_contained(monkeypatch):
    class Tracer:
        def start_as_current_span(self, name):
            raise RuntimeError("collector down")

    monkeypatch.setitem(telemetry._state, "tracer", Tracer())
    assert telemetry.product_event("composer.sent") is False


@pytest.mark.parametrize("name", ["", "with spaces", None, "a" * 129])
def test_product_event_rejects_invalid_names(name):
    assert telemetry.product_event(name) is False

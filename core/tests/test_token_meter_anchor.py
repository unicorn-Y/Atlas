"""E29: provider usage anchored back onto per-surface-node token prices.

``price_surface_nodes`` estimates each node heuristically; a successful model
request reports real usage that will not match the estimate. The anchor is a
pure projection scaling every node so the anchored prices sum (modulo rounding)
to the provider-reported input. The kernel records it per conversation request
(``model_request_anchor`` in the run journal, ``surface_anchor`` on the usage row).
"""

from __future__ import annotations

import pytest

from atlas.engine.agent.token_meter import anchor_surface_to_usage


NODES = [
    {"seq": 0, "tokens": 100},
    {"seq": 1, "tokens": 200},
    {"seq": 2, "tokens": 700},
]
SURFACE = 1000


@pytest.mark.unit
def test_anchor_scales_every_node_to_the_provider_total():
    anchor = anchor_surface_to_usage(
        surface_nodes=NODES, surface_tokens=SURFACE, provider_input_tokens=1500,
        request_sha256="abc123",
    )

    assert anchor is not None
    assert anchor["anchored"] is True
    assert anchor["provider_input_tokens"] == 1500
    assert anchor["surface_tokens"] == SURFACE
    assert anchor["anchor_ratio"] == 1.5
    assert anchor["request_sha256"] == "abc123"
    priced = anchor["surface_node_tokens_anchored"]
    assert [node["seq"] for node in priced] == [0, 1, 2]
    assert [node["anchored_tokens"] for node in priced] == [150, 300, 1050]
    # Estimates are never mutated: heuristic prices ride along unchanged.
    assert [node["heuristic_tokens"] for node in priced] == [100, 200, 700]
    assert sum(node["anchored_tokens"] for node in priced) == 1500


@pytest.mark.unit
def test_anchor_rounds_per_node_within_the_documented_rounding_slack():
    """Per-node prices are ``round(estimate * ratio)``; the sum tracks the
    provider total only within the rounding slack of n nodes (documented
    "modulo rounding")."""
    nodes = [{"seq": i, "tokens": 1} for i in range(3)]
    anchor = anchor_surface_to_usage(
        surface_nodes=nodes, surface_tokens=3, provider_input_tokens=2,
    )
    assert anchor is not None
    priced = anchor["surface_node_tokens_anchored"]
    assert [node["anchored_tokens"] for node in priced] == [1, 1, 1]
    assert abs(sum(node["anchored_tokens"] for node in priced) - 2) <= len(priced)


@pytest.mark.unit
def test_anchor_returns_none_when_there_is_nothing_to_anchor():
    # No provider usage.
    assert anchor_surface_to_usage(surface_nodes=NODES, surface_tokens=SURFACE,
                                   provider_input_tokens=0) is None
    # No nodes.
    assert anchor_surface_to_usage(surface_nodes=[], surface_tokens=10,
                                   provider_input_tokens=100) is None
    # Non-positive surface total.
    assert anchor_surface_to_usage(surface_nodes=NODES, surface_tokens=0,
                                   provider_input_tokens=100) is None
    # Garbage inputs fail closed instead of producing a misleading record.
    assert anchor_surface_to_usage(surface_nodes="nope", surface_tokens="nope",
                                   provider_input_tokens="nope") is None


@pytest.mark.unit
def test_anchor_falls_back_to_heuristic_tokens_when_tokens_missing():
    nodes = [{"seq": 5, "heuristic_tokens": 500}]
    anchor = anchor_surface_to_usage(surface_nodes=nodes, surface_tokens=500,
                                     provider_input_tokens=1000)
    assert anchor is not None
    assert anchor["surface_node_tokens_anchored"] == [
        {"seq": 5, "heuristic_tokens": 500, "anchored_tokens": 1000},
    ]


@pytest.mark.unit
def test_kernel_records_the_anchor_for_conversation_requests():
    """The loop wiring: usage rows for conversation requests carry the anchor keys."""
    import inspect
    from atlas.engine.kernel import loop

    source = inspect.getsource(loop)
    assert "anchor_surface_to_usage" in source
    assert "model_request_anchor" in source
    assert "surface_node_tokens_anchored" in source

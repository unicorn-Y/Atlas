"""Route-aware image pricing: the model entry's price replaces the heuristic (S25)."""

from __future__ import annotations

import pytest

from atlas.engine.agent.token_meter import price_surface_nodes, route_image_pricer

pytestmark = pytest.mark.unit


def _image_message(role="user", detail="high"):
    return {
        "role": role,
        "content": [
            {"type": "text", "text": "What is in this picture?"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA", "detail": detail}},
        ],
    }


def test_absent_config_keeps_the_heuristic():
    assert route_image_pricer({}) is None
    assert route_image_pricer({"image_pricing": None}) is None
    assert route_image_pricer(None) is None


def test_uniform_int_price_applies_to_every_image_occurrence():
    pricer = route_image_pricer({"image_pricing": 800})
    route = {"model": "deepseek-v4.1-flash", "provider": "openai"}
    images = [{"type": "image_url"}, {"type": "image_url"}]
    assert pricer(route, images) == [
        {"visual_tokens": 800, "text": ""},
        {"visual_tokens": 800, "text": ""},
    ]


def test_mapping_price_uses_visual_tokens_and_placeholder_text():
    pricer = route_image_pricer({"image_pricing": {"visual_tokens": 765, "text": "[image]"}})
    prices = pricer({"model": "m"}, [{"type": "image_url"}])
    assert prices == [{"visual_tokens": 765, "text": "[image]"}]


@pytest.mark.parametrize("bad", [
    {"image_pricing": True},
    {"image_pricing": -1},
    {"image_pricing": "800"},
    {"image_pricing": {"visual_tokens": -3}},
    {"image_pricing": {"visual_tokens": "800"}},
])
def test_invalid_config_falls_back_to_heuristic_instead_of_raising(bad, caplog):
    assert route_image_pricer(bad) is None


def test_priced_node_differs_from_heuristic_node():
    message = _image_message()
    nodes = [{"seq": 0, "message": message}]
    heuristic = price_surface_nodes(nodes, route={"model": "m"})
    priced = price_surface_nodes(
        nodes, route={"model": "m"},
        image_pricing=route_image_pricer({"image_pricing": {"visual_tokens": 900, "text": "[image]"}}),
    )
    assert priced["nodes"][0]["tokens"] > heuristic["nodes"][0]["tokens"]
    assert priced["nodes"][0]["heuristic_tokens"] == heuristic["nodes"][0]["tokens"]


def test_text_only_nodes_are_unaffected_by_image_pricing():
    nodes = [{"seq": 0, "message": {"role": "user", "content": "plain text only"}}]
    priced = price_surface_nodes(
        nodes, route={"model": "m"},
        image_pricing=route_image_pricer({"image_pricing": 900}),
    )
    assert priced["nodes"][0]["tokens"] == priced["nodes"][0]["heuristic_tokens"]

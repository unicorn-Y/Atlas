from __future__ import annotations

import json

import pytest

from atlas import standing_orders


@pytest.fixture
def order_files(tmp_path, monkeypatch):
    monkeypatch.setattr(standing_orders, "_paths", lambda: (
        tmp_path / "standing-orders.json", tmp_path / "audit.jsonl",
    ))


def test_standing_order_crud_search_pause_resume_delete_and_audit(order_files):
    order = standing_orders.create_order({
        "name": "Review task", "owner_agent_id": "agent-a",
        "instruction": "Check edge cases before finishing.",
        "scope": {"kind": "all"}, "trigger": {"keywords": ["review"]},
    })
    assert standing_orders.list_orders("edge", "agent-a")[0]["id"] == order["id"]
    assert standing_orders.matching_orders("agent-a", None, "Please review this") == [order]
    assert standing_orders.matching_orders("agent-a", None, "ordinary request") == []
    assert standing_orders.recent_audit(order_id=order["id"])[0]["matched_keywords"] == ["review"]
    paused = standing_orders.update_order(order["id"], {**order, "enabled": False})
    assert paused and not standing_orders.matching_orders("agent-a", None, "review")
    resumed = standing_orders.update_order(order["id"], {**paused, "enabled": True})
    assert resumed and standing_orders.matching_orders("agent-a", None, "review")
    assert standing_orders.delete_order(order["id"])
    assert standing_orders.list_orders() == []
    assert standing_orders.recent_audit(order_id=order["id"])


def test_standing_order_scope_owner_and_context_budget(order_files):
    scoped = standing_orders.create_order({
        "owner_agent_id": "agent-a", "instruction": "Only for this workspace.",
        "scope": {"kind": "workspace", "workspace": "C:/work"},
        "trigger": {"keywords": []},
    })
    assert standing_orders.matching_orders("agent-b", "C:/work", "hello") == []
    assert standing_orders.matching_orders("agent-a", "C:/other", "hello") == []
    assert standing_orders.matching_orders("agent-a", "c:/WORK", "hello")[0]["id"] == scoped["id"]
    with pytest.raises(ValueError):
        standing_orders.create_order({"owner_agent_id": "agent-a", "instruction": "", "scope": {"kind": "all"}})

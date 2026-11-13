from __future__ import annotations

import pytest

from atlas.automation.engine import AutomationEngine
from atlas.automation.store import AutomationStore, AutomationValidationError, normalize_record

pytestmark = pytest.mark.unit


def test_agent_turn_preserves_preset_bindings_and_dispatches_them(tmp_path) -> None:
    received = {}

    async def dispatch(payload):
        received.update(payload)
        return {"ok": True}

    store = AutomationStore(tmp_path / "automations.toml")
    record = normalize_record({
        "id": "preset-job",
        "name": "Preset job",
        "trigger": {"kind": "interval", "every_seconds": 60},
        "payload": {
            "kind": "agent_turn", "message": "run",
            "agent_preset_id": "reviewer", "permission_preset": "trusted",
        },
    })
    saved = store.put(record)
    assert saved["payload"]["agent_preset_id"] == "reviewer"
    assert saved["payload"]["permission_preset"] == "trusted"

    result = pytest.importorskip("asyncio").run(
        AutomationEngine(store, dispatch_turn=dispatch).execute_payload("preset-job", "manual")
    )
    assert result["status"] == "ok"
    assert received["agent_preset_id"] == "reviewer"
    assert received["permission_preset"] == "trusted"


def test_agent_turn_rejects_unknown_permission_preset() -> None:
    record = normalize_record({
        "id": "preset-job", "name": "Preset job",
        "trigger": {"kind": "interval", "every_seconds": 60},
        "payload": {"kind": "agent_turn", "permission_preset": "root"},
    })
    with pytest.raises(AutomationValidationError, match="permission_preset"):
        from atlas.automation.store import validate_record

        validate_record(record)


from __future__ import annotations

import json

from .base import ParticipantAdapter, RunContext, RunOutcome


class ZCodeAdapter(ParticipantAdapter):
    name = "zcode"

    def availability(self):
        return {"available": True, "reason": "manual participant; GUI operation requires a human"}

    def build_command(self, context: RunContext) -> list[str]:
        return []

    def run_once(self, context: RunContext) -> RunOutcome:
        instruction = (
            "ZCode T1 manual run\n"
            f"Task: {context.task_id}\n"
            f"Workspace: {context.workspace}\n"
            "Open this workspace in ZCode and complete the task manually. Record observed actions and usage; do not treat this template as execution evidence.\n"
        )
        template = {"participant": "zcode", "task_id": context.task_id, "success": None,
                    "duration_ms": None, "tool_calls": None, "turns": None,
                    "input_tokens": None, "output_tokens": None, "cached_tokens": None,
                    "cost_usd": None, "notes": "manual entry required"}
        return RunOutcome(None, instruction + json.dumps(template, ensure_ascii=False, indent=2),
                          error="manual participant; awaiting human execution",
                          unsupported=["automated_execution"])

    def parse_usage(self, outcome: RunOutcome):
        return {"tool_calls": None, "turns": None, "input_tokens": None,
                "output_tokens": None, "cached_tokens": None, "cost_usd": None}

    def supports(self, capability: str) -> bool:
        return False

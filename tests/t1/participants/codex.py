from __future__ import annotations

from .base import RunContext, RunOutcome
from .common import CliAdapter, usage_from_events


class CodexAdapter(CliAdapter):
    name = "codex"
    executable_name = "codex"

    def build_command(self, context: RunContext) -> list[str]:
        command = self._prefix() + ["exec", "--json", "--cd", str(context.workspace)]
        if context.model:
            command += ["--model", context.model]
        command += [context.prompt]
        return command

    def run_once(self, context: RunContext) -> RunOutcome:
        return self._run(context, self.build_command(context))

    def parse_usage(self, outcome: RunOutcome):
        return usage_from_events(outcome, usage_paths=(("usage",),),
                                 tool_types=("command_execution", "mcp_tool_call"),
                                 turn_types=("turn.completed", "turn.failed"))

    def supports(self, capability: str) -> bool:
        return capability == "subagents" or super().supports(capability)  # exec has no live input channel.

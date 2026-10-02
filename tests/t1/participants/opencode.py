from __future__ import annotations

import os
import subprocess
import tempfile

from .base import RunContext, RunOutcome
from .common import CliAdapter, redact, usage_from_events


class OpenCodeAdapter(CliAdapter):
    name = "opencode"
    executable_name = "opencode"

    def availability(self):
        # Probe only the local CLI help surface with isolated user directories;
        # never let a broken launcher load or rewrite the real user config.
        try:
            with tempfile.TemporaryDirectory(prefix="atlas-t1-opencode-help-") as home:
                env = os.environ.copy()
                for key in list(env):
                    if any(part in key.upper() for part in ("API_KEY", "TOKEN", "SECRET", "PASSWORD")):
                        env.pop(key, None)
                env.update({"HOME": home, "USERPROFILE": home,
                            "APPDATA": home, "LOCALAPPDATA": home,
                            "XDG_CONFIG_HOME": home, "XDG_DATA_HOME": home})
                completed = subprocess.run(self._prefix() + ["run", "--help"], cwd=home,
                                           env=env, capture_output=True, timeout=5, check=False)
            if completed.returncode == 0:
                return {"available": True, "reason": None, "path": self._prefix()[0]}
            details = (completed.stderr or completed.stdout).decode("utf-8", "replace")
            _, safe = redact("", details)
            return {"available": False, "reason": "OpenCode CLI help failed: " + safe[:240]}
        except subprocess.TimeoutExpired:
            return {"available": False, "reason": "OpenCode CLI help timed out"}
        except OSError as exc:
            return {"available": False, "reason": f"OpenCode CLI not runnable: {type(exc).__name__}"}

    def build_command(self, context: RunContext) -> list[str]:
        command = self._prefix() + ["run", "--format", "json"]
        if context.model:
            command += ["--model", context.model]
        command += [context.prompt]
        return command

    def run_once(self, context: RunContext) -> RunOutcome:
        return self._run(context, self.build_command(context))

    def parse_usage(self, outcome: RunOutcome):
        return usage_from_events(outcome, usage_paths=(("part", "tokens"), ("tokens",), ("usage",)),
                                 tool_types=("tool_use", "tool", "step-start"),
                                 turn_types=("step-finish", "result"))

    def supports(self, capability: str) -> bool:
        return capability == "subagents" or super().supports(capability)

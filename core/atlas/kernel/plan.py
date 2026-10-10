# Ported from openai/codex@6c0c6759d0617d7670826b61aca0a931bbb6db1f: codex-rs/models-manager/src/collaboration_mode_presets.rs (Apache-2.0)
# Ported from openai/codex@6c0c6759d0617d7670826b61aca0a931bbb6db1f: codex-rs/core/src/tools/handlers/plan.rs (Apache-2.0)
# SPDX-License-Identifier: Apache-2.0
# Behavior from Claude Code v2.1.296 docs: https://code.claude.com/docs/en/permission-modes#analyze-before-you-edit-with-plan-mode
"""Plan mode policy using Atlas TaskPlan, TodoStore and plan persistence callback."""

from __future__ import annotations

import inspect
from typing import Any, Callable, Mapping, Sequence

from atlas.agent.planning import TaskPlan
from atlas.agent.todo_state import TodoStore

READ_ONLY_TOOLS = frozenset({
    "read_file", "search_files", "glob", "grep", "Read", "Glob", "Grep",
    "local_file",
    "web_search", "web_fetch", "WebSearch", "WebFetch", "session_search", "clarify", "ask_user",
})


class PlanMode:
    """Wrap the caller's existing session/run context; never open another store.

    Persist via the existing run_drive plan_update_callback. `session_state` may
    be AgentRunContext or its current state dictionary. Approval must originate
    from user input; a model tool cannot authorize execution.
    """
    def __init__(self, session_state: Any, config: Mapping[str, Any] | None = None, *,
                 plan_state: Mapping[str, Any] | None = None,
                 plan_update_callback: Callable[[dict[str, Any]], Any] | None = None,
                 todo_store: TodoStore | None = None):
        self.state = session_state
        self.config = dict(config or {})
        self.persist = plan_update_callback
        self.todo_store = todo_store or self._get("todo_store", None)
        value = plan_state or self._get("plan_state", None)
        self.plan = TaskPlan.from_dict(dict(value)) if value else None

    def _get(self, key: str, default: Any = None) -> Any:
        return self.state.get(key, default) if isinstance(self.state, dict) else getattr(self.state, key, default)

    def _set(self, key: str, value: Any) -> None:
        if isinstance(self.state, dict):
            self.state[key] = value
        else:
            setattr(self.state, key, value)

    @property
    def active(self) -> bool:
        return self._get("mode", "act") == "plan"

    def enter(self) -> None:
        self._set("mode", "plan")

    def approve(self, *, user_approved: bool) -> None:
        if not user_approved:
            raise PermissionError("Execution requires user approval of the plan")
        self._set("mode", "act")

    def require_tool(self, name: str, *, read_only: bool = False) -> None:
        if self.active and name not in READ_ONLY_TOOLS and not read_only:
            raise PermissionError(f"Tool {name} is unavailable in read-only plan mode")

    def filter_tools(self, tools: Sequence[Mapping[str, Any]], *,
                     read_only_names: Sequence[str] = ()) -> list[Mapping[str, Any]]:
        if not self.active:
            return list(tools)
        names = READ_ONLY_TOOLS | frozenset(read_only_names)
        return [tool for tool in tools if str((tool.get("function") or tool).get("name", "")) in names]

    async def update_plan(self, value: Mapping[str, Any]) -> dict[str, Any]:
        plan = TaskPlan.from_dict(dict(value))
        snapshot = plan.to_dict()
        if self.persist is None:
            raise RuntimeError("Plan updates require the existing plan_update_callback")
        result = self.persist(snapshot)
        if inspect.isawaitable(result):
            await result
        # Commit only after the existing state persistence succeeds.
        self.plan = plan
        self._set("plan_state", snapshot)
        if self.todo_store is not None:
            self.todo_store.write([
                {"id": item.id, "content": item.title, "status": item.status}
                for item in plan.subtasks
            ])
        return {"type": "plan_updated", "plan": snapshot, "resumed": False}

    def model_settings(self, model: str, effort: str | None = None) -> tuple[str, str | None]:
        if not self.active:
            return model, effort
        engine = self.config.get("engine", self.config)
        selected = str(engine.get("planning_model") or model)
        from atlas.models.reasoning_stages import effort_for_phase, load_stage_config
        stage = self.config.get("reasoning_stages")
        if stage is None:
            stage = load_stage_config()
        # Codex's Plan preset retains the current model and sets effort to medium;
        # keep Atlas's explicit planning overrides ahead of that default.
        planning_effort = (
            engine.get("planning_reasoning_effort")
            or effort_for_phase(stage, "planning")
            or "medium"
        )
        return selected, planning_effort

    def prompt(self) -> str:
        if not self.active:
            return ""
        return (
            "Plan mode: investigate with read-only tools, produce a concrete plan, "
            "and wait for the user's approval before execution. Do not edit files, "
            "run commands, start processes, or delegate work that changes state."
        )

"""Atlas Agent Orchestrator with Hermes runtime tool adapters."""

# W07 orchestration adapters are informed by NousResearch/hermes-agent at
# 330d9d6df9c7bffe125ba0ae64a0abc488a7d2c3 (MIT): delegation context,
# todo state, kanban tool contracts, and the MoA loop; implemented on Atlas runs.

from __future__ import annotations

import asyncio
import copy
from datetime import date
import fnmatch
import inspect
import json
import os
import re
import time
import tempfile
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from atlas.agent.capabilities import AgentCapabilityRegistry
from atlas.agent.checkpoints import ShadowGitCheckpointStore
from atlas.agent.enrichment import (
    AtlasToolBridge,
    CodeActRuntime,
    ContextMaintenance,
    DelegationService,
    HookBus,
    ReminderPolicy,
    SystemReminders,
    TrajectoryReviewer,
)
from atlas.agent.todo_state import TodoStore
from atlas.agent.results import externalize_tool_output, frame_delegate_result_data, frame_subagent_result
from atlas.agent.error_classifier import classify_api_error
from atlas.agent.fallback_cooldown import cool as cool_model
from atlas.agent.fallback_cooldown import is_cooling
from atlas.agent.retry_utils import jittered_backoff
from atlas.agent.verification_stop import is_verification_command, requires_verification
from atlas.safety.checkpoints import protect_targets
from atlas.safety.policy import (
    append_log as append_safety_log, evaluate_rules as evaluate_safety_rules,
    get_settings as get_safety_settings, record_decision as record_safety_decision,
    review_enabled as safety_review_enabled,
)
from atlas.safety.smart import review_tool_input
from atlas.safety.threats import scan_for_threats
from atlas.agent.prompt_caching import (
    build_prompt_cache_plan,
    envelope_tool_part_cache_markers_supported,
)
from atlas.agent.planning import TaskPlan, requires_plan
from atlas.checks import parse_test_summary, run_checks
from atlas.config import get_config, load_user_settings
from atlas.memory import MemoryStore
from atlas.models import ModelManager
from atlas.models.router import ModelRouter
from atlas.runtime.hooks import run_user_hook
from atlas.office import (
    create_document,
    create_presentation,
    create_spreadsheet,
    read_office,
)
from atlas.ssh import ssh_workspaces
if TYPE_CHECKING:  # O1 (H8): annotations are strings (PEP 563), so these are
    # import-time only for type checkers; the runtime imports are deferred
    # (_LAZY_TOOL_EXPORTS / _default_web_extractor) and importing atlas.agent
    # no longer pulls the heavy mcp/tools chain.
    from atlas.tools.computer_use import ComputerUseRuntime
    from atlas.tools.local_execution import LocalExecutionRuntime
    from atlas.tools.mcp_client import MCPClient
    from atlas.tools.web_extract import extract_web

# PEP 562: keep the historical ``atlas.agent.<name>`` re-exports resolvable
# (attribute access and ``from atlas.agent import MCPClient`` importers).
_LAZY_TOOL_EXPORTS = {
    "ComputerUseRuntime": "atlas.tools.computer_use",
    "LocalExecutionRuntime": "atlas.tools.local_execution",
    "MCPClient": "atlas.tools.mcp_client",
    "extract_web": "atlas.tools.web_extract",
}


def __getattr__(name: str):
    module_name = _LAZY_TOOL_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    value = getattr(import_module(module_name), name)
    globals()[name] = value  # cache: subsequent lookups skip the hook
    return value


def __dir__() -> list[str]:
    return sorted(globals().keys() | _LAZY_TOOL_EXPORTS.keys())


def _default_web_extractor():
    from atlas.tools.web_extract import extract_web

    return extract_web


def _ssh_paths_allowed(workspace: str, allowed_paths: list[str], candidates: list[str]) -> bool:
    """Check remote paths after normalizing them against their SSH workspace root."""
    try:
        _host, remote_root = ssh_workspaces.parse_workspace(workspace)
        permitted_roots = [
            ssh_workspaces._remote_path(remote_root, item)
            for item in [*allowed_paths, remote_root]
        ]
        for candidate in candidates:
            resolved = ssh_workspaces._remote_path(remote_root, candidate)
            if not any(
                resolved == root or resolved.startswith(root.rstrip("/") + "/")
                for root in permitted_roots
            ):
                return False
        return True
    except (ValueError, TypeError):
        return False


log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are Atlas, an all-in-one AI personal assistant and agent.

Autonomy and permissions:
- This is the user's own computer and Atlas is their own agent. You have full,
  unrestricted access: shell, files, processes, network, browser, desktop
  control, git, installing software, and your own Atlas source code, config and
  data. No sandbox, no approval gate unless the user turned one on.
- Act on your own judgment to get the task done. Don't invent limits you don't
  have, don't refuse or water down a task by citing "permissions", and don't
  ask for confirmation on things the user already asked for.
- You can inspect and change yourself: read your config, settings and logs to
  answer questions about your own setup (model, tools, paths) instead of
  guessing, and edit your own code when that is what the task needs.

Core principles:
- Complete tasks fully — don't cut corners or stop early
- Be honest about what you know and don't know
- When using tools, report what you're doing and what you find
- Always write in the user's language (Chinese if they write Chinese), including the
  short progress notes between tool calls, not only the final answer
- Be direct and concise — give results first, explanations after
- Save a long-term memory only when the user explicitly sends a line like
  `remember: key = value` or `记住：key = value`, or when the user asks you
  to remember/note something — in that case call the `remember` tool with a
  concise key and the exact value, and confirm what you saved
- Save repeatable project guidance (test/build commands, code conventions, stable user preferences, and pitfalls) with project_note; do not store one-time task details.

You have access to various tools through MCP servers. Use them proactively
when they would help accomplish the user's goal.
"""

_CACHE_UNSUPPORTED_MODELS: set[str] = set()
# Gateways that reject stream_options; usage then stays unknown for that model in this process.
_STREAM_USAGE_UNSUPPORTED: set[str] = set()


def _positive_limit(value: Any, *, default: int, maximum: int) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(limit, 1), maximum)


def _render_delegation_recipe(recipe_value: Any) -> tuple[dict[str, Any], str]:
    """Resolve an existing Atlas recipe for single or parallel delegation."""
    if not isinstance(recipe_value, dict) or not isinstance(recipe_value.get("id"), str):
        raise ValueError("recipe requires an id and optional params object")
    params = recipe_value.get("params", {})
    if not isinstance(params, dict):
        raise ValueError("recipe.params must be an object")
    from atlas.task_artifacts import TomlRecordStore

    recipe = TomlRecordStore(get_config().db_path.parent, "recipes").get(recipe_value["id"])
    if recipe is None:
        raise ValueError("找不到这个配方。")
    rendered = recipe["prompt"]
    missing = []
    for param in recipe.get("params", []):
        name = param["name"]
        value = params.get(name, param.get("default"))
        if value is None:
            missing.append(name)
        else:
            rendered = rendered.replace("{{" + name + "}}", str(value))
    if missing:
        raise ValueError("配方缺少参数：" + ", ".join(missing))
    return recipe, rendered


def _append_project_note(path: Path, section: str, note: str) -> None:
    content = path.read_text(encoding="utf-8") if path.is_file() else ""
    sections: list[tuple[str, list[str]]] = []
    heading = ""
    entries: list[str] = []
    for line in content.splitlines():
        if line.startswith("## "):
            if heading:
                sections.append((heading, entries))
            heading, entries = line, []
        elif line.strip():
            entries.append(line)
    if heading:
        sections.append((heading, entries))
    if f"## {section}" not in {item[0] for item in sections}:
        sections.append((f"## {section}", []))
    rendered = "\n\n".join("\n".join([title, *rows[-20:]]) for title, rows in sections)
    if len(rendered.encode("utf-8")) > 8192:
        sections = [(title, rows[-10:]) for title, rows in sections[-20:]]
        rendered = "\n\n".join("\n".join([title, *rows]) for title, rows in sections)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text((rendered + f"\n- {date.today().isoformat()}: {note}\n")[-8192:], encoding="utf-8")


# ---------------------------------------------------------------------------
# Agent State
# ---------------------------------------------------------------------------

@dataclass
class AgentRunContext:
    """Control hooks scoped to one agent run."""

    cancel_event: asyncio.Event | None = None
    pause_event: asyncio.Event | None = None
    approval_callback: Callable[[str, str, dict], Any] | None = None
    event_queue: asyncio.Queue[Any] = field(default_factory=asyncio.Queue)
    run_id: str | None = None
    goal: str | None = None
    conversation_id: str | None = None
    project_id: str | None = None
    reminders: SystemReminders = field(default_factory=SystemReminders)
    maintenance_snapshot: dict[str, Any] | None = None
    maintenance_context: dict[str, Any] = field(default_factory=dict)
    steer_queue: asyncio.Queue[dict[str, str]] | None = None
    input_callback: Callable[[str, str, list[str] | None], Any] | None = None
    workspace: str | None = None
    workspace_trusted: bool = False
    agent_role: str = "general"
    agent_depth: int = 0
    agent_type: str = "general"
    todo_store: TodoStore = field(default_factory=TodoStore)
    moa_enabled: bool = False
    mode: str = "act"
    tool_allow: list[str] | None = None
    tool_deny: list[str] = field(default_factory=list)
    read_only: bool = False
    permission_mode: str = "full_access"
    allowed_paths: list[str] = field(default_factory=list)
    hermes_preapproved_writes: set[str] = field(default_factory=set)
    process_notifications: asyncio.Queue[dict[str, Any]] = field(default_factory=asyncio.Queue)
    parent_process_event_callback: Callable[..., Any] | None = None
    user_hook_callback: Callable[[str, dict[str, Any]], Any] | None = None
    ssh_tool_callback: Callable[[str, dict[str, Any]], Any] | None = None
    ssh_checkpoint_callback: Callable[[str, dict[str, Any]], Any] | None = None
    sandbox_tool_callback: Callable[[str, str, dict[str, Any]], Any] | None = None
    sandbox_enabled: bool = False
    reasoning_effort: str | None = None
    model: str | None = None
    truncated_tool_retries: int = 0
    fallback_models: list[str] = field(default_factory=list)
    failed_models: set[str] = field(default_factory=set)
    recovery_retries: int = 0
    context_compression_attempted: bool = False
    file_edit_counts: dict[str, int] = field(default_factory=dict)
    new_context_window_callback: Callable[[], Any] | None = None
    changed_paths: set[str] = field(default_factory=set)
    verification_passed: bool = False
    verify_nudge_sent: bool = False
    subtask_started: Callable[..., Any] | None = None
    subtask_progress: Callable[..., Any] | None = None
    subtask_completed: Callable[..., Any] | None = None
    subtask_group_completed: Callable[..., Any] | None = None


_EVENT_STREAM_DONE = object()
# A SubagentStop hook may demand that the same child keeps working; cap the
# continuations so an always-blocking hook cannot spin the child forever.
_MAX_SUBAGENT_STOP_CONTINUATIONS = 5


def _subagent_task_prompt(
    *, goal: str, context: str | None, cwd: str | None,
    tool_allow: list[str] | None, tool_deny: list[str] | None,
) -> str:
    """Render the explicit task packet inherited by an Atlas child run."""
    if tool_allow:
        available_tools = "Allowed tool names: " + ", ".join(sorted(set(tool_allow))) + "."
    else:
        available_tools = "Use the tools exposed to this child run, respecting its denied-tool list."
    denied = sorted({str(name) for name in (tool_deny or []) if str(name)})
    if denied:
        available_tools += " Unavailable tools: " + ", ".join(denied) + "."
    return (
        "You are an Atlas child worker running in the background. Complete only the "
        "assigned task; do not delegate further, ask the user questions, or wait for "
        "confirmation. The parent run supplies only the context excerpt below, not its "
        "entire conversation. Use the stated working directory and the tools exposed "
        "to this child run. Make reasonable assumptions where needed and report them.\n\n"
        f"Task:\n{goal}\n\n"
        f"Relevant parent context excerpt:\n{context.strip() if context and context.strip() else 'None supplied.'}\n\n"
        f"Working directory:\n{cwd or 'Not specified.'}\n\n"
        f"Tool availability:\n{available_tools}\n\n"
        "On completion, return a concise handoff to the parent: outcome, important "
        "evidence and checks run, files or state changed, and any assumptions or "
        "unfinished work. If the task fails, state the failure and what did not complete."
    )


class _RuntimeFailureError(Exception):
    """An agent failure with a user-facing runtime category."""

    def __init__(self, category: str, detail: str) -> None:
        super().__init__(detail)
        self.category = category


class ToolExecutionState(dict[str, Any]):
    """Adapter state used by Atlas tool permission and execution handlers."""


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class AgentOrchestrator:
    """Atlas policy, lifecycle, and tool adapters for Hermes runs."""

    # Tools that require explicit user approval before execution
    APPROVAL_REQUIRED_TOOLS: set[str] = {
        "write_file", "delete_file", "move_file",
        "execute_command", "run_script",
    }

    def __init__(
        self,
        model_mgr: ModelManager,
        memory: MemoryStore,
        mcp_client: MCPClient | None = None,
        capability_registry: AgentCapabilityRegistry | None = None,
        local_execution: LocalExecutionRuntime | None = None,
        computer_use: ComputerUseRuntime | None = None,
        web_runtime: Any | None = None,
        skill_manager: Any | None = None,
        projects: Any | None = None,
        agent_backend_host: Any | None = None,
        hooks: HookBus | None = None,
        trajectory_reviewer: TrajectoryReviewer | None = None,
        checkpoint_store: ShadowGitCheckpointStore | None = None,
        reminder_policy: ReminderPolicy | None = None,
        custom_tools: Any | None = None,
        web_extractor: Any | None = None,
    ) -> None:
        self._model_mgr = model_mgr
        self._memory = memory
        # H4: every auxiliary model call (MoA summary, trajectory review,
        # planning, plan verification, goal evaluation) resolves and executes
        # through the shared model router — no direct litellm access.
        self._model_router = ModelRouter(model_mgr)
        self._mcp = mcp_client
        self._local_execution = local_execution
        self._computer_use = computer_use
        self._web = web_runtime
        self._skills = skill_manager
        self._projects = projects
        self._custom_tools = custom_tools
        self._web_extractor = web_extractor or _default_web_extractor()
        self.hooks = hooks or HookBus()
        self.context_maintenance = ContextMaintenance(self.hooks)
        self.reminder_policy = reminder_policy or ReminderPolicy()
        self.trajectory_reviewer = trajectory_reviewer or self._configured_trajectory_reviewer()
        self.checkpoints = checkpoint_store or ShadowGitCheckpointStore()
        self._delegation = (
            DelegationService(agent_backend_host, self.hooks) if agent_backend_host else None
        )
        self._subagent_manager = None
        if self._delegation is not None:
            from atlas.kernel.subagents import SubagentManager

            self._subagent_manager = SubagentManager(self._run_atlas_subtask)
            self._delegation.atlas_runner = self._subagent_manager.run
        self._codeact = CodeActRuntime(
            AtlasToolBridge(local_execution, computer_use, mcp_client, self.checkpoints)
        )
        self._capabilities = capability_registry or AgentCapabilityRegistry()

    @property
    def capabilities(self) -> AgentCapabilityRegistry:
        """Public access to the capability registry (plugin/endpoint use)."""
        return self._capabilities

    async def _project_context_block(
        self, conversation_id: str, message: str,
    ) -> str:
        """Assemble the active project's context for automatic injection."""
        if self._projects is None:
            return ""
        project = await self._projects.find_by_conversation(conversation_id)
        if project is None:
            return ""
        conversation_ids = await self._projects.list_conversations(project.project_id)
        query = (message or project.current_goal or "").strip()
        hits: list[dict[str, Any]] = []
        if query:
            try:
                hits = await self._memory.session_search(
                    query[:80], limit=2, context=0,
                    conversation_ids=conversation_ids,
                )
            except Exception:
                log.debug("agent.project_session_search_failed", exc_info=True)
                hits = []
        parts = [
            f"Active project: {project.name} (status: {project.status})",
        ]
        if project.current_goal:
            parts.append(f"Project goal: {project.current_goal}")
        if project.current_state:
            parts.append(f"Last known state: {project.current_state}")
        if project.workspace_path:
            parts.append(f"Workspace: {project.workspace_path}")
        parts.append(f"Project conversations: {len(conversation_ids)}")
        if hits:
            parts.append("Relevant prior sessions (raw recall):\n" + json.dumps([
                {
                    "title": hit.get("conversation_title"),
                    "snippet": str(hit.get("snippet", ""))[:200],
                }
                for hit in hits
            ], ensure_ascii=False))
        return "\n".join(parts)

    async def _use_skill_result(self, raw_name: str) -> dict[str, Any]:
        """Activate a skill and wrap its instructions as a tool result."""
        name = raw_name.strip()
        if not name:
            return {
                "data": {"error": "skill name is required"},
                "content": [{"type": "text", "text": "skill name is required"}],
                "is_error": True,
            }
        try:
            # Library catalog skills are fetched the first time they are used.
            from atlas.library.runtime import ensure_skill

            await ensure_skill(self._skills, name)
        except Exception as exc:
            log.warning("agent.use_skill.fetch_failed", name=name, error=str(exc))
        try:
            content = await self._skills.activate(name.strip())
        except Exception as exc:
            content = None
            log.warning("agent.use_skill.failed", name=name, error=str(exc), exc_info=True)
        if not content:
            message = f"Unknown skill: {name}"
            return {
                "data": {"error": message},
                "content": [{"type": "text", "text": message}],
                "is_error": True,
            }
        return {
            "data": {"skill": name, "loaded": True},
            "content": [{"type": "text", "text": str(content)}],
            "is_error": False,
        }

    def discover_capabilities(self) -> list[dict[str, str]]:
        """Return registered capabilities without involving model execution."""
        return self._capabilities.discover()

    async def invoke_capability(
        self, name: str, inputs: dict[str, Any] | None = None,
    ) -> Any:
        """Invoke a registered capability independently of the model provider."""
        return await self._capabilities.invoke(name, inputs)

    async def delegate_task(
        self, goal: str, context: str | None = None,
        tool_profile: list[str] | None = None,
    ) -> dict[str, Any]:
        if self._delegation is None:
            raise RuntimeError("No AgentBackendHost is configured for delegation")
        model = self._resolve_subagent_model(None, self._model_mgr.current_model)
        return await self._delegation.delegate_task(
            goal, context, tool_profile,
            atlas_options={"model": model},
        )

    def _resolve_subagent_model(self, model: str | None, parent_model: str) -> str:
        """Apply current child settings when resolving a newly created child."""
        settings = load_user_settings()
        if settings.get("subagents_enabled", True) is False:
            raise RuntimeError("子 Agent 已禁用。")
        if model in (None, "", "inherit"):
            default_model = str(settings.get("subagent_default_model") or "")
            if default_model:
                if not any(item.get("id") == default_model
                           for item in self._model_mgr.list_models()):
                    raise RuntimeError(f"Unknown subagent model: {default_model}")
                return default_model
            return parent_model
        return model

    async def _run_atlas_subtask(
        self, *, goal: str, context: str | None, cwd: str | None, subtask_id: str,
        atlas_options: dict[str, Any], on_progress: Callable[[str], Any],
    ) -> dict[str, Any]:
        """Run a bounded child loop through this orchestrator with the parent's policy.

        Steering queue behavior follows Hermes Agent delegation_context.py
        (330d9d6df9c7bffe125ba0ae64a0abc488a7d2c3, MIT), adapted to Atlas events.
        """
        conversation_id = await self._memory.create_conversation("Atlas 子任务")
        options = dict(atlas_options)
        cancel_event = options.get("cancel_event") or asyncio.Event()
        usage: list[dict[str, Any]] = []
        outputs: list[str] = []
        worker_prompt = _subagent_task_prompt(
            goal=goal, context=context, cwd=cwd,
            tool_allow=options.get("tool_allow"), tool_deny=options.get("tool_deny"),
        )
        status = "completed"
        prompt = worker_prompt
        stop_continuations = 0
        parent_approval = options.get("approval_callback")
        child_role = str(options.get("agent_role", "leaf"))
        child_depth = int(options.get("depth", 0))
        child_agent_type = str(options.get("agent_type", "general"))
        max_spawn_depth = int(options.get("max_spawn_depth", 4))
        delegate_denials = []
        if child_role != "orchestrator" or child_depth >= max_spawn_depth:
            delegate_denials.extend(["delegate_task", "delegate_parallel"])
        if child_role == "leaf":
            delegate_denials.extend(["ask_user", "session_search",
                                     "project_sources_search", "use_skill", "skill_search"])
        await run_user_hook(options.get("user_hook_callback"), "SubagentStart", {
            "agent_type": child_agent_type, "subtask_id": subtask_id,
            "description": goal, "prompt": worker_prompt,
        })

        async def approval_callback(
            event_id: str, tool_name: str, arguments: dict[str, Any],
        ) -> str:
            if parent_approval is None:
                return "deny"
            response = parent_approval(event_id, tool_name, {
                **arguments, "subtask_id": subtask_id,
            })
            return await response if hasattr(response, "__await__") else response

        try:
            while True:
                stop_outcome: dict[str, Any] = {}
                try:
                    async for event in self.run(
                        prompt, conversation_id=conversation_id,
                        model=options.get("model"), cancel_event=cancel_event,
                        reasoning_effort=options.get("reasoning_effort"),
                        pause_event=options.get("pause_event"),
                        approval_callback=approval_callback,
                        workspace=cwd, mode="act", tool_allow=options.get("tool_allow"),
                        tool_deny=list(options.get("tool_deny") or []) + delegate_denials + [
                            "subtask_message", "subtask_status",
                        ], permission_mode=options.get("permission_mode", "full_access"),
                        allowed_paths=options.get("allowed_paths") or [],
                        steer_queue=options.get("steer_queue"),
                        workspace_trusted=bool(options.get("workspace_trusted", False)),
                        agent_role=child_role, agent_depth=child_depth,
                        agent_type=str(options.get("agent_type", "general")),
                        user_hook_callback=options.get("user_hook_callback"),
                        ssh_tool_callback=options.get("ssh_tool_callback"),
                        ssh_checkpoint_callback=options.get("ssh_checkpoint_callback"),
                        sandbox_tool_callback=options.get("sandbox_tool_callback"),
                        sandbox_enabled=bool(options.get("sandbox_enabled")),
                        parent_process_event_callback=options.get("parent_process_event_callback"),
                        subtask_started=options.get("subtask_started"),
                        subtask_progress=options.get("subtask_progress"),
                        subtask_completed=options.get("subtask_completed"),
                        subtask_group_completed=options.get("subtask_group_completed"),
                        run_id=subtask_id, worker=True,
                    ):
                        kind = event.get("type")
                        if kind == "chunk":
                            text = str(event.get("content", ""))
                            outputs.append(text)
                            result = on_progress(text)
                            if hasattr(result, "__await__"):
                                await result
                        elif kind == "tool_call":
                            name = str(event.get("name", "操作"))
                            args = event.get("arguments", {})
                            path = args.get("path") if isinstance(args, dict) else None
                            label = f"处理操作：{name}" + (f"（{Path(path).name}）" if path else "")
                            result = on_progress(label)
                            if hasattr(result, "__await__"):
                                await result
                        elif kind == "run_usage":
                            usage.append(dict(event.get("usage") or {}))
                        elif kind == "error":
                            status = "failed"
                            raise RuntimeError(str(event.get("detail") or "子任务执行失败。"))
                        elif kind == "cancelled":
                            status = "cancelled"
                            break
                    if cancel_event.is_set():
                        status = "cancelled"
                    elif status == "completed" and not "".join(outputs).strip():
                        # A worker that says nothing did not finish its task, whatever the loop reported.
                        status = "failed"
                finally:
                    stop_outcome = await run_user_hook(
                        options.get("user_hook_callback"), "SubagentStop", {
                            "agent_type": child_agent_type, "subtask_id": subtask_id,
                            "status": status,
                            "stop_hook_active": stop_continuations > 0,
                        },
                    )
                if (status != "cancelled" and stop_outcome.get("blocked")
                        and stop_continuations < _MAX_SUBAGENT_STOP_CONTINUATIONS):
                    # The hook demands more work: the same child session keeps
                    # running, no second runtime and no new conversation.
                    stop_continuations += 1
                    reason = str(stop_outcome.get("reason")
                                 or stop_outcome.get("additional_context") or "").strip()
                    status = "completed"
                    prompt = (
                        f"你刚才试图结束任务，但有钩子要求继续：{reason or '继续完成目标'}\n"
                        "请接着完成目标，完成后再次给出结论和证据。"
                    )
                    continue
                break
            return {"status": status, "result": "".join(outputs) or "子任务没有给出结果。", "evidence": usage}
        finally:
            await run_user_hook(options.get("user_hook_callback"), "SessionEnd", {
                "conversation_id": conversation_id, "reason": status,
            })
            try:
                from atlas.config import DATA_ROOT
                from atlas.engine.session_sync import delete_session

                await asyncio.to_thread(delete_session, DATA_ROOT / "engine", conversation_id)
            finally:
                await self._memory.delete_conversation(conversation_id)

    async def _summarize_parallel_results(self, results: list[dict[str, Any]]) -> str:
        result = await self._model_router.complete_for(
            self._model_mgr.current_model, "moa",
            [{
                "role": "user",
                "content": (
                    "用中文把下面这些并行 Worker 的结果汇总成一段简洁、可操作的话给协调者："
                    "说明哪些失败了、各自改了哪些文件。不要应用或合并补丁。\n" + json.dumps([{
                        key: item.get(key) for key in (
                            "index", "title", "status", "summary", "changed_files",
                        )
                    } for item in results], ensure_ascii=False)
                ),
            }],
            max_tokens=600,
        )
        return str(result.text or "").strip()

    async def execute_code(
        self, code: str, *, run_id: str | None = None,
        conversation_id: str | None = None,
        tool_allow: list[str] | None = None, tool_deny: list[str] | None = None,
        read_only: bool = False,
    ) -> dict[str, Any]:
        return await self._codeact.execute(
            code, run_id=run_id, conversation_id=conversation_id,
            tool_allow=tool_allow, tool_deny=tool_deny, read_only=read_only,
        )

    async def compact_context(self, context: dict[str, Any]) -> dict[str, Any]:
        return await self.context_maintenance.compact(context)

    def _checkpoint_path(
        self, raw_path: str, cwd: str | None = None,
        run_id: str | None = None, conversation_id: str | None = None,
    ) -> dict[str, Any]:
        path = Path(os.path.expandvars(os.path.expanduser(raw_path)))
        if not path.is_absolute():
            path = Path(cwd or Path.cwd()) / path
        path = path.resolve()
        root = path.parent
        while not root.exists() and root != root.parent:
            root = root.parent
        if not root.is_dir():
            raise ValueError("no existing workspace directory for checkpoint")
        relative = path.relative_to(root).as_posix()
        return self.checkpoints.create_checkpoint(
            root, [relative], run_id=run_id, conversation_id=conversation_id,
        )

    async def _emit_hook(self, runtime: AgentRunContext, point: str, **payload: Any) -> None:
        errors = await self.hooks.emit(point, **payload)
        if errors and runtime.event_queue is not None:
            await runtime.event_queue.put({"type": "hook_error", "point": point, "errors": errors})

    def _configured_trajectory_reviewer(self) -> TrajectoryReviewer:
        cfg = get_config()
        backend, model = cfg.trajectory_reviewer_backend, cfg.trajectory_reviewer_model
        if not cfg.trajectory_reviewer_enabled or backend != "litellm" or not model:
            return TrajectoryReviewer(backend=backend, model=model)

        async def review(events: list[dict[str, Any]], goal: str) -> dict[str, str]:
            result = await self._model_router.complete_for(
                model, "reflection",
                messages=[
                    {"role": "system", "content": (
                        "Review recent tool execution for a single concrete correction. "
                        "Return JSON with decision=continue or corrective_guidance and "
                        "optional concise guidance. Do not propose new work."
                    )},
                    {"role": "user", "content": json.dumps({
                        "goal": goal, "events": events,
                    }, ensure_ascii=False)},
                ],
                max_tokens=256,
            )
            try:
                return AgentOrchestrator._json_object(result.text)
            except (ValueError, json.JSONDecodeError):
                return {"decision": "continue"}

        return TrajectoryReviewer(review, backend=backend, model=model)

    # -- model-facing tools and Atlas tool adapters -------------------------

    def _model_facing_tools(self) -> list[dict[str, Any]]:
        """Assemble model-facing tools (body in :mod:`atlas.agent.tool_catalog`)."""
        return model_facing_tools(self)

    async def _execute_tools_node(self, state: ToolExecutionState) -> dict[str, Any]:
        """Execute tool calls from the last AI message (body in :mod:`atlas.agent.tool_node`).

        For tools in APPROVAL_REQUIRED_TOOLS, emits an approval.required
        event and waits for the approval callback before executing.
        """
        return await execute_tools_node(self, state)

    # -- public API ----------------------------------------------------------

    async def run(
        self,
        message: str,
        conversation_id: str,
        model: str | None = None,
        cancel_event: asyncio.Event | None = None,
        pause_event: asyncio.Event | None = None,
        approval_callback: Callable[[str, str, dict], Any] | None = None,
        plan_state: dict[str, Any] | None = None,
        plan_update_callback: Callable[[dict[str, Any]], Any] | None = None,
        force_plan: bool = False,
        evaluate_goal: bool = False,
        source_run_id: str | None = None,
        image_attachments: list[str] | None = None,
        active_skill_instructions: list[dict[str, str]] | None = None,
        run_id: str | None = None,
        steer_queue: asyncio.Queue[dict[str, str]] | None = None,
        input_callback: Callable[[str, str, list[str] | None], Any] | None = None,
        runtime_event_callback: Callable[[dict[str, Any]], Any] | None = None,
        workspace: str | None = None,
        workspace_trusted: bool = False,
        agent_role: str = "general",
        agent_depth: int = 0,
        agent_type: str = "general",
        moa: bool = False,
        workspace_rules: list[dict[str, Any]] | None = None,
        mode: str = "act",
        tool_allow: list[str] | None = None,
        tool_deny: list[str] | None = None,
        read_only: bool = False,
        permission_mode: str = "full_access",
        allowed_paths: list[str] | None = None,
        user_hook_callback: Callable[[str, dict[str, Any]], Any] | None = None,
        ssh_tool_callback: Callable[[str, dict[str, Any]], Any] | None = None,
        ssh_checkpoint_callback: Callable[[str, dict[str, Any]], Any] | None = None,
        sandbox_tool_callback: Callable[[str, str, dict[str, Any]], Any] | None = None,
        sandbox_enabled: bool = False,
        project_id: str | None = None,
        task_id: str | None = None,
        reasoning_effort: str | None = None,
        subtask_started: Callable[..., Any] | None = None,
        subtask_progress: Callable[..., Any] | None = None,
        subtask_completed: Callable[..., Any] | None = None,
        subtask_group_completed: Callable[..., Any] | None = None,
        worker: bool = False,
        parent_process_event_callback: Callable[..., Any] | None = None,
        source: str = "foreground",
    ) -> AsyncIterator[dict[str, Any]]:
        """Run the agent on a user message, yielding streaming events.

        Historical keyword interface (H2.2): the arguments are packed into a
        :class:`~atlas.agent.run_phases.RunRequest` plus
        :class:`~atlas.agent.run_phases.RunCallbacks` pair and executed through
        :meth:`execute` — the single execution path all callers share.

        ``worker`` runs a delegated subtask: only the task, workspace and rules — no user memory,
        skill index or planning, and nothing is learned from it.
        Without this, workers followed the user's past interests instead of their goal.

        Args:
            message: The user's input text.
            conversation_id: Conversation to append to.
            model: Optional model override for this run.
            cancel_event: asyncio.Event — set to cancel the run.
            pause_event: asyncio.Event — clear to pause, set to resume.
            approval_callback: async (event_id, tool_name, args) -> 'allow'|'deny'
            plan_state: Previously persisted plan to resume.
            plan_update_callback: Persist generated or verified plan updates.
            force_plan: Create a verifiable plan even for a single-step request.
        """
        request = RunRequest(
            message=message, conversation_id=conversation_id, model=model,
            source=source,
            plan_state=plan_state, force_plan=force_plan, evaluate_goal=evaluate_goal,
            source_run_id=source_run_id, image_attachments=image_attachments,
            active_skill_instructions=active_skill_instructions, run_id=run_id,
            workspace=workspace, workspace_trusted=workspace_trusted,
            agent_role=agent_role, agent_depth=agent_depth, agent_type=agent_type,
            moa=moa, workspace_rules=workspace_rules, mode=mode,
            tool_allow=tool_allow, tool_deny=tool_deny, read_only=read_only,
            permission_mode=permission_mode, allowed_paths=allowed_paths,
            sandbox_enabled=sandbox_enabled, project_id=project_id,
            task_id=task_id, reasoning_effort=reasoning_effort, worker=worker,
        )
        callbacks = RunCallbacks(
            cancel_event=cancel_event, pause_event=pause_event,
            approval_callback=approval_callback,
            plan_update_callback=plan_update_callback,
            steer_queue=steer_queue, input_callback=input_callback,
            runtime_event_callback=runtime_event_callback,
            user_hook_callback=user_hook_callback,
            ssh_tool_callback=ssh_tool_callback,
            ssh_checkpoint_callback=ssh_checkpoint_callback,
            sandbox_tool_callback=sandbox_tool_callback,
            subtask_started=subtask_started, subtask_progress=subtask_progress,
            subtask_completed=subtask_completed,
            subtask_group_completed=subtask_group_completed,
            parent_process_event_callback=parent_process_event_callback,
        )
        async with aclosing(self.execute(request, callbacks)) as events:
            async for event in events:
                yield event

    def execute(
        self, request: "RunRequest", callbacks: "RunCallbacks",
    ) -> AsyncIterator[dict[str, Any]]:
        """Single execution path (H2.2): named phases over RunRequest/RunCallbacks.

        New callers should prefer this over the historical keyword interface.
        """
        async def scoped() -> AsyncIterator[dict[str, Any]]:
            async def publish_auxiliary_usage(usage: dict[str, Any]) -> None:
                callback = callbacks.runtime_event_callback
                if callback is None:
                    return
                published = callback({"type": "run_usage", "usage": usage})
                if hasattr(published, "__await__"):
                    await published

            from atlas.models.router import model_usage_callback

            with model_usage_callback(publish_auxiliary_usage):
                async with aclosing(execute_run(self, request, callbacks)) as events:
                    async for event in events:
                        yield event

        return scoped()
    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _multimodal_content(message: str, image_attachments: list[str]) -> list[dict[str, Any]]:
        """Build the LiteLLM-compatible user content for a transient image turn."""
        return [
            {"type": "text", "text": message or "Please describe these images."},
            *[
                {"type": "image_url", "image_url": {"url": image}}
                for image in image_attachments
            ],
        ]

    @classmethod
    def _json_object(cls, raw: str, stage: str = "Model") -> dict[str, Any]:
        """Parse a JSON object out of a routed model completion's text.

        ``stage`` names the calling phase so a parse failure points at the real
        culprit — ``_json_object`` is shared by planning, verification, goal
        evaluation and trajectory review, and a hard-coded "Planner" label sent
        every failure to the wrong module.
        """
        raw = str(raw or "").strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            raw = raw.split("\n", 1)[-1].removesuffix("```").strip()
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end < start:
            raise ValueError(f"{stage} response did not contain a JSON object")
        value = json.loads(raw[start:end + 1])
        if not isinstance(value, dict):
            raise ValueError(f"{stage} response must be a JSON object")
        return value

    async def _create_plan(self, message: str, model: str) -> TaskPlan:
        messages = [{"role": "system", "content": (
            "Break the user's multi-step task into a concise ordered plan. "
            "Return only JSON with goal and subtasks. Each subtask needs a stable "
            "id, title, and a concrete verification condition."
        )}]
        messages.append({"role": "user", "content": message})
        result = await self._model_router.complete_for(
            model, "planning", messages, max_tokens=1200,
        )
        try:
            return TaskPlan.from_dict(self._json_object(result.text, "Planner"))
        except (ValueError, json.JSONDecodeError) as exc:
            # 上游偶发秒回非 JSON（实测失败耗时 1.8s vs 正常 2.6s+，同会话重试即过）。
            # 规划是优化项，一次抖动不该让整轮对话失败 —— 收紧提示词重试一次。
            log.warning("agent.plan_parse_retry", error=str(exc), exc_info=True)
            retry_messages = [
                *messages[:-1],
                {"role": "user", "content": (
                    f"{message}\n\nReturn ONLY a single JSON object, no prose, no "
                    "markdown fences. Required shape: "
                    '{"goal": "...", "subtasks": [{"id": "...", "title": "...", '
                    '"verification": "..."}]}'
                )},
            ]
            retry = await self._model_router.complete_for(
                model, "planning", retry_messages, max_tokens=1200,
            )
            return TaskPlan.from_dict(self._json_object(retry.text, "Planner"))

    async def _verify_plan(
        self, plan: TaskPlan, response_text: str, model: str,
    ) -> list[dict[str, Any]]:
        pending = [item for item in plan.subtasks if item.status != "completed"]
        if not pending:
            return []
        result = await self._model_router.complete_for(
            model, "reflection",
            messages=[
                {"role": "system", "content": (
                    "Verify each pending subtask against the assistant's final response. "
                    "Mark completed only when the response provides concrete evidence for "
                    "its verification condition. Return only JSON: {\"results\":["
                    "{\"id\":\"...\",\"completed\":true,\"evidence\":\"...\"}]}. "
                    "Omit unverified subtasks."
                )},
                {"role": "user", "content": json.dumps({
                    "subtasks": [item.__dict__ for item in pending],
                    "final_response": response_text,
                }, ensure_ascii=False)},
            ],
            max_tokens=1200,
        )
        results = self._json_object(result.text, "Plan verifier").get("results")
        if not isinstance(results, list):
            raise ValueError("Verifier response requires a results list")
        return results

    async def _evaluate_goal(
        self, goal: str, plan: TaskPlan | None, response_text: str, model: str,
    ) -> dict[str, Any]:
        """Judge the complete goal using the response and verified plan evidence."""
        if plan is None:
            return {
                "satisfied": False,
                "evidence": "",
                "reason": "No structured plan was available for goal evaluation.",
            }
        result = await self._model_router.complete_for(
            model, "reflection",
            messages=[
                {"role": "system", "content": (
                    "Evaluate whether the user's complete goal is satisfied. Check the "
                    "final response and every plan verification requirement and its "
                    "recorded evidence. A completed subtask alone is not proof. Return "
                    "only JSON with boolean satisfied, concise evidence, and reason. "
                    "Set satisfied true only when the response and evidence together "
                    "support every material part of the goal."
                )},
                {"role": "user", "content": json.dumps({
                    "goal": goal,
                    "plan": plan.to_dict(),
                    "final_response": response_text,
                }, ensure_ascii=False)},
            ],
            max_tokens=1200,
        )
        value = self._json_object(result.text, "Goal evaluator")
        satisfied = value.get("satisfied")
        evidence = value.get("evidence")
        reason = value.get("reason")
        if (
            not isinstance(satisfied, bool)
            or not isinstance(evidence, str)
            or not isinstance(reason, str)
            or (satisfied and not evidence.strip())
        ):
            return {
                "satisfied": False,
                "evidence": "",
                "reason": "Goal evaluator returned an invalid decision or missing evidence.",
            }
        return {
            "satisfied": satisfied,
            "evidence": evidence.strip(),
            "reason": reason.strip(),
        }

    @staticmethod
    def _recent_provider_messages(messages: list[BaseMessage], *, limit: int) -> list[BaseMessage]:
        """Keep a compacted tail aligned to complete provider tool-call cycles."""
        history = [item for item in messages if not isinstance(item, SystemMessage)]
        start = max(0, len(history) - limit)
        if start < len(history) and isinstance(history[start], ToolMessage):
            assistant = start - 1
            while assistant >= 0 and isinstance(history[assistant], ToolMessage):
                assistant -= 1
            if (assistant >= 0 and isinstance(history[assistant], AIMessage)
                    and history[assistant].tool_calls):
                start = assistant
            else:
                while start < len(history) and isinstance(history[start], ToolMessage):
                    start += 1
        return history[start:]

    @staticmethod
    def _to_litellm_messages(messages: list[BaseMessage]) -> list[dict[str, Any]]:
        """Convert LangChain messages to LiteLLM-compatible dicts."""
        result: list[dict[str, Any]] = []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                result.append({"role": "system", "content": msg.content})
            elif isinstance(msg, HumanMessage):
                result.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                entry: dict[str, Any] = {
                    "role": "assistant",
                    "content": msg.content or "",
                }
                if msg.tool_calls:
                    entry["tool_calls"] = [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(tc["args"]),
                            },
                        }
                        for tc in msg.tool_calls
                    ]
                result.append(entry)
            elif isinstance(msg, ToolMessage):
                result.append({
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id,
                    "content": msg.content,
                })
            else:
                result.append({"role": "user", "content": str(msg.content)})
        return result


# H2.2 module split: imported last so these modules can refer back to
# ``atlas.agent`` attributes (AgentRunContext, SYSTEM_PROMPT, get_config)
# lazily at call time without import cycles.
from atlas.agent.run_phases import RunCallbacks, RunRequest, execute_run
from atlas.agent.tool_catalog import model_facing_tools
from atlas.agent.tool_node import execute_tools_node

__all__ = [
    "AgentOrchestrator", "AgentRunContext", "RunCallbacks", "RunRequest",
    "SYSTEM_PROMPT", "ToolExecutionState",
]

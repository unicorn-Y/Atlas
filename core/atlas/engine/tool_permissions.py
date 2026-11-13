"""Resolve child tool restrictions and per-call sandbox requests."""

import inspect
from collections.abc import Callable, Mapping
from fnmatch import fnmatchcase


SANDBOX_PERMISSION_MODES = frozenset({
    "read-only", "workspace-write", "danger-full-access",
})


def normalize_sandbox_escalation(arguments):
    """Validate a per-call sandbox permission request without granting it.

    The caller must run the returned request through its approval flow and
    apply it to this call only. This helper intentionally does not mutate a
    run's permission preset or treat an omitted/invalid request as consent.
    """
    if not isinstance(arguments, Mapping):
        raise ValueError("sandbox_permissions request must be an object")
    mode = arguments.get("sandbox_permissions")
    if not isinstance(mode, str) or mode not in SANDBOX_PERMISSION_MODES:
        raise ValueError(
            "sandbox_permissions must be read-only, workspace-write, or danger-full-access"
        )
    justification = arguments.get("justification")
    if not isinstance(justification, str) or not justification.strip():
        raise ValueError("justification is required for sandbox permission requests")
    return {
        "sandbox_permissions": mode,
        "justification": justification.strip()[:4000],
    }


async def authorize_sandbox_escalation(
    arguments, approval_callback: Callable | None, *, tool_name: str,
    tool_call_id: str,
):
    """Ask the existing approval channel for a one-call sandbox escalation.

    The result is a decision only; callers must apply the returned mode to
    this invocation and must not persist it as the run's permission mode.
    Missing approval wiring and every non-allowing response fail closed.
    """
    from atlas.approval_outcome import ALLOWED, UNAVAILABLE, normalize

    request = normalize_sandbox_escalation(arguments)
    if approval_callback is None:
        outcome = UNAVAILABLE
    else:
        approval_args = dict(arguments)
        approval_args["sandbox_permissions"] = request["sandbox_permissions"]
        approval_args["justification"] = request["justification"]
        approval_args["_approval_reason"] = request["justification"]
        approval_args["_approval_no_always"] = True
        response = approval_callback(str(tool_call_id), str(tool_name), approval_args)
        if inspect.isawaitable(response):
            response = await response
        outcome = normalize(response)
    return {
        "request": request,
        "approval_outcome": outcome,
        "approved": outcome == ALLOWED,
    }


def tool_allowed(name, allow=None, deny=()):
    from atlas.engine.tool_registry import _ALIASES

    names = {name, _ALIASES.get(name, (name, None))[0]}
    if name == "delegate_parallel":
        names.add("delegate_task")
    if name in {"todo", "todo_list"}:
        names.update({"todo", "todo_list"})
    matches = lambda patterns: any(fnmatchcase(item, pattern) for item in names for pattern in patterns)
    return (allow is None or matches(allow)) and not matches(deny or ())


def _x2_tool_names() -> set[str]:
    """X2 computer/browser tool names so child allow-lists can reference them."""
    try:
        from atlas.tools.x2.permissions import X2_READ_TOOLS

        # Every x2-prefixed registered name: the read set plus the write rule's
        # implicit computer_*/browser_* default. Enumerate explicitly to stay
        # import-light and avoid importing the bridge runtimes.
        return set(X2_READ_TOOLS) | {
            "computer_window", "computer_mouse", "computer_keyboard", "computer_clipboard",
            "browser_navigate", "browser_click", "browser_type", "browser_scroll",
            "browser_back", "browser_press", "browser_replay", "browser_vault_fill",
        }
    except ImportError:  # pragma: no cover
        return set()


def intersect_tool_allow(parent, child, available=()):
    if parent is None:
        return child
    if child is None:
        return parent
    from atlas.engine.tool_registry import _ALIASES

    names = set(available) | set(_ALIASES) | {item[0] for item in _ALIASES.values()} | _x2_tool_names()
    return sorted(name for name in names if tool_allowed(name, parent) and tool_allowed(name, child))

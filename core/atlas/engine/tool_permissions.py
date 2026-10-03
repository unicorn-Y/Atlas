"""Resolve child tool restrictions against the tools actually available to Atlas."""

from fnmatch import fnmatchcase


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

"""Resolve child tool restrictions against the tools actually available to Atlas."""

from fnmatch import fnmatchcase


def tool_allowed(name, allow=None, deny=()):
    from atlas.engine.tool_registry import _ALIASES

    names = {name, _ALIASES.get(name, (name, None))[0]}
    matches = lambda patterns: any(fnmatchcase(item, pattern) for item in names for pattern in patterns)
    return (allow is None or matches(allow)) and not matches(deny or ())


def intersect_tool_allow(parent, child, available=()):
    if parent is None:
        return child
    if child is None:
        return parent
    from atlas.engine.tool_registry import _ALIASES

    names = set(available) | set(_ALIASES) | {item[0] for item in _ALIASES.values()}
    return sorted(name for name in names if tool_allowed(name, parent) and tool_allowed(name, child))

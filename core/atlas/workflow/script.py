"""Turn a model-authored orchestration script into a workflow graph.

The `workflow` tool could only accept a goal and let the planner invent a DAG, so
a model had no way to express control flow the planner does not produce. DSH's
script workflow lets the model write `agent(...)`, `parallel([...])` and
`pipeline(...)` and runs exactly that.

This module is the translation layer: a small, explicitly-restricted script
vocabulary is parsed into the same `WorkflowDefinition` the planner produces, so
the existing journal, scheduler and node runner execute it unchanged.

Safety: this is **not** `eval`. The script is parsed as a restricted expression
tree; only three call forms exist, only literals and previously-bound names may
appear as arguments, and the node count is bounded. A model that writes anything
outside the vocabulary gets a named error, not a Python traceback.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "ScriptError",
    "ScriptPlan",
    "MAX_STEPS",
    "parse_script",
]

#: Upper bound on produced steps. DSH's own limit is far higher; this exists so a
#: runaway script cannot ask Atlas to spawn thousands of subagents.
MAX_STEPS = 256


class ScriptError(ValueError):
    """The script is outside the vocabulary, or asks for something impossible."""


@dataclass
class ScriptPlan:
    """The flat node list a script compiles to."""

    nodes: list[dict[str, Any]] = field(default_factory=list)
    #: Human-readable trace of what the script asked for, useful in the result.
    trace: list[str] = field(default_factory=list)

    def add(self, node_id: str, goal: str, depends_on: list[str],
            group: str | None = None) -> str:
        if len(self.nodes) >= MAX_STEPS:
            raise ScriptError(f"script exceeds the {MAX_STEPS}-step limit")
        self.nodes.append({
            "id": node_id, "goal": goal,
            "depends_on": list(dict.fromkeys(depends_on)),
            **({"group": group} if group else {}),
        })
        return node_id


def _literal(node: ast.AST, what: str) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    raise ScriptError(f"{what} must be a literal string, got {type(node).__name__}")


def _string(node: ast.AST, what: str) -> str:
    value = _literal(node, what)
    if not isinstance(value, str) or not value.strip():
        raise ScriptError(f"{what} must be a non-empty string")
    return value.strip()


def _name_list(node: ast.AST, bound: dict[str, list[str]], what: str) -> list[str]:
    """Resolve a node reference: a bound variable or a literal id."""
    if isinstance(node, ast.Name):
        if node.id not in bound:
            raise ScriptError(f"{what} references unknown name {node.id!r}")
        return bound[node.id]
    if isinstance(node, ast.Constant):
        value = node.value
        if not isinstance(value, str) or not value.strip():
            raise ScriptError(f"{what} must name a step")
        return [value.strip()]
    if isinstance(node, ast.List):
        out: list[str] = []
        for item in node.elts:
            out.extend(_name_list(item, bound, what))
        return out
    raise ScriptError(f"{what} must be a name, a string or a list of them")


def parse_script(source: str) -> ScriptPlan:
    """Compile the restricted script vocabulary into a flat node list.

    Supported forms (one per statement)::

        a = agent("goal")                     # one step
        b = parallel([agent("x"), agent("y")])# independent steps in one group
        c = pipeline([agent("x"), agent("y")])# serial chain
        after(a, agent("z"))                  # depends on the named steps
    """
    if not isinstance(source, str) or not source.strip():
        raise ScriptError("script is empty")
    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError as exc:
        raise ScriptError(f"script does not parse: {exc.msg} (line {exc.lineno})") from exc

    plan = ScriptPlan()
    bound: dict[str, list[str]] = {}
    counter = {"n": 0}

    def _next_id(prefix: str = "step") -> str:
        counter["n"] += 1
        return f"{prefix}-{counter['n']}"

    def emit(node: ast.AST, deps: list[str]) -> list[str]:
        """Compile one expression to ids, threading ``deps`` through."""
        if isinstance(node, ast.Call):
            fn = getattr(node.func, "id", None)
            if fn is None:
                raise ScriptError("only bare calls like agent(...) are allowed")
            if fn == "agent":
                if len(node.args) != 1:
                    raise ScriptError("agent() takes exactly one argument")
                goal = _string(node.args[0], "agent() goal")
                return [plan.add(_next_id("agent"), goal, deps)]
            if fn == "parallel":
                if len(node.args) != 1 or not isinstance(node.args[0], ast.List):
                    raise ScriptError("parallel() takes one list")
                group = _next_id("group")
                ids: list[str] = []
                for item in node.args[0].elts:
                    ids.extend(emit(item, deps))
                for node_id in ids:
                    for entry in plan.nodes:
                        if entry["id"] == node_id:
                            entry["group"] = group
                plan.trace.append(f"parallel({len(ids)} steps)")
                return ids
            if fn == "pipeline":
                if len(node.args) != 1 or not isinstance(node.args[0], ast.List):
                    raise ScriptError("pipeline() takes one list")
                current = list(deps)
                ids = []
                for item in node.args[0].elts:
                    produced = emit(item, current)
                    ids.extend(produced)
                    current = produced
                plan.trace.append(f"pipeline({len(ids)} steps)")
                return ids
            if fn == "after":
                if len(node.args) != 2:
                    raise ScriptError("after(deps, expr) takes two arguments")
                extra = _name_list(node.args[0], bound, "after()")
                return emit(node.args[1], list(dict.fromkeys([*deps, *extra])))
            raise ScriptError(
                f"unknown call {fn!r}; allowed: agent, parallel, pipeline, after"
            )
        raise ScriptError(f"unsupported statement: {type(node).__name__}")

    for statement in tree.body:
        if isinstance(statement, ast.Assign):
            if len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Name):
                raise ScriptError("assignment must bind a single name")
            ids = emit(statement.value, [])
            bound[statement.targets[0].id] = ids
        elif isinstance(statement, ast.Expr):
            emit(statement.value, [])
        else:
            raise ScriptError(
                f"unsupported statement {type(statement).__name__}; "
                "use assignments or bare calls only"
            )

    if not plan.nodes:
        raise ScriptError("script produced no steps")
    return plan

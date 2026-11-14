"""A model must be able to author the workflow's control flow, not just its goal.

The `workflow` tool could only take a goal and let the planner invent a DAG, so
any structure the planner does not produce was unreachable. `script` compiles a
restricted vocabulary into the same WorkflowGraph, and the existing journal,
scheduler and node runner execute it unchanged.

The parser is not `eval`: only four call forms exist, arguments must be literals
or bound names, and the step count is bounded. Anything else gets a named error.
"""

from __future__ import annotations

import pytest

from atlas.workflow.script import MAX_STEPS, ScriptError, parse_script

pytestmark = pytest.mark.unit


def test_single_agent_statement():
    plan = parse_script('a = agent("collect sources")')
    assert len(plan.nodes) == 1
    assert plan.nodes[0]["goal"] == "collect sources"
    assert plan.nodes[0]["depends_on"] == []


def test_parallel_groups_independent_steps():
    plan = parse_script('b = parallel([agent("x"), agent("y")])')
    assert len(plan.nodes) == 2
    groups = {n.get("group") for n in plan.nodes}
    assert len(groups) == 1 and None not in groups, "both steps share one group"
    assert all(n["depends_on"] == [] for n in plan.nodes)


def test_pipeline_chains_steps_in_order():
    plan = parse_script('c = pipeline([agent("draft"), agent("review")])')
    assert len(plan.nodes) == 2
    assert plan.nodes[1]["depends_on"] == [plan.nodes[0]["id"]]


def test_after_adds_an_explicit_dependency():
    plan = parse_script('a = agent("fetch")\nd = after(a, agent("decide"))')
    first, second = plan.nodes
    assert second["depends_on"] == [first["id"]]


def test_unknown_call_is_refused_by_name():
    with pytest.raises(ScriptError) as caught:
        parse_script('a = eval("1+1")')
    assert "unknown call" in str(caught.value)
    assert "eval" in str(caught.value)


def test_unknown_reference_is_refused():
    with pytest.raises(ScriptError) as caught:
        parse_script('d = after(missing, agent("x"))')
    assert "unknown name" in str(caught.value)


def test_non_literal_goal_is_refused():
    with pytest.raises(ScriptError):
        parse_script('a = agent(1 + 2)')


def test_empty_and_syntax_error_are_named():
    with pytest.raises(ScriptError):
        parse_script("   ")
    with pytest.raises(ScriptError) as caught:
        parse_script("a = agent(")
    assert "does not parse" in str(caught.value)


def test_import_and_loop_are_refused():
    for source in ('import os', 'for i in range(3):\n    agent("x")',
                   'while True:\n    agent("x")'):
        with pytest.raises(ScriptError):
            parse_script(source)


def test_step_budget_is_enforced():
    source = "a = parallel([%s])" % ", ".join(
        f'agent("g{i}")' for i in range(MAX_STEPS + 1)
    )
    with pytest.raises(ScriptError) as caught:
        parse_script(source)
    assert "step limit" in str(caught.value)


def test_a_script_compiles_into_a_valid_graph():
    """The compiled nodes must pass the same validation the planner's output does."""
    from atlas.workflow import WorkflowGraph, WorkflowNode
    from atlas.workflow.graph import validate_graph

    plan = parse_script(
        'a = agent("collect")\n'
        'b = parallel([agent("analyze one"), agent("analyze two")])\n'
        'c = pipeline([agent("draft"), agent("review")])\n'
        'd = after(a, agent("decide"))'
    )
    graph = WorkflowGraph(
        goal="test", workspace=".", nodes=[
            WorkflowNode(id=n["id"], goal=n["goal"], depends_on=n["depends_on"])
            for n in plan.nodes
        ],
    )
    validate_graph(graph)
    assert len(graph.nodes) == 6


def test_tool_schema_advertises_the_script_parameter():
    from atlas.engine.kernel.workflow_tool import WORKFLOW_TOOL_SPEC

    props = WORKFLOW_TOOL_SPEC["parameters"]["properties"]
    assert "script" in props
    assert "agent(" in props["script"]["description"]

"""H1 contract: Atlas integrates with Hermes through its public hooks."""

from __future__ import annotations

import ast
import asyncio
import json
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import run_agent
from run_agent import AIAgent

from atlas.engine.hermes_runtime import HermesRuntime
from tests.fakes.fake_llm_provider import FakeLLMServer, Text, ToolCall, write_hermes_home

ATLAS_ROOT = Path(__file__).resolve().parents[1] / "atlas"


@pytest.mark.integration
def test_pinned_hermes_commit_is_on_the_fork_atlas_branch(tmp_path):
    project = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
        encoding="utf-8",
    )
    match = re.search(
        r"hermes-agent\s*@\s*git\+https://github\.com/unicorn-Y/hermes-agent\.git@([0-9a-f]{40})",
        project,
    )
    assert match, "pyproject.toml must pin Hermes to a full commit hash"
    pinned = match.group(1)
    gh = shutil.which("gh")
    if gh:
        try:
            comparison = subprocess.run(
                [
                    gh, "api", "--jq", ".status",
                    f"repos/unicorn-Y/hermes-agent/compare/{pinned}...atlas",
                ],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except subprocess.TimeoutExpired:
            comparison = None
        if comparison is not None and comparison.returncode == 0:
            status = comparison.stdout.strip()
            assert status in {"ahead", "identical"}, (
                f"pinned Hermes commit {pinned} is not an ancestor of fork atlas: status={status!r}"
            )
            return

    remote = "https://github.com/unicorn-Y/hermes-agent.git"
    try:
        advertised = subprocess.run(
            ["git", "ls-remote", remote, "refs/heads/atlas"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.skip("Hermes atlas ancestry check unavailable: git ls-remote timed out after 20 seconds")
    if advertised.returncode:
        error = advertised.stderr.lower()
        network_unavailable = any(
            marker in error for marker in (
                "could not resolve host", "failed to connect", "connection timed out",
                "operation timed out", "connection reset", "connection was reset",
                "recv failure", "network is unreachable", "could not connect",
            )
        )
        if network_unavailable:
            pytest.skip("Hermes atlas ancestry check unavailable: remote network lookup failed")
        pytest.fail(f"Could not query fork atlas ref: {advertised.stderr.strip()}")
    refs = [line.split() for line in advertised.stdout.splitlines() if line.strip()]
    assert len(refs) == 1 and len(refs[0]) == 2, "Fork atlas branch was not returned by git ls-remote"
    atlas_tip = refs[0][0]
    if atlas_tip == pinned:
        return

    ancestry_repo = tmp_path / "hermes-atlas-ancestry.git"
    initialized = subprocess.run(
        ["git", "init", "--bare", "--quiet", str(ancestry_repo)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert initialized.returncode == 0, initialized.stderr.strip()
    try:
        fetched = subprocess.run(
            [
                "git", "-C", str(ancestry_repo),
                "fetch", "--quiet", "--no-tags", "--filter=tree:0",
                "--depth=256", remote, "refs/heads/atlas",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.skip("Hermes atlas ancestry check unavailable: git fetch timed out after 120 seconds")
    if fetched.returncode:
        error = fetched.stderr.lower()
        network_unavailable = any(
            marker in error for marker in (
                "could not resolve host", "failed to connect", "connection timed out",
                "operation timed out", "connection reset", "network is unreachable",
                "connection was reset", "recv failure", "could not connect",
                "could not read from remote repository", "failed to receive data",
            )
        )
        if network_unavailable:
            pytest.skip("Hermes atlas ancestry check unavailable: remote network fetch failed")
        pytest.fail(f"Could not fetch fork atlas for ancestry check: {fetched.stderr.strip()}")

    ancestry = subprocess.run(
        [
            "git", "-C", str(ancestry_repo),
            "merge-base", "--is-ancestor", pinned, "FETCH_HEAD",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert ancestry.returncode == 0, (
        f"pinned Hermes commit {pinned} is not an ancestor of fork atlas"
        if ancestry.returncode == 1
        else f"Could not verify fork atlas ancestry: {ancestry.stderr.strip()}"
    )


def _attribute_path(node: ast.AST) -> list[str]:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return list(reversed(parts))


def test_atlas_does_not_assign_private_hermes_attributes_or_rewrite_hermes_identity():
    private_writes = []
    hermes_identity_literals = []
    for source in ATLAS_ROOT.rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        aliases = {"agent", "hermes_agent"}
        changed = True
        while changed:
            changed = False
            for candidate in ast.walk(tree):
                if not isinstance(candidate, (ast.Assign, ast.AnnAssign)):
                    continue
                value = candidate.value
                if not isinstance(value, ast.Name) or value.id not in aliases:
                    continue
                targets = (
                    candidate.targets if isinstance(candidate, ast.Assign) else [candidate.target]
                )
                for target in targets:
                    if isinstance(target, ast.Name) and target.id not in aliases:
                        aliases.add(target.id)
                        changed = True
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                targets = [node.target]
            for target in targets:
                for child in ast.walk(target):
                    if not isinstance(child, ast.Attribute) or not child.attr.startswith("_"):
                        continue
                    path = _attribute_path(child)
                    if path[0] in aliases or "hermes_agent" in path:
                        private_writes.append((source, node.lineno, ".".join(path)))
            if isinstance(node, ast.Call):
                callee = (
                    node.func.id if isinstance(node.func, ast.Name)
                    else getattr(node.func, "attr", None)
                )
                if callee in {"setattr", "__setattr__"} and len(node.args) >= 2:
                    target_path = _attribute_path(node.args[0])
                    attr = node.args[1]
                    private_name = (
                        isinstance(attr, ast.Constant) and isinstance(attr.value, str)
                        and attr.value.startswith("_")
                    )
                    if private_name and target_path and (
                        target_path[0] in aliases or "hermes_agent" in target_path
                    ):
                        private_writes.append((
                            source, node.lineno, f"setattr({'.'.join(target_path)})",
                        ))
            for child in ast.walk(node):
                if isinstance(child, ast.Constant) and isinstance(child.value, str):
                    if "You are Hermes Agent" in child.value:
                        hermes_identity_literals.append((source, getattr(node, "lineno", 0)))

    assert private_writes == []
    assert hermes_identity_literals == []


@pytest.mark.asyncio
async def test_real_agent_fake_tool_round_uses_atlas_identity_and_keeps_stable_prefix(
    tmp_path, monkeypatch,
):
    from tools.registry import registry

    import atlas.engine.hermes_policy as hermes_policy
    import atlas.engine.tool_registry as tool_registry

    with FakeLLMServer([
        ToolCall("delegate_task", {"goal": "run Atlas delegate hook"}),
        Text("first turn complete"), Text("second turn complete"),
    ]) as fake:
        home = tmp_path / "atlas-data" / "engine"
        write_hermes_home(
            home, fake.base_url,
            extra_config=(
                "auxiliary:\n"
                "  title_generation:\n"
                "    provider: custom\n"
                "    model: openai/fake-model\n"
                f"    base_url: {fake.base_url}\n"
                "    api_key: sk-fake-e2e\n"
            ),
        )
        monkeypatch.setenv("HERMES_HOME", str(home))
        models = SimpleNamespace(
            current_model="fake-model",
            current_litellm_model="openai/fake-model",
            gateway_base_url=fake.base_url,
            _api_key="sk-fake-e2e",
            list_models=lambda: [{"id": "fake-model", "litellm_model": "openai/fake-model"}],
        )
        agents = []

        def factory(**kwargs):
            hooks = kwargs["hooks"]
            for name in (
                "before_model_request", "on_diagnostic", "delegate_dispatcher",
                "on_session_title", "system_prompt_suffix",
            ):
                callback = getattr(hooks, name)
                if callback is None:
                    continue
                def tracked(*args, _name=name, _callback=callback, **kw):
                    hook_counts[_name] += 1
                    if _name == "delegate_dispatcher":
                        agents[0]._emit_diagnostic_status("delegate diagnostic")
                    return _callback(*args, **kw)
                setattr(hooks, name, tracked)
            agent = AIAgent(**kwargs)
            agents.append(agent)
            return agent

        hook_counts = {
            "before_model_request": 0, "on_diagnostic": 0,
            "delegate_dispatcher": 0, "on_session_title": 0,
            "system_prompt_suffix": 0,
        }

        monkeypatch.setattr(hermes_policy, "install_atlas_policy_plugin", lambda: None)
        monkeypatch.setattr(hermes_policy, "wait_before_model_request", lambda *_args: False)
        monkeypatch.setattr(tool_registry, "bind_atlas_tools", lambda *_args: None)
        monkeypatch.setattr(tool_registry, "activate_atlas_tool_context", lambda *_args: None)
        monkeypatch.setattr(HermesRuntime, "_register_atlas_mcp", lambda _self: [])
        def run_delegate(args, **_kwargs):
            agents[0].set_context_handoff_summary("public handoff")
            return '{"delegated": true}'

        monkeypatch.setattr(
            registry, "get_entry",
            lambda name: SimpleNamespace(handler=run_delegate) if name == "delegate_task" else None,
        )

        runtime = HermesRuntime(data_dir=tmp_path / "atlas-data", model_manager=models,
                                agent_factory=factory)
        first_events = [event async for event in runtime.run_turn(
            message="first turn", conversation_id="h1-contract",
            workspace=str(tmp_path), history=[],
            atlas_agent=SimpleNamespace(_delegation=object()),
            atlas_context=SimpleNamespace(mode="act"),
        )]
        second_events = [event async for event in runtime.run_turn(
            message="second turn", conversation_id="h1-contract", workspace=str(tmp_path),
            history=[{"role": "user", "content": "first turn"},
                     {"role": "assistant", "content": "first turn complete"}],
            atlas_agent=SimpleNamespace(_delegation=object()),
            atlas_context=SimpleNamespace(mode="act"),
        )]

        requests = fake.main_requests()
        assert len(requests) == 3
        prompts = [request["messages"][0]["content"] for request in requests]
        assert prompts[0].startswith("You are Atlas, the AI assistant for this workspace.")
        leaks = [prompt for prompt in prompts if "Hermes Agent" in prompt]
        assert not leaks, [prompt[prompt.index("Hermes Agent"):][:80] for prompt in leaks]
        assert "Model-family guidance:" in prompts[0]
        assert first_events[-1]["type"] == "hermes.result"
        assert second_events[-1]["type"] == "hermes.result"
        diagnostic_events = [
            event for event in first_events
            if event.get("type") == "run.recovery.notice"
            and event.get("data", {}).get("detail") == "delegate diagnostic"
        ]
        assert len(diagnostic_events) == 1
        handoff_request = json.dumps(requests[1]["messages"], ensure_ascii=False)
        assert "public handoff" in handoff_request
        assert "first turn" not in handoff_request
        assert agents[0].context_handoff_summary is None
        fake.wait_for_requests(1, kind="aux")
        deadline = asyncio.get_running_loop().time() + 3
        while hook_counts["on_session_title"] == 0 and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.02)
        assert all(count > 0 for count in hook_counts.values()), hook_counts
        # H3: two consecutive turns of the same session reuse ONE Hermes agent
        # (per-session cache) — construction count is the reuse contract itself;
        # per-turn hook rebinding keeps every hook exercised on both turns.
        assert len(agents) == 1
        stable_prefix = agents[0]._cached_system_prompt_static.encode("utf-8")
        actual_prefixes = [prompt.encode("utf-8")[:len(stable_prefix)] for prompt in prompts]
        assert all(prefix == stable_prefix for prefix in actual_prefixes)

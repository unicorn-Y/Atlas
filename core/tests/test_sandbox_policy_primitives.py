"""Unit tests for the absorbed DSH sandbox policy primitives."""

from __future__ import annotations

import pytest

from atlas.safety.sandbox_policy import (
    SANDBOX_MODES,
    SandboxExecutionPolicy,
    SandboxPolicyError,
    is_execution_world_path,
    render_policy_context,
    resolve_additional_writable_roots,
    resolve_execution_policy,
)


@pytest.mark.unit
@pytest.mark.parametrize("path", [
    "/tmp/work",
    "/",
    "C:\\work",
    "C:/work",
    "\\\\server\\share\\work",
    "//server/share/work",
])
def test_absolute_execution_world_paths_are_accepted(path):
    assert is_execution_world_path(path) is True


@pytest.mark.unit
@pytest.mark.parametrize("path", [
    "",
    "work",
    "./work",
    "C:work",
    "\\rooted-without-drive",
    "C:\\bad\x00path",
    123,
    None,
])
def test_non_absolute_or_ambiguous_paths_are_rejected(path):
    assert is_execution_world_path(path) is False


@pytest.mark.unit
def test_windows_override_uses_ntpath_semantics():
    assert is_execution_world_path("C:\\work", windows=True) is True
    assert is_execution_world_path("C:work", windows=True) is False
    assert is_execution_world_path("/tmp/work", windows=False) is True


@pytest.mark.unit
def test_empty_roots_mean_no_extra_grant():
    assert resolve_additional_writable_roots(None) is None
    assert resolve_additional_writable_roots([]) is None


@pytest.mark.unit
def test_roots_are_deduplicated_in_first_seen_order():
    roots = resolve_additional_writable_roots(["/opt/a", "/opt/b", "/opt/a"])
    assert roots == ("/opt/a", "/opt/b")


@pytest.mark.unit
def test_relative_root_is_rejected():
    with pytest.raises(SandboxPolicyError):
        resolve_additional_writable_roots(["/opt/a", "relative"])


@pytest.mark.unit
def test_single_string_is_not_a_sequence():
    with pytest.raises(SandboxPolicyError):
        resolve_additional_writable_roots("/opt/a")


@pytest.mark.unit
def test_policy_rejects_unknown_mode_and_relative_workspace():
    with pytest.raises(SandboxPolicyError):
        resolve_execution_policy("sandbox-ish", "/tmp/work")
    with pytest.raises(SandboxPolicyError):
        resolve_execution_policy("workspace-write", "relative/work")


@pytest.mark.unit
def test_resolved_policy_is_frozen_and_keeps_extra_roots_in_read_only():
    policy = resolve_execution_policy("read-only", "/tmp/work", ["/opt/a"])
    assert policy == SandboxExecutionPolicy("read-only", "/tmp/work", ("/opt/a",))
    with pytest.raises(Exception):
        policy.mode = "danger-full-access"  # type: ignore[misc]


@pytest.mark.unit
def test_rendered_context_names_the_mode_and_scope():
    policy = resolve_execution_policy("workspace-write", "/tmp/work", ["/opt/a"])
    text = render_policy_context(policy)
    assert "workspace-write" in text
    assert "/tmp/work" in text
    assert "/opt/a" in text
    assert "Windows" in text


@pytest.mark.unit
def test_read_only_rendering_does_not_claim_tool_inventory():
    text = render_policy_context(SandboxExecutionPolicy("read-only", "/tmp/work"))
    assert "read-only" in text
    assert "Do not refuse a required modification" in text


@pytest.mark.unit
def test_danger_full_access_rendering_is_explicit():
    text = render_policy_context(SandboxExecutionPolicy("danger-full-access", "/tmp/work"))
    assert "danger-full-access" in text
    assert "does not restrict" in text


@pytest.mark.unit
def test_all_modes_are_renderable():
    for mode in SANDBOX_MODES:
        assert render_policy_context(SandboxExecutionPolicy(mode, "/tmp/work"))
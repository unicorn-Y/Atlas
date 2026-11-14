"""X14 regression: the per-hook fingerprint trust gate binds approval to the
exact hook revision.

``atlas/runtime/hooks.py`` reviews each hook independently (no bulk trust):
approval is keyed by hook id but bound to a fingerprint over the hook's full
identity (command/event/matcher/source/...). These tests pin the whole
lifecycle: unreviewed → blocked, approved → runs, config drift → ``changed``
and blocked again, revoke → ``revoked`` and blocked. The codex fail-closed
path itself is covered by ``test_codex_plugin_hooks.py``.
"""

import pytest

from atlas.runtime.hooks import HookStore

pytestmark = pytest.mark.unit

TOML_PATH = "hooks.toml"


def _write_atlas_hook(path, command: str) -> None:
    path.write_text(
        "[[hooks]]\n"
        'id = "review-me"\n'
        'event = "tool.before"\n'
        f'command = "{command}"\n',
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_atlas_hook_trust_binds_to_exact_config_revision(tmp_path, monkeypatch) -> None:
    toml_path = tmp_path / TOML_PATH
    _write_atlas_hook(toml_path, "python approved.py")
    calls = []

    async def run_command(spec, payload, **kwargs):
        calls.append(spec["command"])
        return 0, "", ""

    monkeypatch.setattr("atlas.runtime.hooks._run_command", run_command)
    store = HookStore(toml_path)

    # 1. Unreviewed hooks fail closed before any command runs.
    listed = store.list_all()[0]
    assert listed["trust_state"] == "unreviewed"
    result = await store.execute("tool.before", {"tool_name": "Bash"})
    assert result["blocked"] is True
    assert "信任审查" in result["reason"]
    assert calls == []

    # 2. Approving the exact revision lets it execute.
    store.set_hook_trust("review-me", True, fingerprint=listed["trust_fingerprint"])
    result = await store.execute("tool.before", {"tool_name": "Bash"})
    assert result["blocked"] is False
    assert calls == ["python approved.py"]

    # 3. Same id, different command: the fingerprint no longer matches the
    #    approved record → state ``changed``, execution blocked again.
    _write_atlas_hook(toml_path, "python evil.py")
    drifted = store.list_all()[0]
    assert drifted["id"] == "review-me"
    assert drifted["trust_fingerprint"] != listed["trust_fingerprint"]
    assert drifted["trust_state"] == "changed"
    result = await store.execute("tool.before", {"tool_name": "Bash"})
    assert result["blocked"] is True
    assert calls == ["python approved.py"]  # the new command never ran

    # 4. An explicit revoke stays blocked even for the approved revision.
    store.set_hook_trust("review-me", True, fingerprint=drifted["trust_fingerprint"])
    revoked = store.set_hook_trust("review-me", False, fingerprint=drifted["trust_fingerprint"])
    assert revoked["trust_state"] == "revoked"
    result = await store.execute("tool.before", {"tool_name": "Bash"})
    assert result["blocked"] is True
    assert calls == ["python approved.py"]


@pytest.mark.asyncio
async def test_set_hook_trust_rejects_stale_fingerprint(tmp_path) -> None:
    toml_path = tmp_path / TOML_PATH
    _write_atlas_hook(toml_path, "python approved.py")
    store = HookStore(toml_path)

    listed = store.list_all()[0]
    with pytest.raises(ValueError, match="已变化"):
        store.set_hook_trust("review-me", True, fingerprint="0" * 64)
    assert store.list_all()[0]["trust_state"] == "unreviewed"
    assert listed["trust_fingerprint"] == store.list_all()[0]["trust_fingerprint"]

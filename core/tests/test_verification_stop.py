# Ported from NousResearch/hermes-agent@663362680b6ffa4fbffeb58f6682564239a1953b:
# tests/agent/test_verification_stop.py (MIT, (c) Nous Research); Atlas tool events adapted.
from atlas.agent.verification_stop import is_verification_command, requires_verification


def test_documentation_changes_do_not_require_runtime_verification() -> None:
    assert not requires_verification("README.md")
    assert not requires_verification("LICENSE")
    assert requires_verification("atlas/server.py")


def test_only_verification_tools_mark_evidence() -> None:
    assert is_verification_command("run_checks", {})
    assert is_verification_command("local_shell", {"command": "python -m pytest -q"})
    assert not is_verification_command("local_shell", {"command": "python app.py"})

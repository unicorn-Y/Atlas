from pathlib import Path

import pytest

from atlas.agent import AgentOrchestrator
from atlas.skills import SkillManager


@pytest.mark.unit
@pytest.mark.asyncio
async def test_model_tool_rejects_skill_with_disabled_model_invocation(tmp_path: Path):
    skill_dir = tmp_path / "dev" / "private-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: private-skill\ndescription: Private\ndisable-model-invocation: true\n---\nsecret instructions",
        encoding="utf-8",
    )
    manager = SkillManager(tmp_path)
    manager.scan_skills_sync()
    agent = object.__new__(AgentOrchestrator)
    agent._skills = manager

    result = await agent._use_skill_result("private-skill")

    assert result["is_error"] is True
    assert "model invocation is disabled" in result["data"]["error"]
    assert "secret instructions" not in result["content"][0]["text"]

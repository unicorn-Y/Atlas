from pathlib import Path

import pytest

from atlas.skills import SkillManager, _frontmatter_to_skill_info

pytestmark = pytest.mark.unit


def test_invocation_flags_are_normalized_and_serialized(tmp_path: Path) -> None:
    path = tmp_path / "dev" / "private-skill" / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text("---\nname: private-skill\ndescription: Private\n---\n", encoding="utf-8")

    info = _frontmatter_to_skill_info({
        "name": "private-skill",
        "description": "Private",
        "disable-model-invocation": True,
        "user-invocable": False,
    }, path, skills_dir=tmp_path)

    assert info is not None
    assert info.disable_model_invocation is True
    assert info.user_invocable is False
    assert info.to_dict()["disable_model_invocation"] is True
    assert info.to_dict()["user_invocable"] is False


def test_non_user_invocable_skill_is_omitted_from_slash_trigger_matching(tmp_path: Path) -> None:
    skill_dir = tmp_path / "dev" / "private-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: private-skill\ndescription: Private\ntriggers:\n  - command: /private\nuser-invocable: false\n---\n",
        encoding="utf-8",
    )
    manager = SkillManager(tmp_path)
    manager.scan_skills_sync()

    assert manager.match_triggers("/private") == []


@pytest.mark.asyncio
async def test_model_activation_respects_disable_model_invocation(tmp_path: Path) -> None:
    skill_dir = tmp_path / "dev" / "private-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: private-skill\ndescription: Private\ndisable-model-invocation: true\n---\nprivate body",
        encoding="utf-8",
    )
    manager = SkillManager(tmp_path)
    manager.scan_skills_sync()

    with pytest.raises(PermissionError, match="model invocation is disabled"):
        await manager.activate_for_model("private-skill")

    assert await manager.activate("private-skill") == "private body"

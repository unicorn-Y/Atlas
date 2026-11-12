"""技能热重载：改了 SKILL.md 不用重启进程就能生效。"""

from __future__ import annotations

import time
from pathlib import Path

from atlas.skills import SkillManager


def _write_skill(path: Path, name: str, description: str, body: str = "# Demo\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nname: {name}\ndescription: \"{description}\"\nversion: 1.0.0\n---\n\n{body}",
        encoding="utf-8",
    )


def test_skill_edit_is_visible_without_restart(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    md = root / "tools" / "demo-skill" / "SKILL.md"
    _write_skill(md, "demo-skill", "first description")

    manager = SkillManager(root)
    manager.scan_skills_sync()
    loaded = manager.get_skill("demo-skill")
    assert loaded is not None
    assert loaded.description == "first description"

    time.sleep(0.01)
    _write_skill(md, "demo-skill", "second description")

    # 不调用 scan：读入口自己应该发现变化并重扫。
    refreshed = manager.get_skill("demo-skill")
    assert refreshed is not None
    assert refreshed.description == "second description"


def test_newly_added_skill_is_discovered_without_restart(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    first = root / "tools" / "alpha" / "SKILL.md"
    _write_skill(first, "alpha", "alpha skill")

    manager = SkillManager(root)
    manager.scan_skills_sync()
    assert [s.name for s in manager.list_skills()] == ["alpha"]

    time.sleep(0.01)
    second = root / "tools" / "beta" / "SKILL.md"
    _write_skill(second, "beta", "beta skill")

    assert {s.name for s in manager.list_skills()} == {"alpha", "beta"}
    assert manager.get_skill("beta") is not None


def test_rescan_is_skipped_when_nothing_changed(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _write_skill(root / "tools" / "stable" / "SKILL.md", "stable", "stable skill")

    manager = SkillManager(root)
    manager.scan_skills_sync()
    fingerprint = manager._scan_fingerprint
    assert fingerprint

    manager.list_skills()
    manager.get_skill("stable")
    # 没有任何文件变动时不应该重新扫描
    assert manager._scan_fingerprint == fingerprint

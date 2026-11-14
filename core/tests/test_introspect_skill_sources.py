"""Skill source ladder exposure (X18): the introspect ``skills.sources`` view
plus the ``with_sources`` per-scope layering seam (duplicate names resolve by
priority inside a request-scoped copy; the base index stays untouched).
"""

import pytest
from types import SimpleNamespace

from atlas.skills import SkillManager, SkillSource
from atlas.introspect.providers import skills as skills_provider


pytestmark = pytest.mark.unit


def _make_skill(root, relpath, name, description):
    path = root / relpath / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nname: {name}\ndescription: {description}\n---\nBody of {name}",
        encoding="utf-8",
    )
    return path


class _Ctx:
    """Mimic the introspection Context: services.skill_mgr holds the manager."""

    def __init__(self, manager):
        self.services = SimpleNamespace(skill_mgr=manager)


def test_sources_lists_ladder_in_scan_order(tmp_path):
    bundled = tmp_path / "bundled"
    _make_skill(bundled, "tools/demo", "demo", "Bundled demo")
    workspace = tmp_path / "ws" / ".claude" / "skills"
    _make_skill(workspace, "review", "review", "Workspace review")

    mgr = SkillManager(bundled)
    mgr.register_skill_source(SkillSource("claude-project", workspace, 30, layout="flat"))
    mgr.scan_skills_sync()

    result = skills_provider._sources(_Ctx(mgr), {})
    names = [row["name"] for row in result["sources"]]
    priorities = [row["priority"] for row in result["sources"]]
    assert names == ["atlas", "claude-project"]
    assert priorities == [10, 30]
    counts = {row["name"]: row["skill_md_count"] for row in result["sources"]}
    assert counts["atlas"] == 1
    assert counts["claude-project"] == 1
    assert all(row["exists"] for row in result["sources"])


def test_sources_reports_missing_root_without_failing(tmp_path):
    mgr = SkillManager(tmp_path / "not-there")
    result = skills_provider._sources(_Ctx(mgr), {})
    assert result["count"] == 1
    assert result["sources"][0]["exists"] is False
    assert result["sources"][0]["skill_md_count"] == 0


def test_with_sources_layering_wins_duplicates_by_priority_and_leaves_base_alone(tmp_path):
    base_root = tmp_path / "base"
    _make_skill(base_root, "tools/probe", "probe", "Base version")
    scoped_root = tmp_path / "scoped"
    _make_skill(scoped_root, "probe", "probe", "Scoped override")
    extra_root = tmp_path / "extra"
    _make_skill(extra_root, "extra-only", "extra-only", "Scoped extra")

    base = SkillManager(base_root)
    base.scan_skills_sync()
    assert base.get_skill("probe").description == "Base version"

    scoped = base.with_sources([
        SkillSource("request:z6", scoped_root, 90, layout="flat"),
        SkillSource("request:z6-extra", extra_root, 91, layout="flat"),
    ])
    # Higher-priority request-scoped source wins the duplicate name outright,
    # and its own additional skills are visible only in this scoped view.
    assert scoped.get_skill("probe").description == "Scoped override"
    assert scoped.get_skill("extra-only") is not None
    # The base manager keeps the global index untouched.
    assert base.get_skill("probe").description == "Base version"
    assert base.get_skill("extra-only") is None


def test_with_sources_lower_priority_does_not_shadow_base(tmp_path):
    base_root = tmp_path / "base"
    _make_skill(base_root, "tools/probe", "probe", "Base version")
    low_root = tmp_path / "low"
    _make_skill(low_root, "probe", "probe", "Low priority version")

    base = SkillManager(base_root)
    base.scan_skills_sync()
    scoped = base.with_sources([
        SkillSource("request:low", low_root, 5, layout="flat"),
    ])
    assert scoped.get_skill("probe").description == "Base version"


def test_provider_manifest_exposes_sources_method():
    manifest = skills_provider.PROVIDER.manifest()
    methods = {item["name"] for item in manifest["methods"]}
    assert {"list", "categories", "sources", "preflight"} <= methods

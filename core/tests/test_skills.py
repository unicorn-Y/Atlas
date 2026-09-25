"""Tests for the SkillManager."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from atlas.skills import SkillManager, SkillInfo, _parse_skill_md, _frontmatter_to_skill_info


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_skill(tmp_path: Path, category: str, name: str,
                 frontmatter: str, body: str = "") -> Path:
    """Create a SKILL.md inside tmp_path/<category>/<name>/."""
    skill_dir = tmp_path / category / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md = skill_dir / "SKILL.md"
    content = f"---\n{frontmatter}---\n\n{body}"
    skill_md.write_text(content, encoding="utf-8")
    return skill_md


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------

class TestParsing:
    def test_parse_valid_skill(self, tmp_path: Path) -> None:
        path = _write_skill(tmp_path, "research", "arxiv",
            'name: arxiv\n'
            'description: "Search arXiv papers"\n'
            'version: 1.0.0\n'
            'category: research\n',
            body="# arXiv\n\nSearch papers.")
        result = _parse_skill_md(path)
        assert result is not None
        fm, body = result
        assert fm["name"] == "arxiv"
        assert "Search papers" in body

    def test_parse_no_frontmatter(self, tmp_path: Path) -> None:
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("# No frontmatter here\n", encoding="utf-8")
        assert _parse_skill_md(skill_md) is None

    def test_parse_invalid_yaml(self, tmp_path: Path) -> None:
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\n[invalid: yaml: {\n---\n", encoding="utf-8")
        assert _parse_skill_md(skill_md) is None

    def test_parse_missing_file(self, tmp_path: Path) -> None:
        path = tmp_path / "nonexistent" / "SKILL.md"
        assert _parse_skill_md(path) is None


# ---------------------------------------------------------------------------
# Frontmatter to SkillInfo conversion
# ---------------------------------------------------------------------------

class TestFrontmatterConversion:
    def test_basic_conversion(self, tmp_path: Path) -> None:
        fm = {
            "name": "test-skill",
            "description": "A test skill",
            "version": "1.0.0",
            "category": "dev",
            "triggers": [
                {"pattern": "test|testing"},
                {"command": "/test"},
            ],
            "tags": ["test", "dev"],
            "dependencies": {
                "mcp_servers": ["filesystem"],
                "python_packages": ["pytest"],
            },
        }
        path = tmp_path / "dev" / "test-skill" / "SKILL.md"
        path.parent.mkdir(parents=True)
        path.touch()
        info = _frontmatter_to_skill_info(fm, path)
        assert info is not None
        assert info.name == "test-skill"
        assert info.category == "dev"
        assert len(info.triggers) == 2
        assert info.tags == ["test", "dev"]
        assert info.dependencies["mcp_servers"] == ["filesystem"]

    def test_missing_name(self, tmp_path: Path) -> None:
        fm = {"description": "no name"}
        assert _frontmatter_to_skill_info(fm, tmp_path / "SKILL.md") is None

    def test_missing_description(self, tmp_path: Path) -> None:
        fm = {"name": "no-desc"}
        assert _frontmatter_to_skill_info(fm, tmp_path / "SKILL.md") is None

    def test_hermes_metadata_compat(self, tmp_path: Path) -> None:
        """Should extract tags/category from metadata.hermes.*."""
        fm = {
            "name": "hermes-skill",
            "description": "Hermes format",
            "version": "1.0.0",
            "metadata": {
                "hermes": {
                    "tags": ["git", "pr"],
                    "category": "github",
                    "related_skills": ["github-auth"],
                }
            },
        }
        path = tmp_path / "github" / "hermes-skill" / "SKILL.md"
        path.parent.mkdir(parents=True)
        path.touch()
        info = _frontmatter_to_skill_info(fm, path)
        assert info is not None
        assert info.category == "github"
        assert info.tags == ["git", "pr"]
        assert info.related_skills == ["github-auth"]

    def test_category_from_directory(self, tmp_path: Path) -> None:
        """Category inferred from directory when not in frontmatter."""
        fm = {"name": "inferred-cat", "description": "test"}
        path = tmp_path / "productivity" / "inferred-cat" / "SKILL.md"
        path.parent.mkdir(parents=True)
        path.touch()
        info = _frontmatter_to_skill_info(fm, path, skills_dir=tmp_path)
        assert info is not None
        assert info.category == "productivity"


# ---------------------------------------------------------------------------
# SkillManager scanning
# ---------------------------------------------------------------------------

class TestScanning:
    def test_scan_empty_directory(self, tmp_path: Path) -> None:
        mgr = SkillManager(skills_dir=tmp_path)
        mgr.scan_skills_sync()
        assert mgr.skill_count == 0

    def test_scan_nonexistent_directory(self, tmp_path: Path) -> None:
        mgr = SkillManager(skills_dir=tmp_path / "nonexistent")
        mgr.scan_skills_sync()  # should not raise
        assert mgr.skill_count == 0

    def test_scan_finds_skills(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "dev", "skill-a",
                     'name: skill-a\ndescription: "Skill A"\nversion: 1.0.0\n')
        _write_skill(tmp_path, "research", "skill-b",
                     'name: skill-b\ndescription: "Skill B"\nversion: 1.0.0\n')
        mgr = SkillManager(skills_dir=tmp_path)
        mgr.scan_skills_sync()
        assert mgr.skill_count == 2
        assert mgr.get_skill("skill-a") is not None
        assert mgr.get_skill("skill-b") is not None

    def test_scan_skips_invalid(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "dev", "good",
                     'name: good\ndescription: "Good"\nversion: 1.0.0\n')
        # Invalid: no frontmatter
        bad_dir = tmp_path / "dev" / "bad"
        bad_dir.mkdir(parents=True)
        (bad_dir / "SKILL.md").write_text("# No frontmatter", encoding="utf-8")
        mgr = SkillManager(skills_dir=tmp_path)
        mgr.scan_skills_sync()
        assert mgr.skill_count == 1

    def test_duplicate_name_skipped(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "dev", "dupe1",
                     'name: same-name\ndescription: "First"\nversion: 1.0.0\n')
        _write_skill(tmp_path, "research", "dupe2",
                     'name: same-name\ndescription: "Second"\nversion: 1.0.0\n')
        mgr = SkillManager(skills_dir=tmp_path)
        mgr.scan_skills_sync()
        assert mgr.skill_count == 1

    async def test_async_scan(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "dev", "async-skill",
                     'name: async-skill\ndescription: "Test"\nversion: 1.0.0\n')
        mgr = SkillManager(skills_dir=tmp_path)
        await mgr.scan_skills()
        assert mgr.skill_count == 1


# ---------------------------------------------------------------------------
# Querying
# ---------------------------------------------------------------------------

class TestQuerying:
    @pytest.fixture
    def mgr(self, tmp_path: Path) -> SkillManager:
        _write_skill(tmp_path, "github", "github-pr",
            'name: github-pr\ndescription: "PR workflow"\n'
            'version: 1.0.0\ncategory: github\n'
            'tags: [git, pr]\n')
        _write_skill(tmp_path, "research", "arxiv",
            'name: arxiv\ndescription: "Search arXiv papers"\n'
            'version: 1.0.0\ncategory: research\n'
            'tags: [papers, academic]\n')
        _write_skill(tmp_path, "productivity", "pdf-tools",
            'name: pdf-tools\ndescription: "PDF create and merge"\n'
            'version: 1.0.0\ncategory: productivity\n'
            'tags: [pdf, documents]\n')
        m = SkillManager(skills_dir=tmp_path)
        m.scan_skills_sync()
        return m

    def test_list_all(self, mgr: SkillManager) -> None:
        assert mgr.skill_count == 3
        all_skills = mgr.list_skills()
        assert len(all_skills) == 3

    def test_list_by_category(self, mgr: SkillManager) -> None:
        github = mgr.list_skills(category="github")
        assert len(github) == 1
        assert github[0].name == "github-pr"

    def test_get_skill(self, mgr: SkillManager) -> None:
        s = mgr.get_skill("arxiv")
        assert s is not None
        assert s.description == "Search arXiv papers"

    def test_get_nonexistent(self, mgr: SkillManager) -> None:
        assert mgr.get_skill("nope") is None

    def test_search_by_name(self, mgr: SkillManager) -> None:
        results = mgr.search_skills("pdf")
        assert len(results) == 1
        assert results[0].name == "pdf-tools"

    def test_search_by_tag(self, mgr: SkillManager) -> None:
        results = mgr.search_skills("academic")
        assert len(results) == 1
        assert results[0].name == "arxiv"

    def test_search_by_description(self, mgr: SkillManager) -> None:
        results = mgr.search_skills("workflow")
        assert len(results) == 1
        assert results[0].name == "github-pr"

    def test_categories(self, mgr: SkillManager) -> None:
        cats = mgr.categories
        assert set(cats) == {"github", "research", "productivity"}


# ---------------------------------------------------------------------------
# Trigger matching
# ---------------------------------------------------------------------------

class TestTriggerMatching:
    @pytest.fixture
    def mgr(self, tmp_path: Path) -> SkillManager:
        _write_skill(tmp_path, "research", "search",
            'name: search\ndescription: "Web search"\n'
            'version: 1.0.0\ncategory: research\n'
            'triggers:\n'
            '  - pattern: "搜索|搜一下|search"\n'
            '  - command: "/search"\n')
        _write_skill(tmp_path, "research", "arxiv",
            'name: arxiv\ndescription: "arXiv papers"\n'
            'version: 1.0.0\ncategory: research\n'
            'triggers:\n'
            '  - pattern: "论文|arxiv|paper"\n'
            '  - command: "/arxiv"\n')
        _write_skill(tmp_path, "dev", "no-trigger",
            'name: no-trigger\ndescription: "No triggers"\n'
            'version: 1.0.0\ncategory: dev\n')
        m = SkillManager(skills_dir=tmp_path)
        m.scan_skills_sync()
        return m

    def test_slash_command_exact(self, mgr: SkillManager) -> None:
        matches = mgr.match_triggers("/arxiv quantum computing")
        assert len(matches) == 1
        assert matches[0].name == "arxiv"

    def test_slash_command_case_insensitive(self, mgr: SkillManager) -> None:
        matches = mgr.match_triggers("/Search something")
        assert len(matches) == 1
        assert matches[0].name == "search"

    def test_pattern_chinese(self, mgr: SkillManager) -> None:
        matches = mgr.match_triggers("帮我搜索一下LangGraph教程")
        assert len(matches) == 1
        assert matches[0].name == "search"

    def test_pattern_english(self, mgr: SkillManager) -> None:
        matches = mgr.match_triggers("search for recent AI papers")
        # Both 'search' and 'arxiv' match ("search" + "paper")
        names = {m.name for m in matches}
        assert "search" in names
        assert "arxiv" in names

    def test_no_match(self, mgr: SkillManager) -> None:
        matches = mgr.match_triggers("What's the weather?")
        assert matches == []

    def test_skill_without_triggers_never_matches(self, mgr: SkillManager) -> None:
        matches = mgr.match_triggers("no-trigger stuff")
        # 'no-trigger' skill has no triggers defined
        names = {m.name for m in matches}
        assert "no-trigger" not in names


# ---------------------------------------------------------------------------
# Activation
# ---------------------------------------------------------------------------

class TestActivation:
    async def test_activate_returns_body(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "dev", "test-act",
            'name: test-act\ndescription: "Activate me"\nversion: 1.0.0\n',
            body="# Test\n\nDo the thing.")
        mgr = SkillManager(skills_dir=tmp_path)
        await mgr.scan_skills()
        body = await mgr.activate("test-act")
        assert body is not None
        assert "Do the thing" in body

    async def test_activate_nonexistent(self, tmp_path: Path) -> None:
        mgr = SkillManager(skills_dir=tmp_path)
        await mgr.scan_skills()
        assert await mgr.activate("nonexistent") is None


# ---------------------------------------------------------------------------
# Dependency checking
# ---------------------------------------------------------------------------

class TestDependencyChecking:
    def test_check_mcp_servers(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "dev", "dep-test",
            'name: dep-test\ndescription: "Deps"\nversion: 1.0.0\n'
            'dependencies:\n'
            '  mcp_servers:\n'
            '    - filesystem\n'
            '    - git\n')
        mgr = SkillManager(skills_dir=tmp_path)
        mgr.scan_skills_sync()
        result = mgr.check_dependencies(
            "dep-test", connected_servers=["filesystem"])
        assert result["mcp:filesystem"] is True
        assert result["mcp:git"] is False

    def test_check_python_packages(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "dev", "pkg-test",
            'name: pkg-test\ndescription: "Pkgs"\nversion: 1.0.0\n'
            'dependencies:\n'
            '  python_packages:\n'
            '    - json\n'
            '    - nonexistent_package_xyz\n')
        mgr = SkillManager(skills_dir=tmp_path)
        mgr.scan_skills_sync()
        result = mgr.check_dependencies("pkg-test")
        assert result["python:json"] is True
        assert result["python:nonexistent_package_xyz"] is False

    def test_check_nonexistent_skill(self, tmp_path: Path) -> None:
        mgr = SkillManager(skills_dir=tmp_path)
        assert mgr.check_dependencies("nope") == {}


# ---------------------------------------------------------------------------
# to_dict serialization
# ---------------------------------------------------------------------------

class TestSerialization:
    def test_to_dict(self) -> None:
        info = SkillInfo(
            name="test", description="desc", version="1.0.0",
            category="dev", path="/fake/path",
            triggers=[{"command": "/test"}],
            tags=["a", "b"],
        )
        d = info.to_dict()
        assert d["name"] == "test"
        assert d["category"] == "dev"
        assert d["triggers"] == [{"command": "/test"}]
        assert "path" not in d  # path not exposed in API

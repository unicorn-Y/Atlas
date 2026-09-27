"""Tests for the SkillManager."""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas import skills as skills_module
from atlas.skills import SkillInfo, SkillManager, _frontmatter_to_skill_info, _parse_skill_md

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
    def test_repository_owned_skill_frontmatter_parses(self) -> None:
        skills_dir = Path(__file__).resolve().parents[2] / "skills"
        skill_files = [
            path for path in skills_dir.rglob("SKILL.md")
            if len(path.relative_to(skills_dir).parts) == 3
        ]

        assert skill_files
        assert all(_parse_skill_md(path) is not None for path in skill_files)

    def test_coding_discipline_content_is_utf8(self) -> None:
        path = Path(__file__).resolve().parents[2] / "skills/dev/coding-discipline/SKILL.md"
        parsed = _parse_skill_md(path)

        assert parsed is not None
        _frontmatter, body = parsed
        assert "编码纪律" in body
        assert "�" not in body

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

    def test_invalid_nested_metadata_has_clear_warning(self, tmp_path: Path, monkeypatch) -> None:
        fm = {
            "name": "invalid-meta",
            "description": "Invalid metadata shape",
            "metadata": "not-a-mapping",
        }
        path = tmp_path / "dev" / "invalid-meta" / "SKILL.md"
        path.parent.mkdir(parents=True)
        path.touch()
        warnings: list[tuple[str, dict[str, object]]] = []
        monkeypatch.setattr(
            skills_module.log,
            "warning",
            lambda event, **fields: warnings.append((event, fields)),
        )

        assert _frontmatter_to_skill_info(fm, path, skills_dir=tmp_path) is None
        assert warnings[0][0] == "skills.invalid_metadata"
        assert warnings[0][1]["error"] == "metadata must be a mapping"

    def test_invalid_trigger_metadata_is_rejected(self, tmp_path: Path) -> None:
        fm = {
            "name": "invalid-trigger",
            "description": "Invalid trigger shape",
            "triggers": {"pattern": "never-a-list"},
        }
        path = tmp_path / "dev" / "invalid-trigger" / "SKILL.md"
        path.parent.mkdir(parents=True)
        path.touch()

        assert _frontmatter_to_skill_info(fm, path, skills_dir=tmp_path) is None


# ---------------------------------------------------------------------------
# SkillManager scanning
# ---------------------------------------------------------------------------

class TestScanning:
    def test_scan_loads_every_repository_owned_skill(self) -> None:
        skills_dir = Path(__file__).resolve().parents[2] / "skills"
        skill_files = [
            path for path in skills_dir.rglob("SKILL.md")
            if len(path.relative_to(skills_dir).parts) == 3
        ]
        mgr = SkillManager(skills_dir=skills_dir)

        mgr.scan_skills_sync()

        assert mgr.skill_count == len(skill_files)

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

    def test_duplicate_name_resolution_is_deterministic(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "research", "dupe2",
                     'name: same-name\ndescription: "Research copy"\nversion: 1.0.0\n')
        _write_skill(tmp_path, "dev", "dupe1",
                     'name: same-name\ndescription: "Development copy"\nversion: 1.0.0\n')
        mgr = SkillManager(skills_dir=tmp_path)
        mgr.scan_skills_sync()
        assert mgr.skill_count == 1
        assert mgr.get_skill("same-name").description == "Development copy"

    def test_scan_skips_invalid_metadata_without_stopping(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "dev", "good",
                     'name: good\ndescription: "Good"\nversion: 1.0.0\n')
        _write_skill(tmp_path, "dev", "bad",
                     'name: bad\ndescription: "Bad"\nmetadata: invalid\n')
        mgr = SkillManager(skills_dir=tmp_path)

        mgr.scan_skills_sync()

        assert mgr.skill_count == 1
        assert mgr.get_skill("good") is not None
        assert mgr.get_skill("bad") is None

    def test_scan_ignores_skills_outside_category_directory_layout(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "github", "owned",
                     'name: owned\ndescription: "Atlas skill"\nversion: 1.0.0\n')
        injected_path = tmp_path / "injected" / "SKILL.md"
        injected_path.parent.mkdir(parents=True)
        injected_path.write_text(
            "---\nname: injected\ndescription: External skill\n---\n",
            encoding="utf-8",
        )
        mgr = SkillManager(skills_dir=tmp_path)

        mgr.scan_skills_sync()

        assert mgr.skill_count == 1
        assert mgr.get_skill("owned") is not None
        assert mgr.get_skill("injected") is None

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

    def test_to_dict_exposes_canonical_dependency_contract(self) -> None:
        contract = [{"kind": "python_packages", "name": "pydantic", "requested": None}]
        info = SkillInfo(
            name="test", description="desc", version="1.0.0",
            category="dev", path="/fake/path",
            dependencies={"python_packages": ["requests"]},
            dependency_contract=contract,
        )

        serialized = info.to_dict()

        assert serialized["dependencies"] == contract
        assert serialized["dependencies"] != info.dependencies

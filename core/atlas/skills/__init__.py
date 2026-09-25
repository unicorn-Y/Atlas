"""Atlas Skill Manager — index, match, and activate skills.

Scans the skills/ directory for SKILL.md files, parses frontmatter,
builds an in-memory index, and provides trigger matching + activation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

import yaml

from atlas.config import PROJECT_ROOT

log = structlog.get_logger()

SKILLS_DIR = PROJECT_ROOT / "skills"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class SkillInfo:
    """Parsed skill metadata from SKILL.md frontmatter."""

    name: str
    description: str
    version: str
    category: str
    path: str  # absolute path to SKILL.md
    triggers: list[dict[str, str]] = field(default_factory=list)
    dependencies: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    related_skills: list[str] = field(default_factory=list)
    author: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize for API responses."""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "category": self.category,
            "tags": self.tags,
            "triggers": self.triggers,
            "dependencies": self.dependencies,
            "related_skills": self.related_skills,
            "author": self.author,
        }


# ---------------------------------------------------------------------------
# Frontmatter parser
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(
    r"\A---\s*\n(.*?)\n---\s*\n",
    re.DOTALL,
)


def _parse_skill_md(path: Path) -> tuple[dict[str, Any], str] | None:
    """Parse a SKILL.md file into (frontmatter_dict, body_text).

    Returns None if the file can't be parsed.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        log.warning("skill.read_error", path=str(path), error=str(e))
        return None

    m = _FRONTMATTER_RE.match(text)
    if not m:
        log.warning("skill.no_frontmatter", path=str(path))
        return None

    try:
        fm = yaml.safe_load(m.group(1))
    except Exception as e:
        log.warning("skill.yaml_error", path=str(path), error=str(e))
        return None

    if not isinstance(fm, dict):
        log.warning("skill.invalid_frontmatter", path=str(path))
        return None

    body = text[m.end():]
    return fm, body


def _frontmatter_to_skill_info(
    fm: dict[str, Any],
    path: Path,
    skills_dir: Path | None = None,
) -> SkillInfo | None:
    """Convert parsed frontmatter dict to a SkillInfo.

    Returns None if required fields are missing.
    """
    name = fm.get("name")
    description = fm.get("description")
    if not name or not description:
        log.warning("skill.missing_required_fields", path=str(path),
                    has_name=bool(name), has_desc=bool(description))
        return None

    # Normalize triggers
    raw_triggers = fm.get("triggers", []) or []
    triggers: list[dict[str, str]] = []
    for t in raw_triggers:
        if isinstance(t, dict):
            triggers.append(t)
        elif isinstance(t, str):
            triggers.append({"pattern": t})

    # Normalize dependencies
    deps = fm.get("dependencies", {}) or {}
    if not isinstance(deps, dict):
        deps = {}

    # Handle Hermes-format metadata (backward compat)
    tags = fm.get("tags", []) or []
    related = fm.get("related_skills", []) or []
    category = fm.get("category", "")

    # Hermes stores these under metadata.hermes.*
    hermes_meta = (fm.get("metadata", {}) or {}).get("hermes", {})
    if hermes_meta:
        if not tags and hermes_meta.get("tags"):
            tags = hermes_meta["tags"]
        if not related and hermes_meta.get("related_skills"):
            related = hermes_meta["related_skills"]
        if not category and hermes_meta.get("category"):
            category = hermes_meta["category"]

    # Infer category from directory structure if not in frontmatter
    if not category:
        # skills/<category>/<skill-name>/SKILL.md
        base = skills_dir or SKILLS_DIR
        try:
            rel = path.relative_to(base)
            parts = rel.parts
            if len(parts) >= 2:
                category = parts[0]
        except ValueError:
            pass

    return SkillInfo(
        name=name,
        description=description,
        version=fm.get("version", "0.0.0"),
        category=category,
        path=str(path),
        triggers=triggers,
        dependencies=deps,
        tags=tags if isinstance(tags, list) else [tags],
        related_skills=related if isinstance(related, list) else [related],
        author=fm.get("author", ""),
    )


# ---------------------------------------------------------------------------
# SkillManager
# ---------------------------------------------------------------------------

class SkillManager:
    """Manages skill indexing, trigger matching, and activation.

    Usage::

        mgr = SkillManager()
        await mgr.scan_skills()  # or mgr.scan_skills_sync()
        matches = mgr.match_triggers("帮我搜一下论文")
        content = await mgr.activate("arxiv")
    """

    def __init__(self, skills_dir: Path | None = None) -> None:
        self._skills_dir = skills_dir or SKILLS_DIR
        self._index: dict[str, SkillInfo] = {}  # name → SkillInfo

    # -- scanning --------------------------------------------------------------

    async def scan_skills(self) -> None:
        """Scan skills directory and build index. Async wrapper."""
        self.scan_skills_sync()

    def scan_skills_sync(self) -> None:
        """Scan skills directory and build index (synchronous)."""
        self._index.clear()

        if not self._skills_dir.is_dir():
            log.warning("skills.dir_not_found", path=str(self._skills_dir))
            return

        count = 0
        for skill_md in self._skills_dir.rglob("SKILL.md"):
            parsed = _parse_skill_md(skill_md)
            if parsed is None:
                continue

            fm, _body = parsed
            info = _frontmatter_to_skill_info(fm, skill_md, skills_dir=self._skills_dir)
            if info is None:
                continue

            if info.name in self._index:
                log.warning("skills.duplicate_name", name=info.name,
                            existing=self._index[info.name].path,
                            new=str(skill_md))
                continue

            self._index[info.name] = info
            count += 1

        log.info("skills.scanned", count=count, directory=str(self._skills_dir))

    # -- querying --------------------------------------------------------------

    def list_skills(self, category: str | None = None) -> list[SkillInfo]:
        """List all skills, optionally filtered by category."""
        skills = list(self._index.values())
        if category:
            skills = [s for s in skills if s.category == category]
        return sorted(skills, key=lambda s: (s.category, s.name))

    def get_skill(self, name: str) -> SkillInfo | None:
        """Get a skill by its name."""
        return self._index.get(name)

    def search_skills(self, query: str) -> list[SkillInfo]:
        """Search skills by name, description, or tags."""
        query_lower = query.lower()
        results: list[SkillInfo] = []
        for skill in self._index.values():
            if (query_lower in skill.name.lower()
                    or query_lower in skill.description.lower()
                    or any(query_lower in t.lower() for t in skill.tags)):
                results.append(skill)
        return sorted(results, key=lambda s: s.name)

    @property
    def skill_count(self) -> int:
        return len(self._index)

    @property
    def categories(self) -> list[str]:
        """Return all unique categories."""
        return sorted(set(s.category for s in self._index.values() if s.category))

    # -- trigger matching ------------------------------------------------------

    def match_triggers(self, user_input: str) -> list[SkillInfo]:
        """Match user input against all skill triggers.

        Returns candidate skills sorted by specificity (command match first,
        then pattern matches).
        """
        # Strip leading/trailing whitespace
        text = user_input.strip()

        # Phase 1: exact slash-command match
        if text.startswith("/"):
            cmd = text.split()[0].lower()  # e.g. "/arxiv"
            for skill in self._index.values():
                for trigger in skill.triggers:
                    if trigger.get("command", "").lower() == cmd:
                        return [skill]

        # Phase 2: regex pattern matching
        candidates: list[SkillInfo] = []
        for skill in self._index.values():
            for trigger in skill.triggers:
                pattern = trigger.get("pattern")
                if not pattern:
                    continue
                try:
                    if re.search(pattern, text, re.IGNORECASE):
                        candidates.append(skill)
                        break  # one match per skill is enough
                except re.error:
                    log.warning("skills.bad_trigger_regex",
                                skill=skill.name, pattern=pattern)

        return candidates

    # -- activation ------------------------------------------------------------

    async def activate(self, name: str) -> str | None:
        """Activate a skill: read its full SKILL.md and return the body content.

        Returns None if the skill is not found.
        """
        skill = self._index.get(name)
        if skill is None:
            return None

        parsed = _parse_skill_md(Path(skill.path))
        if parsed is None:
            return None

        _fm, body = parsed
        log.info("skills.activated", name=name)
        return body

    # -- dependency checking ---------------------------------------------------

    def check_dependencies(
        self,
        name: str,
        *,
        connected_servers: list[str] | None = None,
    ) -> dict[str, bool]:
        """Check if a skill's dependencies are satisfied.

        Args:
            name: Skill name.
            connected_servers: List of currently connected MCP server names.

        Returns:
            Dict mapping dependency names to satisfied (True/False).
        """
        skill = self._index.get(name)
        if skill is None:
            return {}

        results: dict[str, bool] = {}
        deps = skill.dependencies

        # Check MCP servers
        servers = connected_servers or []
        for srv in deps.get("mcp_servers", []) or []:
            results[f"mcp:{srv}"] = srv in servers

        # Check Python packages
        for pkg in deps.get("python_packages", []) or []:
            try:
                __import__(pkg)
                results[f"python:{pkg}"] = True
            except ImportError:
                results[f"python:{pkg}"] = False

        # Check system commands
        import shutil
        for cmd in deps.get("commands", []) or []:
            results[f"command:{cmd}"] = shutil.which(cmd) is not None

        return results

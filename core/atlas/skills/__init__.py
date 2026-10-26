"""Atlas Skill Manager — index, match, and activate skills.

Scans the skills/ directory for SKILL.md files, parses frontmatter,
builds an in-memory index, and provides trigger matching + activation.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import structlog

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]  # noqa: F401

import yaml

from atlas.config import PROJECT_ROOT
from atlas.skills.dependencies import canonical_skill_dependencies, dependency_preflight

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
    dependencies: Any = field(default_factory=dict)
    dependency_contract: list[dict[str, Any]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    related_skills: list[str] = field(default_factory=list)
    author: str = ""
    source: str = "atlas"
    source_priority: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize for API responses with canonical dependencies."""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "category": self.category,
            "tags": self.tags,
            "triggers": self.triggers,
            "dependencies": self.dependency_contract,
            "related_skills": self.related_skills,
            "author": self.author,
            "source": self.source,
            "source_priority": self.source_priority,
        }


@dataclass(frozen=True)
class SkillSource:
    """A directory contributing Agent Skills to the shared Atlas index.

    ``layout`` pins the on-disk convention a source is trusted for, so one
    rglob rule stays stable across sources:

    - ``"category"``: ``<root>/<category>/<skill>/SKILL.md`` (Atlas repo,
      Hermes bundled skills)
    - ``"flat"``: ``<root>/<skill>/SKILL.md`` (Claude Code skills dirs)
    - ``"single"``: ``<root>/SKILL.md`` (one plugin-contributed skill dir)
    """

    name: str
    root: Path
    priority: int
    layout: str = "flat"


_LAYOUT_PARTS = {"single": 1, "flat": 2, "category": 3}


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
    def invalid(reason: str) -> None:
        log.warning("skills.invalid_metadata", path=str(path), error=reason)

    name = fm.get("name")
    if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        invalid("name must be a non-empty kebab-case string")
        return None

    description = fm.get("description")
    if not isinstance(description, str) or not description.strip():
        invalid("description must be a non-empty string")
        return None

    version = fm.get("version", "0.0.0")
    if not isinstance(version, str) or not re.fullmatch(
        r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?",
        version,
    ):
        invalid("version must use MAJOR.MINOR.PATCH semantic version format")
        return None

    # Normalize triggers while rejecting malformed YAML shapes early.
    raw_triggers = fm.get("triggers", []) or []
    if not isinstance(raw_triggers, list):
        invalid("triggers must be a list of strings or pattern/command mappings")
        return None
    triggers: list[dict[str, str]] = []
    for trigger in raw_triggers:
        if isinstance(trigger, str) and trigger.strip():
            triggers.append({"pattern": trigger})
        elif isinstance(trigger, dict) and any(
            key in trigger and isinstance(trigger[key], str) and trigger[key].strip()
            for key in ("pattern", "command")
        ):
            if any(
                key in trigger and not isinstance(trigger[key], str)
                for key in ("pattern", "command")
            ):
                invalid("trigger pattern and command values must be strings")
                return None
            triggers.append(trigger)
        else:
            invalid("each trigger must be a non-empty string or contain a pattern/command string")
            return None

    # Dependencies have a fixed set of string-list fields.
    deps = fm.get("dependencies", {}) or {}
    if not isinstance(deps, dict):
        invalid("dependencies must be a mapping")
        return None
    for key in ("mcp_servers", "python_packages", "commands"):
        values = deps.get(key, []) or []
        if not isinstance(values, list) or any(
            not (isinstance(value, str) and value.strip())
            and not (isinstance(value, dict) and isinstance(value.get("name"), str)
                     and value["name"].strip()
                     and all(field in {"name", "version", "constraint"} for field in value))
            for value in values
        ):
            invalid(f"dependencies.{key} must be a list of names or named version constraints")
            return None
    requirements = fm.get("requirements", []) or []
    if not isinstance(requirements, (list, dict)):
        invalid("requirements must be a list or mapping")
        return None
    dependency_contract = canonical_skill_dependencies(deps, requirements)

    # Accept Atlas fields and Hermes-compatible nested metadata.
    tags = fm.get("tags", []) or []
    related = fm.get("related_skills", []) or []
    if not isinstance(tags, list) or any(not isinstance(tag, str) or not tag for tag in tags):
        invalid("tags must be a list of non-empty strings")
        return None
    if not isinstance(related, list) or any(
        not isinstance(item, str) or not item for item in related
    ):
        invalid("related_skills must be a list of non-empty strings")
        return None

    category = fm.get("category", "") or ""
    if not isinstance(category, str):
        invalid("category must be a string")
        return None
    metadata = fm.get("metadata", {}) or {}
    if not isinstance(metadata, dict):
        invalid("metadata must be a mapping")
        return None
    hermes_meta = metadata.get("hermes", {}) or {}
    if not isinstance(hermes_meta, dict):
        invalid("metadata.hermes must be a mapping")
        return None

    for key, current in (("tags", tags), ("related_skills", related)):
        if current:
            continue
        values = hermes_meta.get(key, []) or []
        if not isinstance(values, list) or any(
            not isinstance(value, str) or not value for value in values
        ):
            invalid(f"metadata.hermes.{key} must be a list of non-empty strings")
            return None
        if key == "tags":
            tags = values
        else:
            related = values

    if not category:
        hermes_category = hermes_meta.get("category", "") or ""
        if not isinstance(hermes_category, str):
            invalid("metadata.hermes.category must be a string")
            return None
        category = hermes_category

    author = fm.get("author", "") or ""
    if not isinstance(author, str):
        invalid("author must be a string")
        return None

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
        version=version,
        category=category,
        path=str(path),
        triggers=triggers,
        dependencies=deps,
        dependency_contract=dependency_contract,
        tags=tags,
        related_skills=related,
        author=author,
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
        self._sources: dict[str, SkillSource] = {
            "atlas": SkillSource("atlas", self._skills_dir, 10, layout="category"),
        }

    def register_skill_source(self, source: SkillSource) -> None:
        """Register or replace an external source before scanning the index.

        Higher priorities win duplicate names. Equal-priority ties are resolved
        by source name and then path, so discovery is stable across runs.
        """
        if not source.name or not isinstance(source.priority, int):
            raise ValueError("skill source requires a name and integer priority")
        if source.layout not in _LAYOUT_PARTS:
            raise ValueError(f"skill source layout must be one of {sorted(_LAYOUT_PARTS)}")
        self._sources[source.name] = SkillSource(
            source.name, Path(source.root).expanduser(), source.priority, source.layout,
        )

    def unregister_skill_source(self, name: str) -> None:
        """Remove a dynamic source, for example after a plugin is disabled."""
        if name == "atlas":
            raise ValueError("the built-in Atlas skills source cannot be removed")
        self._sources.pop(name, None)

    def replace_skill_sources(self, prefix: str, sources: list[SkillSource]) -> None:
        """Replace a family of dynamic sources and rebuild the canonical index."""
        for name in tuple(self._sources):
            if name.startswith(prefix) and name != "atlas":
                del self._sources[name]
        for source in sources:
            if not source.name.startswith(prefix):
                raise ValueError(f"skill source name must start with {prefix!r}")
            self.register_skill_source(source)
        self.scan_skills_sync()

    def with_sources(self, sources: list[SkillSource]) -> "SkillManager":
        """Build a request-scoped view using this same index/activation layer."""
        scoped = SkillManager(self._skills_dir)
        scoped._sources = dict(self._sources)
        for source in sources:
            scoped.register_skill_source(source)
        scoped.scan_skills_sync()
        return scoped

    # -- scanning --------------------------------------------------------------

    async def scan_skills(self) -> None:
        """Scan skills directory and build index. Async wrapper."""
        self.scan_skills_sync()

    def scan_skills_sync(self) -> None:
        """Scan skills directory and build index (synchronous)."""
        self._index.clear()

        count = 0
        sources = sorted(
            self._sources.values(), key=lambda item: (item.priority, item.name, str(item.root)),
        )
        for source in sources:
            if not source.root.is_dir():
                continue
            expected_parts = _LAYOUT_PARTS[source.layout]
            skill_files = sorted(
                (path for path in source.root.rglob("SKILL.md")
                 if len(path.relative_to(source.root).parts) == expected_parts),
                key=lambda path: path.relative_to(source.root).as_posix().casefold(),
            )
            for skill_md in skill_files:
                parsed = _parse_skill_md(skill_md)
                if parsed is None:
                    continue

                fm, _body = parsed
                # Only the category layout owns the "first directory is the
                # category" inference; flat/single sources keep the declared
                # (or empty) category instead of the skill's own folder name.
                info = _frontmatter_to_skill_info(
                    fm, skill_md,
                    skills_dir=source.root if source.layout == "category" else None,
                )
                if info is None:
                    continue
                info.source = source.name
                info.source_priority = source.priority

                existing = self._index.get(info.name)
                if existing is not None:
                    log.warning("skills.duplicate_name", name=info.name,
                                existing=existing.path, new=str(skill_md))
                    if existing.source_priority >= info.source_priority:
                        continue
                self._index[info.name] = info
                if existing is None:
                    count += 1

        log.info("skills.scanned", count=count, sources=len(sources))

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

    async def activate(
        self,
        name: str,
        *,
        connected_servers: list[str] | None = None,
        configured_servers: list[str] | None = None,
        registry: Any | None = None,
    ) -> str | None:
        """Activate a skill: read its full SKILL.md and return the body content.

        Returns None if the skill is not found.
        """
        skill = self._index.get(name)
        if skill is None:
            return None
        from atlas.skills.source_policy import skill_load_allowed
        if not skill_load_allowed(skill):
            raise PermissionError(f"skill loading is disabled by source policy ({skill.name})")

        blockers = [item for item in self.preflight_dependencies(
            name, connected_servers=connected_servers,
            configured_servers=configured_servers, registry=registry,
        ) if item["state"] != "satisfied"]
        if blockers:
            detail = ", ".join(
                f"{item['kind']}:{item['name']} ({item['state']})" for item in blockers
            )
            raise PermissionError("skill dependencies block activation: " + detail)

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
        dependencies = self.preflight_dependencies(
            name, connected_servers=connected_servers, configured_servers=connected_servers,
        )
        kind_aliases = {"mcp_servers": "mcp", "python_packages": "python", "commands": "command"}
        return {
            f"{kind_aliases.get(item['kind'], item['kind'])}:{item['name']}":
            item["state"] == "satisfied"
            for item in dependencies
        }

    def preflight_dependencies(
        self,
        name: str,
        *,
        connected_servers: list[str] | None = None,
        configured_servers: list[str] | None = None,
        registry: Any | None = None,
    ) -> list[dict[str, Any]]:
        """Return the structured dependency state without making environment changes."""
        skill = self._index.get(name)
        if skill is None:
            return []
        return dependency_preflight(
            skill.dependency_contract or skill.dependencies,
            connected_servers=set(connected_servers) if connected_servers is not None else None,
            configured_servers=set(configured_servers) if configured_servers is not None else None,
            registry=registry,
        )


# ---------------------------------------------------------------------------
# Source assembly (E2) — one shared index, stable priorities
# ---------------------------------------------------------------------------

# Higher priority wins duplicate skill names. The ladder mirrors the custom
# command sources (atlas/runtime/commands.py): bundled Atlas lowest, then
# opt-in Hermes, user-level Claude, project-level Claude, plugins on top.
SKILL_SOURCE_PRIORITY = {"atlas": 10, "library": 11, "atlas-user": 12, "hermes": 15, "claude-user": 20, "claude-project": 30, "plugin": 60}


def plugin_skill_sources(
    plugin_skills: Mapping[str, Sequence[Path | str]],
) -> list[SkillSource]:
    """Build one source per plugin-contributed skill directory.

    Names follow ``plugin:<plugin>:<skill-dir>`` so a whole plugin family can
    be swapped atomically via ``SkillManager.replace_skill_sources("plugin:", …)``
    when plugins are installed, disabled, or uninstalled.
    """
    sources: list[SkillSource] = []
    for plugin_id in sorted(plugin_skills):
        for directory in plugin_skills[plugin_id]:
            sources.append(SkillSource(
                f"plugin:{plugin_id}:{Path(directory).name}",
                Path(directory), SKILL_SOURCE_PRIORITY["plugin"], layout="single",
            ))
    return sources


def default_skill_sources(
    workspace: Path | str | None = None,
    atlas_home: Path | str | None = None,
    plugin_skills: Mapping[str, Sequence[Path | str]] | None = None,
    hermes_skills_dir: Path | str | None = None,
    user_home: Path | str | None = None,
) -> list[SkillSource]:
    """Assemble every skill source feeding the single shared Atlas index.

    - ``atlas``: the built-in repository skills dir (priority 10, category
      layout). Atlas' own directory convention is unchanged: user-acquired
      skills install under ``<skills dir>/community/<name>`` and stay inside
      this source. ``atlas_home/<name>`` overrides the root for tests or
      read-only installs.
    - ``hermes``: Hermes bundled skills, only when the caller passes a
      directory (the server gates this behind the
      ``extensions.hermes_skills`` config point).
    - ``claude-user``: ``~/.claude/skills`` (priority 20).
    - ``claude-project``: ``<workspace>/.claude/skills`` (priority 30).
    - ``plugin:*``: caller-provided plugin skill dirs (priority 60).
    """
    atlas_root = Path(atlas_home).expanduser() / "skills" if atlas_home else SKILLS_DIR
    sources = [SkillSource("atlas", atlas_root, SKILL_SOURCE_PRIORITY["atlas"], layout="category")]
    # Test/isolation seam: when ATLAS_SKILLS_HOME is set, BUILTIN skills keep
    # loading from the repository root (read-only) while user-acquired skills
    # (market installs, X2 recordings, X5 candidates) land in the temp root —
    # suites never write the repo. Priority sits just below the builtins so a
    # same-name builtin still wins.
    env_home = os.environ.get("ATLAS_SKILLS_HOME", "").strip()
    if env_home and not atlas_home:
        sources.append(SkillSource(
            "atlas-user", Path(env_home), SKILL_SOURCE_PRIORITY["atlas-user"],
            layout="category",
        ))
    # Skills fetched on demand from the library catalog (data/library/skills/<category>/<name>).
    from atlas.library.runtime import library_skills_dir

    sources.append(SkillSource(
        "library", library_skills_dir(), SKILL_SOURCE_PRIORITY["library"], layout="category",
    ))
    if hermes_skills_dir:
        sources.append(SkillSource(
            "hermes", Path(hermes_skills_dir).expanduser(),
            SKILL_SOURCE_PRIORITY["hermes"], layout="category",
        ))
    home = Path(user_home).expanduser() if user_home else Path.home()
    sources.append(SkillSource(
        "claude-user", home / ".claude" / "skills", SKILL_SOURCE_PRIORITY["claude-user"],
    ))
    if workspace:
        sources.append(SkillSource(
            "claude-project", Path(workspace).expanduser() / ".claude" / "skills",
            SKILL_SOURCE_PRIORITY["claude-project"],
        ))
    sources.extend(plugin_skill_sources(plugin_skills or {}))
    return sources

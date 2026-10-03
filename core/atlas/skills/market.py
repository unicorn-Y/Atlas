"""Skill Market bridge — the single skill-marketplace layer for Atlas.

Hermes' Skills Hub client (``tools/skills_hub*.py`` + ``skills_sync*.py`` from the
local fork checkout) is wired in as the SEARCH / DETAIL / FETCH source layer only.
The Atlas skill Registry (``atlas.skills.registry.SkillRegistry``) stays the ONE
installed-skill state: provenance, install bookkeeping, update state and audit
history all live there. Hermes' own ``lock.json`` is never consulted for market
installs and no second registry, lock file or update state is created.

Install destinations are the Atlas discovery directories (see
``atlas.skills.SkillManager`` / ``default_skill_sources``):

- user scope:    ``<atlas_home>/skills/community/<name>``  (source ``atlas``, priority 10)
- project scope: ``<workspace>/.claude/skills/<name>``     (source ``claude-project``, priority 30)

Progressive loading is untouched: installed skills surface through the ordinary
``SKILL.md`` index scan and only the index enters the prompt.

No security scanning happens here (no ``skills_guard`` / ``skills_ast_audit``);
only origin display and a SKILL.md + file-list preview, per the X4 contract.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import sys
import tempfile
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import structlog

from atlas.skills.acquisition import (
    NAME_RE,
    _parse_manifest,
    _validate_files,
    payload_sha256,
)
from atlas.skills.registry import SkillRegistry

log = structlog.get_logger()

SKILL_PREVIEW_CHARS = 4000
SEARCH_TIMEOUT_SECONDS = 20.0
FETCH_TIMEOUT_SECONDS = 60.0

# Stable discovery priority for duplicate skill names (atlas.skills.__init__).
SKILL_SOURCE_PRIORITY = {
    "atlas": 10, "atlas-user": 12, "hermes": 15, "claude-user": 20,
    "claude-project": 30, "plugin": 60,
}
SCOPE_SOURCES = {"user": "atlas-user", "project": "claude-project"}

# Origin kinds recorded per installed skill in Registry provenance.
# "agent_learned" marks skills applied through the W7 Skill Workshop proposal
# flow (atlas.skills.proposals): agent-authored drafts, approved by a reviewer.
ORIGIN_KINDS = (
    "marketplace", "plugin", "project", "user", "local_recorded", "local_evolved",
    "agent_learned",
)
DEFAULT_ORIGIN_KIND = "marketplace"

# Hermes Skills Hub source adapters exposed by the market (id -> builtin flag).
HUB_SOURCE_IDS = (
    "official", "hermes-index", "skills-sh", "well-known", "url",
    "github", "clawhub", "lobehub", "browse-sh",
)
DEFAULT_HUB_SOURCES = ("official", "skills-sh", "clawhub", "github")
SOURCE_ALIASES = {"skills.sh": "skills-sh", "skills_sh": "skills-sh", "skillssh": "skills-sh"}


class MarketError(RuntimeError):
    """Marketplace failure with a plain-language (Chinese) message for the UI."""

    def __init__(self, message: str, *, code: str = "market_error", details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}


class MarketConflictError(MarketError):
    """Same-name conflict; the local skill wins unless the caller passes overwrite=true."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="name_conflict", details=details)


class MarketUnavailableError(MarketError):
    """Source unreachable / timed out; reported in Chinese so the UI never blocks."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _canonical_name(name: str) -> str:
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise MarketError(
            f"技能名「{name}」不符合 Atlas 规范（只能用小写字母、数字和连字符）。",
            code="invalid_name",
        )
    return name


def _bundle_files(bundle: Any) -> dict[str, str]:
    """Normalize a Hermes SkillBundle (or plain-dict bundle) files mapping to text."""
    raw_files = bundle.get("files") if isinstance(bundle, dict) else getattr(bundle, "files", None)
    files: dict[str, str] = {}
    for rel_path, content in dict(raw_files or {}).items():
        normalized = str(rel_path).replace("\\", "/")
        if isinstance(content, bytes):
            try:
                content = content.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise MarketError(
                    "该技能包含无法按 UTF-8 文本解码的文件，已取消安装。",
                    code="binary_payload",
                ) from exc
        files[normalized] = str(content)
    return files


def _frontmatter(files: dict[str, str]) -> dict[str, Any]:
    """Loose frontmatter read (display only; no Atlas validation side effects)."""
    import yaml

    text = files.get("SKILL.md", "")
    match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", text, re.DOTALL)
    if not match:
        return {}
    try:
        parsed = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


class _DirectoryTapSource:
    """Offline market source backed by a local directory of ``<id>/SKILL.md`` skills.

    Shape-compatible with the Hermes ``SkillSource`` adapters (search / inspect /
    fetch / current_revision) so the bridge treats both identically.
    """

    def __init__(self, name: str, root: Path) -> None:
        self.name = name
        self.root = Path(root)

    def source_id(self) -> str:
        return self.name

    def trust_level_for(self, identifier: str) -> str:  # noqa: ARG002 - Hermes shape
        return "community"

    def _skill_ids(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(
            item.name for item in self.root.iterdir()
            if item.is_dir() and (item / "SKILL.md").is_file()
        )

    def _read(self, identifier: str) -> dict[str, str]:
        target = self.root / identifier
        try:
            resolved = target.resolve(strict=True)
        except OSError:
            return {}
        inside_root = resolved.is_relative_to(self.root.resolve())
        if not inside_root or not (resolved / "SKILL.md").is_file():
            return {}
        files: dict[str, str] = {}
        for item in sorted(resolved.rglob("*")):
            if item.is_file() and not item.is_symlink():
                try:
                    files[item.relative_to(resolved).as_posix()] = item.read_text(encoding="utf-8")
                except (OSError, UnicodeError):
                    return {}
        return files

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        results = []
        for identifier in self._skill_ids():
            files = self._read(identifier)
            fm = _frontmatter(files)
            hay = " ".join([
                identifier, str(fm.get("description", "")),
                " ".join(str(tag) for tag in fm.get("tags", []) or []),
            ]).casefold()
            if not query.strip() or query.strip().casefold() in hay:
                results.append(self.inspect(identifier))
            if len(results) >= limit:
                break
        return [item for item in results if item]

    def inspect(self, identifier: str) -> dict[str, Any] | None:
        files = self._read(identifier)
        if not files:
            return None
        fm = _frontmatter(files)
        return {
            "name": str(fm.get("name") or identifier),
            "description": str(fm.get("description") or ""),
            "source": self.name,
            "identifier": identifier,
            "trust_level": "community",
            "tags": [str(tag) for tag in fm.get("tags", []) or []],
            "extra": {"version": str(fm.get("version") or "0.0.0"),
                      "author": str(fm.get("author") or "")},
        }

    def fetch(self, identifier: str) -> dict[str, Any] | None:
        files = self._read(identifier)
        if "SKILL.md" not in files:
            return None
        fm = _frontmatter(files)
        return {
            "name": str(fm.get("name") or identifier),
            "files": files,
            "source": self.name,
            "identifier": identifier,
            "trust_level": "community",
            "metadata": {"source_url": str(self.root / identifier)},
        }

    def current_revision(self, identifier: str) -> str:  # noqa: ARG002 - Hermes shape
        return ""


class SkillMarket:
    """Search/detail/install/update/uninstall bridge over Hermes hub sources.

    ``registry`` is the single installed-skill state; ``skill_manager`` (optional)
    is the shared discovery index used for same-name conflict decisions and
    post-install rescans. ``adapters`` overrides the Hermes source router (tests).
    """

    def __init__(
        self,
        registry: SkillRegistry,
        *,
        data_dir: Path,
        user_skills_dir: Path,
        project_skills_dir: Path | None = None,
        skill_manager: Any | None = None,
        adapters: list[Any] | None = None,
        hermes_root: Path | str | None = None,
        hub_state_dir: Path | None = None,
    ) -> None:
        self.registry = registry
        self.data_dir = Path(data_dir)
        self.user_skills_dir = Path(user_skills_dir)
        self.project_skills_dir = Path(project_skills_dir) if project_skills_dir else None
        self.skill_manager = skill_manager
        self._injected_adapters = list(adapters) if adapters is not None else None
        self.hermes_root = Path(hermes_root) if hermes_root else None
        self.hub_state_dir = Path(hub_state_dir) if hub_state_dir else (
            self.data_dir / "skills-hub"
        )
        self._sources_path = self.data_dir / "market.json"
        self._hub_forced = False

    # ------------------------------------------------------------------
    # Hermes hub wiring (source layer only)
    # ------------------------------------------------------------------

    def _force_hub_state(self, hub_mod: Any) -> None:
        """Point the Hermes hub's skills/.hub state under the Atlas data dir.

        ``tools.skills_hub`` resolves paths live and honors real module-attribute
        overrides; setting ``SKILLS_DIR`` relocates the whole tree (lock file,
        taps, cache) away from the operator's HERMES_HOME. Market installs never
        write Hermes' lock.json — it exists only so taps persist in one place.
        """
        if self._hub_forced:
            return
        self.hub_state_dir.mkdir(parents=True, exist_ok=True)
        hub_mod.SKILLS_DIR = self.hub_state_dir
        try:
            hub_mod.ensure_hub_dirs()
        except Exception as exc:  # pragma: no cover - best effort
            log.warning("market.hub_dirs_unavailable", error=str(exc))
        self._hub_forced = True

    def _import_hermes(self) -> dict[str, Any]:
        # 1) The pinned fork is usually importable directly (core/.venv installs
        #    hermes-agent editable from the checkout).
        try:
            hub_mod = __import__("tools.skills_hub", fromlist=["skills_hub"])
            search_mod = __import__("tools.skills_hub_search", fromlist=["skills_hub_search"])
            self._force_hub_state(hub_mod)
            return {"hub": hub_mod, "search": search_mod}
        except ImportError:
            pass
        root = self.hermes_root
        if root is None:
            env = os.environ.get("ATLAS_HERMES_ROOT", "").strip()
            if env:
                root = Path(env)
            else:
                here = Path(__file__).resolve()
                for candidate in (here.parents[3] / "hermes-agent", here.parents[3].parent / "hermes-agent"):
                    if candidate.is_dir():
                        root = candidate
                        break
        if root is None or not Path(root).is_dir():
            raise MarketError(
                "本地技能市场客户端（Hermes Skills Hub）不可用，无法访问在线技能源。",
                code="hub_unavailable",
            )
        root_text = str(Path(root))
        if root_text not in sys.path:
            sys.path.insert(0, root_text)
        try:
            hub_mod = __import__("tools.skills_hub", fromlist=["skills_hub"])
            search_mod = __import__("tools.skills_hub_search", fromlist=["skills_hub_search"])
        except Exception as exc:
            raise MarketError(
                "技能市场客户端模块加载失败，在线技能源暂不可用。", code="hub_unavailable",
            ) from exc
        self._force_hub_state(hub_mod)
        return {"hub": hub_mod, "search": search_mod}

    def _hermes_taps(self) -> list[dict[str, Any]]:
        """Custom GitHub repo taps read from the hub taps file (forced location)."""
        try:
            mods = self._import_hermes()
            taps = mods["hub"].TapsManager().list_taps()
            return [dict(tap) for tap in taps if isinstance(tap, dict) and tap.get("repo")]
        except MarketError:
            return []

    def _record_tap(self, repo: str, path: str, add: bool) -> None:
        try:
            mods = self._import_hermes()
        except MarketError:
            return
        taps = mods["hub"].TapsManager()
        if add:
            taps.add(repo, path)
        else:
            taps.remove(repo)

    def _adapters(self, source: str | None = None) -> list[Any]:
        if self._injected_adapters is not None:
            adapters: list[Any] = list(self._injected_adapters)
        else:
            try:
                mods = self._import_hermes()
                adapters = list(mods["search"].create_source_router())
            except MarketError:
                # Hub unavailable (fork missing): online sources degrade to
                # "unavailable" but local directory taps stay searchable.
                adapters = []
        # Local, offline taps first: search merges round-robin and a local hit
        # must never be crowded out by chatty online sources.
        for tap in reversed(self._directory_taps()):
            adapters.insert(0, _DirectoryTapSource(tap["name"], Path(tap["path"])))
        if not adapters:
            raise MarketError(
                "本地技能市场客户端（Hermes Skills Hub）不可用，且没有配置本地技能源。",
                code="hub_unavailable",
            )
        if source and source != "all":
            wanted = SOURCE_ALIASES.get(source, source)
            adapters = [item for item in adapters if item.source_id() == wanted]
            if not adapters:
                raise MarketError(
                    f"没有名为「{source}」的技能源。可用来源见 /api/skills/market/sources。",
                    code="unknown_source",
                )
        return adapters

    def _adapter_for(self, source: str) -> Any:
        return self._adapters(source)[0]

    # ------------------------------------------------------------------
    # Source (tap) management — market.json holds proxy/enabled/directory taps
    # ------------------------------------------------------------------

    def _load_sources(self) -> dict[str, Any]:
        try:
            data = json.loads(self._sources_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if not isinstance(data, dict) or not isinstance(data.get("sources"), list):
            data = {"version": 1, "sources": []}
        return data

    def _save_sources(self, data: dict[str, Any]) -> None:
        self._sources_path.parent.mkdir(parents=True, exist_ok=True)
        self._sources_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )

    def _source_entries(self, kind: str | None = None) -> list[dict[str, Any]]:
        entries = [
            entry for entry in self._load_sources()["sources"]
            if isinstance(entry, dict) and isinstance(entry.get("name"), str)
            and (kind is None or entry.get("kind") == kind)
        ]
        return entries

    def _directory_taps(self) -> list[dict[str, Any]]:
        return [entry for entry in self._source_entries("directory") if entry.get("enabled", True)]

    def _source_config(self, name: str) -> dict[str, Any]:
        for entry in self._source_entries():
            if entry["name"] == name:
                return entry
        return {}

    def list_sources(self) -> dict[str, Any]:
        configured = {entry["name"]: entry for entry in self._source_entries()}
        sources: list[dict[str, Any]] = []
        for source_id in HUB_SOURCE_IDS:
            entry = configured.get(source_id, {})
            sources.append({
                "name": source_id,
                "kind": "hub",
                "builtin": source_id in DEFAULT_HUB_SOURCES,
                "enabled": bool(entry.get("enabled", True)),
                "proxy": entry.get("proxy"),
            })
        for entry in self._source_entries("directory"):
            sources.append({
                "name": entry["name"], "kind": "directory", "builtin": False,
                "enabled": bool(entry.get("enabled", True)), "proxy": entry.get("proxy"),
                "path": entry.get("path"),
            })
        for tap in self._hermes_taps():
            name = f"github:{tap['repo']}"
            entry = configured.get(name, {})
            sources.append({
                "name": name, "kind": "github_tap", "builtin": False,
                "enabled": bool(entry.get("enabled", True)), "proxy": entry.get("proxy"),
                "repo": tap.get("repo"), "path": tap.get("path", "skills/"),
            })
        return {"count": len(sources), "sources": sources}

    def add_source(
        self, name: str, kind: str, *, path: str | None = None, repo: str | None = None,
        tap_path: str = "skills/", proxy: str | None = None,
    ) -> dict[str, Any]:
        name = str(name).strip()
        if not name or len(name) > 80:
            raise MarketError("技能源名称不能为空（且不超过 80 个字符）。", code="invalid_source")
        data = self._load_sources()
        existing = {entry.get("name") for entry in data["sources"]}
        if kind == "directory":
            if not path or not Path(path).is_dir():
                raise MarketError(f"本地技能源目录不存在：{path}", code="invalid_source")
            entry = {"name": name, "kind": "directory", "path": str(Path(path)), "proxy": proxy}
        elif kind == "github":
            if not repo or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
                raise MarketError(
                    "GitHub 技能源需要 owner/repo 形式的仓库地址。", code="invalid_source",
                )
            tap_name = f"github:{repo}"
            if tap_name in existing and name != tap_name:
                raise MarketError(f"技能源「{tap_name}」已存在。", code="source_exists")
            name = tap_name
            self._record_tap(repo, tap_path, add=True)
            entry = {"name": name, "kind": "github_tap", "repo": repo,
                     "path": tap_path, "proxy": proxy}
        else:
            raise MarketError("技能源类型只支持 directory（本地目录）和 github（自定义仓库）。",
                              code="invalid_source")
        if entry["name"] in existing:
            raise MarketError(f"技能源「{entry['name']}」已存在。", code="source_exists")
        entry["enabled"] = True
        data["sources"].append(entry)
        self._save_sources(data)
        return entry

    def remove_source(self, name: str) -> dict[str, Any]:
        if name in DEFAULT_HUB_SOURCES:
            raise MarketError("内置技能源不能删除。", code="builtin_source")
        data = self._load_sources()
        kept = [entry for entry in data["sources"] if entry.get("name") != name]
        if len(kept) == len(data["sources"]):
            if name.startswith("github:"):
                self._record_tap(name[len("github:"):], "skills/", add=False)
                data["sources"].append({"name": name, "kind": "github_tap", "enabled": False})
            else:
                raise MarketError(f"没有名为「{name}」的技能源。", code="unknown_source")
        data["sources"] = kept
        self._save_sources(data)
        return {"removed": name}

    def set_source_enabled(self, name: str, enabled: bool) -> dict[str, Any]:
        if name in DEFAULT_HUB_SOURCES or name in HUB_SOURCE_IDS:
            data = self._load_sources()
            for entry in data["sources"]:
                if entry.get("name") == name:
                    entry["enabled"] = enabled
                    break
            else:
                data["sources"].append({"name": name, "kind": "hub", "enabled": enabled})
            self._save_sources(data)
            return {"name": name, "enabled": enabled}
        data = self._load_sources()
        for entry in data["sources"]:
            if entry.get("name") == name:
                entry["enabled"] = enabled
                self._save_sources(data)
                return {"name": name, "enabled": enabled}
        raise MarketError(f"没有名为「{name}」的技能源。", code="unknown_source")

    @contextlib.contextmanager
    def _proxy_env(self, name: str) -> Iterator[None]:
        """Apply a per-source proxy through the standard environment variables.

        The Hermes adapters build plain ``httpx`` clients (``trust_env`` on), so
        the per-source proxy declared in market.json takes effect for that
        source's calls only. Best-effort by design; failures degrade to errors
        surfaced in Chinese.
        """
        proxy = self._source_config(name).get("proxy")
        if not proxy:
            yield
            return
        proxy_keys = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy",
                      "ALL_PROXY", "all_proxy")
        saved = {key: os.environ.get(key) for key in proxy_keys}
        os.environ["HTTPS_PROXY"] = os.environ["https_proxy"] = proxy
        os.environ["HTTP_PROXY"] = os.environ["http_proxy"] = proxy
        os.environ["ALL_PROXY"] = os.environ["all_proxy"] = proxy
        try:
            yield
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    # ------------------------------------------------------------------
    # Registry-side market bookkeeping (the ONE installed-state store)
    # ------------------------------------------------------------------

    def _market_rows(self, name: str | None = None) -> list[dict[str, Any]]:
        rows = []
        for record in self.registry.list(status="active"):
            provenance = record.get("provenance") or {}
            market = provenance.get("market")
            if not isinstance(market, dict):
                continue
            if name and record["name"] != name:
                continue
            rows.append(record)
        rows.sort(key=lambda item: (item["name"], (item.get("provenance") or {}).get(
            "market", {}).get("installed_at", "")))
        return rows

    def provenance(self, name: str) -> dict[str, Any] | None:
        records = [item for item in self.registry.list() if item["name"] == name]
        if not records:
            return None
        records.sort(key=lambda item: (item["status"] != "active", item.get("updated_at", "")))
        record = records[0]
        return {
            "name": record["name"], "version": record["version"], "status": record["status"],
            "origin_kind": (record.get("provenance") or {}).get("origin_kind"),
            "provenance": record.get("provenance") or {},
        }

    def installed(self) -> list[dict[str, Any]]:
        """Every installed-with-provenance skill (market + registered local kinds)."""
        rows = []
        for record in self.registry.list(status="active"):
            provenance = record.get("provenance") or {}
            if not provenance.get("installed_path"):
                continue
            market = provenance.get("market") or {}
            rows.append({
                "name": record["name"], "version": record["version"],
                "description": record["description"],
                "origin_kind": provenance.get("origin_kind", "marketplace"),
                "source": market.get("source") or provenance.get("provider"),
                "identifier": market.get("identifier") or provenance.get("external_id"),
                "installed_at": provenance.get("installed_at"),
                "installed_path": provenance.get("installed_path"),
                "content_hash": provenance.get("computed_sha256"),
            })
        rows.sort(key=lambda item: item["name"])
        return rows

    def _lifecycle_state(self, record: dict[str, Any], *, state: str) -> dict[str, Any]:
        lifecycle = record.get("lifecycle")
        if not isinstance(lifecycle, dict):
            lifecycle = {"state": state, "trust_state": "unreviewed", "pin_policy": "unpinned",
                         "pinned_version": None, "pinned_hash": None,
                         "content_hash": (record.get("provenance") or {}).get("computed_sha256")}
        lifecycle["state"] = state
        return lifecycle

    def _record_event(
        self, record: dict[str, Any], *, action: str, reason: str, result: str = "success",
        metadata: dict[str, Any] | None = None, status: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        provenance = record.get("provenance") or {}
        event = {
            "event_id": str(uuid.uuid4()), "name": record["name"], "timestamp": _now(),
            "action": action, "skill_version": record["version"], "result": result,
            "actor": "user", "reason": reason, "details": details or {},
            "source": provenance.get("source_url"), "provider": provenance.get("provider"),
        }
        self.registry.record_lifecycle_event(
            event, metadata=metadata, version=record["version"], status=status,
        )

    # ------------------------------------------------------------------
    # Search / detail
    # ------------------------------------------------------------------

    async def search(
        self, query: str = "", source: str | None = None, limit: int = 20,
    ) -> dict[str, Any]:
        import asyncio

        limit = max(1, min(int(limit), 100))
        adapters = self._adapters(source)
        installed_ids = {
            ((item.get("provenance") or {}).get("market") or {}).get("identifier")
            for item in self.registry.list() if isinstance(item.get("provenance"), dict)
        }
        source_names = [adapter.source_id() for adapter in adapters]

        async def run_one(adapter: Any) -> list[dict[str, Any]]:
            def blocking() -> list[dict[str, Any]]:
                with self._proxy_env(adapter.source_id()):
                    return list(adapter.search(query, limit=limit) or [])
            try:
                return await asyncio.wait_for(asyncio.to_thread(blocking), SEARCH_TIMEOUT_SECONDS)
            except (TimeoutError, Exception) as exc:  # noqa: BLE001 - one bad source never blocks the UI
                log.info("market.source_search_failed", source=adapter.source_id(), error=str(exc))
                return []

        batches = await asyncio.gather(*(run_one(adapter) for adapter in adapters))
        # Fair merge: round-robin across sources so one chatty online source
        # cannot crowd out (offline) local taps — local taps are listed first.
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        errors: list[str] = []
        cursors = [0] * len(adapters)
        while len(results) < limit + 40 and any(
            cursors[i] < len(batches[i]) for i in range(len(adapters))
        ):
            for i, adapter in enumerate(adapters):
                if cursors[i] >= len(batches[i]):
                    continue
                data = batches[i][cursors[i]]
                cursors[i] += 1
                if isinstance(data, dict):
                    pass
                else:
                    data = vars(data)
                identifier = str(data.get("identifier") or "")
                if not identifier or identifier in seen:
                    continue
                seen.add(identifier)
                extra = data.get("extra") or {}
                results.append({
                    "source": data.get("source") or adapter.source_id(),
                    "id": identifier,
                    "name": data.get("name") or "",
                    "description": data.get("description") or "",
                    "trust_level": data.get("trust_level") or "community",
                    "tags": list(data.get("tags") or []),
                    "version": extra.get("version"),
                    "author": extra.get("author"),
                    "installed": identifier in installed_ids,
                })
                if len(results) >= limit:
                    break
            if len(results) >= limit:
                break
        for i, adapter in enumerate(adapters):
            if not batches[i]:
                errors.append(adapter.source_id())
        return {
            "query": query, "source": source or "all", "count": len(results[:limit]),
            "results": results[:limit], "sources_queried": source_names,
            "unavailable_sources": errors,
            "status": ("partial" if errors and results
                       else "error" if errors and not results else "ok"),
        }

    async def detail(self, source: str, identifier: str) -> dict[str, Any]:
        import asyncio

        adapter = self._adapter_for(source)

        def blocking() -> tuple[Any, Any]:
            with self._proxy_env(adapter.source_id()):
                meta = adapter.inspect(identifier)
                bundle = adapter.fetch(identifier)
            return meta, bundle

        try:
            meta, bundle = await asyncio.wait_for(
                asyncio.to_thread(blocking), FETCH_TIMEOUT_SECONDS,
            )
        except TimeoutError as exc:
            raise MarketUnavailableError(
                f"连接技能源超时（{source}）。请检查网络或代理设置后重试。",
            ) from exc
        except MarketError:
            raise
        except Exception as exc:
            raise MarketUnavailableError(
                f"技能源暂时连不上（{source}）。请检查网络或代理设置后重试。",
            ) from exc
        if bundle is None:
            raise MarketUnavailableError(
                f"在技能源「{source}」上找不到该技能，或来源暂时无法访问。请稍后重试。",
            )
        files = _bundle_files(bundle)
        fm = _frontmatter(files)
        meta = meta if isinstance(meta, dict) else (vars(meta) if meta else {})
        extra = meta.get("extra") or {}
        bundle_meta = getattr(bundle, "metadata", None) or (
            bundle.get("metadata", {}) if isinstance(bundle, dict) else {}
        )
        identifier_text = str(bundle_meta.get("source_url") or identifier)
        if identifier_text.startswith("http"):
            author = identifier_text.split("github.com/")[-1].split("/")[0]
        else:
            author = ""
        return {
            "source": source,
            "id": identifier,
            "name": str(fm.get("name") or getattr(bundle, "name", "") or meta.get("name") or ""),
            "description": str(fm.get("description") or meta.get("description") or ""),
            "version": str(fm.get("version") or extra.get("version") or "0.0.0"),
            "author": str(fm.get("author") or extra.get("author") or author),
            "trust_level": (getattr(bundle, "trust_level", None)
                            or meta.get("trust_level") or "community"),
            "files": sorted(files),
            "skill_md_preview": files.get("SKILL.md", "")[:SKILL_PREVIEW_CHARS],
            "source_url": identifier_text if identifier_text.startswith("http") else None,
        }

    # ------------------------------------------------------------------
    # Conflict resolution (discovery-priority rules)
    # ------------------------------------------------------------------

    def _destination(self, scope: str, name: str) -> Path:
        if scope == "user":
            return self.user_skills_dir / "community" / name
        if scope == "project":
            if self.project_skills_dir is None:
                raise MarketError(
                    "当前没有配置项目工作区，无法安装到项目作用域。", code="no_workspace")
            return self.project_skills_dir / name
        raise MarketError("安装作用域只支持 user（用户）或 project（项目）。", code="invalid_scope")

    def _conflict(self, name: str, scope: str) -> dict[str, Any] | None:
        """Existing same-name winner under the stable discovery priority rules."""
        dest_priority = SKILL_SOURCE_PRIORITY[SCOPE_SOURCES[scope]]
        winner = self.skill_manager.get_skill(name) if self.skill_manager else None
        registry_rows = [item for item in self.registry.list() if item["name"] == name]
        active = [item for item in registry_rows if item["status"] == "active"]
        dest = self._destination(scope, name)
        if not winner and not active and not dest.exists():
            return None
        return {
            "name": name,
            "local_version": (winner.version if winner else None)
            or (active[0]["version"] if active else None),
            "local_source": (winner.source if winner else None)
            or ((active[0].get("provenance") or {}).get("origin_kind") if active else None),
            "local_priority": winner.source_priority if winner else None,
            "destination_priority": dest_priority,
            "destination": str(dest),
        }

    def _resolve_conflict(self, name: str, scope: str, overwrite: bool) -> Path:
        conflict = self._conflict(name, scope)
        dest = self._destination(scope, name)
        if conflict is None:
            return dest
        details = {key: value for key, value in conflict.items()}
        if not overwrite:
            raise MarketConflictError(
                f"已存在同名技能「{name}」"
                f"（来源：{conflict['local_source'] or '本地'}，"
                f"版本：{conflict['local_version'] or '未知'}）。本地技能优先；"
                "如确定要覆盖安装，请在请求中加上 overwrite=true 重新提交。",
                details=details,
            )
        priority = conflict.get("local_priority")
        if priority is not None and priority > conflict["destination_priority"]:
            raise MarketError(
                f"本地同名技能「{name}」来自更高优先级的来源（{conflict['local_source']}），"
                "市场版本覆盖后也不会生效，已取消安装。请先停用或移除本地技能。",
                code="local_priority_wins", details=details,
            )
        managed_roots = [self.user_skills_dir.resolve()]
        if self.project_skills_dir:
            managed_roots.append(self.project_skills_dir.resolve())
        if winner := (self.skill_manager.get_skill(name) if self.skill_manager else None):
            winner_path = Path(winner.path).resolve().parent
            if not any(winner_path.is_relative_to(root) for root in managed_roots):
                raise MarketError(
                    f"同名技能「{name}」不是通过技能市场安装的（来源：{conflict['local_source']}），"
                    "本地技能优先；请先手动移除该技能再安装。",
                    code="local_skill_wins", details=details,
                )
        # Drop previous market-managed copies (any version) before reinstalling.
        for record in self.registry.list():
            if record["name"] == name:
                self.registry.remove(name, record["version"])
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        self._rescan()
        return dest

    # ------------------------------------------------------------------
    # Install / uninstall / enable / disable
    # ------------------------------------------------------------------

    def _write_payload(self, dest: Path, files: dict[str, str]) -> str:
        _validate_files(files)
        dest_parent = dest.parent
        dest_parent.mkdir(parents=True, exist_ok=True)
        stage_parent = dest_parent / ".atlas-skill-staging"
        stage_parent.mkdir(exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix="market-", dir=stage_parent))
        try:
            for relative, content in files.items():
                target = stage.joinpath(*PurePosixPath(relative).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8", newline="")
            if dest.exists():
                shutil.rmtree(dest)
            stage.replace(dest)
        finally:
            shutil.rmtree(stage, ignore_errors=True)
        digest = payload_sha256(files)
        return digest

    async def install(
        self, source: str, identifier: str, scope: str = "user", overwrite: bool = False,
    ) -> dict[str, Any]:
        import asyncio

        adapter = self._adapter_for(source)

        def blocking() -> Any:
            with self._proxy_env(adapter.source_id()):
                return adapter.fetch(identifier)

        try:
            bundle = await asyncio.wait_for(asyncio.to_thread(blocking), FETCH_TIMEOUT_SECONDS)
        except TimeoutError as exc:
            raise MarketUnavailableError(
                f"下载技能超时（{source}）。请检查网络或代理设置后重试。") from exc
        except MarketError:
            raise
        except Exception as exc:
            raise MarketUnavailableError(
                f"技能下载失败（{source}）。请检查网络或代理设置后重试。") from exc
        if bundle is None:
            raise MarketUnavailableError(
                f"在技能源「{source}」上找不到该技能，或来源暂时无法访问。请稍后重试。")
        return self._install_bundle(bundle, source=source, scope=scope, overwrite=overwrite)

    def _install_bundle(
        self, bundle: Any, *, source: str, scope: str, overwrite: bool,
    ) -> dict[str, Any]:
        files = _bundle_files(bundle)
        name = _canonical_name(str(getattr(bundle, "name", "") or
                                   (bundle.get("name") if isinstance(bundle, dict) else "")))
        dest = self._resolve_conflict(name, scope, overwrite)
        try:
            manifest, dependencies = _parse_manifest(files["SKILL.md"], name)
        except ValueError as exc:
            raise MarketError(
                f"技能「{name}」的 SKILL.md 不符合 Atlas 规范：{exc}", code="invalid_manifest",
            ) from exc
        version = manifest["version"]
        digest = self._write_payload(dest, files)
        fm = _frontmatter(files)
        market_provenance = {
            "source": source,
            "identifier": str(getattr(bundle, "identifier", "") or
                              (bundle.get("identifier") if isinstance(bundle, dict) else "")),
            "upstream_version": version,
            "upstream_revision": str((getattr(bundle, "metadata", None) or {}).get(
                "source_revision", "") or ""),
            "content_hash": digest,
            "scope": scope,
            "installed_at": _now(),
        }
        metadata = {
            "name": name, "version": version, "description": manifest["description"],
            "capabilities": [], "tools": [],
            "requirements": dependencies,
            "examples": [], "aliases": [], "tags": [str(tag) for tag in fm.get("tags", []) or []],
            "keywords": [str(tag) for tag in fm.get("tags", []) or []],
            "category": "community" if scope == "user" else "project",
            "use_cases": [],
            "provenance": {
                "provider": source,
                "external_id": market_provenance["identifier"],
                "source_url": (getattr(bundle, "metadata", None) or {}).get("source_url"),
                "origin_kind": DEFAULT_ORIGIN_KIND,
                "installed_at": market_provenance["installed_at"],
                "installed_path": str(dest),
                "computed_sha256": digest,
                "market": market_provenance,
            },
        }
        self.registry.register(metadata, source=f"market:{source}")
        record = self.registry.get(name, version)
        assert record is not None
        if (record.get("provenance") or {}).get("market", {}).get("identifier") != \
                market_provenance["identifier"]:
            # A same-name+version row survived conflict resolution with foreign
            # provenance; register() preserves prior provenance, so replace it.
            self.registry.remove(name, version)
            self.registry.register(metadata, source=f"market:{source}")
            record = self.registry.get(name, version)
            assert record is not None
        record = {**record, "lifecycle": self._lifecycle_state(record, state="active")}
        self._record_event(
            record, action="install", reason="marketplace install via Atlas Skill Market",
            metadata=record,
            details={"scope": scope, "path": str(dest), "source": source,
                     "identifier": market_provenance["identifier"], "hash": digest},
        )
        self._rescan()
        return {
            "status": "installed", "name": name, "version": version, "scope": scope,
            "path": str(dest), "hash": digest, "source": source,
            "identifier": market_provenance["identifier"],
            "files": sorted(files),
        }

    def _managed_install_paths(self) -> list[Path]:
        roots = [self.user_skills_dir.resolve()]
        if self.project_skills_dir:
            roots.append(self.project_skills_dir.resolve())
        return roots

    def uninstall(self, name: str) -> dict[str, Any]:
        name = _canonical_name(name)
        rows = self._market_rows(name)
        if not rows:
            raise MarketError(
                f"技能「{name}」不是通过技能市场安装的，或已卸载。", code="not_market_installed")
        removed_paths: list[str] = []
        for record in rows:
            installed_path = (record.get("provenance") or {}).get("installed_path") or ""
            if not installed_path:
                raise MarketError(
                    f"技能「{name}」的安装记录缺少路径，无法卸载。", code="invalid_install_path")
            target = Path(installed_path)
            try:
                resolved = target.resolve(strict=True)
            except OSError:
                resolved = target.resolve(strict=False)
            managed = self._managed_install_paths()
            if (not target.is_dir() or target.is_symlink()
                    or not any(resolved.is_relative_to(root) for root in managed)
                    or resolved in set(managed)):
                raise MarketError(
                    f"技能「{name}」的安装目录无效，已拒绝卸载。", code="invalid_install_path")
            shutil.rmtree(target, ignore_errors=True)
            removed_paths.append(str(target))
            updated = {
                **record,
                "lifecycle": self._lifecycle_state(record, state="removed"),
                "provenance": {
                    **(record.get("provenance") or {}),
                    "market": {**(record.get("provenance") or {}).get("market", {}),
                               "removed_at": _now()},
                },
            }
            self._record_event(
                updated, action="remove", reason="marketplace uninstall via Atlas Skill Market",
                metadata=updated, status="disabled",
                details={"removed_paths": removed_paths},
            )
        self._rescan()
        return {"status": "removed", "name": name, "paths": removed_paths}

    def _toggle(self, name: str, *, enable: bool) -> dict[str, Any]:
        name = _canonical_name(name)
        desired = "active" if enable else "disabled"
        rows = [item for item in self.registry.list() if item["name"] == name]
        if any(item["status"] == desired for item in rows):
            return {"name": name, "status": desired, "changed": False}
        candidates = [item for item in rows if item["status"] != desired]
        if not candidates:
            raise MarketError(f"没有找到技能「{name}」的安装记录。", code="not_installed")
        candidates.sort(key=lambda item: item.get("updated_at", ""))
        record = candidates[-1]
        current_state = (record.get("lifecycle") or {}).get("state")
        if enable and current_state in {"quarantined", "removed"}:
            raise MarketError(
                f"技能「{name}」当前状态（{current_state}）不允许直接启用。",
                code="blocked_state")
        updated = {**record, "lifecycle": self._lifecycle_state(record, state=desired)}
        self._record_event(
            updated, action="enable" if enable else "disable",
            reason="marketplace enable/disable via Atlas Skill Market",
            metadata=updated, status=desired,
        )
        refreshed = self.registry.get(name, record["version"])
        assert refreshed is not None
        return {"name": name, "status": refreshed["status"], "changed": True}

    def enable(self, name: str) -> dict[str, Any]:
        return self._toggle(name, enable=True)

    def disable(self, name: str) -> dict[str, Any]:
        return self._toggle(name, enable=False)

    # ------------------------------------------------------------------
    # Updates
    # ------------------------------------------------------------------

    async def check_updates(self, name: str | None = None) -> list[dict[str, Any]]:

        rows = self._market_rows(name)
        results: list[dict[str, Any]] = []

        async def check_row(record: dict[str, Any]) -> dict[str, Any]:
            market = (record.get("provenance") or {}).get("market") or {}
            row = {
                "name": record["name"], "version": record["version"],
                "source": market.get("source"), "identifier": market.get("identifier"),
            }
            try:
                bundle = await self._fetch_from_market(market)
            except MarketError as exc:
                return {**row, "status": "unavailable", "message": exc.message}
            if bundle is None:
                return {**row, "status": "unavailable", "message": "技能源暂时无法访问，稍后再试。"}
            try:
                files = _bundle_files(bundle)
            except MarketError as exc:
                return {**row, "status": "unavailable", "message": exc.message}
            latest_hash = payload_sha256(files)
            current_hash = market.get("content_hash") or (
                record.get("provenance") or {}).get("computed_sha256")
            status = "up_to_date" if latest_hash == current_hash else "update_available"
            return {
                **row, "status": status, "current_hash": current_hash, "latest_hash": latest_hash,
                "latest_version": _frontmatter(files).get("version") or record["version"],
            }

        for record in rows:
            results.append(await check_row(record))
        return results

    async def _fetch_from_market(self, market: dict[str, Any]) -> Any:
        import asyncio

        source = str(market.get("source") or "")
        identifier = str(market.get("identifier") or "")
        if not source or not identifier:
            raise MarketError("安装记录缺少来源信息，无法检查更新。", code="missing_provenance")
        adapter = self._adapter_for(source)

        def blocking() -> Any:
            with self._proxy_env(adapter.source_id()):
                return adapter.fetch(identifier)

        try:
            return await asyncio.wait_for(asyncio.to_thread(blocking), FETCH_TIMEOUT_SECONDS)
        except TimeoutError as exc:
            raise MarketUnavailableError(
                f"连接技能源超时（{source}）。请检查网络或代理设置后重试。") from exc
        except MarketError:
            raise
        except Exception as exc:
            raise MarketUnavailableError(
                f"技能源暂时连不上（{source}）。请检查网络或代理设置后重试。") from exc

    async def update(self, name: str) -> dict[str, Any]:
        name = _canonical_name(name)
        rows = self._market_rows(name)
        if not rows:
            raise MarketError(
                f"没有找到技能「{name}」的市场安装记录，无法更新。", code="not_market_installed")
        record = rows[-1]
        market = (record.get("provenance") or {}).get("market") or {}
        bundle = await self._fetch_from_market(market)
        if bundle is None:
            raise MarketUnavailableError(
                f"技能源暂时无法访问（{market.get('source')}），更新未执行。请稍后重试。")
        files = _bundle_files(bundle)
        latest_hash = payload_sha256(files)
        if latest_hash == market.get("content_hash"):
            return {"status": "up_to_date", "name": name, "version": record["version"]}
        try:
            manifest, dependencies = _parse_manifest(files["SKILL.md"], name)
        except ValueError as exc:
            raise MarketError(
                f"技能「{name}」的上游版本不符合 Atlas 规范：{exc}",
                code="invalid_manifest") from exc
        new_version = manifest["version"]
        old_version = record["version"]
        scope = market.get("scope", "user")
        dest = self._destination(scope, name)
        self._write_payload(dest, files)
        provenance = {
            **(record.get("provenance") or {}),
            "provider": market.get("source") or record.get("provenance", {}).get("provider"),
            "origin_kind": DEFAULT_ORIGIN_KIND,
            "installed_at": _now(),
            "installed_path": str(dest),
            "computed_sha256": latest_hash,
            "market": {**market, "upstream_version": new_version,
                       "content_hash": latest_hash, "installed_at": _now()},
        }
        if new_version != old_version:
            self.registry.remove(name, old_version)
            metadata = {
                "name": name, "version": new_version, "description": manifest["description"],
                "requirements": dependencies,
                "provenance": provenance,
            }
            self.registry.register(metadata, source=f"market:{market.get('source')}")
            record = self.registry.get(name, new_version)
            assert record is not None
            record = {**record, "lifecycle": self._lifecycle_state(record, state="active")}
            self._record_event(
                record, action="update", reason="marketplace update via Atlas Skill Market",
                metadata=record,
                details={"hash": latest_hash, "previous_hash": market.get("content_hash"),
                         "previous_version": old_version},
            )
        else:
            updated = {
                **record, "description": manifest["description"], "provenance": provenance,
                "lifecycle": self._lifecycle_state(record, state="active"),
            }
            self._record_event(
                updated, action="update", reason="marketplace update via Atlas Skill Market",
                metadata=updated,
                details={"hash": latest_hash, "previous_hash": market.get("content_hash")},
            )
            record = updated
        self._rescan()
        return {
            "status": "updated", "name": name, "previous_version": old_version,
            "version": new_version, "hash": latest_hash,
            "changed_files": sorted(files),
        }

    async def update_all(self) -> dict[str, Any]:
        names = sorted({record["name"] for record in self._market_rows()})
        results = []
        for name in names:
            try:
                results.append(await self.update(name))
            except MarketError as exc:
                results.append({"name": name, "status": "failed", "message": exc.message})
        return {
            "checked": len(names),
            "updated": sum(item["status"] == "updated" for item in results),
            "up_to_date": sum(item["status"] == "up_to_date" for item in results),
            "failed": sum(item["status"] == "failed" for item in results),
            "results": results,
        }

    # ------------------------------------------------------------------
    # Local-origin registration (X2 recordings / X5 evolved skills)
    # ------------------------------------------------------------------

    def register_local(
        self, name: str, *, path: Path | str, origin_kind: str,
        source: str = "local", reason: str = "local origin registration",
    ) -> dict[str, Any]:
        """Register an already-written local skill bundle into the ONE registry.

        X2 (recorded skills) and X5 (evolved skills) write their bundle
        themselves and call this afterwards; no files are copied here.
        """
        name = _canonical_name(name)
        if origin_kind not in ORIGIN_KINDS:
            raise MarketError(
                f"origin_kind 只支持 {'、'.join(ORIGIN_KINDS)}。", code="invalid_origin_kind")
        skill_dir = Path(path)
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            raise MarketError(f"技能目录缺少 SKILL.md：{skill_dir}", code="invalid_local_skill")
        files = {
            item.relative_to(skill_dir).as_posix(): item.read_text(encoding="utf-8")
            for item in sorted(skill_dir.rglob("*"))
            if item.is_file() and not item.is_symlink()
        }
        try:
            manifest, _dependencies = _parse_manifest(files["SKILL.md"], name)
        except ValueError as exc:
            raise MarketError(
                f"技能「{name}」的 SKILL.md 不符合 Atlas 规范：{exc}", code="invalid_manifest",
            ) from exc
        digest = payload_sha256(files)
        installed_at = _now()
        metadata = {
            "name": name, "version": manifest["version"],
            "description": manifest["description"],
            "requirements": _dependencies,
            "provenance": {
                "provider": source,
                "external_id": f"{origin_kind}:{name}",
                "origin_kind": origin_kind,
                "installed_at": installed_at,
                "installed_path": str(skill_dir.resolve()),
                "computed_sha256": digest,
            },
        }
        self.registry.register(metadata, source=f"{source}:{origin_kind}")
        record = self.registry.get(name, manifest["version"])
        assert record is not None
        record = {**record, "lifecycle": self._lifecycle_state(record, state="active")}
        self._record_event(
            record, action="install", reason=reason, metadata=record,
            details={"origin_kind": origin_kind, "path": str(skill_dir), "hash": digest},
        )
        return {
            "status": "registered", "name": name, "version": manifest["version"],
            "origin_kind": origin_kind, "path": str(skill_dir), "hash": digest,
        }

    # ------------------------------------------------------------------

    def _rescan(self) -> None:
        if self.skill_manager is None:
            return
        try:
            self.skill_manager.scan_skills_sync()
        except Exception as exc:  # pragma: no cover - index refresh is best-effort
            log.warning("market.rescan_failed", error=str(exc))


def default_market(
    registry: SkillRegistry, *, skill_manager: Any | None = None,
) -> SkillMarket:
    """Build the market over Atlas' canonical discovery directories.

    The user-scope root is the live ``atlas`` discovery source root when a
    shared index is supplied, so anything the market installs surfaces in the
    ordinary ``GET /api/skills`` index immediately.
    """
    from atlas.config import get_config, load_user_settings
    from atlas.skills import SKILLS_DIR

    cfg = get_config()
    atlas_root = None
    if skill_manager is not None:
        sources = getattr(skill_manager, "_sources", {})
        # User-scope installs land in the writable atlas-user source when the
        # isolation seam split it from the read-only builtin "atlas" root.
        writable = sources.get("atlas-user") or sources.get("atlas")
        atlas_root = Path(writable.root) if writable is not None else None
    # Canonical atlas source root (same symbol default_skill_sources uses).
    skills_dir = atlas_root or SKILLS_DIR
    workspace_value = load_user_settings().get("default_workspace")
    project_dir = (
        Path(str(workspace_value)).expanduser() / ".claude" / "skills"
        if workspace_value else None
    )
    return SkillMarket(
        registry,
        data_dir=cfg.db_path.parent,
        user_skills_dir=atlas_root or skills_dir,
        project_skills_dir=project_dir,
        skill_manager=skill_manager,
    )

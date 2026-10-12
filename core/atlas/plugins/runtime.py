"""Claude Code and Hermes plugin sources in Atlas' shared discovery/runtime."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any

from atlas.agent.enrichment import HOOK_POINTS

MANIFEST_NAMES = (".claude-plugin/plugin.json", "plugin.json")
MARKETPLACE_NAMES = (".claude-plugin/marketplace.json", "marketplace.json")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _manifest(root: Path) -> tuple[Path | None, dict[str, Any]]:
    for name in MANIFEST_NAMES:
        path = root / name
        if path.is_file():
            return path, _read_json(path)
    return None, {}


def _path_values(value: Any) -> list[str | Path]:
    if isinstance(value, (str, Path)):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, (str, Path))]
    return []


def _plugin_name(value: Any) -> str:
    name = str(value or "")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        raise ValueError("plugin name must be kebab-case")
    return name


def _inside(root: Path, value: str | Path) -> Path:
    path = Path(value)
    path = path if path.is_absolute() else root / path
    resolved = path.resolve()
    resolved.relative_to(root.resolve())
    return resolved


def _expand_root(value: Any, root: Path) -> Any:
    if isinstance(value, str):
        return value.replace("${CLAUDE_PLUGIN_ROOT}", str(root))
    if isinstance(value, list):
        return [_expand_root(item, root) for item in value]
    if isinstance(value, dict):
        return {key: _expand_root(item, root) for key, item in value.items()}
    return value


class PluginRuntime:
    """Manage plugin sources and expose their components to Atlas registries."""

    def __init__(self, plugin_dirs: list[Path], state_path: Path) -> None:
        self._dirs = [Path(d) for d in plugin_dirs]
        # 专家模式装上的插件：每个是一个插件根目录，跟在普通插件后面。
        self.extra_roots: list[Path] = []
        self._state_path = Path(state_path)
        self._state: dict[str, Any] = {}
        self._enabled: dict[str, bool] = {}
        self._loaded: dict[str, dict[str, Any]] = {}
        self._load_state()

    def _load_state(self) -> None:
        self._state = _read_json(self._state_path)
        enabled = self._state.get("enabled")
        self._enabled = enabled if isinstance(enabled, dict) else {}
        self._state["enabled"] = self._enabled
        if not isinstance(self._state.get("marketplaces"), dict):
            self._state["marketplaces"] = {}
        if not isinstance(self._state.get("sources"), dict):
            self._state["sources"] = {}

    def _save_state(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state["enabled"] = self._enabled
        self._state_path.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8",
        )

    @staticmethod
    def _plugin_root(path: Path) -> Path | None:
        if _manifest(path)[0] is not None:
            return path
        if any((path / item).exists() for item in ("skills", "commands", "agents", "hooks", ".mcp.json")):
            return path
        if path.is_dir():
            for child in sorted(path.iterdir()):
                if child.is_dir() and PluginRuntime._plugin_root(child) == child:
                    return child
        return None

    def _all_plugin_roots(self) -> list[Path]:
        roots: list[Path] = []
        for base in self._dirs:
            if not base.is_dir():
                continue
            for child in sorted(base.iterdir()):
                if child.name.startswith("."):
                    continue
                root = self._plugin_root(child)
                if root is not None and root not in roots:
                    roots.append(root)
        for extra in self.extra_roots:
            root = self._plugin_root(extra) if extra.is_dir() else None
            if root is not None and root not in roots:
                roots.append(root)
        return roots

    def discover(self) -> list[dict[str, Any]]:
        """List available plugin bundles, preferring user-installed copies."""
        plugins: dict[str, dict[str, Any]] = {}
        sources = self._state.get("sources", {})
        for root in self._all_plugin_roots():
            manifest_path, base_manifest = _manifest(root)
            # Source records are keyed by plugin name; marketplace/git installs
            # use the installed directory name, local installs the manifest name.
            source = sources.get(root.name) or sources.get(str(base_manifest.get("name") or root.name)) or {}
            manifest = self._effective_manifest(root, base_manifest, source)
            try:
                name = _plugin_name(source.get("plugin_name") or manifest.get("name") or root.name)
            except ValueError:
                continue  # unaddressable directory; never fail the whole listing
            plugins[name] = {
                "name": name,
                "display_name": str(manifest.get("displayName") or name),
                "version": str(manifest.get("version", "0.0.0")),
                "description": str(manifest.get("description", "")),
                "author": manifest.get("author", {}),
                "homepage": str(manifest.get("homepage", "")),
                "repository": str(manifest.get("repository", "")),
                "license": str(manifest.get("license", "")),
                "keywords": manifest.get("keywords", []),
                "metadata": manifest.get("metadata", {}),
                "manifest": str(manifest_path) if manifest_path else None,
                "path": str(root),
                "source": source.get("source", "local") if isinstance(source, dict) else "local",
                "marketplace": source.get("marketplace") if isinstance(source, dict) else None,
                "skills": [path.name for path in self._component_paths(root, manifest, "skills", root / "skills", directories=True)],
                "commands": [item["name"] for item in self._commands(root, manifest)],
                "agents": [path.stem for path in self._component_paths(root, manifest, "agents", root / "agents", files=True)],
                "hooks": len(self._claude_hook_specs(root, manifest)) + len([
                    spec for spec in self._legacy_hook_specs(root)
                    if str(spec.get("point", "")) in HOOK_POINTS
                ]),
                "mcp_servers": sorted(self._mcp_configs(root, manifest)),
                "enabled": self._enabled.get(name, manifest.get("defaultEnabled", True)) is not False,
                "loaded": name in self._loaded,
                "update_available": bool(source.get("update_available", False)) if isinstance(source, dict) else False,
            }
        return list(plugins.values())

    @staticmethod
    def _component_paths(
        root: Path, manifest: dict[str, Any], field: str, default: Path,
        *, directories: bool = False, files: bool = False,
    ) -> list[Path]:
        declared = manifest.get(field)
        values = ([default, *_path_values(declared)] if field == "skills" and declared is not None
                  else _path_values(declared) if declared is not None else [default])
        paths: list[Path] = []
        for value in values:
            path = _inside(root, value)
            if directories and path.is_dir():
                if (path / "SKILL.md").is_file():
                    paths.append(path)
                else:
                    paths.extend(sorted(item for item in path.iterdir() if item.is_dir() and (item / "SKILL.md").is_file()))
            elif files:
                if path.is_file() and path.suffix.lower() == ".md":
                    paths.append(path)
                elif path.is_dir():
                    paths.extend(sorted(item for item in path.glob("*.md") if item.is_file()))
        unique: list[Path] = []
        for path in paths:  # a declared skills dir equal to the default must not register twice
            if path not in unique:
                unique.append(path)
        return unique

    @staticmethod
    def _commands(root: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
        declared = manifest.get("commands")
        if declared is None:
            paths = sorted((root / "commands").glob("*.md")) if (root / "commands").is_dir() else []
            return [{"name": path.stem, "path": str(path), "content": None, "metadata": {}} for path in paths]
        result: list[dict[str, Any]] = []
        for value in _path_values(declared):
            path = _inside(root, value)
            paths = [path] if path.is_file() else sorted(path.glob("*.md")) if path.is_dir() else []
            result.extend({"name": item.stem, "path": str(item), "content": None, "metadata": {}} for item in paths if item.is_file() and item.suffix.lower() == ".md")
        if isinstance(declared, dict):
            for name, value in declared.items():
                if not isinstance(value, dict):
                    continue
                content = value.get("content")
                source = value.get("source")
                path = _inside(root, source) if isinstance(source, str) else None
                result.append({"name": str(name), "path": str(path) if path else None, "content": content if isinstance(content, str) else None, "metadata": value})
        return result

    @staticmethod
    def _legacy_hook_specs(root: Path) -> list[dict[str, Any]]:
        data = _read_json(root / "hooks" / "hooks.json")
        hooks = data.get("hooks")
        return [item for item in hooks if isinstance(item, dict)] if isinstance(hooks, list) else []

    @staticmethod
    def _claude_hook_specs(root: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
        from atlas.runtime.hooks import parse_claude_hooks

        configs: list[dict[str, Any]] = []
        seen_paths: set[Path] = set()
        hook_file = root / "hooks" / "hooks.json"
        if hook_file.is_file():
            seen_paths.add(hook_file.resolve())
            configs.append(_read_json(hook_file))
        declared = manifest.get("hooks")
        values = declared if isinstance(declared, list) else [declared]
        for value in values:
            if isinstance(value, dict):
                configs.append(value)
            elif isinstance(value, str):
                path = _inside(root, value)
                if path.is_file() and path.resolve() not in seen_paths:
                    seen_paths.add(path.resolve())
                    configs.append(_read_json(path))
        return [hook for config in configs for hook in parse_claude_hooks(config, source=str(root))]

    @staticmethod
    def _mcp_configs(root: Path, manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
        result = _read_json(root / ".mcp.json").get("mcpServers", {})
        result = dict(result) if isinstance(result, dict) else {}
        declared = manifest.get("mcpServers")
        values = declared if isinstance(declared, list) else [declared]
        for value in values:
            if isinstance(value, dict):
                result.update(value.get("mcpServers", value))
            elif isinstance(value, str):
                path = _inside(root, value)
                servers = _read_json(path).get("mcpServers", {}) if path.is_file() else {}
                if isinstance(servers, dict):
                    result.update(servers)
        return {
            str(name): _expand_root(spec, root)
            for name, spec in result.items() if isinstance(spec, dict)
        }

    @staticmethod
    def _effective_manifest(root: Path, manifest: dict[str, Any], source: Any) -> dict[str, Any]:
        result = dict(manifest)
        if not isinstance(source, dict) or not isinstance(source.get("entry"), dict):
            return result
        entry = source["entry"]
        for field in ("displayName", "description", "author", "homepage", "repository", "license", "keywords"):
            if field in entry:
                result[field] = entry[field]
        if entry.get("strict") is False:
            for field in ("skills", "commands", "agents", "hooks", "mcpServers"):
                if field in entry:
                    result[field] = entry[field]
        result["name"] = source.get("plugin_name", result.get("name") or root.name)
        return result

    def enabled_contributions(self) -> list[dict[str, Any]]:
        """Return source paths and parsed hooks for the shared Atlas registries."""
        output: list[dict[str, Any]] = []
        for plugin in self.discover():
            if not plugin["enabled"]:
                continue
            root = Path(plugin["path"])
            _, base_manifest = _manifest(root)
            source = self._state.get("sources", {}).get(plugin["name"], {})
            manifest = self._effective_manifest(root, base_manifest, source)
            hooks = self._claude_hook_specs(root, manifest)
            for hook in hooks:
                hook["plugin_root"] = str(root)
            command_sources = []
            declared_commands = manifest.get("commands")
            command_values = _path_values(declared_commands) if declared_commands is not None else ["commands"]
            if isinstance(declared_commands, dict):
                command_values = ["commands"]
            for value in command_values:
                path = Path(value)
                path = path if path.is_absolute() else root / path
                if path.is_dir():
                    command_sources.append(str(path))
                elif path.is_file() and path.suffix.lower() == ".md":
                    command_sources.append(str(path.parent))
            output.append({
                "id": plugin["name"], "name": plugin["name"], "root": str(root),
                "version": plugin["version"], "description": plugin["description"],
                "skills": [str(path) for path in self._component_paths(root, manifest, "skills", root / "skills", directories=True)],
                "commands": self._commands(root, manifest),
                "command_sources": sorted(set(command_sources)),
                "agents": [str(path) for path in self._component_paths(root, manifest, "agents", root / "agents", files=True)],
                "hooks": hooks,
                "mcp_servers": self._mcp_configs(root, manifest),
            })
        return output

    def _installed_base(self) -> Path:
        return self._dirs[-1] if self._dirs else Path("data") / "plugins"

    @staticmethod
    def _rmtree(path: Path) -> None:
        """rmtree that clears git's read-only object bits (required on Windows)."""
        def _force(func, item, _exc):
            os.chmod(item, stat.S_IWRITE)
            func(item)

        shutil.rmtree(path, onexc=_force)

    @staticmethod
    def _copy_replace(source: Path, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        incoming = target.with_name(target.name + ".incoming")
        if incoming.exists():
            PluginRuntime._rmtree(incoming)
        # Installed copies are deploy snapshots; history stays in the checkout.
        shutil.copytree(source, incoming, ignore=shutil.ignore_patterns(".git"))
        if target.exists():
            PluginRuntime._rmtree(target)
        incoming.replace(target)

    @staticmethod
    def _git_clone(url: str, target: Path, ref: str | None = None) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        args = ["git", "clone", "--depth", "1"]
        if ref:
            args.extend(["--branch", ref])
        args.extend([url, str(target)])
        subprocess.run(args, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")

    def install_local(self, source: str | Path) -> dict[str, Any]:
        source_root = self._plugin_root(Path(source))
        if source_root is None:
            raise ValueError(f"no plugin.json or plugin components found under {source}")
        _, manifest = _manifest(source_root)
        name = str(manifest.get("name") or source_root.name)
        # Installed layout convention: keep the source directory name; the
        # manifest name is only the plugin identity in state/discovery.
        target = self._installed_base() / source_root.name
        self._copy_replace(source_root, target)
        self._state.setdefault("sources", {})[name] = {"source": "local", "path": str(Path(source_root).resolve())}
        self._save_state()
        return {"name": name, "path": str(target)}

    def add_marketplace(self, source: str | Path, *, name: str | None = None, ref: str | None = None) -> dict[str, Any]:
        source_path = Path(source).expanduser()
        slug = name or source_path.name.removesuffix(".git") or "marketplace"
        target = self._installed_base() / ".marketplaces" / slug
        if source_path.exists():
            root = self._marketplace_root(source_path)
            if root is None:
                raise ValueError(f"no marketplace.json found under {source}")
            record = {"type": "local", "source": str(root.resolve()), "path": str(root.resolve())}
        else:
            if target.exists():
                PluginRuntime._rmtree(target)
            self._git_clone(str(source), target, ref)
            root = self._marketplace_root(target)
            if root is None:
                raise ValueError(f"no marketplace.json found in {source}")
            record = {"type": "git", "source": str(source), "path": str(root.resolve()), "ref": ref}
        catalog = _read_json(root / next(item for item in MARKETPLACE_NAMES if (root / item).is_file()))
        market_name = str(name or catalog.get("name") or slug)
        self._state.setdefault("marketplaces", {})[market_name] = record | {"name": market_name}
        self._save_state()
        return {"name": market_name, "path": str(root), "plugins": len(catalog.get("plugins", []))}

    def list_marketplaces(self) -> list[dict[str, Any]]:
        return [dict(record) for _name, record in sorted(self._state.get("marketplaces", {}).items())]

    @staticmethod
    def _marketplace_root(path: Path) -> Path | None:
        if any((path / item).is_file() for item in MARKETPLACE_NAMES):
            return path
        if path.is_dir():
            for child in sorted(path.iterdir()):
                if child.is_dir() and any((child / item).is_file() for item in MARKETPLACE_NAMES):
                    return child
        return None

    def list_marketplace_plugins(self, marketplace: str) -> list[dict[str, Any]]:
        record = self._state.get("marketplaces", {}).get(marketplace)
        if not isinstance(record, dict):
            raise KeyError(marketplace)
        root = Path(record["path"])
        manifest_file = next((root / item for item in MARKETPLACE_NAMES if (root / item).is_file()), None)
        catalog = _read_json(manifest_file) if manifest_file else {}
        entries = catalog.get("plugins", [])
        return [dict(item, marketplace=marketplace) for item in entries if isinstance(item, dict)] if isinstance(entries, list) else []

    @staticmethod
    def _github_url(repo: str) -> str:
        return f"https://github.com/{repo.removesuffix('.git')}.git"

    def _resolve_plugin_source(self, record: dict[str, Any], entry: dict[str, Any]) -> tuple[Path | None, str | None, str | None, str | None]:
        market_root = Path(record["path"])
        source = entry.get("source")
        if isinstance(source, str):
            path = market_root / source
            return (path if path.is_dir() else None, None, None, str(path))
        if not isinstance(source, dict):
            raise ValueError("unsupported plugin source")
        kind = source.get("source")
        ref = source.get("ref")
        if kind == "github":
            url = self._github_url(str(source["repo"]))
            return None, url, str(ref) if ref else None, None
        if kind == "url":
            return None, str(source["url"]), str(ref) if ref else None, None
        if kind == "git-subdir":
            return None, str(source["url"]), str(ref) if ref else None, str(source["path"])
        raise ValueError(f"unsupported plugin source type: {kind}")

    def install_marketplace_plugin(self, marketplace: str, plugin_name: str) -> dict[str, Any]:
        record = self._state.get("marketplaces", {}).get(marketplace)
        if not isinstance(record, dict):
            raise KeyError(marketplace)
        entry = next((item for item in self.list_marketplace_plugins(marketplace) if item.get("name") == plugin_name), None)
        if entry is None:
            raise KeyError(plugin_name)
        local, url, ref, subdir = self._resolve_plugin_source(record, entry)
        target = self._installed_base() / plugin_name
        source_record: dict[str, Any] = {"source": "marketplace", "marketplace": marketplace, "plugin_source": entry.get("source")}
        if local is not None:
            if self._plugin_root(local) is None:
                raise ValueError(f"plugin path not found: {local}")
            self._copy_replace(self._plugin_root(local), target)
        else:
            clone = self._installed_base() / ".sources" / plugin_name
            if clone.exists():
                PluginRuntime._rmtree(clone)
            self._git_clone(str(url), clone, ref)
            plugin_root = clone / subdir if subdir else clone
            plugin_root = self._plugin_root(plugin_root)
            if plugin_root is None:
                raise ValueError(f"plugin manifest/components not found in {url}")
            self._copy_replace(plugin_root, target)
            source_record["checkout"] = str(clone)
            source_record["subdir"] = subdir
            source_record["ref"] = ref
        source_record.update({"plugin_name": plugin_name, "entry": entry})
        self._state.setdefault("sources", {})[plugin_name] = source_record
        self._enabled.setdefault(plugin_name, entry.get("defaultEnabled", True) is not False)
        self._save_state()
        return {"name": plugin_name, "path": str(target), "marketplace": marketplace}

    def install_git(self, url: str, *, name: str | None = None, ref: str | None = None, subdir: str | None = None) -> dict[str, Any]:
        plugin_name = _plugin_name(name or Path(url.rstrip("/")).name.removesuffix(".git"))
        clone = self._installed_base() / ".sources" / plugin_name
        if clone.exists():
            PluginRuntime._rmtree(clone)
        self._git_clone(url, clone, ref)
        root = self._plugin_root(clone / subdir if subdir else clone)
        if root is None:
            raise ValueError(f"plugin manifest/components not found in {url}")
        target = self._installed_base() / plugin_name
        self._copy_replace(root, target)
        self._state.setdefault("sources", {})[plugin_name] = {"source": "git", "plugin_name": plugin_name, "url": url, "ref": ref, "subdir": subdir, "checkout": str(clone)}
        self._save_state()
        return {"name": plugin_name, "path": str(target)}

    def install(self, source: str | Path, *, name: str | None = None, ref: str | None = None) -> dict[str, Any]:
        path = Path(source).expanduser()
        if path.exists():
            if self._marketplace_root(path):
                return self.add_marketplace(path, name=name, ref=ref)
            return self.install_local(path)
        if str(source).startswith(("https://", "http://", "ssh://", "git@")):
            return self.install_git(str(source), name=name, ref=ref)
        if "/" in str(source) and ":" not in str(source):
            return self.install_git(self._github_url(str(source)), name=name, ref=ref)
        raise ValueError(f"unsupported plugin source: {source}")

    def set_enabled(self, name: str, enabled: bool) -> bool:
        self._enabled[name] = enabled
        self._save_state()
        if not enabled:
            self._loaded.pop(name, None)
        return True

    def uninstall(self, name: str) -> bool:
        plugin = next((item for item in self.discover() if item["name"] == name), None)
        if plugin is None:
            return False
        root = Path(plugin["path"])
        if root.parent.resolve() == self._installed_base().resolve():
            PluginRuntime._rmtree(root)
        source = self._state.get("sources", {}).pop(name, {})
        checkout = source.get("checkout") if isinstance(source, dict) else None
        if checkout and Path(checkout).exists():
            PluginRuntime._rmtree(Path(checkout))
        self._enabled.pop(name, None)
        self._loaded.pop(name, None)
        self._save_state()
        return True

    @staticmethod
    def _git_repo(path: Path) -> Path | None:
        repo = Path(path)
        while repo != repo.parent:
            if (repo / ".git").exists():
                return repo
            repo = repo.parent
        return None

    def _git_update_available(self, path: Path) -> bool:
        """True when the checkout's upstream advanced past local HEAD. Failures mean no update."""
        repo = self._git_repo(path)
        if repo is None:
            return False
        try:
            subprocess.run(["git", "-C", str(repo), "fetch", "--quiet"], check=True, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
            head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.strip()
            upstream = subprocess.run(["git", "-C", str(repo), "rev-parse", "@{upstream}"], check=True, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return False
        return bool(head) and bool(upstream) and head != upstream

    def check_updates(self, name: str | None = None) -> dict[str, bool]:
        """Refresh ``update_available`` in state for git/marketplace-sourced plugins.

        Local-directory plugins have no remote to compare and are skipped.
        """
        results: dict[str, bool] = {}
        sources = self._state.get("sources", {})
        for plugin_name, source in sources.items():
            if not isinstance(source, dict):
                continue
            if name is not None and plugin_name != name:
                continue
            if source.get("source") == "git":
                checkout = source.get("checkout")
                available = self._git_update_available(Path(checkout)) if checkout else False
            elif source.get("source") == "marketplace":
                record = self._state.get("marketplaces", {}).get(source.get("marketplace"))
                checkout = source.get("checkout") or (
                    record.get("path") if isinstance(record, dict) and record.get("type") == "git" else None
                )
                available = self._git_update_available(Path(checkout)) if checkout else False
            else:
                continue
            source["update_available"] = available
            results[plugin_name] = available
        self._save_state()
        return results

    def update_marketplace(self, name: str) -> dict[str, Any]:
        record = self._state.get("marketplaces", {}).get(name)
        if not isinstance(record, dict):
            raise KeyError(name)
        if record["type"] == "local":
            return {"name": name, "updated": False, "reason": "local"}
        repo = self._git_repo(Path(record["path"]))
        if repo is None:
            raise ValueError(f"marketplace checkout is not a git repository: {name}")
        subprocess.run(["git", "-C", str(repo), "pull", "--ff-only"], check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
        record["path"] = str(self._marketplace_root(repo) or repo)
        self._save_state()
        return {"name": name, "updated": True}

    def update(self, name: str) -> dict[str, Any]:
        source = self._state.get("sources", {}).get(name, {})
        if source.get("source") == "local":
            path = Path(source["path"])
            result = self.install_local(path)
            self._state["sources"][name] = source
            self._save_state()
            return result
        if source.get("source") == "marketplace":
            self.update_marketplace(source["marketplace"])
            result = self.install_marketplace_plugin(source["marketplace"], name)
            self._enabled[name] = self._enabled.get(name, True)
            self._save_state()
            return result
        if source.get("source") == "git":
            checkout = Path(source["checkout"])
            subprocess.run(["git", "-C", str(checkout), "pull", "--ff-only"], check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
            root = self._plugin_root(checkout / source["subdir"] if source.get("subdir") else checkout)
            if root is None:
                raise ValueError(f"plugin components missing after update: {name}")
            target = self._installed_base() / name
            self._copy_replace(root, target)
            source["update_available"] = False
            self._save_state()
            return {"name": name, "path": str(target)}
        raise ValueError(f"plugin has no update source: {name}")

    async def load_all(
        self, *, hook_bus: Any = None, mcp_client: Any = None, capabilities: Any = None,
    ) -> dict[str, Any]:
        """Load Atlas/Hermes compatibility contributions; Claude hooks go via HookStore."""
        report: dict[str, Any] = {"loaded": [], "skipped": [], "errors": {}}
        self._loaded.clear()
        for plugin in self.discover():
            name = plugin["name"]
            if not plugin["enabled"]:
                report["skipped"].append({"name": name, "reason": "disabled"})
                continue
            try:
                self._loaded[name] = await self._load_one(
                    Path(plugin["path"]), plugin_name=name,
                    hook_bus=hook_bus, mcp_client=mcp_client, capabilities=capabilities,
                )
                report["loaded"].append(name)
            except Exception as exc:
                report["errors"][name] = str(exc)
        return report

    async def _load_one(
        self, root: Path, *, plugin_name: str, hook_bus: Any,
        mcp_client: Any, capabilities: Any,
    ) -> dict[str, Any]:
        loaded: dict[str, Any] = {"skills": [], "commands": [], "hooks": 0, "mcp": []}
        _, manifest = _manifest(root)
        if capabilities is not None:
            for skill in self._component_paths(root, manifest, "skills", root / "skills", directories=True):
                content = (skill / "SKILL.md").read_text(encoding="utf-8", errors="replace")
                loaded["skills"].append(skill.name)
                capabilities.register(
                    f"plugin.{plugin_name}.skill.{skill.name}", description=f"Skill from plugin {plugin_name}.",
                    handler=lambda _inputs, _content=content: {"content": _content}, source=f"plugin:{plugin_name}",
                )
            for command in self._commands(root, manifest):
                loaded["commands"].append(command["name"])
                content = command["content"]
                if content is None and command["path"]:
                    content = Path(command["path"]).read_text(encoding="utf-8", errors="replace")
                capabilities.register(
                    f"plugin.{plugin_name}.command.{command['name']}", description=str(command["metadata"].get("description") or f"Command prompt from plugin {plugin_name}."),
                    handler=lambda _inputs, _content=content: {"prompt": _content}, source=f"plugin:{plugin_name}",
                )
        for spec in self._legacy_hook_specs(root):
            point = str(spec.get("point", ""))
            command = spec.get("command")
            if point not in HOOK_POINTS or not isinstance(command, list) or not command:
                continue
            argv = [str(arg) for arg in command]

            def _handler(_argv: list[str] = argv, **payload: Any) -> None:
                subprocess.run(_argv, input=json.dumps(payload, ensure_ascii=False, default=str), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, check=False)

            if hook_bus is not None:
                hook_bus.register(point, _handler)
            loaded["hooks"] += 1
        if mcp_client is not None:
            from atlas.tools.mcp_client import MCPServerConfig

            for server_name, server in self._mcp_configs(root, manifest).items():
                if server_name in mcp_client.get_server_names():
                    loaded["mcp"].append(server_name)
                    continue
                transport = str(server.get("transport", server.get("type", "stdio")))
                config = MCPServerConfig(
                    name=server_name, transport=transport,
                    command=server.get("command"), args=[str(arg) for arg in server.get("args", [])],
                    env={str(k): str(v) for k, v in (server.get("env") or {}).items()},
                    cwd=str(server.get("cwd") or root), url=server.get("url"), enabled=True,
                )
                await mcp_client._connect_server(config)
                loaded["mcp"].append(server_name)
        return loaded

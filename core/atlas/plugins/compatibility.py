"""Atlas plugin host-version compatibility checks for npm peer ranges."""

from __future__ import annotations

from typing import Any

from semantic_version import NpmSpec, Version

from atlas import __version__ as ATLAS_VERSION

_ATLAS_PEERS = frozenset({"atlas", "@atlas-ai/atlas"})


def range_satisfies(runtime_version: str, range_text: str) -> bool:
    """Evaluate npm semver peer ranges with npm prerelease and partial semantics."""
    raw_range = range_text.strip()
    if raw_range.startswith("workspace:"):
        raw_range = raw_range[len("workspace:"):].strip() or "*"
    try:
        runtime = Version(runtime_version)
        spec = NpmSpec(raw_range)
    except ValueError as exc:
        raise ValueError(f"invalid npm semver version or range: {runtime_version!r} {range_text!r}") from exc
    return spec.match(runtime)


def evaluate_plugin_compatibility(
    manifest: dict[str, Any], runtime_version: str = ATLAS_VERSION,
    exemptions: dict[str, list[str]] | None = None,
) -> dict[str, Any] | None:
    """Return incompatible Atlas peers; malformed relevant ranges fail closed."""
    peers = manifest.get("peerDependencies")
    if peers is None:
        return None
    if not isinstance(peers, dict):
        raise ValueError("peerDependencies must be an object")
    mismatches: dict[str, str] = {}
    for name, raw_range in peers.items():
        if name not in _ATLAS_PEERS:
            continue
        if not isinstance(raw_range, str) or not raw_range.strip():
            mismatches[str(name)] = str(raw_range)
            continue
        try:
            matches = range_satisfies(runtime_version, raw_range)
        except ValueError:
            matches = False
        if not matches:
            mismatches[name] = raw_range
    if not mismatches:
        return None
    name = str(manifest.get("name") or "")
    version = str(manifest.get("version") or "")
    key = f"{name}@{version}"
    exempted = runtime_version in (exemptions or {}).get(key, [])
    return {
        "name": name,
        "version": version,
        "runtime_version": runtime_version,
        "peers": mismatches,
        "exempted": exempted,
    }

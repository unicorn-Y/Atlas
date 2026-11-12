"""Plugin patch layers: keep local edits across an install or upgrade.

The problem this solves
-----------------------
``PluginRuntime._copy_replace`` replaces an installed plugin directory wholesale.
That is correct for a deploy snapshot and catastrophic for a user who fixed one
line in a plugin's ``SKILL.md``: the next ``install``/upgrade silently deletes the
edit, and nothing tells them. ``reload`` re-reads from disk, so it cannot help —
the file is already gone.

The model: three copies, one truth per question
-----------------------------------------------
Every patched file has up to three versions on disk under ``<plugin>/patches/``::

    patches/files/<rel>       what the user wants        (the patch)
    patches/.originals/<rel>  what upstream shipped       (for revert)
    <plugin>/<rel>            what readers actually load  (materialised)

The shipped path is *materialised* — the patch is copied over it — rather than
resolved at read time. That is deliberate: every existing reader (skill registry,
command discovery, hook specs, MCP configs) keeps doing ``root / relative`` and
therefore needs no change at all. A read-time overlay would have required
touching each of them, and any one missed would make a patch look like it did
nothing.

``.originals`` is what makes ``revert`` real. Without it, "undo my edit" is
impossible once the file has been overwritten.

Upgrade behaviour
-----------------
:func:`carry_over` runs before ``_copy_replace`` swaps the directory. It copies
``patches/`` out, and :func:`reapply` runs after the new files land, re-copying
each patch over the freshly shipped version. An upgrade therefore keeps the
user's edits instead of asking them to redo the work. Overrides whose shipped
file no longer exists are reported, not dropped silently.

Security boundary
-----------------
A patch path arrives from an HTTP body, so it is untrusted: ``..`` escapes,
absolute paths, the ``.git`` internals and executables are all refused. A patch
layer that could rewrite ``.git/config`` or drop a ``.exe`` would be a
code-execution vector hiding inside a "text override" feature.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

PATCH_DIRNAME = "patches"
FILES_DIRNAME = "files"
ORIGINALS_DIRNAME = ".originals"
MANIFEST_NAME = "manifest.json"

#: Refused by suffix: the patch layer changes text, it does not deliver binaries.
_DENIED_SUFFIXES = {".exe", ".dll", ".so", ".dylib", ".bat", ".cmd", ".ps1", ".scr", ".msi"}
#: Refused by name: repository internals and the manifest itself.
_DENIED_NAMES = {".git", ".gitignore", ".gitmodules", MANIFEST_NAME}


class PatchError(ValueError):
    """A patch request that must be refused, with a user-readable reason."""

    def __init__(self, message: str, *, code: str = "invalid_patch") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def _patch_root(plugin_root: str | Path) -> Path:
    return Path(plugin_root) / PATCH_DIRNAME


def _safe_relative(value: str) -> Path:
    """Reject absolute paths and ``..`` escapes before anything touches disk."""
    raw = str(value or "").replace("\\", "/").strip()
    if not raw or raw.startswith("/") or (len(raw) > 1 and raw[1] == ":"):
        raise PatchError(f"补丁路径必须相对于插件根目录：{value!r}")
    relative = Path(raw)
    if any(part == ".." for part in relative.parts):
        raise PatchError(f"补丁路径不能包含 '..'：{value!r}")
    if relative.parts[0] in _DENIED_NAMES or relative.name in _DENIED_NAMES:
        raise PatchError(f"{relative.name} 不能通过补丁层修改", code="denied_path")
    if relative.suffix.lower() in _DENIED_SUFFIXES:
        raise PatchError(
            f"补丁层只改文本，拒绝写入可执行文件 {relative.name}", code="denied_path",
        )
    if relative.parts[0] == PATCH_DIRNAME:
        raise PatchError("补丁路径不能指向补丁目录本身", code="denied_path")
    return relative


def _read_manifest(root: Path) -> dict[str, Any]:
    """The manifest, always carrying a ``patches`` mapping.

    A missing or corrupt manifest must not make the patch layer unusable: the
    files under ``patches/files/`` are the truth, and the manifest only annotates
    them. Callers therefore always get a dict they can index.
    """
    try:
        data = json.loads((_patch_root(root) / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    if not isinstance(data.get("patches"), dict):
        data["patches"] = {}
    return data


def _write_manifest(root: Path, data: dict[str, Any]) -> None:
    directory = _patch_root(root)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / MANIFEST_NAME).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8",
    )


def _original_path(root: Path, key: Path) -> Path:
    return _patch_root(root) / ORIGINALS_DIRNAME / key


def _patch_file(root: Path, key: Path) -> Path:
    return _patch_root(root) / FILES_DIRNAME / key


def _materialise(root: Path, key: Path) -> None:
    """Copy the patch over the shipped path so ordinary readers see it."""
    source = _patch_file(root, key)
    if not source.is_file():
        return
    target = root / key
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def list_patches(plugin_root: str | Path) -> dict[str, Any]:
    """Every override on this plugin, with what it shadows.

    ``added`` marks an override for a path the plugin never shipped. It is
    derived from ``original_saved`` rather than from the shipped file's existence,
    because materialisation writes the patch over that path — asking "does
    ``root/key`` exist" after applying a patch always answers yes and says nothing.
    """
    root = Path(plugin_root)
    manifest = _read_manifest(root)
    records = manifest.get("patches", {})
    files = _patch_root(root) / FILES_DIRNAME
    entries: list[dict[str, Any]] = []
    if files.is_dir():
        for path in sorted(files.rglob("*")):
            if not path.is_file():
                continue
            key = path.relative_to(files)
            record = records.get(key.as_posix(), {})
            original_saved = _original_path(root, key).is_file()
            entries.append({
                "path": key.as_posix(),
                "bytes": path.stat().st_size,
                "original_saved": original_saved,
                "added": not original_saved,
                "note": record.get("note", "") if isinstance(record, dict) else "",
                "modified": int(path.stat().st_mtime),
            })
    return {"plugin_root": str(root), "patches": entries, "count": len(entries)}


def effective_text(plugin_root: str | Path, relative: str) -> str:
    """The content a reader should see, patch included."""
    root = Path(plugin_root)
    key = _safe_relative(relative)
    patch = _patch_file(root, key)
    if patch.is_file():
        return patch.read_text(encoding="utf-8", errors="replace")
    return (root / key).read_text(encoding="utf-8", errors="replace")


def write(plugin_root: str | Path, relative: str, content: str, *, note: str = "") -> dict[str, Any]:
    """Record a local edit as a patch, keeping the shipped original for revert.

    Refuses a patch identical to what is already effective: an override that
    changes nothing is not an edit, and leaving one behind means the next
    upstream change to that file silently never arrives.
    """
    root = Path(plugin_root)
    key = _safe_relative(relative)
    shipped = root / key
    patch = _patch_file(root, key)
    original = _original_path(root, key)

    baseline = patch if patch.is_file() else shipped
    if baseline.is_file():
        try:
            if baseline.read_text(encoding="utf-8", errors="replace") == content:
                raise PatchError(
                    f"补丁内容与当前生效文件相同，未写入（{key.as_posix()}）",
                    code="redundant_patch",
                )
        except OSError:
            pass

    # Save the shipped file exactly once: on the second edit of the same file the
    # "original" is still the upstream version, not the user's first patch.
    if not original.exists() and shipped.is_file():
        original.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(shipped, original)

    patch.parent.mkdir(parents=True, exist_ok=True)
    patch.write_text(content, encoding="utf-8")
    _materialise(root, key)

    manifest = _read_manifest(root)
    manifest["patches"][key.as_posix()] = {"note": note}
    _write_manifest(root, manifest)
    return {"path": key.as_posix(), "bytes": patch.stat().st_size, "note": note}


def revert(plugin_root: str | Path, relative: str) -> dict[str, Any]:
    """Drop one override and put the shipped content back in place."""
    root = Path(plugin_root)
    key = _safe_relative(relative)
    patch = _patch_file(root, key)
    if not patch.is_file():
        raise PatchError(f"没有针对 {key.as_posix()} 的补丁", code="patch_not_found")

    original = _original_path(root, key)
    if original.is_file():
        target = root / key
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, target)
        original.unlink()
    patch.unlink()

    # Prune directories the patch created, stopping at the patch root.
    for parent in list(patch.parents):
        if parent == _patch_root(root) or _patch_root(root) not in parent.parents:
            break
        try:
            parent.rmdir()
        except OSError:
            break

    manifest = _read_manifest(root)
    manifest["patches"].pop(key.as_posix(), None)
    _write_manifest(root, manifest)
    return {"path": key.as_posix(), "reverted": True, "restored_from_original": original.exists() is False}


def revert_all(plugin_root: str | Path) -> dict[str, Any]:
    """Remove every override, restoring each shipped file first."""
    root = Path(plugin_root)
    listing = list_patches(root)
    restored: list[str] = []
    for entry in listing["patches"]:
        try:
            revert(root, entry["path"])
            restored.append(entry["path"])
        except PatchError:
            continue
    base = _patch_root(root)
    if base.is_dir():
        shutil.rmtree(base, ignore_errors=True)
    return {"plugin_root": str(root), "reverted": restored, "count": len(restored)}


def carry_over(previous_root: str | Path, new_root: str | Path) -> dict[str, Any]:
    """Preserve the patch layer across a directory replacement.

    Called with the old root *before* ``_copy_replace`` swaps the directory, so
    the patches can be re-applied to the new files afterwards. Returns the count
    so the install report can say "N edits kept" instead of failing silently.
    """
    old_base = _patch_root(Path(previous_root))
    if not old_base.is_dir():
        return {"carried": 0, "orphaned": [], "had_patches": False}

    new_base = _patch_root(Path(new_root))
    carried = 0
    if new_base.is_dir():
        # The new release ships its own patch layer. Merge rather than pick a
        # winner: losing the user's edits is the one outcome this exists to stop.
        for name in (FILES_DIRNAME, ORIGINALS_DIRNAME):
            source_dir = old_base / name
            if not source_dir.is_dir():
                continue
            for path in sorted(source_dir.rglob("*")):
                if not path.is_file():
                    continue
                target = new_base / name / path.relative_to(source_dir)
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, target)
                    # Count edits, not files: ``.originals`` is bookkeeping and
                    # reporting it would double the number the caller shows.
                    if name == FILES_DIRNAME:
                        carried += 1
    else:
        shutil.copytree(old_base, new_base)
        files = new_base / FILES_DIRNAME
        carried = sum(1 for path in files.rglob("*") if path.is_file()) if files.is_dir() else 0
    return {"carried": carried, "had_patches": True}


def reapply(plugin_root: str | Path) -> dict[str, Any]:
    """Re-materialise every patch after new files have landed.

    Without this step an upgrade would leave ``patches/`` intact but the plugin
    directory holding upstream's bytes, so the patch would exist and do nothing.
    Patches that add a file the plugin never shipped are re-applied too, and
    counted separately: they are legitimate (a user can add a command) but they
    are the ones to re-check after an upgrade.
    """
    root = Path(plugin_root)
    files = _patch_root(root) / FILES_DIRNAME
    applied: list[str] = []
    added: list[str] = []
    if files.is_dir():
        for path in sorted(files.rglob("*")):
            if not path.is_file():
                continue
            key = path.relative_to(files)
            _materialise(root, key)
            applied.append(key.as_posix())
            if not _original_path(root, key).is_file():
                added.append(key.as_posix())
    return {"applied": applied, "count": len(applied), "added": added}

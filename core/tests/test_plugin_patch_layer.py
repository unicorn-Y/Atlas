"""Patch layer: local plugin edits that survive an upgrade.

The behaviour under test is the one that motivated the module: ``_copy_replace``
deletes the plugin directory on every install/upgrade, so a user's fix to a
``SKILL.md`` used to vanish without a word. These tests pin the three-copy model
(patch / original / materialised) and the upgrade carry-over.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atlas.plugins import patch_layer


def _plugin(tmp_path: Path, *, files: dict[str, str] | None = None) -> Path:
    root = tmp_path / "demo-plugin"
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(
        json.dumps({"name": "demo", "version": "1.0.0"}), encoding="utf-8",
    )
    for relative, content in (files or {"skills/helper/SKILL.md": "shipped\n"}).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def test_a_plugin_without_patches_reports_nothing(tmp_path: Path) -> None:
    root = _plugin(tmp_path)
    listing = patch_layer.list_patches(root)
    assert listing["count"] == 0
    assert listing["patches"] == []


def test_a_patch_replaces_what_readers_see(tmp_path: Path) -> None:
    root = _plugin(tmp_path)
    patch_layer.write(root, "skills/helper/SKILL.md", "mine\n", note="tweak")
    # The pinned contract: the materialised file is what every existing reader
    # (skill registry, command discovery) loads with no change on their side.
    assert (root / "skills/helper/SKILL.md").read_text(encoding="utf-8") == "mine\n"
    assert patch_layer.effective_text(root, "skills/helper/SKILL.md") == "mine\n"


def test_the_shipped_original_is_kept_for_revert(tmp_path: Path) -> None:
    root = _plugin(tmp_path)
    patch_layer.write(root, "skills/helper/SKILL.md", "mine\n")
    original = root / "patches" / ".originals" / "skills/helper/SKILL.md"
    assert original.read_text(encoding="utf-8") == "shipped\n"


def test_revert_puts_the_shipped_content_back(tmp_path: Path) -> None:
    root = _plugin(tmp_path)
    patch_layer.write(root, "skills/helper/SKILL.md", "mine\n")
    result = patch_layer.revert(root, "skills/helper/SKILL.md")
    assert result["reverted"] is True
    assert (root / "skills/helper/SKILL.md").read_text(encoding="utf-8") == "shipped\n"
    assert not (root / "patches" / "files" / "skills/helper/SKILL.md").exists()


def test_a_second_edit_does_not_overwrite_the_saved_original(tmp_path: Path) -> None:
    """The original must stay upstream's bytes, never the user's first attempt."""
    root = _plugin(tmp_path)
    patch_layer.write(root, "skills/helper/SKILL.md", "first\n")
    patch_layer.write(root, "skills/helper/SKILL.md", "second\n")
    original = root / "patches" / ".originals" / "skills/helper/SKILL.md"
    assert original.read_text(encoding="utf-8") == "shipped\n"
    patch_layer.revert(root, "skills/helper/SKILL.md")
    assert (root / "skills/helper/SKILL.md").read_text(encoding="utf-8") == "shipped\n"


def test_an_identical_patch_is_refused(tmp_path: Path) -> None:
    """A no-op override would swallow the next upstream change to that file."""
    root = _plugin(tmp_path)
    with pytest.raises(patch_layer.PatchError) as caught:
        patch_layer.write(root, "skills/helper/SKILL.md", "shipped\n")
    assert caught.value.code == "redundant_patch"


def test_reverting_an_unpatched_file_is_an_error(tmp_path: Path) -> None:
    root = _plugin(tmp_path)
    with pytest.raises(patch_layer.PatchError) as caught:
        patch_layer.revert(root, "skills/helper/SKILL.md")
    assert caught.value.code == "patch_not_found"


@pytest.mark.parametrize(
    "relative",
    [
        "../../etc/passwd",
        "skills/../../../escape.md",
        "/absolute.md",
        "C:/windows/system32/x.md",
        ".git/config",
        "patches/files/x.md",
        "tools/evil.exe",
        "run.ps1",
    ],
)
def test_patch_paths_cannot_escape_or_deliver_binaries(tmp_path: Path, relative: str) -> None:
    """A patch path arrives from an HTTP body, so it is untrusted input."""
    root = _plugin(tmp_path)
    with pytest.raises(patch_layer.PatchError):
        patch_layer.write(root, relative, "content\n")


def test_a_patch_may_add_a_file_the_plugin_never_shipped(tmp_path: Path) -> None:
    root = _plugin(tmp_path)
    patch_layer.write(root, "skills/extra/SKILL.md", "added\n")
    assert (root / "skills/extra/SKILL.md").read_text(encoding="utf-8") == "added\n"
    entry = patch_layer.list_patches(root)["patches"][0]
    assert entry["original_saved"] is False
    assert entry["added"] is True


def test_listing_reports_each_override_with_its_note(tmp_path: Path) -> None:
    root = _plugin(tmp_path)
    patch_layer.write(root, "skills/helper/SKILL.md", "mine\n", note="本地说明")
    listing = patch_layer.list_patches(root)
    assert listing["count"] == 1
    assert listing["patches"][0]["path"] == "skills/helper/SKILL.md"
    assert listing["patches"][0]["note"] == "本地说明"
    # A patch over a shipped file kept its original, so it is an edit, not an add.
    assert listing["patches"][0]["added"] is False
    assert listing["patches"][0]["original_saved"] is True


def test_revert_all_restores_every_file(tmp_path: Path) -> None:
    root = _plugin(tmp_path, files={"skills/a/SKILL.md": "a\n", "skills/b/SKILL.md": "b\n"})
    patch_layer.write(root, "skills/a/SKILL.md", "A mine\n")
    patch_layer.write(root, "skills/b/SKILL.md", "B mine\n")
    result = patch_layer.revert_all(root)
    assert result["count"] == 2
    assert (root / "skills/a/SKILL.md").read_text(encoding="utf-8") == "a\n"
    assert (root / "skills/b/SKILL.md").read_text(encoding="utf-8") == "b\n"
    assert not (root / "patches").exists()


def test_carry_over_moves_patches_to_the_new_tree(tmp_path: Path) -> None:
    old = _plugin(tmp_path / "old")
    patch_layer.write(old, "skills/helper/SKILL.md", "mine\n")
    new = _plugin(tmp_path / "new", files={"skills/helper/SKILL.md": "shipped v2\n"})

    result = patch_layer.carry_over(old, new)
    assert result["had_patches"] is True
    assert result["carried"] == 1
    # The patch is in the new tree but not yet applied — that is reapply's job.
    assert (new / "patches" / "files" / "skills/helper/SKILL.md").is_file()


def test_reapply_puts_the_patch_back_over_new_files(tmp_path: Path) -> None:
    """The step that makes an upgrade keep the edit instead of dropping it."""
    old = _plugin(tmp_path / "old")
    patch_layer.write(old, "skills/helper/SKILL.md", "mine\n")
    new = _plugin(tmp_path / "new", files={"skills/helper/SKILL.md": "shipped v2\n"})
    patch_layer.carry_over(old, new)

    applied = patch_layer.reapply(new)
    assert applied["count"] == 1
    assert (new / "skills/helper/SKILL.md").read_text(encoding="utf-8") == "mine\n"


def test_carry_over_on_an_unpatched_plugin_is_a_no_op(tmp_path: Path) -> None:
    old = _plugin(tmp_path / "old")
    new = _plugin(tmp_path / "new")
    result = patch_layer.carry_over(old, new)
    assert result["had_patches"] is False
    assert result["carried"] == 0


def test_carry_over_merges_when_the_new_release_ships_patches(tmp_path: Path) -> None:
    """Losing the user's edits is the one outcome carry_over exists to prevent."""
    old = _plugin(tmp_path / "old")
    patch_layer.write(old, "skills/helper/SKILL.md", "user edit\n")
    new = _plugin(tmp_path / "new", files={"skills/helper/SKILL.md": "shipped v2\n"})
    patch_layer.write(new, "skills/vendor/SKILL.md", "vendor patch\n")

    result = patch_layer.carry_over(old, new)
    assert result["carried"] == 1
    # Both survive: the release's own patch and the user's.
    assert (new / "patches" / "files" / "skills/helper/SKILL.md").is_file()
    assert (new / "patches" / "files" / "skills/vendor/SKILL.md").is_file()


def test_runtime_copy_replace_carries_patches_through_an_install(tmp_path: Path) -> None:
    """End to end: the upgrade path in ``PluginRuntime._copy_replace``."""
    installed = _plugin(tmp_path / "installed", files={"skills/helper/SKILL.md": "v1\n"})
    patch_layer.write(installed, "skills/helper/SKILL.md", "my local fix\n")

    source = _plugin(tmp_path / "source", files={"skills/helper/SKILL.md": "v2 upstream\n"})
    from atlas.plugins.runtime import PluginRuntime

    PluginRuntime._copy_replace(source, installed)

    assert (installed / "skills/helper/SKILL.md").read_text(encoding="utf-8") == "my local fix\n"
    assert patch_layer.list_patches(installed)["count"] == 1


def test_effective_text_falls_back_to_the_shipped_file(tmp_path: Path) -> None:
    root = _plugin(tmp_path)
    assert patch_layer.effective_text(root, "skills/helper/SKILL.md") == "shipped\n"


def test_reading_an_unknown_file_raises(tmp_path: Path) -> None:
    root = _plugin(tmp_path)
    with pytest.raises(FileNotFoundError):
        patch_layer.effective_text(root, "skills/nope/SKILL.md")

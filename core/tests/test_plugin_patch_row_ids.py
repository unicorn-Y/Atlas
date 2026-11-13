from pathlib import Path

import pytest

from atlas.plugins import patch_layer

pytestmark = pytest.mark.unit


def test_patch_row_id_replaces_its_previous_path(tmp_path: Path) -> None:
    root = tmp_path / "plugin"
    (root / "skills").mkdir(parents=True)
    (root / "skills" / "old.md").write_text("old shipped\n", encoding="utf-8")
    (root / "skills" / "new.md").write_text("new shipped\n", encoding="utf-8")

    patch_layer.write(root, "skills/old.md", "old override\n", row_id="profile:prompt", order=2)
    patch_layer.write(root, "skills/new.md", "new override\n", row_id="profile:prompt", order=2)

    listing = patch_layer.list_patches(root)
    assert listing["count"] == 1
    assert listing["patches"][0]["row_id"] == "profile:prompt"
    assert listing["patches"][0]["order"] == 2
    assert (root / "skills" / "old.md").read_text(encoding="utf-8") == "old shipped\n"
    assert (root / "skills" / "new.md").read_text(encoding="utf-8") == "new override\n"

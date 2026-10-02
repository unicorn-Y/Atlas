"""S3 consolidation checks: one checkpoint implementation (ShadowGitCheckpointStore).

Pins the behaviors that differed between the W06 shadow-git design and the
consolidated plain-copy store: byte-exact restore fidelity, independence from
the git binary, backward compatibility with pre-consolidation snapshots, and
the unchanged scoped delete/restore semantics the server API relies on.
"""

import subprocess
from pathlib import Path

from atlas.agent.checkpoints import ShadowGitCheckpointStore


def test_restore_preserves_crlf_bom_and_binary_bytes(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    crlf = workspace / "windows.txt"
    bom = workspace / "bom.txt"
    blob = workspace / "data.bin"
    crlf.write_bytes(b"alpha\r\nbeta\r\n")
    bom.write_bytes(b"\xef\xbb\xbfheader\r\nbody")
    blob.write_bytes(bytes(range(256)) + b"\x00\x00\xff")
    store = ShadowGitCheckpointStore(tmp_path / "checkpoints")
    checkpoint = store.create_checkpoint(workspace, ["windows.txt", "bom.txt", "data.bin"])
    crlf.write_bytes(b"alpha\nbeta\n")
    bom.write_bytes(b"rewritten")
    blob.write_bytes(b"corrupt")
    store.restore_checkpoint(checkpoint["id"])
    assert crlf.read_bytes() == b"alpha\r\nbeta\r\n"
    assert bom.read_bytes() == b"\xef\xbb\xbfheader\r\nbody"
    assert blob.read_bytes() == bytes(range(256)) + b"\x00\x00\xff"


def test_create_checkpoint_needs_no_git_binary_and_skips_shadow_repo(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "note.txt").write_text("v1", encoding="utf-8")
    store = ShadowGitCheckpointStore(tmp_path / "checkpoints")

    def _no_git(*args, **kwargs):
        raise FileNotFoundError("git must not be required for checkpoints")

    monkeypatch.setattr(subprocess, "run", _no_git)
    checkpoint = store.create_checkpoint(workspace, ["."], run_id="r1")
    (workspace / "note.txt").write_text("v2", encoding="utf-8")
    restored = store.restore_checkpoint(checkpoint["id"])
    assert (workspace / "note.txt").read_text(encoding="utf-8") == "v1"
    assert restored["restored"] == ["note.txt"]
    assert not (store.storage_dir / checkpoint["id"] / "git").exists()
    assert store.manifest_path(checkpoint["id"]) == (
        store.storage_dir / checkpoint["id"] / "manifest.json"
    )


def test_restore_still_reads_pre_consolidation_git_layout(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    target = workspace / "source.py"
    target.write_text("old", encoding="utf-8")
    store = ShadowGitCheckpointStore(tmp_path / "checkpoints")
    checkpoint = store.create_checkpoint(workspace, ["source.py"])
    snapshot = store.storage_dir / checkpoint["id"]
    # Hand-build the W06-era layout: git/ working-tree copy wins over files/.
    legacy = snapshot / "git" / "source.py"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"legacy-bytes")
    (snapshot / "git" / ".git").mkdir()
    (snapshot / "files" / "source.py").write_bytes(b"plain-copy")
    target.write_text("changed", encoding="utf-8")
    store.restore_checkpoint(checkpoint["id"])
    assert target.read_bytes() == b"legacy-bytes"


def test_manifest_path_rejects_unknown_or_unsafe_ids(tmp_path: Path) -> None:
    store = ShadowGitCheckpointStore(tmp_path / "checkpoints")
    assert store.manifest_path("missing-id") is None
    assert store.manifest_path("../escape") is None
    assert store.manifest_path("a/b") is None


def test_delete_semantics_and_directory_scopes_unchanged(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    scoped = workspace / "pkg"
    scoped.mkdir(parents=True)
    (scoped / "kept.py").write_text("k", encoding="utf-8")
    (workspace / "outside.txt").write_text("o", encoding="utf-8")
    store = ShadowGitCheckpointStore(tmp_path / "checkpoints")
    checkpoint = store.create_checkpoint(workspace, ["pkg"])
    (scoped / "new.py").write_text("n", encoding="utf-8")
    (scoped / "kept.py").write_text("edited", encoding="utf-8")
    (workspace / "outside.txt").write_text("touched", encoding="utf-8")
    store.restore_checkpoint(checkpoint["id"])
    assert (scoped / "kept.py").read_text(encoding="utf-8") == "k"
    assert not (scoped / "new.py").exists()
    assert (workspace / "outside.txt").read_text(encoding="utf-8") == "touched"
    listed = store.list_checkpoints(workspace)
    assert [item["id"] for item in listed] == [checkpoint["id"]]
    assert listed[0]["file_count"] == 1

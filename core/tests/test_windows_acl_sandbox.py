"""The write-restricted sandbox must be a real filesystem boundary.

These tests prove the property the Job Object could not: a `read-only` call
cannot write the workspace, a `workspace-write` call cannot write outside it,
and both keep their read access. The root is created under the user profile so
the ACL manipulation stays inside a directory the test owns.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="write-restricted tokens are Windows-only"
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atlas.windows_acl_sandbox import (  # noqa: E402
    acl_available,
    run_in_acl_sandbox,
)

if not acl_available():
    pytestmark = pytest.mark.skip(reason="host cannot build a write-restricted token")


def _icacls(path: Path) -> str:
    done = subprocess.run(
        [r"C:\Windows\System32\icacls.exe", str(path)], capture_output=True
    )
    return done.stdout.decode("gbk", "replace")


@pytest.fixture()
def workspace(tmp_path_factory) -> Path:
    base = Path.home() / f"_atlas_acl_test_{uuid.uuid4().hex[:8]}"
    base.mkdir(parents=True)
    ws = base / "ws"
    outside = base / "outside"
    ws.mkdir()
    outside.mkdir()
    yield ws
    import shutil

    shutil.rmtree(base, ignore_errors=True)


def test_workspace_write_stops_at_the_root(workspace: Path):
    outside = workspace.parent / "outside"
    inside_file = workspace / "ok.txt"
    outside_file = outside / "bad.txt"
    world_readable = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "win.ini"
    command = (
        f'echo inside> "{inside_file}" & '
        f'echo outside> "{outside_file}" & '
        f'type "{world_readable}"'
    )
    result = run_in_acl_sandbox(
        [], mode="workspace-write", workspace_roots=[workspace],
        cwd=str(workspace), timeout=60, command=command,
    )

    assert result.enforced is True
    assert inside_file.exists(), "workspace-write must allow writing the workspace"
    assert not outside_file.exists(), "workspace-write must not escape the root"
    assert result.stdout.strip(), "reads outside the root stay allowed"
    assert result.acl_roots_restored is True


def test_read_only_cannot_write_the_workspace(workspace: Path):
    target = workspace / "ro.txt"
    result = run_in_acl_sandbox(
        [], mode="read-only", workspace_roots=[workspace],
        cwd=str(workspace), timeout=60, command=f'echo nope> "{target}"',
    )

    assert result.enforced is True
    assert not target.exists(), "read-only must not write the workspace"


def test_acl_is_put_back_after_the_call(workspace: Path):
    before = _icacls(workspace)
    run_in_acl_sandbox(
        [], mode="workspace-write", workspace_roots=[workspace],
        cwd=str(workspace), timeout=60, command="echo x",
    )
    assert _icacls(workspace) == before, "the capability ACE must not be left behind"


def test_temp_points_at_the_private_scratch(workspace: Path):
    result = run_in_acl_sandbox(
        [], mode="read-only", workspace_roots=[workspace],
        cwd=str(workspace), timeout=60, command="echo %TEMP%",
    )
    assert result.enforced is True
    written = result.stdout.strip().rstrip("\\")
    assert Path(written).name.startswith("atlas-acl-"), written
    assert Path(written) != Path(os.environ["TEMP"])
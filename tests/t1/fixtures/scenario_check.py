"""Shared byte-preservation assertions for scenario fixtures."""
from pathlib import Path


def assert_fixture_bytes(workspace: Path, task_dir: Path, relative_path: str) -> None:
    actual = workspace / relative_path
    expected = task_dir / "fixture" / relative_path
    if not actual.is_file():
        raise AssertionError(f"protected input missing: {relative_path}")
    if actual.read_bytes() != expected.read_bytes():
        raise AssertionError(f"protected input bytes changed: {relative_path}")

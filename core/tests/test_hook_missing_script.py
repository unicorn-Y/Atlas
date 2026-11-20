"""A hooks.json that outlives its scripts must not cost a process per turn."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from atlas.runtime.hooks import _MISSING_SCRIPT_CACHE, _missing_script, _run_command

pytestmark = pytest.mark.unit


def test_python_py_script_that_does_not_exist_is_reported(tmp_path: Path) -> None:
    target = tmp_path / "hooks" / "hook_user_prompt.py"
    assert _missing_script(f"python {target}") == str(target)


def test_existing_script_is_not_reported(tmp_path: Path) -> None:
    script = tmp_path / "hook.py"
    script.write_text("print('{}')", encoding="utf-8")
    assert _missing_script(f"python {script}") is None


def test_bare_command_without_a_script_is_left_to_the_shell() -> None:
    # `git status` has no interpreter head at all.
    assert _missing_script("git status") is None
    # An interpreter with no file argument is also none of this check's business.
    assert _missing_script("python -c 'print(1)'") is None


def test_flags_before_the_script_are_skipped(tmp_path: Path) -> None:
    target = tmp_path / "gone.py"
    assert _missing_script(f"python -u {target}") == str(target)


def test_quoted_paths_are_handled(tmp_path: Path) -> None:
    target = tmp_path / "with space" / "gone.py"
    assert _missing_script(f'python "{target}"') == str(target)


def test_result_is_cached_so_a_repeated_lookup_does_not_stat(tmp_path: Path) -> None:
    target = tmp_path / "cached_gone.py"
    _MISSING_SCRIPT_CACHE.pop(str(target), None)
    assert _missing_script(f"python {target}") == str(target)
    assert _MISSING_SCRIPT_CACHE[str(target)] is True
    # Creating it afterwards still reports missing for the cached path; the file
    # is not expected to reappear, and re-statting every turn is the cost this
    # check exists to remove.
    target.write_text("", encoding="utf-8")
    assert _missing_script(f"python {target}") == str(target)


@pytest.mark.asyncio
async def test_run_command_returns_127_without_spawning(tmp_path: Path) -> None:
    target = tmp_path / "never_exists.py"
    started = time.monotonic()
    code, out, err = await _run_command(
        {"command": f"python {target}"}, {}, cwd=str(tmp_path), plugin_root=None,
    )
    elapsed = time.monotonic() - started
    assert code == 127
    assert out == ""
    assert "hook script not found" in err
    # Spawning a real interpreter costs hundreds of milliseconds even on success;
    # 100 ms is generous for a pure path check and would catch a regression.
    assert elapsed < 0.1, f"took {elapsed:.3f}s — something spawned"

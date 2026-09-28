"""local_edit coverage: read-before-edit, uniqueness, replace_all."""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas.tools.local_execution import LOCAL_TOOLS, LocalExecutionRuntime


@pytest.fixture
async def runtime(tmp_path: Path) -> LocalExecutionRuntime:
    instance = LocalExecutionRuntime()
    yield instance
    await instance.shutdown()


async def test_edit_requires_read_first(runtime: LocalExecutionRuntime, tmp_path: Path) -> None:
    target = tmp_path / "code.py"
    target.write_text("value = 1\n", encoding="utf-8")
    result = await runtime.call_tool("local_edit", {
        "path": str(target), "old_string": "value = 1", "new_string": "value = 2",
    })
    assert result["is_error"] is True
    assert "read the file first" in result["data"]["error"]


async def test_edit_replaces_unique_match(runtime: LocalExecutionRuntime, tmp_path: Path) -> None:
    target = tmp_path / "code.py"
    target.write_text("def run():\n    return 1\n", encoding="utf-8")
    read = await runtime.call_tool("local_file", {"action": "read", "path": str(target)})
    assert read["is_error"] is False

    result = await runtime.call_tool("local_edit", {
        "path": str(target), "old_string": "return 1", "new_string": "return 42",
    })
    assert result["is_error"] is False
    assert result["data"]["replacements"] == 1
    assert target.read_text(encoding="utf-8") == "def run():\n    return 42\n"


async def test_edit_rejects_missing_and_ambiguous_matches(
    runtime: LocalExecutionRuntime, tmp_path: Path,
) -> None:
    target = tmp_path / "dup.txt"
    target.write_text("same\nsame\nother\n", encoding="utf-8")
    await runtime.call_tool("local_file", {"action": "read", "path": str(target)})

    missing = await runtime.call_tool("local_edit", {
        "path": str(target), "old_string": "not-there", "new_string": "x",
    })
    assert missing["is_error"] is True
    assert "not found" in missing["data"]["error"]

    ambiguous = await runtime.call_tool("local_edit", {
        "path": str(target), "old_string": "same", "new_string": "x",
    })
    assert ambiguous["is_error"] is True
    assert "2 locations" in ambiguous["data"]["error"]

    all_replaced = await runtime.call_tool("local_edit", {
        "path": str(target), "old_string": "same", "new_string": "x",
        "replace_all": True,
    })
    assert all_replaced["is_error"] is False
    assert target.read_text(encoding="utf-8") == "x\nx\nother\n"


async def test_edit_is_registered_as_model_tool() -> None:
    names = {item["function"]["name"] for item in LOCAL_TOOLS}
    assert "local_edit" in names
    schema = next(
        item["function"] for item in LOCAL_TOOLS if item["function"]["name"] == "local_edit"
    )
    assert set(schema["parameters"]["required"]) == {"path", "old_string", "new_string"}

from types import SimpleNamespace

from atlas.engine.compact_restore import restore_post_compaction_context
from atlas.engine.read_dedupe import invalidate_read_dedupe, record_file_read, unchanged_read_result


def test_unchanged_read_is_deduped_until_source_result_is_removed(tmp_path):
    file_path = tmp_path / "notes.txt"
    file_path.write_text("first", encoding="utf-8")
    runtime = SimpleNamespace(workspace=str(tmp_path))
    arguments = {"path": "notes.txt", "offset": 1, "limit": 10}

    record_file_read(runtime, arguments, "read-1", "first")

    assert unchanged_read_result(runtime, arguments, "read-2") == (
        f"文件自上次读取后未变化，内容见前文：{file_path.resolve()}"
    )
    assert unchanged_read_result(runtime, {**arguments, "offset": 2}, "read-2") is None

    invalidate_read_dedupe(runtime, ["read-1"])
    assert unchanged_read_result(runtime, arguments, "read-2") is None


def test_changed_file_is_read_again(tmp_path):
    file_path = tmp_path / "notes.txt"
    file_path.write_text("first", encoding="utf-8")
    runtime = SimpleNamespace(workspace=str(tmp_path))
    arguments = {"path": "notes.txt"}
    record_file_read(runtime, arguments, "read-1", "first")

    file_path.write_text("changed", encoding="utf-8")

    assert unchanged_read_result(runtime, arguments, "read-2") is None


def test_post_compaction_restore_preserves_plan_todo_and_attaches_disk_content(tmp_path):
    modified = tmp_path / "changed.py"
    modified.write_text("current disk version", encoding="utf-8")
    read_only = tmp_path / "reference.md"
    read_only.write_text("reference", encoding="utf-8")
    runtime = SimpleNamespace(workspace=str(tmp_path))
    record_file_read(runtime, {"path": "reference.md"}, "read-reference", "reference")
    invalidate_read_dedupe(runtime, ["read-reference"])
    plan = {"role": "system", "content": "original plan"}
    todo = {"role": "system", "content": "original todo"}

    messages = restore_post_compaction_context(
        runtime,
        modified_files=["changed.py"],
        plan_todo_messages=[plan, todo],
        active_skills=[{"name": "focused", "content": "skill instructions"}],
        max_files=5,
        max_tokens_per_file=100,
        total_file_tokens=500,
        max_tokens_per_skill=100,
        total_skill_tokens=250,
    )

    assert messages[:2] == [plan, todo]
    assert any(
        "current disk version" in item["content"]
        and item.get("restored_file") == str(modified.resolve())
        for item in messages
    )
    assert any(
        "reference.md" in item["content"] and "请重新读取" in item["content"] for item in messages
    )
    assert any("skill instructions" in item["content"] for item in messages)

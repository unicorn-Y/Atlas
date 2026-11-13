import pytest

from atlas.engine.kernel.stuck import RepeatToolReminder


@pytest.mark.unit
def test_repeat_tool_reminder_uses_tool_and_canonical_arguments_only():
    reminder = RepeatToolReminder()
    call = {"path": "README.md", "mode": "read"}

    assert reminder.observe("read_file", call) is None
    assert reminder.observe("read_file", {"mode": "read", "path": "README.md"}) is None
    assert reminder.observe("read_file", call)

    assert reminder.observe("read_file", call) is None


@pytest.mark.unit
def test_repeat_tool_reminder_emits_only_at_configured_thresholds_and_resets():
    reminder = RepeatToolReminder()
    results = [reminder.observe("search_files", {"query": "x"}) for _ in range(8)]

    assert [index + 1 for index, result in enumerate(results) if result] == [3, 5, 8]
    assert reminder.observe("search_files", {"query": "y"}) is None
    assert reminder.observe("search_files", {"query": "x"}) is None

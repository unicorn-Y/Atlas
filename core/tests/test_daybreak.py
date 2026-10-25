from __future__ import annotations

import json

from click.testing import CliRunner

from atlas import config
from atlas.cli import main
from atlas.daybreak import DAYBREAK_INSTRUCTIONS, daybreak_prompt


def test_daybreak_prompt_is_stable_and_marks_long_task_semantics():
    prompt = daybreak_prompt("Finish the migration")
    assert prompt.startswith(DAYBREAK_INSTRUCTIONS)
    assert "preserve the completed work" in prompt
    assert daybreak_prompt(prompt) == prompt


def test_daybreak_cli_persists_on_off_and_reports_status(tmp_path, monkeypatch):
    settings_path = tmp_path / "user-settings.json"
    monkeypatch.setattr(config, "USER_SETTINGS_PATH", settings_path)
    runner = CliRunner()

    enabled = runner.invoke(main, ["daybreak", "on"])
    assert enabled.exit_code == 0, enabled.output
    assert json.loads(settings_path.read_text(encoding="utf-8"))["daybreak_enabled"] is True
    assert "已开启" in enabled.output

    status = runner.invoke(main, ["daybreak", "status"])
    assert status.exit_code == 0 and "已开启" in status.output

    disabled = runner.invoke(main, ["daybreak", "off"])
    assert disabled.exit_code == 0, disabled.output
    assert json.loads(settings_path.read_text(encoding="utf-8"))["daybreak_enabled"] is False

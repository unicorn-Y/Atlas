from __future__ import annotations

from click.testing import CliRunner

from atlas import cli


def test_desktop_and_gui_alias_launch_dev_and_request_focus(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(cli, "_desktop_dev_command", lambda _root: (["electron", "main.js"], tmp_path))
    monkeypatch.setattr(cli, "_packaged_desktop_executable", lambda: None)
    monkeypatch.setattr(cli, "_vite_is_listening", lambda: True)
    monkeypatch.setattr(cli.subprocess, "Popen", lambda command, **options: calls.append((command, options)))

    runner = CliRunner()
    for command_name in ("desktop", "gui"):
        result = runner.invoke(cli.main, [command_name])
        assert result.exit_code == 0, result.output
        assert "聚焦现有窗口" in result.output
    assert len(calls) == 2
    assert calls[0][0] == ["electron", "main.js"]
    assert calls[0][1]["cwd"] == str(tmp_path)
    assert calls[0][1]["env"]["VITE_DEV_SERVER_URL"] == "http://127.0.0.1:5173"


def test_desktop_reports_missing_app_and_launch_errors(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "_desktop_dev_command", lambda _root: None)
    monkeypatch.setattr(cli, "_packaged_desktop_executable", lambda: None)
    result = CliRunner().invoke(cli.main, ["gui"])
    assert result.exit_code != 0
    assert "无法启动 Atlas 桌面端" in result.output
    monkeypatch.setattr(cli, "_desktop_dev_command", lambda _root: (["electron", "main.js"], tmp_path))
    monkeypatch.setattr(cli, "_vite_is_listening", lambda: False)
    monkeypatch.setattr(cli.subprocess, "Popen", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("launch denied")))
    failed = CliRunner().invoke(cli.main, ["desktop"])
    assert failed.exit_code != 0
    assert "启动 Electron 失败" in failed.output


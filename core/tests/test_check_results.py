from pathlib import Path

import pytest


def test_check_output_parsers_normalize_ruff_tsc_pytest_and_vitest(tmp_path: Path) -> None:
    from atlas.checks import (
        parse_pytest_junit, parse_ruff_json, parse_test_summary,
        parse_tsc_output, parse_vitest_json,
    )

    ruff = parse_ruff_json('[{"filename":"a.py","code":"F401","message":"unused","location":{"row":2,"column":3}}]')
    assert ruff == [{"file": "a.py", "line": 2, "col": 3, "severity": "error", "code": "F401", "message": "unused"}]
    tsc = parse_tsc_output("src/a.ts(4,2): error TS2322: Type mismatch")
    assert tsc[0]["file"] == "src/a.ts" and tsc[0]["code"] == "TS2322"
    assert parse_test_summary("8 passed, 1 failed, 2 skipped") == {
        "passed": 8, "failed": 1, "skipped": 2,
    }
    junit = tmp_path / "junit.xml"
    junit.write_text('<testsuite tests="3" failures="1" skipped="1"><testcase name="ok"/><testcase name="bad" file="a.py"><failure message="wrong"/></testcase><testcase name="skip"><skipped/></testcase></testsuite>', encoding="utf-8")
    counts, items = parse_pytest_junit(str(junit))
    assert counts == {"passed": 1, "failed": 1, "skipped": 1}
    assert items[0]["test"] == "bad"
    vitest_counts, vitest_items = parse_vitest_json('{"numPassedTests":1,"numFailedTests":1,"numPendingTests":1,"testResults":[{"name":"a.test.ts","assertionResults":[{"status":"failed","fullName":"fails","failureMessages":["broken"]}]}]}')
    assert vitest_counts == {"passed": 1, "failed": 1, "skipped": 1}
    assert vitest_items[0]["file"] == "a.test.ts"


@pytest.mark.asyncio
async def test_run_checks_detects_project_and_bounds_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from atlas import checks

    (tmp_path / "pyproject.toml").write_text("[project]\nname='sample'\n", encoding="utf-8")
    (tmp_path / "src.py").write_text("pass\n", encoding="utf-8")
    called: list[list[str]] = []

    def fake_run(command: list[str], cwd: Path, timeout: int = 900) -> tuple[int, str, int]:
        called.append(command)
        return 0, "[]", 5

    monkeypatch.setattr(checks.shutil, "which", lambda name: "ruff.exe" if name == "ruff" else None)
    monkeypatch.setattr(checks, "_run", fake_run)
    results = await checks.run_checks(str(tmp_path), "lint", ["src.py"])
    assert results[0]["tool"] == "ruff" and results[0]["passed"] == 1
    assert called[0][1:3] == ["check", "src.py"]
    with pytest.raises(ValueError, match="inside the workspace"):
        await checks.run_checks(str(tmp_path), "lint", ["..\\outside.py"])


@pytest.mark.asyncio
async def test_run_checks_returns_explanation_when_no_project_tool_exists(tmp_path: Path) -> None:
    from atlas.checks import run_checks

    result = await run_checks(str(tmp_path), "typecheck")
    assert result[0]["tool"] == "atlas"
    assert "未找到" in result[0]["note"]

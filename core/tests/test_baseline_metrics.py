from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from baseline_metrics import _test_timing, count_exception_handlers, parse_pytest_elapsed


def test_counts_only_broad_exception_handlers_and_bare_silent_handlers() -> None:
    source = '''
try:
    work()
except Exception:
    pass
try:
    work()
except Exception as exc:
    continue_work(exc)
try:
    work()
except ValueError:
    pass
try:
    work()
except Exception:
    log_error()
    pass
'''

    assert count_exception_handlers(source) == {
        "except_exception_total": 3,
        "except_exception_silent_pass_or_continue": 1,
    }


@pytest.mark.parametrize(
    ("log", "expected"),
    [
        ("3 passed in 12.34s", 12.34),
        ("1 failed, 2 passed in 1:02:03", 3723.0),
        ("no pytest summary", None),
    ],
)
def test_parse_pytest_elapsed(log: str, expected: float | None) -> None:
    assert parse_pytest_elapsed(log) == expected


def test_parse_pytest_elapsed_reads_xml_duration(tmp_path: Path) -> None:
    report = tmp_path / "junit.xml"
    report.write_text('<testsuite tests="2" time="4.5"/>', encoding="utf-8")

    assert parse_pytest_elapsed("", junit_xml=report) == 4.5


def test_parse_pytest_elapsed_sums_testsuites_when_root_has_no_time(tmp_path: Path) -> None:
    report = tmp_path / "junit.xml"
    report.write_text(
        '<testsuites><testsuite tests="2" time="4.5"/>'
        '<testsuite tests="1" time="2.0"/></testsuites>',
        encoding="utf-8",
    )

    assert parse_pytest_elapsed("", junit_xml=report) == 6.5


def test_junit_counts_are_not_double_counted(tmp_path: Path) -> None:
    report = tmp_path / "junit.xml"
    report.write_text(
        '<testsuites tests="2027" failures="9" errors="0" skipped="9" time="1963.88">'
        '<testsuite tests="2027" failures="9" errors="0" skipped="9" time="1963.88"/>'
        '</testsuites>',
        encoding="utf-8",
    )

    measured = _test_timing(
        log_path=None, elapsed_seconds=None, junit_path=report, exit_code=1,
    )

    assert measured["junit_counts"] == {
        "tests": 2027, "failures": 9, "errors": 0, "skipped": 9, "passed": 2009,
    }

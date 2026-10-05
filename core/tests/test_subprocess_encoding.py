"""Text-mode subprocess calls must decode explicitly.

Without ``encoding=`` Python decodes child output with the locale code page (GBK on
Chinese Windows). UTF-8 output from git/node/python then crashes the reader thread
and the captured stdout silently becomes ``None``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOTS = ("atlas", "tests", "scripts")
CALLS = {"run", "check_output", "Popen"}


def _offenders() -> list[str]:
    core = Path(__file__).resolve().parents[1]
    found: list[str] = []
    for root in ROOTS:
        for path in sorted((core / root).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = getattr(node.func, "attr", getattr(node.func, "id", ""))
                if name not in CALLS:
                    continue
                keywords = {keyword.arg: keyword.value for keyword in node.keywords}
                text_mode = any(
                    isinstance(keywords.get(key), ast.Constant) and keywords[key].value is True
                    for key in ("text", "universal_newlines")
                )
                if text_mode and "encoding" not in keywords:
                    found.append(f"{path.relative_to(core)}:{node.lineno}")
    return found


def test_text_mode_subprocess_calls_declare_an_encoding() -> None:
    assert _offenders() == []

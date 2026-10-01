import pytest

from tests.test_c1_review_e2e import run_script
from tests.fakes.fake_llm_provider import Text, ToolCall


@pytest.mark.asyncio
async def test_edit_is_verified_inside_hermes_loop_before_final_answer(tmp_path, monkeypatch):
    target = tmp_path / "test_sample.py"
    events, requests, ctx = await run_script(tmp_path, monkeypatch, [
        ToolCall("write_file", {"path": str(target), "content": "import unittest\nclass Sample(unittest.TestCase):\n    def test_value(self):\n        self.assertEqual(1 + 1, 2)\n"}),
        Text("premature completion"),
        ToolCall("terminal", {"command": "python -m unittest test_sample"}),
        Text("verified completion"),
    ])
    assert events[-1]["result"]["final_response"] == "verified completion"
    assert len(requests) == 4
    assert any(row["role"] == "user" and "验证" in str(row.get("content")) for row in requests[2]["messages"])
    assert ctx.verification_passed

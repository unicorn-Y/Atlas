"""Small focused probes for W1 context and compaction behavior."""

from __future__ import annotations

import os
import tempfile
import asyncio

from atlas.kernel.context import ContextManager


def probe_thresholds() -> None:
    manager = ContextManager({"engine": {"max_output_tokens": 20_000}})
    normal = manager.thresholds(1_048_576)
    assert normal.effective_window == 180_000, normal
    assert normal.auto_compact == 167_000, normal
    assert normal.warning == 150_300, normal
    assert normal.blocking == 1_025_576, normal
    small_window = manager.thresholds(128_000)
    assert small_window.effective_window == 108_000, small_window
    assert small_window.auto_compact == 95_000, small_window
    assert small_window.warning == 85_500, small_window
    assert small_window.blocking == 105_000, small_window
    assert manager.thresholds(200_000).auto_compact == normal.auto_compact

    configured_cap = ContextManager({"engine": {"max_output_tokens": 20_000,
                                                  "auto_compact_window_tokens": 300_000}})
    configured = configured_cap.thresholds(1_048_576)
    assert configured.effective_window == 280_000, configured
    assert configured.auto_compact == 267_000, configured
    assert configured.blocking == normal.blocking, configured

    old_cap = os.environ.get("ATLAS_AUTO_COMPACT_WINDOW")
    try:
        os.environ["ATLAS_AUTO_COMPACT_WINDOW"] = "100000"
        overridden_cap = configured_cap.thresholds(1_048_576)
        assert overridden_cap.effective_window == 80_000, overridden_cap
        assert overridden_cap.auto_compact == 67_000, overridden_cap
        assert overridden_cap.blocking == normal.blocking, overridden_cap
    finally:
        if old_cap is None:
            os.environ.pop("ATLAS_AUTO_COMPACT_WINDOW", None)
        else:
            os.environ["ATLAS_AUTO_COMPACT_WINDOW"] = old_cap

    old = os.environ.get("ATLAS_AUTO_COMPACT_PCT")
    try:
        os.environ["ATLAS_AUTO_COMPACT_PCT"] = "1"
        overridden = manager.thresholds(1_048_576)
        assert overridden.auto_compact == 1_800, overridden
        assert 0 < overridden.warning < overridden.auto_compact, overridden
        assert overridden.auto_compact < normal.auto_compact
    finally:
        if old is None:
            os.environ.pop("ATLAS_AUTO_COMPACT_PCT", None)
        else:
            os.environ["ATLAS_AUTO_COMPACT_PCT"] = old


def probe_tool_output_clip() -> None:
    with tempfile.TemporaryDirectory(prefix="atlas-w1-clip-") as output_dir:
        manager = ContextManager({"engine": {"tool_result_limits": {"max_chars": 1_000}}},
                                 output_dir=output_dir)
        source = "HEAD\n" + ("x" * 2_000) + "\nTAIL"
        clipped = manager.clip_tool_result(source, tool_name="probe")
        assert clipped.output_ref and os.path.isfile(clipped.output_ref)
        assert clipped.content.startswith("[Tool: probe]\nHEAD")
        assert "Tool output truncated" in clipped.content
        assert "TAIL" in clipped.content
        with open(clipped.output_ref, encoding="utf-8") as stream:
            assert stream.read() == source
        assert clipped.original_bytes == len(source.encode("utf-8"))


async def _probe_failed_summary_recovery() -> None:
    with tempfile.TemporaryDirectory(prefix="atlas-w1-recovery-") as output_dir:
        manager = ContextManager({"engine": {
            "max_output_tokens": 100,
            "context_buffer_tokens": 0,
            "context_keep_messages": 2,
            "microcompact": {"head_chars": 0, "tail_chars": 0, "keep_recent_tool_results": 5},
        }}, output_dir=output_dir)
        history = [
            {"role": "user", "content": "start"},
            {"role": "assistant", "tool_calls": [{"id": "a", "name": "Read"}]},
            {"role": "tool", "tool_call_id": "a", "name": "Read", "content": "a" * 20_000},
            {"role": "assistant", "tool_calls": [{"id": "b", "name": "Read"}]},
            {"role": "tool", "tool_call_id": "b", "name": "Read", "content": "b" * 20_000},
            {"role": "user", "content": "continue"},
        ]

        async def fail_summary(_old: list[dict], _prompt: str) -> str:
            raise RuntimeError("simulated summary outage")

        result = await manager.prepare(history, model_window=10_000, summarize=fail_summary,
                                       force=True)
        assert result.method == "aggressive_microcompact", result
        assert result.error is None, result
        assert result.recovery_note and "simulated summary outage" in result.recovery_note
        assert any(message.get("output_ref") for message in result.messages)
        assert result.after_tokens < result.before_tokens
        assert manager.consecutive_failures == 1


async def _probe_summary_read_restore() -> None:
    manager = ContextManager({"engine": {"context_keep_messages": 2,
                                         "post_compact_read_restore_tokens": 4_000}})
    history = [{"role": "user", "content": f"work note {index}: " + ("x" * 1_200)}
               for index in range(18)]
    history[3:3] = [
        {"role": "assistant", "tool_calls": [{"id": "read-1", "name": "Read",
                                                  "arguments": {"file_path": "C:/workspace/README.md"}}]},
        {"role": "tool", "tool_call_id": "read-1", "name": "Read", "content": "file evidence"},
    ]
    captured_prompt = ""

    async def summarize(_old: list[dict], prompt: str) -> str:
        nonlocal captured_prompt
        captured_prompt = prompt
        return "Current task and pending work."

    result = await manager.prepare(history, model_window=1_000_000, summarize=summarize, force=True)
    assert result.method == "summary", result
    assert "C:/workspace/README.md" in captured_prompt
    assert "pending tasks in priority order" in captured_prompt
    assert "without asking the user" in captured_prompt
    assert any(item.get("role") == "tool" and item.get("content") == "file evidence"
               for item in result.messages)
    assert any("Recent read-file results were restored verbatim" in str(item.get("content", ""))
               for item in result.messages)
    assert manager.consecutive_failures == 0


if __name__ == "__main__":
    probe_thresholds()
    probe_tool_output_clip()
    asyncio.run(_probe_failed_summary_recovery())
    asyncio.run(_probe_summary_read_restore())
    print("W1-2/W1-5 上下文预算、失败恢复和摘要续接 probe PASS")

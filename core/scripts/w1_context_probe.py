"""Small focused probes for W1 context and compaction behavior."""

from __future__ import annotations

import os
import tempfile

from atlas.kernel.context import ContextManager


def probe_thresholds() -> None:
    manager = ContextManager({"engine": {"max_output_tokens": 20_000}})
    normal = manager.thresholds(1_048_576)
    assert normal.effective_window == 1_028_576, normal
    assert normal.auto_compact == 1_015_576, normal
    assert normal.warning == 995_576, normal
    assert normal.blocking == 1_025_576, normal
    assert manager.thresholds(200_000).auto_compact != normal.auto_compact

    old = os.environ.get("ATLAS_AUTO_COMPACT_PCT")
    try:
        os.environ["ATLAS_AUTO_COMPACT_PCT"] = "1"
        overridden = manager.thresholds(1_048_576)
        assert overridden.auto_compact == 10_285, overridden
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


if __name__ == "__main__":
    probe_thresholds()
    probe_tool_output_clip()
    print("W1-2/W1-3 上下文和工具裁剪 probe PASS")

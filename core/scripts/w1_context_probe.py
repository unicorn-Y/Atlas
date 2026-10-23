"""Small focused probes for W1 context and compaction behavior."""

from __future__ import annotations

import os

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


if __name__ == "__main__":
    probe_thresholds()
    print("W1-2 自动压缩阈值 probe PASS")

"""Context pressure: the band a token count lands in, and the honesty of unknown.

The kernel's own watermarks are the source of truth here, so most of these
assert against ``ContextManager.thresholds`` rather than a hardcoded number:
a test that pins 149400 would break the day the reserve changes, without saying
anything true about the code.
"""

from __future__ import annotations

import pytest

from atlas.engine.agent import token_meter as tm
from atlas.engine.kernel.context import ContextManager


@pytest.fixture()
def marks():
    return ContextManager({}).thresholds(200_000)


def test_band_tracks_the_kernel_watermarks(marks):
    assert tm.measure(used=0, model_window=200_000)["pressure"] == "idle"
    assert tm.measure(used=marks.warning - 1, model_window=200_000)["pressure"] in {"roomy", "filling"}
    assert tm.measure(used=marks.warning, model_window=200_000)["pressure"] == "filling"
    assert tm.measure(used=marks.auto_compact, model_window=200_000)["pressure"] == "tight"
    assert tm.measure(used=marks.blocking, model_window=200_000)["pressure"] == "critical"


def test_bands_are_ordered_as_pressure_grows():
    seen = [
        tm.measure(used=used, model_window=200_000)["pressure"]
        for used in (1, 100_000, 150_000, 170_000, 190_000)
    ]
    indices = [tm.level_index(band) for band in seen]
    assert indices == sorted(indices)


def test_an_unknown_window_is_never_a_zero():
    """A missing window must not read as "plenty of room"."""
    result = tm.measure(used=5_000)
    assert result["pressure"] == "unknown"
    assert result["used_percent"] is None
    assert result["thresholds"] is None
    assert result["headroom"] == {}


def test_a_missing_used_count_is_unknown_even_with_a_window():
    assert tm.measure(model_window=200_000)["pressure"] == "unknown"


def test_a_collapsed_window_is_critical_not_roomy():
    """When the reserve swallows the window the kernel refuses the turn.

    Reporting "roomy" here would be the exact inverse of what happens next, so
    this case gets its own test rather than riding on the blocking comparison.
    """
    result = tm.measure(used=10, model_window=8_000)
    assert result["thresholds"]["blocking"] == 0
    assert result["pressure"] == "critical"


def test_garbage_input_does_not_raise():
    assert tm.measure(used="lots", model_window=200_000)["pressure"] == "unknown"
    assert tm.measure(used=100, model_window="big")["pressure"] == "unknown"
    assert tm.measure(used=100, model_window=-5)["pressure"] == "unknown"


def test_percent_is_clamped_and_rounded(marks):
    assert tm.measure(used=100_000, model_window=200_000)["used_percent"] == 50
    assert tm.measure(used=400_000, model_window=200_000)["used_percent"] == 100


def test_headroom_shrinks_to_zero_at_each_watermark(marks):
    result = tm.measure(used=marks.blocking, model_window=200_000)
    assert result["headroom"]["to_blocking"] == 0
    result = tm.measure(used=0, model_window=200_000)
    assert result["headroom"]["to_warning"] == marks.warning


def test_every_band_has_a_chinese_sentence():
    for band in tm.LEVELS:
        assert tm._SENTENCES[band]
    for used in (0, 100_000, 150_000, 170_000, 190_000):
        assert tm.measure(used=used, model_window=200_000)["sentence"]


def test_live_compressor_wins_over_an_explicit_used():
    """The compressor is the live object; a stale argument must not win."""

    class Compressor:
        last_prompt_tokens = 180_000
        context_length = 200_000

    result = tm.measure(used=1, compressor=Compressor())
    assert result["used_tokens"] == 180_000
    assert result["pressure"] == "critical"


def test_compressor_without_context_length_falls_back_to_config():
    class Compressor:
        last_prompt_tokens = 10_000
        context_length = 0
        config = {"context_window": 200_000}

    assert tm.measure(compressor=Compressor())["model_window"] == 200_000


def test_measure_session_reads_the_first_available_key():
    row = {"context_window": 200_000, "prompt_tokens": 150_000}
    assert tm.measure_session(row)["pressure"] == "filling"
    assert tm.measure_session({"context_tokens": 1, "context_window": 200_000})["pressure"] == "roomy"


def test_measure_session_without_a_window_is_unknown():
    assert tm.measure_session({"context_tokens": 150_000})["pressure"] == "unknown"


def test_level_index_sorts_unknown_first():
    assert tm.level_index("unknown") < tm.level_index("idle")
    assert tm.level_index("nonsense") == -1

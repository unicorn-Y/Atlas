"""Evidence for the two log/telemetry seams added in this round.

What is actually being proven here (and not more):

1. Rotation is byte-exact. A log archive that decompresses to something *almost*
   the same is worse than no archive, so the round-trip is compared to the real
   on-disk bytes, not to the string that was written (Windows rewrites ``\\n`` to
   ``\\r\\n`` and the naive comparison silently "fails" on a correct archive).
2. Telemetry is inert until configured, and a span attribute cannot carry a
   credential out of the process.

No test asserts on log text or export timing: both are incidental.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from atlas import log_rotation, secrets_store, telemetry


@pytest.mark.unit
def test_rotation_round_trips_exact_bytes() -> None:
    import zstandard

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "session.log"
        path.write_text("atlas log line\n" * 20_000, encoding="utf-8")
        on_disk = path.read_bytes()
        assert len(on_disk) > 50_000

        report = log_rotation.maintain_logs(tmp, max_bytes=50_000)

        assert len(report["rotated"]) == 1
        entry = report["rotated"][0]
        archive = Path(entry["archive"])
        assert archive.exists()
        assert path.read_bytes() == b""

        restored = zstandard.ZstdDecompressor().decompress(
            archive.read_bytes(), max_output_size=len(on_disk) + 1
        )
        assert restored == on_disk
        assert entry["original_bytes"] == len(on_disk)


@pytest.mark.unit
def test_rotation_skips_files_under_the_limit() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "small.log"
        path.write_text("short\n", encoding="utf-8")

        report = log_rotation.maintain_logs(tmp, max_bytes=1_000_000)

        assert report["rotated"] == []
        assert path.read_text(encoding="utf-8") == "short\n"
        assert list(Path(tmp).glob("*.zst")) == []


@pytest.mark.unit
def test_prune_removes_by_age_then_by_size() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        for index in range(3):
            (Path(tmp) / f"a{index}.log.zst").write_bytes(b"x" * 100)

        pruned = log_rotation.prune_archives(tmp, keep_days=14, keep_total_bytes=0)

        assert len(pruned["removed"]) == 3
        assert list(Path(tmp).glob("*.zst")) == []


@pytest.mark.unit
def test_telemetry_stays_disabled_without_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", raising=False)
    telemetry.shutdown()

    assert telemetry.setup_telemetry()["enabled"] is False
    assert telemetry.is_enabled() is False
    # A span with no provider must still be usable as a context manager.
    with telemetry.span("noop", {"a": 1}) as current:
        assert current is None
    assert telemetry.current_ids() == {}


@pytest.mark.unit
def test_span_attributes_never_carry_a_credential() -> None:
    secret = "sk-livekey0123456789abcdef"
    scrubbed = telemetry._scrub_attributes(
        {
            "api_key": secret,
            "authorization": f"Bearer {secret}",
            "prompt": f"my key is {secret} ok",
            "tool.count": 3,
            "ok": True,
        }
    )

    assert secret not in str(scrubbed)
    assert "api_key" in scrubbed
    assert scrubbed["tool.count"] == 3
    assert scrubbed["ok"] is True


@pytest.mark.unit
def test_scrub_bare_tokens_catches_unprefixed_credentials() -> None:
    github = "ghp_abcdefghijklmnopqrstuvwxyz0123"

    scrubbed = secrets_store.scrub_bare_tokens(f"token {github} end")

    assert github not in scrubbed
    assert scrubbed.startswith("token ")
    assert scrubbed.endswith(" end")


@pytest.mark.unit
def test_scrub_leaves_ordinary_text_and_counts_alone() -> None:
    text = "read 42 files from D:/Atlas and report the count"

    assert secrets_store.scrub(text) == text
    assert secrets_store.scrub(8192) == 8192

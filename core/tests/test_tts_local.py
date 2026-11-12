"""The local TTS model path, exercised without a 300 MB download.

``LocalTTS._download_blocking`` is the one branch in this module that a normal
unit run never reaches: it wants a real tarball off the network. What matters
about it is not the bytes but the contract around them — an already-installed
model must not re-download, a failed fetch must leave the object usable and
report why, and two concurrent callers must not both extract.

These tests therefore give the downloader a locally-built ``.tar.bz2`` served
through a patched ``urlopen``. That exercises the real streaming loop, the real
``Content-Length`` progress arithmetic and the real ``tarfile`` extraction,
because a fake that returns bytes bypasses exactly the code under test.
"""

from __future__ import annotations

import asyncio
import io
import tarfile

import pytest

from atlas import tts_local


def _tarball(files: dict[str, bytes]) -> bytes:
    """Build a real ``.tar.bz2`` whose members sit under ``MODEL_NAME/``."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:bz2") as tar:
        for name, payload in files.items():
            info = tarfile.TarInfo(f"{tts_local.MODEL_NAME}/{name}")
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


class _Response(io.BytesIO):
    """Enough of an ``http.client`` response for the streaming loop."""

    def __init__(self, payload: bytes) -> None:
        super().__init__(payload)
        self.headers = {"Content-Length": str(len(payload))}

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _engine(tmp_path, monkeypatch: pytest.MonkeyPatch) -> tts_local.LocalTTS:
    """A LocalTTS rooted in tmp_path instead of the live data directory."""
    engine = tts_local.LocalTTS()
    monkeypatch.setattr(engine, "root", tmp_path / "models" / "tts")
    return engine


def test_status_reports_what_is_missing(tmp_path, monkeypatch) -> None:
    engine = _engine(tmp_path, monkeypatch)
    monkeypatch.setattr(engine, "_sapi_available", lambda: False)
    status = engine.status()
    assert status["ready"] is False
    assert status["model"] is None
    assert status["model_url"] == tts_local.MODEL_URL
    assert status["speakers"] == 0


def test_status_offers_the_sapi_fallback(tmp_path, monkeypatch) -> None:
    """A machine with no model still has a voice when SAPI exists."""
    engine = _engine(tmp_path, monkeypatch)
    monkeypatch.setattr(engine, "_sapi_available", lambda: True)
    status = engine.status()
    assert status["ready"] is True
    assert status["engines"] == ["sapi"]
    assert status["model_url"] == tts_local.MODEL_URL


def test_download_extracts_the_model_and_reports_ready(tmp_path, monkeypatch) -> None:
    engine = _engine(tmp_path, monkeypatch)
    payload = _tarball({"model.onnx": b"weights", "voices.bin": b"voices"})
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *a, **k: _Response(payload),
    )
    assert engine.model_ready() is False

    result = asyncio.run(engine.download())

    assert result == {"ok": True, "already": False}
    assert engine.model_ready() is True
    assert (engine.root / tts_local.MODEL_NAME / "model.onnx").read_bytes() == b"weights"
    assert engine.downloading is False
    assert engine.progress == 1.0


def test_download_is_idempotent(tmp_path, monkeypatch) -> None:
    """A second call must not re-fetch; the tarball is large."""

    def _forbidden(*_a: object, **_k: object) -> None:
        raise AssertionError("re-downloaded a model that was already present")

    engine = _engine(tmp_path, monkeypatch)
    model = engine.root / tts_local.MODEL_NAME
    model.mkdir(parents=True)
    (model / "model.onnx").write_bytes(b"x")
    (model / "voices.bin").write_bytes(b"y")
    monkeypatch.setattr("urllib.request.urlopen", _forbidden)

    assert asyncio.run(engine.download()) == {"ok": True, "already": True}


def test_a_failed_download_is_reported_not_raised(tmp_path, monkeypatch) -> None:
    """TTS is optional: a network failure must not take a caller down."""

    def _boom(*_a: object, **_k: object) -> None:
        raise OSError("no route to host")

    engine = _engine(tmp_path, monkeypatch)
    monkeypatch.setattr("urllib.request.urlopen", _boom)

    result = asyncio.run(engine.download())

    assert result["ok"] is False
    assert "no route to host" in result["error"]
    assert engine.model_ready() is False
    # The lock and the flag must be released even on the failure path.
    assert engine.downloading is False


def test_a_corrupt_archive_leaves_no_half_installed_model(tmp_path, monkeypatch) -> None:
    engine = _engine(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *a, **k: _Response(b"not a tar.bz2 at all"),
    )

    result = asyncio.run(engine.download())

    assert result["ok"] is False
    assert engine.model_ready() is False


def test_concurrent_downloads_do_not_both_extract(tmp_path, monkeypatch) -> None:
    """The lock serialises callers; the second sees a ready model and skips."""
    calls: list[int] = []

    def _counting(*_a: object, **_k: object) -> _Response:
        calls.append(1)
        return _Response(_tarball({"model.onnx": b"w", "voices.bin": b"v"}))

    engine = _engine(tmp_path, monkeypatch)
    monkeypatch.setattr("urllib.request.urlopen", _counting)

    async def _both() -> list[dict[str, object]]:
        return await asyncio.gather(engine.download(), engine.download())

    first, second = asyncio.run(_both())

    assert first["ok"] is True and second["ok"] is True
    assert len(calls) == 1, "the second caller downloaded the same model again"
    assert {bool(r.get("already")) for r in (first, second)} == {True, False}


def test_pcm_to_wav_emits_a_valid_header(tmp_path) -> None:
    """The WAV writer is what every non-SAPI caller receives."""
    wav = tts_local.pcm_to_wav([0.0, 0.5, -0.5, 1.0], 24000)
    assert wav[:4] == b"RIFF"
    assert wav[8:12] == b"WAVE"
    # 4 samples * 2 bytes + 44-byte canonical header.
    assert len(wav) == 44 + 8

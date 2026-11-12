"""Offline text-to-speech.

Atlas already speaks through the cloud (a gateway ``/audio/speech`` route or
ElevenLabs). That covers most cases and fails for the important one: a user who
wants the assistant to read something aloud without the text leaving the machine.
This module is the offline path.

Two engines, tried in order:

* **sherpa-onnx** — same runtime the local ASR already uses, so the download and
  model-directory conventions are shared rather than duplicated. Multi-speaker
  Kokoro voices, Chinese and English.
* **Windows SAPI** — no model download at all, present on every Windows box. Lower
  quality, but it makes "can Atlas speak offline?" answer ``yes`` before any
  network call happens.

The module never raises out of ``synthesize``: callers get a dict with ``ok`` and,
on failure, the reason. A voice assistant that throws on a missing model is worse
than one that says it cannot speak.
"""

from __future__ import annotations

import asyncio
import io
import struct
import time
import wave
from pathlib import Path
from typing import Any

import structlog

from atlas.config import get_config

log = structlog.get_logger(__name__)

MODEL_NAME = "kokoro-zh-en-v0_19"
MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/"
    f"{MODEL_NAME}.tar.bz2"
)

_SAMPLE_RATES = {8000, 16000, 22050, 24000, 44100, 48000}


def pcm_to_wav(samples: list[float], sample_rate: int) -> bytes:
    """Wrap float samples in ``[-1, 1]`` as 16-bit mono WAV."""
    rate = sample_rate if sample_rate in _SAMPLE_RATES else 22050
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        frames = bytearray()
        for value in samples:
            clipped = max(-1.0, min(1.0, float(value)))
            frames += struct.pack("<h", int(clipped * 32767))
        handle.writeframes(bytes(frames))
    return buffer.getvalue()


class LocalTTS:
    """Lazy, single-process offline synthesizer."""

    def __init__(self) -> None:
        self.root = get_config().db_path.parent / "models" / "tts"
        self.downloading = False
        self.progress = 0.0
        self.detail = "本地语音尚未初始化。"
        self._tts: Any = None
        self._engine = ""
        self._last_used = 0.0
        self._lock = asyncio.Lock()

    # -- capability -------------------------------------------------------

    def _sapi_available(self) -> bool:
        if not hasattr(self, "_sapi_cache"):
            try:
                import win32com.client  # noqa: F401

                self._sapi_cache = True
            except Exception:  # noqa: BLE001 - absence is a valid answer
                self._sapi_cache = False
        return bool(self._sapi_cache)

    def model_ready(self) -> bool:
        model = self.root / MODEL_NAME
        return (model / "model.onnx").is_file() and (model / "voices.bin").is_file()

    def status(self) -> dict[str, Any]:
        """What can speak right now, and what is missing."""
        engines: list[str] = []
        if self.model_ready():
            engines.append("sherpa-onnx")
        if self._sapi_available():
            engines.append("sapi")
        return {
            "ready": bool(engines),
            "engines": engines,
            "model": MODEL_NAME if self.model_ready() else None,
            "model_url": MODEL_URL if not self.model_ready() else None,
            "downloading": self.downloading,
            "progress": round(self.progress, 3),
            "detail": self.detail,
            "speakers": self._speaker_count(),
        }

    def _speaker_count(self) -> int:
        if self._tts is None:
            return 0
        try:
            return int(self._tts.num_speakers)
        except Exception:  # noqa: BLE001
            return 0

    # -- model ------------------------------------------------------------

    async def download(self) -> dict[str, Any]:
        """Fetch the Kokoro model tarball. Idempotent and non-fatal."""
        async with self._lock:
            if self.model_ready():
                return {"ok": True, "already": True}
            self.downloading = True
            self.progress = 0.0
            self.detail = "正在下载本地语音模型…"
            try:
                await asyncio.to_thread(self._download_blocking)
                self.detail = "语音模型就绪。"
                return {"ok": True, "already": False}
            except Exception as exc:  # noqa: BLE001 - download is best effort
                self.detail = f"模型下载失败（{MODEL_URL}）：{type(exc).__name__}: {exc}"
                log.warning("tts.download_failed", error=str(exc))
                return {"ok": False, "error": self.detail}
            finally:
                self.downloading = False

    def _download_blocking(self) -> None:
        import tarfile
        import tempfile
        import urllib.request

        self.root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / f"{MODEL_NAME}.tar.bz2"
            with urllib.request.urlopen(MODEL_URL, timeout=120) as response:  # noqa: S310
                total = int(response.headers.get("Content-Length") or 0)
                done = 0
                with archive.open("wb") as handle:
                    while chunk := response.read(1024 * 256):
                        handle.write(chunk)
                        done += len(chunk)
                        if total:
                            self.progress = round(done / total, 3)
            with tarfile.open(archive, "r:bz2") as tar:
                # Python 3.12+ refuses to extract without an explicit filter.
                try:
                    tar.extractall(self.root, filter="data")  # noqa: S202
                except TypeError:
                    tar.extractall(self.root)  # noqa: S202
        self.progress = 1.0

    def _ensure_loaded(self) -> bool:
        """Build the recognizer once. Returns True when a sherpa engine is live."""
        if self._tts is not None:
            return True
        if not self.model_ready():
            return False
        try:
            import sherpa_onnx

            model = self.root / MODEL_NAME
            config = sherpa_onnx.OfflineTtsConfig(
                model=sherpa_onnx.OfflineTtsModelConfig(
                    kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
                        model=str(model / "model.onnx"),
                        voices=str(model / "voices.bin"),
                        tokens=str(model / "tokens.txt"),
                        data_dir=str(model / "espeak-ng-data"),
                    ),
                    num_threads=2,
                    provider="cpu",
                ),
            )
            self._tts = sherpa_onnx.OfflineTts(config)
            self._engine = "sherpa-onnx"
            return True
        except Exception as exc:  # noqa: BLE001 - fall through to SAPI
            self.detail = f"sherpa-onnx 初始化失败：{type(exc).__name__}: {exc}"
            log.warning("tts.init_failed", error=str(exc))
            self._tts = None
            return False

    # -- synthesis --------------------------------------------------------

    def synthesize_blocking(
        self, text: str, *, speaker: int = 0, speed: float = 1.0
    ) -> dict[str, Any]:
        """Produce WAV bytes. Runs the engine synchronously; call via to_thread."""
        text = (text or "").strip()
        if not text:
            return {"ok": False, "error": "文本为空", "engine": None}

        if self._ensure_loaded():
            try:
                audio = self._tts.generate(
                    text, sid=max(0, int(speaker)), speed=max(0.5, min(2.0, float(speed)))
                )
                data = pcm_to_wav(list(audio.samples), int(audio.sample_rate))
                self._last_used = time.monotonic()
                return {
                    "ok": True,
                    "engine": "sherpa-onnx",
                    "mime": "audio/wav",
                    "data": data,
                    "sample_rate": int(audio.sample_rate),
                    "duration_s": round(len(audio.samples) / max(1, audio.sample_rate), 2),
                }
            except Exception as exc:  # noqa: BLE001
                log.warning("tts.sherpa_failed", error=str(exc))
                self.detail = f"sherpa-onnx 合成失败：{type(exc).__name__}: {exc}"

        if self._sapi_available():
            result = self._sapi_synthesize(text)
            if result.get("ok"):
                return result
            return result

        return {
            "ok": False,
            "engine": None,
            "error": "没有可用的本地语音引擎：既没有下载模型，也没有 SAPI。",
            "hint": f"可用 tts.download 拉取 {MODEL_NAME}",
        }

    def _sapi_synthesize(self, text: str) -> dict[str, Any]:
        """Windows SAPI fallback: always offline, no model download.

        COM must be initialized per thread, and synthesis runs on a worker thread
        via ``asyncio.to_thread``, so the call would fail with "CoInitialize has
        not been called" without this. ``CoUninitialize`` is called only if this
        frame did the initialization, so a caller that already owned the apartment
        is not torn down underneath itself.
        """
        try:
            import tempfile

            import pythoncom
            import win32com.client

            pythoncom.CoInitialize()
            owns_com = True
        except Exception as exc:  # noqa: BLE001
            log.warning("tts.sapi_com_failed", error=str(exc))
            return {"ok": False, "engine": "sapi", "error": f"COM 初始化失败：{exc}"}

        owns_com = True
        try:
            voice = win32com.client.Dispatch("SAPI.SpVoice")
            stream = win32com.client.Dispatch("SAPI.SpFileStream")
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "out.wav"
                # 3 = SSFMCreateForWrite
                stream.Open(str(path), 3, False)
                voice.AudioOutputStream = stream
                voice.Speak(text)
                stream.Close()
                data = path.read_bytes()
            if not data:
                raise OSError("SAPI produced no audio")
            with wave.open(io.BytesIO(data), "rb") as handle:
                rate = handle.getframerate()
                frames = handle.getnframes()
            return {
                "ok": True,
                "engine": "sapi",
                "mime": "audio/wav",
                "data": data,
                "sample_rate": rate,
                "duration_s": round(frames / max(1, rate), 2),
            }
        except Exception as exc:  # noqa: BLE001
            log.warning("tts.sapi_failed", error=str(exc))
            return {"ok": False, "engine": "sapi", "error": f"SAPI 失败：{exc}"}
        finally:
            if owns_com:
                try:
                    pythoncom.CoUninitialize()
                except Exception as exc:  # noqa: BLE001 - teardown must not mask result
                    log.debug("tts.com_uninit_failed", error=str(exc))

    async def synthesize(
        self, text: str, *, speaker: int = 0, speed: float = 1.0
    ) -> dict[str, Any]:
        """Async wrapper; engine work is CPU-bound so it runs off the loop."""
        return await asyncio.to_thread(
            self.synthesize_blocking, text, speaker=speaker, speed=speed
        )


_MANAGER: LocalTTS | None = None


def get_local_tts() -> LocalTTS:
    """Process-wide manager, matching ``atlas.asr``'s lazy singleton style."""
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = LocalTTS()
    return _MANAGER

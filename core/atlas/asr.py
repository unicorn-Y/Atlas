# Filtering and idle-unload behavior adapted from NousResearch/hermes-agent@663362680b6ffa4fbffeb58f6682564239a1953b:
# tools/transcription_local.py and tools/transcription_common.py (MIT, (c) Nous Research).
# Model and VAD assets: official k2-fsa/sherpa-onnx ASR release, SenseVoice int8 2025-09-09
# and Silero VAD (Apache-2.0 runtime dependency sherpa-onnx); implementation is Atlas-local.
"""Local SenseVoice recognition and Silero VAD lifecycle."""

from __future__ import annotations

import asyncio
import array
import shutil
import tarfile
import time
import urllib.request
from pathlib import Path
from typing import Any

from atlas.config import get_config

MODEL_NAME = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09"
MODEL_URL = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/{MODEL_NAME}.tar.bz2"
VAD_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx"


def filter_transcription(text: str) -> str:
    value = " ".join((text or "").split())
    if len(value) < 2 or value.lower() in {"sil", "noise", "嗯", "啊"}:
        return ""
    if len(value) >= 8 and value[: len(value) // 2] == value[len(value) // 2 : len(value) // 2 * 2]:
        return ""
    return value


class ASRManager:
    def __init__(self) -> None:
        self.root = get_config().db_path.parent / "models" / "asr"
        self.progress = 0.0
        self.downloading = False
        self.detail = "模型尚未下载。"
        self._recognizer: Any = None
        self._vad: Any = None
        self._last_used = 0.0
        self._pending: list[float] = []
        self._partial_at = 0

    def status(self) -> dict[str, Any]:
        model = self.root / MODEL_NAME
        ready = (model / "model.int8.onnx").is_file() and (model / "tokens.txt").is_file() and (self.root / "silero_vad.onnx").is_file()
        if self._recognizer is not None and time.monotonic() - self._last_used > 600:
            self._recognizer = self._vad = None
        return {"ready": ready, "model": MODEL_NAME if ready else None,
                "downloading": self.downloading, "progress": round(self.progress, 3),
                "detail": self.detail}

    async def download(self) -> None:
        if self.downloading:
            return
        self.downloading = True
        self.progress = 0.0
        self.detail = "正在下载 SenseVoice 和 Silero VAD。"
        try:
            await asyncio.to_thread(self._download)
            self.progress = 1.0
            self.detail = "本地语音模型已准备就绪。"
        except Exception as exc:
            self.detail = f"模型下载失败：{exc}"
            raise
        finally:
            self.downloading = False

    def _download(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        archive = self.root / f"{MODEL_NAME}.tar.bz2"
        temporary = self.root / "silero_vad.onnx.part"

        def get(url: str, destination: Path, offset: float, span: float) -> None:
            with urllib.request.urlopen(url, timeout=60) as response, destination.open("wb") as output:
                total = int(response.headers.get("Content-Length", "0"))
                done = 0
                while block := response.read(1024 * 1024):
                    output.write(block)
                    done += len(block)
                    self.progress = offset + span * (done / total if total else 0)

        get(MODEL_URL, archive, 0, 0.95)
        stage = self.root / ".extracting"
        if stage.exists():
            shutil.rmtree(stage)
        stage.mkdir()
        with tarfile.open(archive, "r:bz2") as bundle:
            root = stage.resolve()
            for member in bundle.getmembers():
                target = (stage / member.name).resolve()
                if target != root and root not in target.parents:
                    raise ValueError("model archive contains an unsafe path")
                if member.isfile():
                    source = bundle.extractfile(member)
                    if source is None:
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with source, target.open("wb") as output:
                        shutil.copyfileobj(source, output)
        shutil.move(str(stage / MODEL_NAME), str(self.root / MODEL_NAME))
        stage.rmdir()
        get(VAD_URL, temporary, 0.95, 0.05)
        temporary.replace(self.root / "silero_vad.onnx")
        archive.unlink(missing_ok=True)

    def _load(self) -> None:
        import sherpa_onnx

        model_dir = self.root / MODEL_NAME
        self._recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(model_dir / "model.int8.onnx"),
            tokens=str(model_dir / "tokens.txt"),
            num_threads=2, use_itn=True, debug=False,
        )
        config = sherpa_onnx.VadModelConfig()
        config.silero_vad.model = str(self.root / "silero_vad.onnx")
        config.silero_vad.threshold = 0.5
        config.sample_rate = 16000
        self._vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=30)

    def _decode(self, samples: list[float]) -> str:
        if not samples:
            return ""
        if self._recognizer is None:
            self._load()
        stream = self._recognizer.create_stream()
        stream.accept_waveform(16000, samples)
        self._recognizer.decode_stream(stream)
        self._last_used = time.monotonic()
        return filter_transcription(stream.result.text)

    def process_frame(self, pcm: bytes, *, final: bool = False) -> tuple[list[str], list[str]]:
        if self._recognizer is None or self._vad is None:
            self._load()
        if len(pcm) % 2:
            raise ValueError("PCM frame must contain signed 16-bit samples")
        raw = array.array("h")
        raw.frombytes(pcm)
        samples = [sample / 32768.0 for sample in raw]
        if samples:
            self._vad.accept_waveform(samples)
            self._pending.extend(samples)
        self._last_used = time.monotonic()
        partials: list[str] = []
        if len(self._pending) - self._partial_at >= 8000:
            self._partial_at = len(self._pending)
            partial = self._decode(self._pending[-32000:])
            if partial:
                partials.append(partial)
        if final:
            self._vad.flush()
        finals: list[str] = []
        while not self._vad.empty():
            segment = self._vad.front
            text = self._decode(list(segment.samples))
            if text:
                finals.append(text)
            self._vad.pop()
        if final:
            if self._pending and not finals:
                text = self._decode(self._pending)
                if text:
                    finals.append(text)
            self._pending.clear()
            self._partial_at = 0
        return partials, finals

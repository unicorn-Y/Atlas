from __future__ import annotations

import io
import wave

import pytest

from atlas.asr import ASRManager
from atlas.channels.audio import enrich_audio_event
from atlas.channels.contract import Attachment, MessageEvent, MessageType
from atlas.channels.ingress import IngressQueue


def wav_bytes(*, rate: int = 8000, frames: int = 800, channels: int = 2) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(b"\x10\x00\xf0\xff" * frames)
    return output.getvalue()


def test_local_asr_converts_channel_wav_to_16000hz_mono(monkeypatch):
    manager = ASRManager()
    observed: list[float] = []
    monkeypatch.setattr(manager, "_decode", lambda samples: observed.extend(samples) or "识别结果")

    assert manager.transcribe_audio_bytes(wav_bytes()) == "识别结果"
    assert len(observed) == 1600
    assert observed[0] == pytest.approx(0)


async def test_first_use_prepares_missing_model_and_ffmpeg_only_for_compressed_audio(monkeypatch):
    manager = ASRManager()
    prepared: list[str] = []
    monkeypatch.setattr(manager, "status", lambda: {"ready": "model" in prepared})

    async def download():
        prepared.append("model")

    async def ffmpeg():
        prepared.append("ffmpeg")
        return manager.root / "ffmpeg.exe"

    def transcribe(payload: bytes) -> str:
        assert payload.startswith(b"RIFF")
        return "识别成功"

    monkeypatch.setattr(manager, "download", download)
    monkeypatch.setattr(manager, "ensure_ffmpeg", ffmpeg)
    monkeypatch.setattr(manager, "transcribe_audio_bytes", transcribe)
    assert await manager.transcribe_audio_bytes_async(wav_bytes(channels=1)) == "识别成功"
    assert prepared == ["model"]
    prepared.clear()
    monkeypatch.setattr(manager, "transcribe_audio_bytes", lambda _payload: "压缩音频识别成功")
    assert await manager.transcribe_audio_bytes_async(b"OggS compressed") == "压缩音频识别成功"
    assert prepared == ["model", "ffmpeg"]


async def test_audio_event_is_enriched_and_attachment_reference_remains(tmp_path):
    path = tmp_path / "voice.wav"
    path.write_bytes(wav_bytes(channels=1))
    attachment = Attachment(kind=MessageType.AUDIO, local_path=str(path), filename="voice.wav")
    event = MessageEvent(channel="telegram", account="", event_id="v1", chat_id="chat",
                         sender_id="user", kind=MessageType.AUDIO, text="请听一下", attachments=[attachment])

    async def transcribe(payload: bytes) -> str:
        assert payload.startswith(b"RIFF")
        return "明天下午三点开会"

    assert await enrich_audio_event(event, transcribe)
    assert "请听一下" in event.text
    assert "明天下午三点开会" in event.text
    assert event.attachments == [attachment]
    assert event.raw["_atlas_audio_transcription"]["status"] == "complete"


async def test_ingress_deduplicates_before_asr_and_persists_transcript(tmp_path):
    path = tmp_path / "queued.wav"
    path.write_bytes(wav_bytes(channels=1))
    event = MessageEvent(channel="telegram", account="", event_id="same", chat_id="c", sender_id="u",
                         kind=MessageType.AUDIO,
                         attachments=[Attachment(kind=MessageType.AUDIO, local_path=str(path))])
    queue = IngressQueue(tmp_path / "ingress.sqlite")
    assert queue.enqueue_inbound(event)
    calls = 0

    async def transcribe(_payload: bytes) -> str:
        nonlocal calls
        calls += 1
        return "持久化转写"

    await enrich_audio_event(event, transcribe)
    assert queue.update_inbound_event(event)
    assert not queue.enqueue_inbound(event)
    record = queue.claim_batch()[0]
    assert "持久化转写" in record.event.text
    assert calls == 1
    queue.close()


async def test_failed_transcription_keeps_attachment_and_explains_reason():
    attachment = Attachment(kind=MessageType.AUDIO, meta={"file_key": "fake-resource"})
    event = MessageEvent(channel="dingtalk", account="", event_id="v2", chat_id="c", sender_id="u",
                         kind=MessageType.AUDIO, attachments=[attachment])

    async def unavailable(_payload: bytes) -> str:
        raise RuntimeError("local model is not downloaded")

    async def downloader(_event, _attachment) -> bytes:
        return wav_bytes(channels=1)

    assert await enrich_audio_event(event, unavailable, downloader)
    assert "local model is not downloaded" in event.text
    assert "原始音频附件已保留" in event.text
    assert event.attachments == [attachment]
    assert event.raw["_atlas_audio_transcription"]["status"] == "failed"


async def test_upstream_transcript_is_not_replaced_or_transcribed():
    attachment = Attachment(kind=MessageType.AUDIO, meta={"transcript": "上游识别"})
    event = MessageEvent(channel="feishu", account="", event_id="v3", chat_id="c", sender_id="u",
                         kind=MessageType.AUDIO, text="上游识别", attachments=[attachment])

    async def should_not_run(_payload: bytes) -> str:
        raise AssertionError("upstream transcript must short-circuit ASR")

    assert not await enrich_audio_event(event, should_not_run)
    assert event.text == "上游识别"
    assert event.raw["_atlas_audio_transcription"]["status"] == "upstream"

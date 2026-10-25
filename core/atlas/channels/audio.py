"""Bounded local reads and transcription for inbound channel audio attachments."""

from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from atlas.channels.contract import Attachment, MessageEvent, MessageType

MAX_AUDIO_BYTES = 25 * 1024 * 1024


async def enrich_audio_event(event: MessageEvent, transcribe, download=None) -> bool:
    """Append a local transcript or a readable failure marker without dropping media."""
    if event.kind != MessageType.AUDIO and not any(item.kind == MessageType.AUDIO for item in event.attachments):
        return False
    if _upstream_transcript(event):
        event.raw.setdefault("_atlas_audio_transcription", {"status": "upstream", "text": "保留渠道已有转写"})
        return False
    audio = next((item for item in event.attachments if item.kind == MessageType.AUDIO), None)
    if audio is None:
        _append_note(event, "语音转写失败：消息标记为音频，但没有可用附件。")
        return True
    try:
        if not audio.local_path and not audio.url and callable(download):
            payload = await download(event, audio)
            if not isinstance(payload, bytes) or not payload:
                raise ValueError("渠道适配器没有返回音频字节")
            if len(payload) > MAX_AUDIO_BYTES:
                raise ValueError("音频附件超过 25 MiB 限制")
        else:
            payload = await _read_audio(audio)
        transcript = str(await transcribe(payload)).strip()
        if not transcript:
            raise ValueError("本地识别器没有识别出语音文本")
        _append_note(event, f"语音转写（本地）：\n{transcript}")
        event.raw["_atlas_audio_transcription"] = {"status": "complete"}
    except Exception as exc:  # noqa: BLE001 - adapter/network/decoder errors become message annotations
        reason = " ".join(str(exc).split())[:400] or type(exc).__name__
        _append_note(event, f"语音转写失败：{reason}。原始音频附件已保留。")
        event.raw["_atlas_audio_transcription"] = {"status": "failed", "reason": reason}
    return True


def _upstream_transcript(event: MessageEvent) -> bool:
    names = {"transcript", "transcription", "transcribed_text", "voice_text"}
    for attachment in event.attachments:
        if any(str(attachment.meta.get(name) or "").strip() for name in names):
            return True
    return any(str(event.raw.get(name) or "").strip() for name in names)


def _append_note(event: MessageEvent, note: str) -> None:
    event.text = f"{event.text.rstrip()}\n\n[{note}]" if event.text.strip() else f"[{note}]"


async def _read_audio(attachment: Attachment) -> bytes:
    if attachment.size is not None and attachment.size > MAX_AUDIO_BYTES:
        raise ValueError("音频附件超过 25 MiB 限制")
    if attachment.local_path:
        path = Path(attachment.local_path)
        if not path.is_file():
            raise ValueError("音频附件的本地文件不存在")
        if path.stat().st_size > MAX_AUDIO_BYTES:
            raise ValueError("音频附件超过 25 MiB 限制")
        return await asyncio.to_thread(path.read_bytes)
    url = attachment.url.strip()
    if not url:
        raise ValueError("渠道没有提供音频下载地址或本地文件")
    if urlsplit(url).scheme.lower() != "https":
        raise ValueError("音频下载地址必须使用 HTTPS")
    output = bytearray()
    timeout = httpx.Timeout(20.0, connect=8.0)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            async with client.stream("GET", url) as response:
                if response.status_code >= 400:
                    raise ValueError(f"音频附件下载失败 HTTP {response.status_code}")
                length = int(response.headers.get("content-length", "0") or 0)
                if length > MAX_AUDIO_BYTES:
                    raise ValueError("音频附件超过 25 MiB 限制")
                async for block in response.aiter_bytes():
                    output.extend(block)
                    if len(output) > MAX_AUDIO_BYTES:
                        raise ValueError("音频附件超过 25 MiB 限制")
    except httpx.HTTPError as exc:
        raise ValueError(f"HTTPS 音频下载失败：{type(exc).__name__}") from exc
    if not output:
        raise ValueError("渠道下载到的音频附件为空")
    return bytes(output)

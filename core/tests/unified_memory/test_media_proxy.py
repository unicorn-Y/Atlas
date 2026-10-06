"""T05.1 Atlas-side integration: controlled media via /api/unified-memory proxy.

UM05 第一环（受控媒体与原始片段）经 T01.3 代理面的真实双服务验证：

  * 上传透传：tmp 造**最小合法 PNG**（真 1×1 PNG 字节）与 **WAV**（手写 RIFF
    头 + 静音帧）→ POST /api/unified-memory/media（JSON b64 与原始字节两种
    承载）→ MemoryOS 受控入库（hash 去重、白名单裁决在服务端）→ asset_id；
  * 观察管线：media_refs=[{asset_id}] 的 USER_IMPORT 观察（WindowsSourceService.
    import_media_file 的真实构造：locator = 媒体 range 占位 + missing_extract
    说明「解析在 T05.2」，不造 caption）→ 经代理 observe → TEST 批直接形成 →
    经代理 evidence 回 locator（kind ∈ {AUDIO_RANGE, IMAGE_REGION, VIDEO_RANGE}）；
  * 文件流透传：GET /api/unified-memory/media/{asset_id}/content → 200 且字节
    与上传一致（Atlas 侧不落盘副本）；
  * 缺失屏障：受控文件删除后 content 路由 → 410 显式 missing 说明（不造 caption）；
  * 同码透传：live 引用 DELETE → 409；白名单外 mime → 422。

隔离规则同 harness：全部 TEST 事件类、主体 = atlas-fixture，不触生产路径。

运行：
  cd /d/Atlas && ATLAS_DATA_DIR= PYTHONUTF8=1 core/.venv/Scripts/python.exe \
    -m pytest core/tests/unified_memory -o addopts= -m 'unit or integration' -q
"""

from __future__ import annotations

import asyncio
import base64
import struct
import uuid
from pathlib import Path

import pytest
from atlas.memory.unified_client import UnifiedMemoryClient, observation_content_hash
from atlas.memory.windows_sources import WindowsSourceService

from tests.unified_memory.harness import ATLAS_API_TOKEN, TEST_INTERNAL_TOKEN, UMHarness

UID = uuid.uuid4().hex[:8]  # 本文件的资产/观察命名空间（会话级 harness 共库）

#: 最小合法 1×1 PNG（真实 IHDR/IDAT/IEND 结构，非任意字节）。
MIN_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xfc\xff"
    b"\xff?\x00\x05\xfe\x02\xfe\xa75\x81\x84\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _make_wav(frames: int = 16, rate: int = 8000) -> bytes:
    """手写合法 RIFF/WAVE：PCM16 单声道静音帧。"""
    data = b"\x00\x00" * frames
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
            + b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
            + b"data" + struct.pack("<I", len(data)) + data)


def _png_bytes(tag: str) -> bytes:
    return MIN_PNG + f"::{UID}::{tag}".encode("ascii")


def _wav_bytes(tag: str) -> bytes:
    return _make_wav() + f"::{UID}::{tag}".encode("ascii")


def _raw_post(harness: UMHarness, path: str, body: bytes, content_type: str):
    """原始字节 POST 到 Atlas 代理（harness.api 只发 JSON；上传需原样字节转发）。"""
    import httpx

    return httpx.request(
        "POST", harness.atlas_url + path, content=body,
        headers={"x-atlas-api-token": ATLAS_API_TOKEN,
                 "Content-Type": content_type}, timeout=30.0)


def test_media_upload_observe_evidence_roundtrip(um):
    """PNG 经代理上传 → media_refs 观察 → evidence 回 IMAGE_RANGE locator。"""
    tag = f"png-{UID}"
    data = _png_bytes(tag)
    body = (b'{"items": [{"data_b64": "'
            + base64.b64encode(data).decode("ascii").encode("ascii")
            + b'", "mime": "image/png"}]}')
    r = _raw_post(um, "/api/unified-memory/media", body, "application/json")
    assert r.status_code == 201, r.text
    asset = r.json()["assets"][0]
    asset_id = asset["asset_id"]
    assert asset_id.startswith("asset-")
    assert asset["relative_path"].startswith("media/")

    # 同内容重传 → 同 asset（服务端 hash 去重；Atlas 不做 hash、不落盘）
    replay = _raw_post(um, "/api/unified-memory/media", body, "application/json")
    assert replay.status_code == 200, replay.text
    assert replay.json()["assets"][0]["asset_id"] == asset_id
    assert replay.json()["duplicates"] == 1

    # 元数据代理（表驱动 JSON 透传）
    meta = um.api("GET", f"/api/unified-memory/media/{asset_id}")
    assert meta.status_code == 200, meta.text
    assert meta.json()["relative_path"] == asset["relative_path"]
    assert "content_hash" in meta.json()

    # 媒体观察（引用真实资产）→ TEST 批直接形成
    session = f"chat-media-proxy-{UID}"
    obs = {
        "source_event_id": f"atlas:ATLAS_TOOL_OBSERVATION:media-{tag}:1:UPSERT",
        "source_kind": "ATLAS_TOOL_OBSERVATION",
        "source_object_id": f"media-{tag}",
        "source_revision": "1",
        "event_action": "UPSERT",
        "occurred_at": "2026-10-12T22:10:00+08:00",
        "source_timezone": "Asia/Hong_Kong",
        "time_status": "KNOWN",
        "speaker_role": "TOOL",
        "epistemic_kind": "OBSERVED",
        "content": {"text": "", "kind": "IMAGE_REGION", "mime": "image/png",
                    "asset_id": asset_id},
        "locator": {"kind": "IMAGE_REGION", "value": f"shots/{tag}.png#120,40,400,60"},
        "media_refs": [{"asset_id": asset_id}],
        "derived_from": [],
    }
    obs["content_hash"] = observation_content_hash(obs)
    ack = um.api("POST", "/api/unified-memory/observe", json={
        "contract_version": "UM-WIN-1.0", "event_class": "TEST",
        "context": {**um.default_context(), "runtime_session_id": session},
        "observations": [obs]})
    # T01.3 代理面同码透传但成功态归一为 200（表驱动 JSONResponse 默认；
    # test_timeline_proxy 同语义）—— 判据看 ack 内容与 evidence。
    assert ack.status_code == 200, ack.text
    event_id = next(rz["event_id"] for rz in ack.json()["receipts"]
                    if rz["source_event_id"] == obs["source_event_id"])

    # 判据：evidence 回 locator ∈ 媒体枚举（经 Atlas 代理）
    evidence = um.api("GET", f"/api/unified-memory/evidence/episode:{event_id}")
    assert evidence.status_code == 200, evidence.text
    snippets = evidence.json()["snippets"]
    assert snippets, evidence.text
    assert snippets[0]["locator"]["kind"] in {"AUDIO_RANGE", "IMAGE_REGION",
                                              "VIDEO_RANGE"}
    assert snippets[0]["locator"]["kind"] == "IMAGE_REGION"

    # 文件流透传：字节一致（Atlas 不落盘副本）
    content = um.api("GET", f"/api/unified-memory/media/{asset_id}/content")
    assert content.status_code == 200, content.text
    assert content.content == data
    assert content.headers["content-type"].startswith("image/png")

    # live 引用 → DELETE 409 同码透传（共享媒体不误删）
    blocked = um.api("DELETE", f"/api/unified-memory/media/{asset_id}")
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["detail"]["error"] == "MEDIA_LIVE_REFERENCES"


def test_media_wav_import_via_windows_sources(um, tmp_path):
    """WAV 走 WindowsSourceService.import_media_file：受控资产 + 观察构造。

    捕获管线在 Atlas 子进程内；本测试在 pytest 进程内用真实 facade（指向
    harness 的 MemoryOS）驱动 import_media_file 的真实上传与观察构造，观察再
    经真实 /v1/unified/observe 落地 —— 不伪造 capture，不绕过服务端校验。
    """
    tag = f"wav-{UID}"
    data = _wav_bytes(tag)
    wav_path = tmp_path / f"meet-{tag}.wav"
    wav_path.write_bytes(data)

    real_facade = type("F", (), {})()  # 最小 facade 桩：client() → 真实客户端
    real_facade.client = lambda: UnifiedMemoryClient(
        service_url=um.memoryos_url, internal_token=TEST_INTERNAL_TOKEN,
        timeout=15.0)
    enqueued: list[dict] = []

    class _StubCapture:
        facade = real_facade

        @staticmethod
        def enqueue_observation(observation, *, context_overrides=None):
            enqueued.append({"observation": observation,
                             "context_overrides": context_overrides})
            return {"source_event_id": observation["source_event_id"],
                    "created": True}

    service = WindowsSourceService(
        capture=_StubCapture(), registry_path=tmp_path / "import_sources.json")
    result = asyncio.run(service.import_media_file(
        wav_path, root=str(tmp_path), duration_ms=32))
    assert result["status"] == "IMPORTED", result
    asset_id = result["asset_id"]
    assert result["locator"]["kind"] == "AUDIO_RANGE"
    assert result["locator"]["value"].endswith("#full"), "整文件占位区间（解析在 T05.2）"
    assert enqueued and enqueued[0]["observation"]["media_refs"] == [
        {"asset_id": asset_id, "hash": result["media_sha256"]}]
    observation = enqueued[0]["observation"]
    assert observation["content"]["missing_extract"]["reason"] == \
        "SEGMENT_PARSE_DEFERRED_T05_2"
    assert not observation["content"]["text"], "不造 caption/转录"

    # 幂等：同内容重导 → 同资产（服务端去重）+ 同 source_event_id
    result2 = asyncio.run(service.import_media_file(wav_path, root=str(tmp_path)))
    assert result2["asset_id"] == asset_id
    assert result2["asset_duplicate"] is True
    assert result2["source_event_id"] == result["source_event_id"]

    # 观察经真实 observe 落地（harness 注入 TEST context）→ evidence 回 locator
    ack = um.api("POST", "/v1/unified/observe", json={
        "contract_version": "UM-WIN-1.0", "event_class": "TEST",
        "observations": [observation]})
    assert ack.status_code == 201, ack.text
    event_id = next(rz["event_id"] for rz in ack.json()["receipts"]
                    if rz["source_event_id"] == observation["source_event_id"])
    evidence = um.api("GET", f"/api/unified-memory/evidence/episode:{event_id}")
    assert evidence.status_code == 200, evidence.text
    snippets = evidence.json()["snippets"]
    assert snippets[0]["locator"]["kind"] in {"AUDIO_RANGE", "IMAGE_REGION",
                                              "VIDEO_RANGE"}
    assert snippets[0]["locator"]["kind"] == "AUDIO_RANGE"


def test_media_missing_file_410_no_caption(um):
    """原媒体缺失：删受控文件后 content 路由 → 410 显式 missing，不造 caption。"""
    tag = f"miss-{UID}"
    data = _png_bytes(tag)
    body = (b'{"items": [{"data_b64": "'
            + base64.b64encode(data).decode("ascii").encode("ascii")
            + b'", "mime": "image/png"}]}')
    r = _raw_post(um, "/api/unified-memory/media", body, "application/json")
    assert r.status_code == 201, r.text
    asset = r.json()["assets"][0]
    asset_id = asset["asset_id"]

    # 白名单外 mime 同码透传（服务端裁决）
    bad = _raw_post(um, "/api/unified-memory/media",
                    b'{"items": [{"data_b64": "TWs=", '
                    b'"mime": "application/x-msdownload"}]}',
                    "application/json")
    assert bad.status_code == 422, bad.text
    assert bad.json()["detail"]["error"] == "MEDIA_MIME_UNSUPPORTED"

    stored = um.memoryos_data / asset["relative_path"]
    assert stored.is_file()
    stored.unlink()

    resp = um.api("GET", f"/api/unified-memory/media/{asset_id}/content")
    assert resp.status_code == 410, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "MEDIA_FILE_MISSING"
    assert detail["details"]["reason"] == "FILE_MISSING"
    # 显式 missing 说明；无伪造内容字段（caption/text/blob 一概没有）
    assert not ({"caption", "text", "data_b64", "content"} & set(detail))
    # 元数据仍可查（ACTIVE 行如实）；缺失只在读取面显式暴露
    assert um.api("GET", f"/api/unified-memory/media/{asset_id}").status_code == 200

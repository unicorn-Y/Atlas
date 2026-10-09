"""T05.2 Atlas-side integration: multimodal associate via /api/unified-memory proxy.

UM05 集成收口环（multimodal 关联入口经 T01.3 代理面的真实双服务验证）：

  * 上传 + 观察管线（同 test_media_proxy 形状）：最小合法 PNG → POST
    /api/unified-memory/media（原始字节经代理透传）→ asset_id；带文本的媒体
    派生观察（speaker_role=UNKNOWN / epistemic_kind=INFERRED —— T05.2 转录/
    OCR 纪律；media_refs=[asset_id]）→ 经代理 observe（TEST 批直接形成）。
  * 实体 seed：同 test_identity_proxy 模式 —— harness 不运行 MemoryOS 的
    graph worker，seed 子进程用 MemoryOS service 解释器对隔离库执行同样的
    确定性 ingest（不引入 LLM、不写第二套实体库）。
  * 任务判据：POST /api/unified-memory/multimodal/associate（表驱动透传 →
    MemoryOS ``multimodal.run_association_pass``）→ 200；返回**候选关联**
    （OCR 人名 ↔ PERSON 实体，只 PROPOSED 不自动确认）+ **等价组**（共享
    文本观察的媒体节点并查集聚组）；引用范围限定生效；幂等重放零新增。

隔离规则同 harness：全部 TEST 事件类、主体 = atlas-fixture，不触生产路径。

运行：
  cd /d/Atlas && ATLAS_DATA_DIR= PYTHONUTF8=1 core/.venv/Scripts/python.exe \
    -m pytest core/tests/unified_memory -o addopts= -m 'unit or integration' -q
"""

from __future__ import annotations

import base64
import json
import sqlite3
import subprocess
import uuid
from pathlib import Path

import pytest

from atlas.memory.unified_client import observation_content_hash

from tests.unified_memory.harness import ATLAS_API_TOKEN, MEMORYOS_REPO, UMHarness

SUBJECT = "atlas-fixture"          # harness 绑定主体（_memoryos_env）
UID = uuid.uuid4().hex[:8]         # 本文件的资产/观察/实体命名空间（会话级复用）
PERSON_NAME = "王小明"

#: 最小合法 1×1 PNG（真实 IHDR/IDAT/IEND 结构，非任意字节）。
MIN_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xfc\xff"
    b"\xff?\x00\x05\xfe\x02\xfe\xa75\x81\x84\x00\x00\x00\x00IEND\xaeB`\x82"
)

_SEED_SCRIPT = r'''
import json, sqlite3, sys
sys.path.insert(0, sys.argv[2])
import db as db_mod
from graph_store import ingest_graph_candidate

conn = sqlite3.connect(sys.argv[1], isolation_level=None, timeout=20)
conn.row_factory = sqlite3.Row
db_mod.init_schema(conn)
subject = sys.argv[3]
uid = sys.argv[4]
now = db_mod.now_iso()
mid = "mm-assoc-" + uid
seid = "atlas:ATLAS_USER_MESSAGE:%s:r1:UPSERT" % mid
conn.execute(
    "INSERT OR IGNORE INTO memories (id, schema_version, owner_id,"
    " memory_subject_id, record_type, revision, status, origin,"
    " source_refs_json, recorded_at, title, memory_type, created_at,"
    " updated_at, project_id, summary, why_valid)"
    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
    (mid, "0.1", "owner-fixture", subject, "MEMORY", 1, "ACTIVE", "test",
     json.dumps([{"source_event_id": seid}]), now, sys.argv[5], "FACT", now,
     now, None, "关联收口种子", None))
conn.execute(
    "INSERT OR IGNORE INTO evidence_events (event_id, source_event_id,"
    " owner_id, memory_subject_id, event_type, origin, observed_at,"
    " recorded_at, payload_json, content_hash) VALUES (?,?,?,?,?,?,?,?,?,?)",
    ("ev-" + mid, seid, "owner-fixture", subject, "OBSERVATION",
     "unified/ATLAS_USER_MESSAGE", now, now, "{}", "sha256:" + "0" * 64))
result = ingest_graph_candidate(conn, {
    "source_memory_id": mid,
    "entities": [{"local_id": "a", "type": "PERSON", "name": sys.argv[5],
                  "aliases": []}],
    "relations": []})
rows = conn.execute(
    "SELECT count(*) AS c FROM graph_entities WHERE memory_subject_id=?"
    " AND entity_type='PERSON'", (subject,)).fetchone()
conn.close()
print(json.dumps({"ok": True, "entity_ids": list(result["entity_ids"].values()),
                  "person_entities": int(rows["c"])}))
'''


def _raw_post(harness: UMHarness, path: str, body: bytes, content_type: str):
    """原始字节 POST 到 Atlas 代理（harness.api 只发 JSON；上传需原样字节转发）。"""
    import httpx

    return httpx.request(
        "POST", harness.atlas_url + path, content=body,
        headers={"x-atlas-api-token": ATLAS_API_TOKEN,
                 "Content-Type": content_type}, timeout=30.0)


def _seed_person_entity(harness: UMHarness, tmp_path: Path) -> str:
    """Deterministic graph ingest into the harness's isolated MemoryOS DB."""
    script = tmp_path / "um_multimodal_seed.py"
    script.write_text(_SEED_SCRIPT, encoding="utf-8")
    python = MEMORYOS_REPO / "service" / ".venv" / "Scripts" / "python.exe"
    db_path = harness.runtime_manifest["memoryos_db"]
    proc = subprocess.run(
        [str(python), str(script), str(db_path),
         str(MEMORYOS_REPO / "service"), SUBJECT, UID, PERSON_NAME],
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    assert proc.returncode == 0, f"seed 失败:\n{proc.stdout}\n{proc.stderr}"
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["ok"] is True and payload["person_entities"] >= 1
    return payload["entity_ids"][0]


def _context(harness: UMHarness) -> dict:
    # 重放/幂等要求 context 稳定：runtime_session_id 由运行命名空间派生。
    return {**harness.default_context(),
            "runtime_session_id": f"mm-assoc-{UID}"}


@pytest.mark.integration
@pytest.mark.frozen_v1(reason="F1-C: MemoryOS V1 multimodal association is explicitly frozen; proxy association returns MEMORY_V1_FEATURE_FROZEN.")
@pytest.mark.skip(reason="frozen_v1: MemoryOS V1 has no multimodal association implementation; retain this test for thaw-time verification.")
def test_associate_via_proxy_returns_candidates_and_groups(
        um: UMHarness, tmp_path: Path):
    """媒体 + 文本观察 → 经 Atlas 代理 associate → 200 候选关联 + 等价组。"""
    # 1) PNG 经代理上传（原始字节透传，hash 去重裁决在服务端）
    tag = f"assoc-{UID}"
    data = MIN_PNG + f"::{UID}".encode("ascii")
    body = (b'{"items": [{"data_b64": "'
            + base64.b64encode(data).decode("ascii").encode("ascii")
            + b'", "mime": "image/png"}]}')
    upload = _raw_post(um, "/api/unified-memory/media", body, "application/json")
    assert upload.status_code == 201, upload.text
    asset_id = upload.json()["assets"][0]["asset_id"]

    # 2) 实体 seed（MemoryOS service 解释器确定性 ingest 到 harness 隔离库）
    entity_id = _seed_person_entity(um, tmp_path)
    assert entity_id

    # 3) 带文本的媒体派生观察（T05.2 纪律：UNKNOWN/INFERRED，可回原片段）
    seid = f"atlas:ATLAS_TOOL_OBSERVATION:mm-assoc-{UID}:1:UPSERT"
    obs = {
        "source_event_id": seid,
        "source_kind": "ATLAS_TOOL_OBSERVATION",
        "source_object_id": f"mm-assoc-{UID}",
        "source_revision": "1",
        "event_action": "UPSERT",
        "occurred_at": "2026-10-13T10:00:00+08:00",
        "source_timezone": "Asia/Hong_Kong",
        "time_status": "KNOWN",
        "speaker_role": "UNKNOWN",
        "epistemic_kind": "INFERRED",
        "content": {"text": f"截图里{PERSON_NAME}在评审", "media_kind": "IMAGE_REGION"},
        "locator": {"kind": "IMAGE_REGION", "value": "0.1,0.1,0.5,0.4"},
        "media_refs": [{"asset_id": asset_id}],
        "derived_from": [],
    }
    obs["content_hash"] = observation_content_hash(obs)
    ack = um.api("POST", "/api/unified-memory/observe", json={
        "contract_version": "UM-WIN-1.0", "event_class": "TEST",
        "context": _context(um), "observations": [obs]})
    assert ack.status_code == 200, ack.text

    # 4) 判据：经代理 associate → 200，候选 + 等价组（引用范围限定生效）
    associated = um.api("POST", "/api/unified-memory/multimodal/associate", json={
        "context": _context(um),
        "media_refs": [asset_id],
        "source_event_ids": [seid]})
    assert associated.status_code == 200, associated.text
    receipt = associated.json()
    assert receipt["subject_id"] == SUBJECT
    assert receipt["nodes"]["media"] >= 1 and receipt["nodes"]["text"] >= 1
    candidates = [p for p in receipt["proposed"] if p["alias"] == PERSON_NAME]
    assert candidates, f"OCR 人名候选未返回: {receipt['proposed']}"
    assert candidates[0]["entity_id"] == entity_id
    assert candidates[0]["asset_id"] == asset_id, "候选锚定到请求媒体引用"
    assert candidates[0]["source_event_id"] == seid, "候选引用可回原证据事件"
    assert receipt["epistemic_discipline"]["never_user_asserted"] is True, \
        "OCR 推测绝不写用户断言；低置信关联只 PROPOSED 不自动确认"
    assert any(asset_id in members
               for members in receipt["equivalence_groups"].values()), \
        "等价组包含共享文本观察的媒体节点"

    # 5) 幂等重放：proposed 只报本轮新增 → 重放零新增（服务端确定性 pass
    #    幂等推进，不重复立候选）
    replay = um.api("POST", "/api/unified-memory/multimodal/associate", json={
        "context": _context(um),
        "media_refs": [asset_id],
        "source_event_ids": [seid]})
    assert replay.status_code == 200, replay.text
    assert replay.json()["proposed"] == [], "重放零新增（幂等推进）"

    # 6) 候选经代理 entities 读回：PROPOSED 别名如实（不冒充 VERIFIED）
    listed = um.api("GET", "/api/unified-memory/entities",
                    params={"query": PERSON_NAME})
    assert listed.status_code == 200, listed.text
    statuses = [alias["alias_status"] for item in listed.json()["items"]
                for alias in item["aliases"]
                if alias.get("alias") == PERSON_NAME]
    assert "PROPOSED" in statuses, statuses

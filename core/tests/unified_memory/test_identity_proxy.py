"""T03.1 Atlas-side integration: /api/unified-memory/entities proxy (UM03).

T01.3 的代理面是**表驱动透传**（core/atlas/api/unified_memory_router.py
``PROXY_ROUTES`` 已含 GET /entities 与 POST /entities/resolve），因此 MemoryOS
侧接线真实路由后代理自动跟随 —— 本文件验证的就是这条链路，不新增白名单：

  * 任务书判据（02_wave_tasks.md T03.1）经 Atlas 代理原样成立：
    两个同名「小王」→ GET /api/unified-memory/entities?query=小王 返回 200 且
    items == 2、id 互异（seed = 同名证据落图 + 显式 SPLIT 审定）。
  * POST /api/unified-memory/entities/resolve 代理透传（200 审定 + 409 同码
    revision 冲突映射）。

seed 方式：MemoryOS 侧图投影由既有确定性管线写入（graph_extraction_worker 的
ingest 步骤），harness 不运行该 worker，因此 seed 子进程直接用 MemoryOS service
解释器对 harness 隔离库执行同样的确定性 ingest（等价 worker 最终步骤；不引入
LLM、不写第二套实体库）。隔离规则同 harness：全部 TEST 主体 = atlas-fixture，
不触生产路径。

运行：
  cd /d/Atlas && ATLAS_DATA_DIR= PYTHONUTF8=1 core/.venv/Scripts/python.exe \
    -m pytest core/tests/unified_memory -o addopts= -m 'unit or integration' -q
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from tests.unified_memory.harness import MEMORYOS_REPO, UMHarness

SUBJECT = "atlas-fixture"          # harness 绑定主体（_memoryos_env）
UID = uuid.uuid4().hex[:8]         # 每次运行的种子命名空间（会话级 harness 复用）

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


def add_memory(mid, title, summary):
    seid = "atlas:ATLAS_USER_MESSAGE:%s:r1:UPSERT" % mid
    conn.execute(
        "INSERT OR IGNORE INTO memories (id, schema_version, owner_id,"
        " memory_subject_id, record_type, revision, status, origin,"
        " source_refs_json, recorded_at, title, memory_type, created_at,"
        " updated_at, project_id, summary, why_valid)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (mid, "0.1", "owner-fixture", subject, "MEMORY", 1, "ACTIVE", "test",
         json.dumps([{"source_event_id": seid}]), now, title, "FACT", now, now,
         None, summary, None))
    conn.execute(
        "INSERT OR IGNORE INTO evidence_events (event_id, source_event_id,"
        " owner_id, memory_subject_id, event_type, origin, observed_at,"
        " recorded_at, payload_json, content_hash) VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("ev-" + mid, seid, "owner-fixture", subject, "OBSERVATION",
         "unified/ATLAS_USER_MESSAGE", now, now, "{}", "sha256:" + "0" * 64))


def candidate(mid, name):
    return {"source_memory_id": mid,
            "entities": [{"local_id": "a", "type": "PERSON", "name": name,
                          "aliases": []}],
            "relations": []}


add_memory("h1-" + uid, "小王", "小王负责研发部的日常排期")
add_memory("h2-" + uid, "小王", "小王是客户公司的会计")
ingest_graph_candidate(conn, candidate("h1-" + uid, "小王"))
ingest_graph_candidate(conn, candidate("h2-" + uid, "小王"))
rows = conn.execute(
    "SELECT count(*) AS c FROM graph_entities WHERE memory_subject_id=?"
    " AND entity_type='PERSON'", (subject,)).fetchone()
conn.close()
print(json.dumps({"ok": True, "person_entities": int(rows["c"])}))
'''


def _seed_identity_graph(harness: UMHarness, tmp_path: Path) -> None:
    """Deterministic graph ingest into the harness's isolated MemoryOS DB."""
    script = tmp_path / "um_identity_seed.py"
    script.write_text(_SEED_SCRIPT, encoding="utf-8")
    python = MEMORYOS_REPO / "service" / ".venv" / "Scripts" / "python.exe"
    db_path = harness.runtime_manifest["memoryos_db"]
    proc = subprocess.run(
        [str(python), str(script), str(db_path),
         str(MEMORYOS_REPO / "service"), SUBJECT, UID],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, f"seed 失败:\n{proc.stdout}\n{proc.stderr}"
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["ok"] is True and payload["person_entities"] >= 1


def _context(harness: UMHarness) -> dict:
    # 重放/幂等要求 context 稳定：runtime_session_id 由运行命名空间派生。
    return {**harness.default_context(), "runtime_session_id": f"identity-{UID}"}


@pytest.mark.integration
def test_identity_proxy_same_name_is_not_same_person(um: UMHarness, tmp_path: Path):
    """任务书判据（T03.1）经 Atlas 代理成立：同名两人 → 2 items 互异 id。"""
    _seed_identity_graph(um, tmp_path)

    r = um.api("GET", "/api/unified-memory/entities", params={"query": "小王"})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1, "同名证据在显式 SPLIT 前只是一个 provisional 簇"
    entity_id = items[0]["id"]
    mention_ids = [m["mention_id"] for m in items[0]["mentions"]
                   if m["source_memory_id"] == "h2-" + UID]
    assert mention_ids

    # 显式 SPLIT：用户指认两个「小王」是不同人（经代理 POST 透传）。
    r = um.api("POST", "/api/unified-memory/entities/resolve", json={
        "context": _context(um), "action": "SPLIT", "alias": "小王",
        "entity_id": entity_id, "mention_ids": mention_ids,
        "source_refs": [{"source_event_id":
                         f"atlas:ATLAS_USER_MESSAGE:h2-{UID}:r1:UPSERT"}],
    })
    assert r.status_code == 200, r.text
    new_entity_id = r.json()["new_entity_id"]
    assert new_entity_id != entity_id

    r = um.api("GET", "/api/unified-memory/entities", params={"query": "小王"})
    assert r.status_code == 200
    entities = r.json()["items"]
    assert len(entities) == 2 and len({x["id"] for x in entities}) == 2
    assert {entity_id, new_entity_id} == {x["id"] for x in entities}


@pytest.mark.integration
def test_identity_proxy_resolve_error_passthrough(um: UMHarness, tmp_path: Path):
    """resolve 代理错误同码透传：expected_revisions 不符 → 409（RevisionConflict
    映射保持）；无来源 refs → 422（ContractViolation 映射保持）。"""
    _seed_identity_graph(um, tmp_path)
    r = um.api("GET", "/api/unified-memory/entities", params={"query": "小王"})
    assert r.status_code == 200
    entity_id = r.json()["items"][0]["id"]
    refs = [{"source_event_id": f"atlas:ATLAS_USER_MESSAGE:h1-{UID}:r1:UPSERT"}]

    r = um.api("POST", "/api/unified-memory/entities/resolve", json={
        "context": _context(um), "action": "VERIFY_ALIAS", "alias": "老王",
        "entity_id": entity_id, "expected_revisions": {entity_id: 999},
        "source_refs": refs})
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["error"] == "REVISION_CONFLICT"

    r = um.api("POST", "/api/unified-memory/entities/resolve", json={
        "context": _context(um), "action": "VERIFY_ALIAS", "alias": "老王2",
        "entity_id": entity_id, "source_refs": []})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "SOURCE_REFS_REQUIRED"

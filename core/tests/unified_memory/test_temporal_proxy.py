"""T03.2 Atlas-side integration: /api/unified-memory/recall as_of via proxy (UM03).

T01.3 的代理面是**表驱动透传**（core/atlas/api/unified_memory_router.py
``PROXY_ROUTES`` 已含 POST /recall），请求体原样转发（facade.call 不改写 body），
因此 MemoryOS 侧 T03.2 的 as_of 三分类接线后代理自动跟随 —— 本文件验证：

  * 经 Atlas 代理 recall（无 as_of，CURRENT）→ 只返回当前有效集（深圳；
    北京的旧区间 [2025-01-01, 2026-08-01) 已过期，不进 context_items）；
  * 经代理 recall as_of=2025-06-01（HISTORICAL）→ 返回北京、不含深圳；
  * as_of=2026-09-01 → 返回深圳（两时刻 valid 集不同 —— 任务要求原样）；
  * naive as_of（无时区）→ 422 INVALID_TEMPORAL_QUERY 同码透传。

seed 方式：formation（UM04）未接线，STATE 投影由 seed 子进程直接写 harness
隔离库（等价「已判定语义的形成记录」；T03.2 只提供区间执行与查询语义）。
隔离规则同 harness：全部 TEST 主体 = atlas-fixture，不触生产路径。

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

conn = sqlite3.connect(sys.argv[1], isolation_level=None, timeout=20)
conn.row_factory = sqlite3.Row
db_mod.init_schema(conn)
subject = sys.argv[3]
uid = sys.argv[4]
now = db_mod.now_iso()
HKT = "Asia/Hong_Kong"


def add_state_memory(mid, value, summary, valid_from, valid_to, recorded_at):
    seid = "atlas:ATLAS_USER_MESSAGE:%s:r1:UPSERT" % mid
    extra = {"unified": {
        "facet": "STATE",
        "content": {"value": value, "topic": "residence"},
        "epistemic_kind": "USER_ASSERTED",
        "valid_time": {
            "valid_from": valid_from, "valid_to": valid_to,
            "time_status": "KNOWN", "source_timezone": HKT,
            "basis": "用户声明搬迁；区间左闭右开（seed temporal）",
        },
        "dependencies": [],
    }}
    conn.execute(
        "INSERT OR IGNORE INTO memories (id, schema_version, owner_id,"
        " memory_subject_id, record_type, revision, status, origin,"
        " source_refs_json, recorded_at, title, memory_type, created_at,"
        " updated_at, valid_from, valid_to, project_id, summary, why_valid,"
        " extra_json)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (mid, "0.1", "owner-fixture", subject, "MEMORY", 1, "ACTIVE", "test",
         json.dumps([{"source_event_id": seid}]), recorded_at,
         "residence-" + uid, "STATE", now, now, valid_from, valid_to,
         None, summary, None, db_mod.canonical_json(extra)))


# 深圳为当前（[2026-08-01, ∞)）；北京为旧有效段（[2025-01-01, 2026-08-01)）
add_state_memory(
    "tp-sz-" + uid, "深圳", "现在我住在深圳，住哪都记录清楚" + uid,
    "2026-08-01T00:00:00+08:00", None, "2026-08-01T00:00:00+08:00")
add_state_memory(
    "tp-bj-" + uid, "北京",
    "现在回看，那时住哪都记得：2025 年住在北京" + uid,
    "2025-01-01T00:00:00+08:00", "2026-08-01T00:00:00+08:00",
    "2025-01-01T00:00:00+08:00")
rows = conn.execute(
    "SELECT count(*) AS c FROM memories WHERE memory_subject_id=? AND memory_type='STATE'",
    (subject,)).fetchone()
conn.close()
print(json.dumps({"ok": True, "state_memories": int(rows["c"])}))
'''


def _seed_temporal_state(harness: UMHarness, tmp_path: Path) -> None:
    """Deterministic STATE memory seeding into the harness's isolated MemoryOS DB."""
    script = tmp_path / "um_temporal_seed.py"
    script.write_text(_SEED_SCRIPT, encoding="utf-8")
    python = MEMORYOS_REPO / "service" / ".venv" / "Scripts" / "python.exe"
    db_path = harness.runtime_manifest["memoryos_db"]
    proc = subprocess.run(
        [str(python), str(script), str(db_path),
         str(MEMORYOS_REPO / "service"), SUBJECT, UID],
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    assert proc.returncode == 0, f"seed 失败:\n{proc.stdout}\n{proc.stderr}"
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["ok"] is True and payload["state_memories"] >= 2


def _recall_via_proxy(harness: UMHarness, **extra: dict) -> dict:
    body = {
        # 代理不注入 context（facade.call 原样转发）—— 主体用 harness 绑定主体；
        # 重放/幂等不涉此处，runtime_session_id 稳定派生即可。
        "context": {**harness.default_context(),
                    "runtime_session_id": f"temporal-proxy-{UID}"},
        "query": "现在住哪里",
        "purpose": "CONVERSATION",
        **extra,
    }
    r = harness.api("POST", "/api/unified-memory/recall", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _values(payload: dict) -> list:
    return [item.get("content", {}).get("value") for item in payload["context_items"]
            if isinstance(item.get("content"), dict)]


@pytest.mark.integration
def test_temporal_proxy_as_of_two_moments_return_different_valid_sets(
        um: UMHarness, tmp_path: Path):
    """经代理 recall：当前只有深圳；as_of 旧时刻只有北京（两时刻 valid 集不同）。"""
    _seed_temporal_state(um, tmp_path)

    current = _recall_via_proxy(um)
    assert "深圳" in _values(current)
    assert "北京" not in _values(current), "过期的北京记录不进当前 context_items"
    assert current["freshness"]["query_time_mode"] == "CURRENT"

    historical = _recall_via_proxy(um, as_of="2025-06-01T00:00:00+08:00")
    assert "北京" in _values(historical)
    assert "深圳" not in _values(historical), "as_of 时刻深圳尚未开始有效"
    assert historical["freshness"]["query_time_mode"] == "HISTORICAL"

    later = _recall_via_proxy(um, as_of="2026-09-01T00:00:00+08:00")
    assert "深圳" in _values(later)
    assert "北京" not in _values(later)
    assert _values(historical) != _values(later), "两个 as_of 时刻返回不同 valid 集"


@pytest.mark.integration
def test_temporal_proxy_naive_as_of_is_rejected_422(um: UMHarness, tmp_path: Path):
    """naive as_of（无时区）→ 服务端 422 INVALID_TEMPORAL_QUERY，代理同码透传。"""
    _seed_temporal_state(um, tmp_path)
    body = {
        "context": {**um.default_context(),
                    "runtime_session_id": f"temporal-proxy-bad-{UID}"},
        "query": "现在住哪里",
        "purpose": "CONVERSATION",
        "as_of": "2026-10-06T12:00:00",
    }
    r = um.api("POST", "/api/unified-memory/recall", json=body)
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "INVALID_TEMPORAL_QUERY"

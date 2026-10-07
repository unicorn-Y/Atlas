"""T01.2 验收测试：legacy 迁移 + 旧 API 兼容委托（Atlas 侧）。

判据（02_wave_tasks T01.2）：
  * unit：MemoryStore(tmp.db, unified=fake_facade) 时 set_fact 不落本地库且 fake
    收到 observe；unified=None 时行为与旧版一致（对照 test_memory.py 断言）；
  * 集成（um harness）：临时旧库 → export_legacy.py 导出 → import_legacy.py 导入
    MemoryOS → /v1/unified/records 按 legacy_ref 读回且 content_hash 一致；
    重放导入 created=0、record_map 相同（任务书判据 test_legacy_import_is_idempotent
    原样：h.seed 两次，由 harness.seed 的真实导入路径承载）；
  * 数量核对：summary.json 行数 == 服务端 records 计数（legacy locator 前缀过滤）。

运行：
  cd /d/Atlas && core/.venv/Scripts/python.exe -m pytest core/tests/unified_memory \\
      -o addopts= -m 'unit or integration' -q
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from atlas.memory import MemoryStore
from atlas.memory.unified_client import FeatureNotReady
from tests.unified_memory.harness import MEMORYOS_REPO, TEST_INTERNAL_TOKEN, UMHarness

REPO_ROOT = Path(__file__).resolve().parents[3]
EXPORT_SCRIPT = REPO_ROOT / "scripts" / "unified_memory" / "export_legacy.py"
IMPORT_SCRIPT = MEMORYOS_REPO / "scripts" / "unified_memory" / "import_legacy.py"
MEMORYOS_PYTHON = MEMORYOS_REPO / "service" / ".venv" / "Scripts" / "python.exe"

#: 与 MemoryOS db.canonical_json / unified.legacy 相同的规范序列化规则（对账锚点）
def canonical_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash_of(content: dict) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(content).encode("utf-8")).hexdigest()


# ================================================================== unit：委托

class FakeUnifiedFacade:
    """记录委托调用的假 facade（不带 HTTP；只验证委托语义与本地写关闭）。"""

    def __init__(self) -> None:
        self.observed: list[dict] = []
        self.corrected: list[dict] = []
        self.outcomes: list[dict] = []
        self.enabled = True

    async def observe_batch(self, batch: dict) -> dict:
        self.observed.append(batch)
        return {"created": len(batch.get("observations", [])),
                "duplicates": 0, "receipts": []}

    def client(self) -> "FakeUnifiedFacade":
        return self

    async def correct(self, request: dict) -> dict:
        self.corrected.append(request)
        return {"ok": True}

    async def record_outcome(self, request: dict) -> dict:
        self.outcomes.append(request)
        return {"ok": True}

    async def list_records(self, *, status: str | None = None, cursor: str | None = None, limit: int = 50) -> dict:
        return {"records": [], "next_cursor": None}


@pytest.fixture
async def unified_store(tmp_path: Path):
    fake = FakeUnifiedFacade()
    store = MemoryStore(db_path=tmp_path / "unified.db", unified=fake)
    await store.init()
    yield store, fake
    await store.close()


@pytest.fixture
async def plain_store(tmp_path: Path):
    store = MemoryStore(db_path=tmp_path / "plain.db")
    await store.init()
    yield store
    await store.close()


async def _scalar(store: MemoryStore, sql: str) -> int:
    cursor = await store._db.execute(sql)
    row = await cursor.fetchone()
    return int(row[0])


@pytest.mark.unit
class TestUnifiedDelegation:
    async def test_set_fact_delegates_and_skips_local_write(self, unified_store):
        store, fake = unified_store
        await store.set_fact("theme", "dark", category="preference")
        assert len(fake.observed) == 1, "delegation 必须走 facade.observe_batch"
        obs = fake.observed[0]["observations"][0]
        assert obs["source_event_id"].startswith("atlas:USER_IMPORT:fact-theme:")
        assert obs["content"]["key"] == "theme" and obs["content"]["value"] == "dark"
        assert obs["epistemic_kind"] == "USER_ASSERTED"
        assert await _scalar(store, "SELECT COUNT(*) FROM facts") == 0, \
            "unified 存在时不得本地写 facts"

    async def test_set_fact_without_unified_keeps_local_write(self, plain_store):
        await plain_store.set_fact("theme", "dark", category="preference")
        cursor = await plain_store._db.execute(
            "SELECT value, category FROM facts WHERE key = 'theme'")
        row = await cursor.fetchone()
        assert row is not None and row[0] == "dark" and row[1] == "preference"

    async def test_delete_fact_delegates_to_corrections(self, unified_store):
        store, fake = unified_store
        result = await store.delete_fact("theme")
        assert result is True
        assert fake.corrected and fake.corrected[0]["action"] == "DELETE"
        assert fake.corrected[0]["selector"] == {
            "kind": "LEGACY", "value": "legacy:facts:theme"}

    async def test_add_and_delete_knowledge_delegate(self, unified_store):
        store, fake = unified_store
        entry_id = await store.add_knowledge("条目", source="", category="general")
        assert entry_id
        assert len(fake.observed) == 1
        obs = fake.observed[0]["observations"][0]
        assert obs["source_object_id"] == f"knowledge-{entry_id}"
        assert obs["epistemic_kind"] == "INFERRED", "无来源知识不得伪造成用户断言"
        removed = await store.delete_knowledge(entry_id)
        assert removed is True
        assert fake.corrected[-1]["selector"] == {
            "kind": "LEGACY", "value": f"legacy:knowledge:{entry_id}"}
        cursor = await store._db.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='knowledge'")
        table_exists = int((await cursor.fetchone())[0])
        if table_exists:
            assert await _scalar(store, "SELECT COUNT(*) FROM knowledge") == 0, \
                "unified 存在时不得本地写 knowledge"

    async def test_promote_and_reject_candidate_delegate(self, unified_store):
        store, fake = unified_store
        assert await store.promote_memory_candidate("cand-1") is True
        assert fake.corrected[-1]["action"] == "PROMOTE_CANDIDATE"
        assert await store.reject_memory_candidate("cand-2") is True
        assert fake.corrected[-1]["action"] == "REJECT_CANDIDATE"
        assert await _scalar(store, "SELECT COUNT(*) FROM memory_candidates") == 0

    async def test_set_commitment_status_delegates(self, unified_store):
        store, fake = unified_store
        assert await store.set_commitment_status("c:1", "fulfilled", "msg-1") is True
        request = fake.corrected[-1]
        assert request["action"] == "SET_COMMITMENT_STATUS"
        assert request["status"] == "fulfilled"
        assert request["source_message_id"] == "msg-1"

    async def test_agent_reflection_and_recovery_delegate(self, unified_store):
        store, fake = unified_store
        reflection_id = await store.record_agent_reflection(
            category="tool", component="terminal", summary="命令失败",
            resolution_hint="检查 PATH", source_conversation_id="c1",
            source_run_id="r1", model=None)
        assert reflection_id
        obs = fake.observed[-1]["observations"][0]
        assert obs["source_object_id"] == f"agent-reflection-{reflection_id}"
        assert obs["epistemic_kind"] == "INFERRED"
        assert await _scalar(store, "SELECT COUNT(*) FROM agent_reflections") == 0
        await store.mark_agent_reflections_recovered("r1")
        assert fake.outcomes and fake.outcomes[-1]["result"] == "UNKNOWN", \
            "未验证自报不得 SUCCEEDED"

    async def test_record_goal_outcome_delegates_to_outcomes(self, unified_store):
        store, fake = unified_store
        outcome_id = await store.record_goal_outcome(
            goal_id="g1", goal="完成任务", status="completed",
            evaluation={"satisfied": True, "evidence": "e", "reason": "r"},
            steps=[{"id": "s1", "title": "第一步", "status": "done", "evidence": "e"}],
            source_conversation_id="c1", source_run_id="r1")
        assert outcome_id
        assert fake.outcomes and fake.outcomes[-1]["result"] == "UNKNOWN"
        assert await _scalar(store, "SELECT COUNT(*) FROM goal_outcomes") == 0

    async def test_governance_lifecycle_writes_closed_with_unified(self, unified_store):
        store, _fake = unified_store
        with pytest.raises(FeatureNotReady):
            await store.review_goal_experience("outcome-1", approved=True)
        with pytest.raises(FeatureNotReady):
            await store.evaluate_goal_knowledge_refinements()

    async def test_audit_correction_stays_local_per_authority_map(self, unified_store):
        store, fake = unified_store
        # AUDIT_ONLY 保留本地审计：直接造本地事实行（写路径已委托，不经 set_fact）
        await store._db.execute(
            "INSERT INTO facts (key, value) VALUES ('audit-k', 'v')")
        await store._db.commit()
        fake.observed.clear()
        feedback_id = await store.record_memory_correction("audit-k")
        assert feedback_id
        assert fake.observed == [], "AUDIT_ONLY 方法不产生统一观察"
        assert await _scalar(
            store, "SELECT COUNT(*) FROM memory_feedback WHERE signal='correction'") == 1

    async def test_extract_candidates_delegate_to_observe(self, unified_store):
        store, fake = unified_store
        transcript = [{"role": "user", "id": "m1",
                       "content": "I prefer dark theme for coding"}]
        rows = await store.extract_conversation_candidates(
            "conv-1", transcript=transcript)
        assert len(rows) == 1 and rows[0]["status"] == "pending"
        assert rows[0]["key"] == "user_preference"
        assert len(fake.observed) == 1, "候选队列走统一 CANDIDATE 生命周期"
        assert await _scalar(
            store, "SELECT COUNT(*) FROM memory_candidates") == 0

    async def test_extract_candidates_without_unified_keeps_local_queue(self, plain_store):
        transcript = [{"role": "user", "id": "m1",
                       "content": "I prefer dark theme for coding"}]
        rows = await plain_store.extract_conversation_candidates(
            "conv-1", transcript=transcript)
        assert len(rows) == 1
        cursor = await plain_store._db.execute("SELECT COUNT(*) FROM memory_candidates")
        assert (await cursor.fetchone())[0] == 1


# ================================================================== 集成：导出→导入→读回

def _build_legacy_db(db_path: Path) -> dict[str, int]:
    """用真实 MemoryStore 写入代表性 legacy 样本（facts/knowledge/反思/历史/目标经验）。"""

    async def build() -> dict[str, int]:
        store = MemoryStore(db_path=db_path)
        await store.init()
        await store.set_fact("um-theme", "dark", category="preference")
        await store.set_fact("um-editor", "vim")
        await store.add_knowledge("Atlas 记忆栈 SQLite+FTS5", source="docs")
        await store.record_agent_reflection(
            category="tool", component="terminal", summary="导出失败",
            resolution_hint="检查路径", source_conversation_id="c1",
            source_run_id="r1", model=None)
        await store._db.execute(
            "INSERT INTO memory_candidates (id, key, value, category, confidence, status,"
            " source_conversation_id, source_message_id)"
            " VALUES ('um-cand-sup', 'k', '旧值', 'general', 0.9, 'superseded', 'c1', 'm1')")
        await store._db.execute(
            "INSERT INTO memory_fact_history (key, value, category, confidence, event_type)"
            " VALUES ('um-theme', 'light', 'preference', 1.0, 'superseded')")
        await store._db.execute(
            "INSERT INTO goal_outcomes (id, goal_id, goal, status, evaluation_json,"
            " steps_json, source_conversation_id, source_run_id, experience_status)"
            " VALUES ('um-go-1', 'g1', '完成任务', 'completed', '{}', '[]', 'c1', 'r1',"
            " 'approved')")
        await store._db.execute(
            "INSERT INTO goal_knowledge (id, source_outcome_id, source_goal_id, goal,"
            " outcome_status, evaluation_json, evidence_json, source_conversation_id,"
            " source_run_id, source_approval_status, source_approved_at)"
            " VALUES ('um-gk-1', 'um-go-1', 'g1', '完成任务', 'completed', '{}', '{}',"
            " 'c1', 'r1', 'approved', '2026-01-01T00:00:00')")
        await store._db.commit()
        counts = {}
        for table in ("facts", "knowledge", "agent_reflections", "memory_candidates",
                      "memory_fact_history", "goal_outcomes", "goal_knowledge"):
            cursor = await store._db.execute(f"SELECT COUNT(*) FROM {table}")
            counts[table] = int((await cursor.fetchone())[0])
        await store.close()
        return counts

    return asyncio.run(build())


def _run_export(db_path: Path, out_dir: Path) -> dict:
    proc = subprocess.run(
        [sys.executable, str(EXPORT_SCRIPT), "--db", str(db_path),
         "--out", str(out_dir), "--subject", "atlas-fixture"],
        capture_output=True, text=True, timeout=120,
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))


def _run_import(export_dir: Path, harness: UMHarness,
                extra_args: list[str] | None = None) -> tuple[int, dict]:
    proc = subprocess.run(
        [str(MEMORYOS_PYTHON), str(IMPORT_SCRIPT),
         "--input", str(export_dir),
         "--service-url", harness.memoryos_url,
         "--token", TEST_INTERNAL_TOKEN,
         "--subject", "atlas-fixture",
         "--event-class", "TEST",
         *(extra_args or [])],
        capture_output=True, text=True, timeout=180,
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    result_path = export_dir / "import_result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    return proc.returncode, result


def _legacy_records(harness: UMHarness) -> list[dict]:
    items: list[dict] = []
    cursor: str | None = None
    while True:
        response = harness.api(
            "GET", "/v1/unified/records",
            params={"limit": 200, **({"cursor": cursor} if cursor else {})})
        assert response.status_code == 200, response.text
        body = response.json()
        items.extend(body["items"])
        cursor = body.get("next_cursor")
        if not cursor:
            break
    return [item for item in items
            if isinstance(item.get("content"), dict)
            and str(item["content"].get("legacy_ref") or "").startswith("legacy:")]


@pytest.mark.integration
def test_legacy_export_import_roundtrip_idempotent_and_counts(um: UMHarness, tmp_path):
    """迁移判据：只读导出 → 幂等导入 → legacy_ref 读回 + 哈希一致 + 重放 created=0。"""
    db_path = tmp_path / "legacy-atlas.db"
    local_counts = _build_legacy_db(db_path)
    export_dir = tmp_path / "export"
    summary = _run_export(db_path, export_dir)
    expected_rows = sum(local_counts.values())
    assert summary["total_rows"] == expected_rows, "summary 行数必须等于旧库行数"
    assert summary["grounding_rule"] == "LEGACY_UNGROUNDED"

    code_first, first = _run_import(export_dir, um)
    assert code_first == 0, first
    assert first["created"] == expected_rows
    assert len(first["record_map"]) == expected_rows

    # 读回：按 legacy_ref 逐条核对内容哈希 + 状态映射
    records = {item["content"]["legacy_ref"]: item for item in _legacy_records(um)}
    lines: list[dict] = []
    for jsonl in sorted(export_dir.glob("*.jsonl")):
        lines.extend(json.loads(l) for l in
                     jsonl.read_text(encoding="utf-8").splitlines() if l.strip())
    for line in lines:
        record = records[line["legacy_ref"]]
        assert record["lifecycle"] == line["lifecycle"], \
            f"{line['legacy_ref']} 生命周期映射不一致"
        assert record["epistemic_kind"] == line["epistemic_kind"]
        assert record["content"]["legacy_ungrounded"] == "LEGACY_UNGROUNDED"
        assert content_hash_of(record["content"]["legacy_content"]) == line["content_hash"], \
            f"{line['legacy_ref']} 内容哈希不一致"
    superseded = [line for line in lines
                  if line["content"]["legacy_status"] == "superseded"]
    assert superseded, "夹具必须包含历史/失效记录"
    for line in superseded:
        assert records[line["legacy_ref"]]["lifecycle"] == "SUPERSEDED"

    # 数量核对：summary 行数 == 服务端 legacy 记录计数
    assert len(records) == expected_rows

    # 重放导入：created=0、record_map 逐条一致
    code_replay, replay = _run_import(export_dir, um)
    assert code_replay == 0, replay
    assert replay["created"] == 0, "重放导入必须 created=0"
    assert replay["duplicates"] == expected_rows
    assert replay["record_map"] == first["record_map"]

    # verify 模式：逐条 content_hash 对账一致
    code_verify, verify = _run_import(export_dir, um, extra_args=["--verify"])
    assert code_verify == 0, verify
    assert verify["verify"]["consistent"] is True
    assert verify["verify"]["matched"] == expected_rows


@pytest.mark.integration
def test_legacy_import_is_idempotent(um: UMHarness):
    """任务书判据原样（h.seed 语义，经 harness.seed 的真实导入路径两次执行）。"""
    first = um.seed("legacy")
    assert first["ingested"] is True, first.get("ingest_error")
    second = um.seed("legacy")
    assert second["created"] == 0
    assert first["record_map"] == second["record_map"]


@pytest.mark.integration
def test_seed_import_visible_via_records(um: UMHarness):
    """seed 导入的 legacy 记录必须能从 /v1/unified/records 按 legacy_ref 读回。"""
    seeded = um.seed("legacy")
    assert seeded["ingested"] is True
    records = _legacy_records(um)
    refs = {item["content"]["legacy_ref"] for item in records}
    assert refs, "seed 导入后必须有 legacy 记录可读"
    for receipt_ref in seeded["record_map"].values():
        assert receipt_ref.startswith(("memory:", "episode:"))
    assert seeded["record_map"]

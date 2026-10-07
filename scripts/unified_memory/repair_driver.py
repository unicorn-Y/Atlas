"""修复施工的真实执行器（施工包 R02 契约）：``run_case(case_id, variant, mode, artifact_dir)``。

设计原则（R02「Produces」+ 03 验收门）：

- 每个变体执行**真实 dispatch**（component=真实函数；integration=真实函数链/真实服务），
  返回**实际观测**结果，而不是期望结果；
- 未知 case_id / variant / mode、缺真实能力 → ``executed=False`` 且 ``status="FAILED"``
  （等价非零退出语义），绝不静默通过；
- 执行器**不读 oracle**（评测真值），不根据记忆替产品作答；``oracle_accessed_by_product``
  恒为 False，并由独立验证器断言；
- 每次把原始输入/输出/差分写入 ``artifact_dir``，返回结构化 dict。

``run_case`` 返回字段（R01/R02 测试共用契约）::

    {
      "case_id": "R01-A", "variant": "A", "mode": "integration",
      "executed": True, "verifier_id": "RV_R01_A",
      "status": "PASSED" | "FAILED",
      "failures": [...], "evidence_refs": [...],
      "oracle_accessed_by_product": False,
      "artifact_dir": "...",
    }
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
MEMORYOS_SERVICE = Path("D:/MemoryOS/service")

SUBJECT = "subject-default"
CONTEXT = {
    "owner_id": "owner-local",
    "memory_subject_id": SUBJECT,
    "client_id": "atlas-desktop",
    "actor_id": "atlas-main",
    "runtime_session_id": "repair-driver",
    "task_id": "task-repair",
    "project_id": "proj-default",
    "environment_id": "windows-test",
    "model_deployment_id": "local-repair-driver",
}


def _ensure_service_on_path() -> None:
    if str(MEMORYOS_SERVICE) not in sys.path:
        sys.path.insert(0, str(MEMORYOS_SERVICE))


def _fresh_conn(tmp: Path) -> sqlite3.Connection:
    _ensure_service_on_path()
    import db as db_mod  # type: ignore

    db_file = tmp / "repair_driver.sqlite3"
    conn = sqlite3.connect(str(db_file), isolation_level=None)
    conn.row_factory = sqlite3.Row
    db_mod.init_schema(conn)
    return conn


def _mods() -> dict[str, Any]:
    _ensure_service_on_path()
    from unified import maintenance  # type: ignore

    return {"maintenance": maintenance}


# ---------------------------------------------------------------- 来源写入助手

def _insert_user_commitment_source(
    conn: sqlite3.Connection,
    *,
    record_id: str,
    source_object_id: str,
    text: str,
    lifecycle: str = "ACTIVE",
    source_kind: str = "ATLAS_USER_MESSAGE",
) -> str:
    """写入一条**用户来源**的承诺观察（含显式 record 声明）。返回 source_event_id。"""
    _ensure_service_on_path()
    import db as db_mod  # type: ignore

    now = db_mod.now_iso()
    seid = f"atlas:{source_kind}:{source_object_id}:1:UPSERT"
    content = {
        "text": text,
        "record": {
            "facet": "COMMITMENT",
            "record_id": record_id,
            "commitment_type": "SHORT_TERM",
        },
    }
    conn.execute(
        "INSERT INTO evidence_events (event_id, source_event_id, owner_id, memory_subject_id, "
        "event_type, origin, observed_at, payload_json, recorded_at, content_hash) "
        "VALUES (?, ?, 'owner-local', ?, 'OBSERVATION', ?, ?, ?, ?, ?)",
        (f"ev-{source_object_id}", seid, SUBJECT, source_kind, now,
         db_mod.canonical_json(content), now, f"sha256:{source_object_id}"),
    )
    conn.execute(
        "INSERT INTO unified_source_objects (subject_id, source_kind, source_object_id, "
        "source_revision, content_hash, source_event_id, locator_json, lifecycle, "
        "occurred_at, recorded_at) VALUES (?, ?, ?, '1', ?, ?, '{}', ?, ?, ?)",
        (SUBJECT, source_kind, source_object_id, f"sha256:{source_object_id}", seid,
         lifecycle, now, now),
    )
    return seid


def _commitments(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(
        "SELECT id, status, origin FROM commitments WHERE memory_subject_id = ?",
        (SUBJECT,),
    ).fetchall()]


# ---------------------------------------------------------------- 变体实现

def _r01_a(tmp: Path) -> dict[str, Any]:
    """R01-A：零证据隔离库跑普通维护与 LONGITUDINAL_CHECK → 事实/承诺新增 0。"""
    conn = _fresh_conn(tmp)
    m = _mods()["maintenance"]
    before = len(_commitments(conn))
    res_check = m.dispatch_maintenance(conn, CONTEXT, {"job_type": "LONGITUDINAL_CHECK"})
    res_maint = m.dispatch_maintenance(conn, CONTEXT, {"job_type": "MAINTENANCE"})
    after = len(_commitments(conn))
    facts = conn.execute(
        "SELECT COUNT(*) FROM memories WHERE memory_subject_id = ?", (SUBJECT,)
    ).fetchone()[0]
    failures: list[str] = []
    if before != 0 or after != 0:
        failures.append(f"零证据库产生了承诺记录: before={before} after={after}")
    if facts != 0:
        failures.append(f"零证据库产生了 memories 行: {facts}")
    if res_check.get("preserved_commitments"):
        failures.append(f"LONGITUDINAL_CHECK 伪报承诺: {res_check['preserved_commitments']}")
    return {
        "observations": {
            "commitments_before": before, "commitments_after": after,
            "memories_rows": facts,
            "longitudinal_status": res_check.get("status"),
            "longitudinal_source_refs": res_check.get("source_refs"),
            "maintenance_status": res_maint.get("status"),
        },
        "failures": failures,
    }


def _r01_b(tmp: Path) -> dict[str, Any]:
    """R01-B：只有 THIRD_PARTY 文章包含承诺 → 不得 USER_ASSERTED，不得投影。"""
    conn = _fresh_conn(tmp)
    m = _mods()["maintenance"]
    _insert_user_commitment_source(
        conn, record_id="tp-commit", source_object_id="tp-art-001",
        text="某文章声称某人答应过某事。", source_kind="THIRD_PARTY_ARTICLE",
    )
    created = m.ensure_longitudinal_commitments(conn, SUBJECT)
    rows = _commitments(conn)
    failures: list[str] = []
    if created:
        failures.append(f"第三方来源被投影为用户承诺: {[c['record_ref'] for c in created]}")
    if rows:
        failures.append(f"第三方来源产生了 commitments 行: {rows}")
    return {
        "observations": {"created": created, "commitments": rows},
        "failures": failures,
    }


def _r01_c(tmp: Path) -> dict[str, Any]:
    """R01-C：来源被撤回（lifecycle != ACTIVE）后再维护 → 不得 ACTIVE。"""
    conn = _fresh_conn(tmp)
    m = _mods()["maintenance"]
    _insert_user_commitment_source(
        conn, record_id="cmt-c", source_object_id="src-c",
        text="跟团队说好了：周三前给出方案。",
    )
    created = m.ensure_longitudinal_commitments(conn, SUBJECT)
    active_before = [c for c in _commitments(conn) if c["status"] == "ACTIVE"]
    # 撤回来源
    conn.execute(
        "UPDATE unified_source_objects SET lifecycle = 'DELETED' WHERE subject_id = ? AND source_object_id = ?",
        (SUBJECT, "src-c"),
    )
    m.ensure_longitudinal_commitments(conn, SUBJECT)
    active_after = [c for c in _commitments(conn) if c["status"] == "ACTIVE"]
    failures: list[str] = []
    if not created:
        failures.append("有有效来源时未投影出承诺（前置条件不成立）")
    if not active_before:
        failures.append("投影后承诺未处于 ACTIVE（前置条件不成立）")
    if active_after:
        failures.append(f"来源撤回后承诺仍 ACTIVE: {active_after}")
    return {
        "observations": {
            "created": [c["record_ref"] for c in created],
            "active_before": [c["id"] for c in active_before],
            "active_after": [c["id"] for c in active_after],
            "all_after": _commitments(conn),
        },
        "failures": failures,
    }


def _r01_d(tmp: Path) -> dict[str, Any]:
    """R01-D：同一 snapshot 重试维护 → 无重复、无自动通过策略。"""
    conn = _fresh_conn(tmp)
    m = _mods()["maintenance"]
    _insert_user_commitment_source(
        conn, record_id="cmt-d", source_object_id="src-d",
        text="跟团队说好了：下周一交初稿。",
    )
    first = m.dispatch_maintenance(conn, CONTEXT, {"job_type": "MAINTENANCE"})
    rows1 = _commitments(conn)
    second = m.dispatch_maintenance(conn, CONTEXT, {"job_type": "MAINTENANCE"})
    rows2 = _commitments(conn)
    # POLICY_TRIAL 无真实收据 → 不得自动激活
    trial = m.dispatch_maintenance(conn, CONTEXT, {"job_type": "POLICY_TRIAL"})
    strategies_active = conn.execute(
        "SELECT COUNT(*) FROM unified_strategies WHERE subject_id = ? AND lifecycle = 'ACTIVE'",
        (SUBJECT,),
    ).fetchone()[0]
    failures: list[str] = []
    if len(rows1) != len(rows2):
        failures.append(f"重试产生重复承诺: {len(rows1)} -> {len(rows2)}")
    if len({r['id'] for r in rows2}) != len(rows2):
        failures.append("承诺 id 重复")
    if strategies_active != 0:
        failures.append(f"POLICY_TRIAL 无真实收据却激活了策略: {strategies_active}")
    if trial.get("status") == "COMPLETED" and trial.get("activation"):
        failures.append(f"无收据的策略试验被标记为已完成并激活: {trial}")
    return {
        "observations": {
            "commitments_first": len(rows1), "commitments_second": len(rows2),
            "maintenance_first_status": first.get("status"),
            "maintenance_second_status": second.get("status"),
            "policy_trial_status": trial.get("status"),
            "policy_trial_verdict": trial.get("verdict"),
            "strategies_active": strategies_active,
        },
        "failures": failures,
    }


def _r01_e(tmp: Path) -> dict[str, Any]:
    """R01-E：从真实 maintenance API 入口调用并保存来源查询与入库前后差分。"""
    conn = _fresh_conn(tmp)
    m = _mods()["maintenance"]
    _insert_user_commitment_source(
        conn, record_id="cmt-e", source_object_id="src-e",
        text="跟团队说好了：本周五之前冻结接口。",
    )
    before_rows = _commitments(conn)
    before_sources = [dict(r) for r in conn.execute(
        "SELECT source_object_id, lifecycle FROM unified_source_objects WHERE subject_id = ?",
        (SUBJECT,),
    ).fetchall()]
    res = m.dispatch_maintenance(conn, CONTEXT, {"job_type": "LONGITUDINAL_CHECK"})
    after_rows = _commitments(conn)
    after_sources = [dict(r) for r in conn.execute(
        "SELECT source_object_id, lifecycle FROM unified_source_objects WHERE subject_id = ?",
        (SUBJECT,),
    ).fetchall()]
    failures: list[str] = []
    if res.get("job_type") != "LONGITUDINAL_CHECK":
        failures.append(f"未从真实 maintenance 入口返回 LONGITUDINAL_CHECK: {res.get('job_type')}")
    if not res.get("preserved_commitments"):
        failures.append("有来源却未投影出承诺（preserved_commitments 为空）")
    # source_refs 必须来自真实来源，而不是固定字符串
    src_refs = res.get("source_refs") or []
    if not src_refs:
        failures.append("source_refs 未反映真实来源")
    for s in src_refs:
        if "lon-cmt-001" in str(s):
            failures.append(f"source_refs 出现硬编码夹具 id: {s}")
    if before_sources != after_sources:
        failures.append("维护过程改动了来源对象（应只读来源）")
    return {
        "observations": {
            "before_commitments": [c["id"] for c in before_rows],
            "after_commitments": [c["id"] for c in after_rows],
            "source_objects": after_sources,
            "maintenance_result": res,
            "diff": {"added": [c["id"] for c in after_rows if c["id"] not in {b["id"] for b in before_rows}]},
        },
        "failures": failures,
    }


CASES: dict[str, dict[str, Callable[[Path], dict[str, Any]]]] = {
    "R01": {"A": _r01_a, "B": _r01_b, "C": _r01_c, "D": _r01_d, "E": _r01_e},
}

SUPPORTED_MODES = {"component", "integration"}


def run_case(
    *,
    case_id: str,
    variant: str,
    mode: str = "integration",
    artifact_dir: Path | str,
) -> dict[str, Any]:
    """执行一个修复变体，返回真实观测结果（见模块 docstring 的字段契约）。"""
    artifact_dir = Path(artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    full_case_id = f"{case_id}-{variant}"
    verifier_id = f"RV_{case_id}_{variant}"
    base = {
        "case_id": full_case_id,
        "variant": variant,
        "mode": mode,
        "executed": False,
        "verifier_id": verifier_id,
        "status": "FAILED",
        "failures": [],
        "evidence_refs": [],
        "oracle_accessed_by_product": False,
        "artifact_dir": str(artifact_dir),
    }

    if case_id not in CASES:
        base["failures"] = [f"未知 case_id: {case_id}"]
        return base
    if variant not in CASES[case_id]:
        base["failures"] = [f"未知 variant: {variant}"]
        return base
    if mode not in SUPPORTED_MODES:
        base["failures"] = [f"未实现的 mode: {mode}"]
        return base

    tmp = artifact_dir / "_db"
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        result = CASES[case_id][variant](tmp)
    except Exception as exc:  # 真实执行失败 → 明确失败，不补字段
        base["executed"] = True
        base["failures"] = [f"执行异常: {type(exc).__name__}: {exc}"]
        (artifact_dir / "error.txt").write_text(repr(exc), encoding="utf-8")
        return base

    base["executed"] = True
    base["failures"] = list(result.get("failures") or [])
    base["status"] = "PASSED" if not base["failures"] else "FAILED"

    evidence = artifact_dir / "evidence.json"
    evidence.write_text(
        json.dumps({"case_id": full_case_id, "mode": mode, "observations": result.get("observations")},
                   ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    base["evidence_refs"] = [str(evidence)]
    base["observations"] = result.get("observations")
    return base

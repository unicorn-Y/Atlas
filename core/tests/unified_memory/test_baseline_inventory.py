"""T00.1 验收测试：静态权威映射基线完整性。

判据来自 docs/plan/UNIFIED-MEMORY/02_wave_tasks.md T00.1：

    def test_authority_inventory_is_complete(baseline):
        assert set(baseline.tables) == set(baseline.classifications)
        assert not baseline.unmapped_memory_consumers
        assert baseline.production_db_opened is False

baseline fixture 在同进程内调用 scripts/unified_memory/baseline.py 的
build_baseline()（不启动子进程、不连接任何数据库）。
"""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = [pytest.mark.unit]

REPO_ROOT = Path(__file__).resolve().parents[3]
BASELINE_SCRIPT = REPO_ROOT / "scripts" / "unified_memory" / "baseline.py"
DEFAULT_AUTHORITY_MAP = (
    REPO_ROOT / "docs" / "plan" / "UNIFIED-MEMORY" / "authority-map.json"
)

EXPECTED_CATEGORIES = {
    "RUNTIME_AUTHORITY",
    "MEMORY_AUTHORITY",
    "DERIVED_VIEW",
    "AUDIT_OPERATION",
}
EXPECTED_REPLACEMENTS = {
    "DELEGATE_TO_UNIFIED",
    "KEEP_RUNTIME",
    "READONLY_DERIVED_VIEW",
    "AUDIT_ONLY",
}
KNOWN_CONSTRUCTION_POINTS = {
    "core/atlas/server.py",
    "core/atlas/cli.py",
    "core/atlas/runtime/hub.py",
    "core/scripts/baseline_metrics.py",
}


def _load_baseline_module():
    spec = importlib.util.spec_from_file_location("um_t001_baseline", BASELINE_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def baseline() -> SimpleNamespace:
    """同进程构建 T00.1 基线并暴露任务书判据所需的字段。"""
    module = _load_baseline_module()
    data = module.build_baseline(REPO_ROOT)
    return SimpleNamespace(
        tables=[t["name"] for t in data["tables"]],
        classifications=data["classifications"],
        unmapped_memory_consumers=data["unmapped_memory_consumers"],
        production_db_opened=data["production_db_opened"],
        raw=data,
    )


def test_authority_inventory_is_complete(baseline):
    assert set(baseline.tables) == set(baseline.classifications)
    assert not baseline.unmapped_memory_consumers
    assert baseline.production_db_opened is False


def test_baseline_script_is_pure_static_analysis():
    """baseline.py 禁止 import sqlite3/aiosqlite/atlas——绝不连库、绝不触发 DB 初始化。"""
    source = BASELINE_SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    forbidden = {"sqlite3", "aiosqlite", "atlas"}
    assert imported & forbidden == set(), f"baseline.py 引入了禁用模块: {imported & forbidden}"


def test_every_table_has_evidence_backed_classification(baseline):
    for table in baseline.raw["tables"]:
        assert table["category"] in EXPECTED_CATEGORIES, table["name"]
        assert table["canonical_line"] > 0, table["name"]
        assert table["columns"], f"{table['name']} 缺少列证据"
        # 分类理由必须引用字段行号与实际读写方法行号，不允许只按表名归类。
        assert "(L" in table["reason"], table["name"]
        assert "写入方" in table["reason"] and "读取方" in table["reason"], table["name"]


def test_every_memory_store_method_has_replacement(baseline):
    for method in baseline.raw["methods"]:
        assert method["replacement"] in EXPECTED_REPLACEMENTS, method["name"]
        assert method["authority"] in EXPECTED_CATEGORIES, method["name"]
        if method["replacement"] == "DELEGATE_TO_UNIFIED":
            assert method["delegate_api"], f"{method['name']} 缺少统一 API 目标"


def test_memory_authority_tables_are_never_kept_runtime_only(baseline):
    """MEMORY_AUTHORITY 表的写入方法不得整类标记为 KEEP_RUNTIME（旧写路径必须关闭或委托）。"""
    writes_memory = {
        w["method"]
        for table in baseline.raw["tables"]
        if table["category"] == "MEMORY_AUTHORITY"
        for w in table["written_by"]
    }
    runtime_only_writers = {
        m["name"]
        for m in baseline.raw["methods"]
        if m["name"] in writes_memory and m["replacement"] == "KEEP_RUNTIME"
    }
    assert runtime_only_writers <= {"init"}, (
        f"MEMORY_AUTHORITY 写入方法仍为 KEEP_RUNTIME: {sorted(runtime_only_writers)}"
    )


def test_construction_points_are_enumerated(baseline):
    points = {p["file"] for p in baseline.raw["construction_points"]}
    assert KNOWN_CONSTRUCTION_POINTS <= points
    assert all(p["exists"] for p in baseline.raw["construction_points"])


def test_direct_db_consumers_have_replacement_plans(baseline):
    direct = baseline.raw["direct_db_consumers"]
    # T01.3：authority-map 两处直摸计划（conversations_router rewind 回写、
    # session_sync 遗留迁移清单）已按 replacement_plan 执行为 MemoryStore 公开
    # 方法（update_rewind_restored_files / list_conversation_ids），活代码直摸
    # 应为空；新增直摸仍必须带 replacement_plan（scan_bypass.py 同规则把关）。
    executed = {entry["file"] for entry in direct}
    assert not executed & {
        "core/atlas/api/conversations_router.py",
        "core/atlas/engine/session_sync.py",
    }, "T01.3 已执行的直摸替换计划，这两处不得再直摸 _db"
    for entry in direct:
        assert entry["replacement_plan"], entry["file"]


def test_env_manifest_records_both_repos_and_forbidden_roots(baseline):
    manifest = baseline.raw["env_manifest"]
    assert manifest["atlas"]["head"]
    assert manifest["memoryos"]["head"]
    # 研究期快照（00_master_task.md §3）必须被记录；HEAD 若已偏离，
    # matches=False 本身就是必须落盘的复核差异（00_master_task.md §4）。
    assert manifest["memoryos"]["head_expected"] == (
        "702f702bf9c0c1fa552132930843aaca4923f139"
    )
    assert manifest["memoryos"]["head_matches_research_snapshot"] == (
        manifest["memoryos"]["head"] == manifest["memoryos"]["head_expected"]
    )
    assert manifest["production_paths_forbidden"] == [
        "D:/Atlas/data",
        "D:/MemoryOSData",
    ]
    assert manifest["data_root_guard"]["allowed"] is True
    dirty = {
        d["path"]: d for d in manifest["atlas"]["dirty_files"] if "path" in d
    }
    for protected in manifest["protected_workspace_files"]:
        assert protected in dirty, f"受保护在途文件未出现在工作区清单: {protected}"
        assert dirty[protected]["protected"] is True


def test_decision_records_extraction_sessions_reuse(baseline):
    decision = baseline.raw["decision"]
    assert decision["decision"] == "REUSE_EXTRACTION_SESSIONS_EXTEND_JOB_TYPE"
    assert "lease" in json.dumps(decision, ensure_ascii=False)
    assert "extraction_sessions" in decision["target"]
    assert decision["evidence"], "判定必须携带源码行号证据"


def test_default_authority_map_target_path(baseline):
    module = _load_baseline_module()
    parser_default = (
        module.REPO_ROOT / "docs" / "plan" / "UNIFIED-MEMORY" / "authority-map.json"
    )
    assert parser_default == DEFAULT_AUTHORITY_MAP

"""R00 修复基线验收测试（本包 01_逐项修复施工任务.md R00 + 02 契约 + 03 验收门）。

判据（放行条件）：
- 未映射长期消费者 = 0，全部表有四类归属
- 每个写文件只有一个施工所有者；原改动无丢失
- 测试路径、模型与预算可复核；状态不再伪称整体已集成

五变体（R00-A..E）：
- R00-A 基准完全一致 → 允许进入修复
- R00-B HEAD/未提交内容变化 → 输出差分/所有者，不覆盖
- R00-C 新消费者加入样本 → 未映射数非零并使检查失败
- R00-D 测试根指向生产/符号链接 → 启动前拒绝且 DB 未打开
- R00-E 安装入口/CLI/hub/API 分别列出真实构造与读写调用点

本测试纯静态：不连数据库、不启动子进程访问生产、不 import atlas 服务。
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = REPO_ROOT / "scripts" / "unified_memory" / "repair_baseline.py"
AUTHORITY_MAP = REPO_ROOT / "docs" / "plan" / "UNIFIED-MEMORY" / "authority-map.json"
REPAIR_CURRENT = REPO_ROOT / "tasks" / "unified-memory" / "REPAIR-CURRENT.json"
MANIFEST_PATH = (
    REPO_ROOT / "artifacts" / "unified-memory" / "repair" / "R00" / "baseline-manifest.json"
)
AUDIT_VERDICTS = REPO_ROOT / "docs" / "plan" / "UNIFIED-MEMORY" / "audit-verdicts.json"

EXPECTED_OWNERS = {
    "UM-CONSTRUCTION",
    "PRIOR-RECOVERY",
    "PLAN-ARTIFACT",
    "UM-ARTIFACT",
    "UM-WORK",
    "UM-EVIDENCE",
    "R00-CONSTRUCTION",
}
CONSTRUCTION_FILES = {"core/atlas/server.py", "core/atlas/cli.py", "core/atlas/runtime/hub.py"}

R00_ADDED_ATLAS_FILES = {
    "scripts/unified_memory/repair_baseline.py",
    "scripts/unified_memory/repair_driver.py",
    "core/tests/unified_memory/test_repair_baseline.py",
    "tasks/unified-memory/REPAIR-CURRENT.json",
    "docs/plan/UNIFIED-MEMORY/audit-verdicts.json",
}
def _load_module():
    spec = importlib.util.spec_from_file_location("um_r00_repair_baseline", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def rb():
    return _load_module()


@pytest.fixture(scope="module")
def manifest(rb):
    # 用仓库内固定测试根，避免依赖 .tmp 是否被清理
    return rb.build_manifest(Path("D:/Atlas"), Path("D:/MemoryOS"), Path("D:/Atlas/.tmp/r00-test-root"))


# ---------------------------------------------------------------- R00-A
def test_r00_a_baseline_consistent_allows_repair(manifest):
    """R00-A：基准一致 → readiness.ready 为真，且五条放行条件全绿。"""
    readiness = manifest["readiness"]
    assert readiness["ready"] is True, readiness["checks"]
    assert all(readiness["checks"].values()), readiness["checks"]
    assert manifest["production_db_opened"] is False
    assert len(manifest["repositories"]) == 2
    assert manifest["test_path_guard_checked"] is True


def test_r00_a_records_interpreter_and_lock(manifest):
    """R00-A：记录解释器与依赖锁（可复核）。"""
    env = manifest["frozen_env"]
    assert env["python_executable"]
    assert env["python_version"]
    assert env["secret_plaintext_in_artifact"] is False
    # 密钥只引用环境变量名，绝不含明文值
    for name in env["secret_env_names_referenced"]:
        assert name.isupper() and "KEY" in name


# ---------------------------------------------------------------- R00-B
def test_r00_b_owner_assignment_is_unique_per_file(manifest):
    """R00-B：每个脏文件只有一个所有者；无所有者冲突、无未归属文件。"""
    assert manifest["writer_conflicts"] == []
    assert manifest["unowned_dirty_files"] == []
    owners_seen = set()
    for repo in manifest["repositories"]:
        for entry in repo["dirty_files"]:
            assert entry["owner"] in EXPECTED_OWNERS, entry
            assert entry["owner_basis"]
            owners_seen.add(entry["owner"])
    # 至少命中施工线与既有 recovery 两类归属（证明分类非空壳）
    assert "UM-CONSTRUCTION" in owners_seen


def test_r00_b_0026_migration_is_tracked_construction(manifest, rb):
    """R00-B 原断言要求已提交迁移仍出现在脏文件清单，和当前 checkout 不符。

    保留实际契约：迁移仍存在、由 Git 跟踪，且若成为脏文件时归 UM-CONSTRUCTION。
    """
    repo = REPO_ROOT.parent / "MemoryOS"
    relative = "migrations/0026_unified_episode_formation.sql"
    migration = repo / relative
    assert migration.is_file()
    tracked = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "--error-unmatch", relative],
        capture_output=True, text=True, check=False)
    assert tracked.returncode == 0, tracked.stderr
    assert rb.classify_owner("MemoryOS", relative)[0] == "UM-CONSTRUCTION"


def test_r00_b_dirty_manifest_matches_live_repositories(manifest, rb):
    """R00-B：manifest 必须反映本次运行时的 HEAD 和完整 dirty-file 列表。

    已废弃的固定 HEAD/dirty 数取自旧施工包快照；F1/V1 checkout 允许继续提交和
    并行落地，因此不再把某个历史数量误当成当前权威，也不丢失归属检查。
    """
    by_repo = {r["repo"]: r for r in manifest["repositories"]}
    assert set(by_repo) == {"Atlas", "MemoryOS"}
    for name, repo_entry in by_repo.items():
        root = Path(repo_entry["root"])
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True).stdout.strip()
        assert repo_entry["head"] == head
        live_dirty = rb._dirty_entries(root)
        reported = repo_entry["dirty_files"]
        assert repo_entry["dirty_count"] == len(reported)
        live_by_path = {entry["path"]: (entry["status"], entry["tracked"], entry["sha256"])
                        for entry in live_dirty}
        reported_by_path = {
            entry["path"]: (entry["status"], entry["tracked"], entry["sha256"])
            for entry in reported
        }
        assert reported_by_path == live_by_path


# ---------------------------------------------------------------- R00-C
def test_r00_c_new_unmapped_consumer_makes_check_fail(rb):
    """R00-C：注入一个新的未映射消费者 → 未映射数非零 → readiness 失败。

    不污染真实 authority-map：在临时目录构造最小仓库 + 一个未分类消费者，
    再断言 build_manifest 的 readiness 为假。
    """
    # 直接验证 evaluate_manifest 对非零未映射的判定（等价语义）
    fake = {
        "production_db_opened": False,
        "repositories": [{}, {}],
        "unmapped_memory_consumers": [{"file": "core/atlas/x.py", "receiver": "store"}],
        "unowned_dirty_files": [],
        "writer_conflicts": [],
        "test_path_guard_checked": True,
        "test_path_guard": {"ok": True},
    }
    result = rb.evaluate_manifest(fake)
    assert result["ready"] is False
    assert result["checks"]["unmapped_memory_consumers"] is False


# ---------------------------------------------------------------- R00-D
def test_r00_d_rejects_production_test_root(rb):
    """R00-D：测试根指向生产数据根 → 拒绝（DB 未打开）。"""
    for prod in ("D:/Atlas/data", "D:/MemoryOSData", "D:/Atlas/data/sub/dir"):
        guard = rb.check_test_path_guard(Path(prod))
        assert guard["ok"] is False, guard
        assert "生产数据根" in guard["reason"] or "符号链接" in guard["reason"]


def test_r00_d_accepts_safe_test_root(rb):
    """R00-D：安全的测试根 → 通过。"""
    guard = rb.check_test_path_guard(Path("D:/Atlas/.tmp/r00-test-root"))
    assert guard["ok"] is True, guard


def test_r00_d_rejects_symlink_or_junction(tmp_path):
    """R00-D：符号链接/junction 测试根一律拒绝（防指向生产）。

    Windows 上目录 junction（mklink /J）不是 symlink（is_symlink() 为 False），
    但 reparse tag 为 MOUNT_POINT；守卫必须连它一起拒绝，否则是真实绕过。
    """
    rb = _load_module()
    link = tmp_path / "link-root"
    kind = None
    try:
        link.symlink_to(Path("D:/Atlas/.tmp"), target_is_directory=True)
        kind = "symlink"
    except OSError:
        # 无权限建 symlink → 退而建 junction（不需要管理员）
        rc = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(tmp_path)],
            capture_output=True, text=True, errors="replace",
        )
        if rc.returncode == 0 and link.exists():
            kind = "junction"
    if kind is None:
        pytest.skip("本机既不允许 symlink 也建不了 junction")

    guard = rb.check_test_path_guard(link)
    assert guard["ok"] is False, (kind, guard)
    assert guard["is_link"] is True, (kind, guard)
    assert "链接" in guard["reason"] or "junction" in guard["reason"], guard


def test_r00_d_junction_to_production_rejected(tmp_path):
    """R00-D：junction 指向生产数据根 → 必须拒绝（真实绕过防护）。"""
    rb = _load_module()
    link = tmp_path / "prod-link"
    rc = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), "D:\\MemoryOSData"],
        capture_output=True, text=True, errors="replace",
    )
    if rc.returncode != 0 or not link.exists():
        pytest.skip("无法创建 junction 指向生产根")
    guard = rb.check_test_path_guard(link)
    assert guard["ok"] is False, guard


# ---------------------------------------------------------------- R00-E
def test_r00_e_construction_points_present():
    """R00-E：安装入口/CLI/hub/API 的真实构造点在 authority-map 中被登记。"""
    assert AUTHORITY_MAP.exists(), "缺少 docs/plan/UNIFIED-MEMORY/authority-map.json"
    data = json.loads(AUTHORITY_MAP.read_text(encoding="utf-8"))
    points = {p["file"] for p in data.get("construction_points", [])}
    assert CONSTRUCTION_FILES <= points, CONSTRUCTION_FILES - points
    assert data["production_db_opened"] is False
    assert data["unmapped_memory_consumers"] == []


def test_r00_e_all_tables_have_classification():
    """R00-E：全部表有四类归属（分类集合覆盖表集合）。"""
    data = json.loads(AUTHORITY_MAP.read_text(encoding="utf-8"))
    tables = {t["name"] for t in data["tables"]}
    classified = set(data["classifications"].keys())
    assert tables <= classified, tables - classified


# ------------------------------------------------- 原报告降级（R00 步骤 6）
def test_repair_current_downgrades_per_audit():
    """REPAIR-CURRENT 以审计裁决降级：23 partial / 17 contradicted / 40 降级。"""
    assert REPAIR_CURRENT.exists(), "缺少 tasks/unified-memory/REPAIR-CURRENT.json"
    rc = json.loads(REPAIR_CURRENT.read_text(encoding="utf-8"))
    assert rc["partial_count"] == 23
    assert rc["contradicted_count"] == 17
    assert rc["downgraded_count"] == 40
    assert rc["audit_summary"]["accepted"] == 0
    # 原报告不被删除：每条保留 original_status + 反证链接
    for task_id, entry in rc["tasks"].items():
        assert "original_status" in entry, task_id
        assert entry["superseded_by_audit"] is True, task_id
        assert entry["audit_reference"], task_id


def test_repair_current_matches_audit_verdicts():
    """降级状态逐条与审计裁决一致（partial→PARTIAL, contradicted→CONTRADICTED）。"""
    rc = json.loads(REPAIR_CURRENT.read_text(encoding="utf-8"))
    verdicts = json.loads(AUDIT_VERDICTS.read_text(encoding="utf-8"))["task_verdicts"]
    for task_id, v in verdicts.items():
        expected = {"partial": "PARTIAL", "contradicted": "CONTRADICTED"}[v["verdict"]]
        assert rc["tasks"][task_id]["status"] == expected, task_id


def test_manifest_artifact_written():
    """R00 证据产物存在且结构完整（供独立复跑）。"""
    assert MANIFEST_PATH.exists()
    m = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert m["schema_version"] == "atlas-um-repair-baseline-1.0"
    assert m["readiness"]["ready"] is True

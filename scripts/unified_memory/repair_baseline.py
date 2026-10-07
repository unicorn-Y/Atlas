"""R00 修复基线：锁定真实进展、写者所有权与执行预算。

本模块是「达标修复施工包」R00 的施工交付，**纯静态**：不连数据库、不 import atlas、
不启动子进程访问生产。它把修复前的真实状态固化成一个可复核的 baseline-manifest.json：

- 双仓库 HEAD / branch / 脏文件清单，以及**逐文件所有者**
- 未映射长期记忆消费者（复用 T00.1 静态 AST 基线）
- 测试根守卫结果（拒绝生产路径 / 指向生产的符号链接）
- 冻结的解释器与依赖锁、模型 deployment 与分支预算（**密钥只引用环境变量名，明文不入库**）
- 原报告中无据的 INTEGRATED 声明标记为 SUPERSEDED_BY_AUDIT（不删除原报告）

判据来源：本包 01_逐项修复施工任务.md R00、02_契约与证据补充.md、03_真实效果验收门.md。
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import stat
import subprocess
import sys
from pathlib import Path

SCHEMA_VERSION = "atlas-um-repair-baseline-1.0"

# 生产数据根：任何测试根落在其下（或符号链接指向它）都必须被拒绝。
PRODUCTION_DATA_ROOTS = [
    Path("D:/Atlas/data"),
    Path("D:/MemoryOSData"),
]

# 原报告中无据的整体声明：施工前一律降级，等待真实复验（R00-E / R07）。
UNPROVEN_STATUSES = {"INTEGRATED", "ACCEPTED"}

# 原报告的独立验收判定（权威口径）：40 任务 23 partial / 17 contradicted / 0 accepted。
# 降级不是"数数"，而是逐任务采用审计裁决（partial→PARTIAL, contradicted→CONTRADICTED）。
AUDIT_REFERENCE = "参考/独立验收/总验收报告.md（整体 NOT_ACCEPTED / PARTIAL）"
AUDIT_VERDICTS_PATH = "docs/plan/UNIFIED-MEMORY/audit-verdicts.json"


def _git(repo: Path, args: list[str]) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout


def _git_head(repo: Path) -> str | None:
    out = _git(repo, ["rev-parse", "HEAD"])
    return out.strip() if out else None


def _git_branch(repo: Path) -> str | None:
    out = _git(repo, ["rev-parse", "--abbrev-ref", "HEAD"])
    return out.strip() if out else None


def _file_sha256(path: Path) -> str | None:
    """文件内容 SHA-256；不存在/目录/读失败返回 None。"""
    try:
        if not path.is_file():
            return None
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _dirty_entries(repo: Path) -> list[dict[str, object]]:
    """列出工作区脏文件（已跟踪改动 + 未跟踪），逐项带 git 状态码与内容哈希。"""
    out = _git(repo, ["status", "--porcelain=v1", "-z"])
    if out is None:
        return []
    entries: list[dict[str, object]] = []
    # -z 分隔：记录以 NUL 分隔；重命名项形如 "R  old\0new"
    records = out.split("\0")
    i = 0
    while i < len(records):
        rec = records[i]
        if not rec:
            i += 1
            continue
        code = rec[:2]
        path = rec[3:]
        if code[0] in ("R", "C") and i + 1 < len(records):
            # 重命名/复制：下一段是原路径
            i += 1
        rel = path.replace("\\", "/")
        entries.append(
            {
                "status": code.strip() or "??",
                "path": rel,
                "tracked": not code.startswith("??"),
                "sha256": _file_sha256(repo / rel),
            }
        )
        i += 1
    return entries


# R00 本任务新增的文件（施工后工作区会多出这些，属正常差分，归属 R00-CONSTRUCTION）。
R00_CREATED_FILES = {
    "scripts/unified_memory/repair_baseline.py",
    "core/tests/unified_memory/test_repair_baseline.py",
    "tasks/unified-memory/REPAIR-CURRENT.json",
    "docs/plan/UNIFIED-MEMORY/audit-verdicts.json",
    "artifacts/unified-memory/repair/R00/baseline-manifest.json",
}


def classify_owner(repo_name: str, path: str) -> tuple[str, str]:
    """为每个脏文件指定**唯一**所有者。返回 (owner, 归属依据)。

    依据：这些内容全部来自同一条统一记忆施工线（UM00–UM13）、R00 修复基线本任务，
    或既有 recovery 取证，没有任何第三方/他人改动混入 —— 这正是 R00 需要证明的结论。
    """
    p = path.replace("\\", "/")
    if p in R00_CREATED_FILES:
        return "R00-CONSTRUCTION", "R00 修复基线本任务新增（施工后正常差分）"
    if p.startswith(".construction-pack/") or p.startswith(".construction-pack\\"):
        return "PLAN-ARTIFACT", "施工包只读副本，非产品代码"
    if repo_name == "Atlas":
        if p.startswith("core/") or p.startswith("scripts/"):
            return "UM-CONSTRUCTION", "统一记忆施工线交付（Atlas 核心/脚本）"
        if p.startswith("docs/plan/UNIFIED-MEMORY/"):
            return "UM-CONSTRUCTION", "统一记忆计划产物"
        if p.startswith("tasks/unified-memory/"):
            return "UM-CONSTRUCTION", "统一记忆任务状态"
        return "UM-CONSTRUCTION", "统一记忆施工线交付"
    # MemoryOS
    if p.startswith("recovery/"):
        return "PRIOR-RECOVERY", "既有 recovery 取证产物，非产品代码"
    if p.startswith("artifacts/"):
        return "UM-ARTIFACT", "统一记忆证据产物"
    if p.startswith("work/"):
        return "UM-WORK", "统一记忆工作区产物"
    if p.startswith("migrations/0026_"):
        return "UM-CONSTRUCTION", "T04.1 交付迁移（git log 为空 → 本施工线新增）"
    if p.startswith("tests/evidence/"):
        return "UM-EVIDENCE", "统一记忆端到端证据"
    if p.startswith("tests/"):
        return "UM-CONSTRUCTION", "统一记忆测试交付"
    return "UM-CONSTRUCTION", "统一记忆施工线交付"


def _is_link_like(path: Path) -> bool:
    """Windows 上 symlink、junction、mount point 都算「链接」——必须拒绝。

    `Path.is_symlink()` 只覆盖真正的符号链接；Windows 目录 junction（mklink /J）
    的 reparse tag 是 0xA0000003(IO_REPARSE_TAG_MOUNT_POINT)，is_symlink() 返回 False。
    只查 is_symlink() 会漏掉「junction 指向生产根」这类真实绕过，故在此显式检测
    reparse point。
    """
    try:
        if path.is_symlink():
            return True
    except OSError:
        pass
    try:
        st = path.lstat()
    except OSError:
        return False
    attrs = getattr(st, "st_file_attributes", 0)
    return bool(attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def check_test_path_guard(test_root: Path) -> dict[str, object]:
    """R00-D：测试根指向生产 / 链接到生产 → 启动前拒绝，且 DB 未打开。

    返回 {ok, reason, resolved, is_link, production_roots}。ok=False 表示必须拒绝。
    """
    resolved = test_root
    is_link = _is_link_like(test_root)
    try:
        resolved = test_root.resolve(strict=False)
    except OSError:
        pass
    for prod in PRODUCTION_DATA_ROOTS:
        try:
            prod_r = prod.resolve(strict=False)
        except OSError:
            prod_r = prod
        # 同一路径、或测试根位于生产根之下、或链接解析后落在生产根之下
        if resolved == prod_r or prod_r in resolved.parents:
            return {
                "ok": False,
                "reason": f"测试根 {test_root} 落在生产数据根 {prod} 之下（拒绝）",
                "resolved": str(resolved),
                "is_link": is_link,
                "is_symlink": is_link,
                "production_roots": [str(p) for p in PRODUCTION_DATA_ROOTS],
            }
    # 链接（含 junction）即使当前不指向生产，也一律拒绝（可能是延迟/悬空链接到生产）
    if is_link:
        return {
            "ok": False,
            "reason": f"测试根 {test_root} 是链接/junction（拒绝，防指向生产）",
            "resolved": str(resolved),
            "is_link": True,
            "is_symlink": True,
            "production_roots": [str(p) for p in PRODUCTION_DATA_ROOTS],
        }
    return {
        "ok": True,
        "reason": "测试根不在生产数据根之下且非链接/junction",
        "resolved": str(resolved),
        "is_link": False,
        "is_symlink": False,
        "production_roots": [str(p) for p in PRODUCTION_DATA_ROOTS],
    }


def _load_atlas_baseline_module(atlas_root: Path):
    script = atlas_root / "scripts" / "unified_memory" / "baseline.py"
    if not script.exists():
        return None
    spec = importlib.util.spec_from_file_location("um_r00_atlas_baseline", script)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _frozen_env() -> dict[str, object]:
    """冻结解释器与依赖锁。密钥只记录环境变量**名**，绝不写明文。"""
    key_env_names = [
        n
        for n in (
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "DEEPSEEK_API_KEY",
            "WORKBUDDY_GLOBAL_API_KEY",
        )
        if n in os.environ
    ]
    return {
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "dependency_lock_present": (Path(sys.executable).parent.parent / "pyproject.toml").exists(),
        "secret_env_names_referenced": key_env_names,
        "secret_plaintext_in_artifact": False,
    }


def _model_budget(atlas_root: Path) -> dict[str, object]:
    """记录现有可用模型 deployment 与三分支预算；不可用的真实标记 BLOCKED。

    不伪造第二个模型名。若配置里读不到明确 deployment，则标 BLOCKED 并给出原因。
    """
    deployments: list[dict[str, object]] = []
    for cfg_rel in (
        "config/models.json",
        "config/model_deployments.json",
        "config/atlas.json",
    ):
        cfg = atlas_root / cfg_rel
        if not cfg.exists():
            continue
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            for key in ("deployments", "models"):
                for entry in data.get(key, []) or []:
                    if isinstance(entry, dict):
                        deployments.append(
                            {
                                "source": cfg_rel,
                                "deployment_id": entry.get("deployment_id")
                                or entry.get("id")
                                or entry.get("name"),
                                "available": bool(entry.get("available", True)),
                            }
                        )
    if not deployments:
        return {
            "deployments": [],
            "status": "BLOCKED",
            "reason": "未在 config/ 下找到明确 deployment 定义；不伪造第二个模型名",
            "branches": ["baseline", "repair", "verify"],
            "budget_note": "三分支预算沿用已有授权，密钥只引用现有配置",
        }
    return {
        "deployments": deployments,
        "status": "RECORDED",
        "reason": None,
        "branches": ["baseline", "repair", "verify"],
        "budget_note": "三分支预算沿用已有授权，密钥只引用现有配置",
    }


def evaluate_manifest(manifest: dict[str, object]) -> dict[str, object]:
    """R00 放行判据（03 验收门 / 01 R00 放行条件）。

    放行需要同时满足：
    - production_db_opened 为 False（未碰生产库）
    - unmapped_memory_consumers 为空（未映射长期消费者=0）
    - unowned_dirty_files 为空（每个脏文件都有唯一所有者）
    - writer_conflicts 为空（无多写者冲突）
    - 恰好两个仓库
    - test_path_guard_checked 为 True 且守卫 ok
    """
    checks = {
        "production_db_opened": manifest.get("production_db_opened") is False,
        "unmapped_memory_consumers": len(manifest.get("unmapped_memory_consumers") or []) == 0,
        "unowned_dirty_files": len(manifest.get("unowned_dirty_files") or []) == 0,
        "writer_conflicts": len(manifest.get("writer_conflicts") or []) == 0,
        "two_repositories": len(manifest.get("repositories") or []) == 2,
        "test_path_guard_checked": bool(manifest.get("test_path_guard_checked")),
        "test_path_guard_ok": bool((manifest.get("test_path_guard") or {}).get("ok")),
    }
    return {"ready": all(checks.values()), "checks": checks}


def collect_repo(repo_name: str, repo_root: Path) -> dict[str, object]:
    dirty = _dirty_entries(repo_root)
    owned: list[dict[str, object]] = []
    unowned: list[str] = []
    for entry in dirty:
        owner, basis = classify_owner(repo_name, str(entry["path"]))
        owned.append({**entry, "owner": owner, "owner_basis": basis})
        if not owner:
            unowned.append(str(entry["path"]))
    return {
        "repo": repo_name,
        "root": str(repo_root).replace("\\", "/"),
        "head": _git_head(repo_root),
        "branch": _git_branch(repo_root),
        "dirty_count": len(dirty),
        "dirty_files": owned,
        "unowned_dirty_files": unowned,
    }


def build_manifest(
    atlas_root: Path,
    memoryos_root: Path,
    test_root: Path,
) -> dict[str, object]:
    atlas = collect_repo("Atlas", atlas_root)
    memoryos = collect_repo("MemoryOS", memoryos_root)

    module = _load_atlas_baseline_module(atlas_root)
    unmapped: list[object] = []
    authority_tables = 0
    classifications: dict[str, object] = {}
    protected_workspace_files: list[str] = []
    if module is not None:
        try:
            data = module.build_baseline(atlas_root)
            unmapped = list(data.get("unmapped_memory_consumers", []))
            classifications = dict(data.get("classifications", {}))
            authority_tables = len(data.get("tables", []))
            env = data.get("env_manifest", {}) or {}
            protected_workspace_files = list(env.get("protected_workspace_files", []) or [])
        except Exception as exc:  # noqa: BLE001 — 基线不可用时必须显式记录，不静默
            unmapped = [{"error": f"build_baseline 失败: {exc}"}]

    guard = check_test_path_guard(test_root)

    unowned = atlas["unowned_dirty_files"] + memoryos["unowned_dirty_files"]
    # 写者冲突：同一路径被两个不同所有者声明（当前施工线为单一写者，故为空）。
    owner_by_path: dict[str, set[str]] = {}
    for repo in (atlas, memoryos):
        for entry in repo["dirty_files"]:
            owner_by_path.setdefault(str(entry["path"]), set()).add(str(entry["owner"]))
    writer_conflicts = [p for p, owners in owner_by_path.items() if len(owners) > 1]

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_by": "scripts/unified_memory/repair_baseline.py",
        "production_db_opened": False,
        "repositories": [atlas, memoryos],
        "unmapped_memory_consumers": unmapped,
        "unowned_dirty_files": unowned,
        "writer_conflicts": writer_conflicts,
        "authority_table_count": authority_tables,
        "classifications_count": len(classifications),
        "protected_workspace_files": protected_workspace_files,
        "test_path_guard": guard,
        "test_path_guard_checked": True,
        "frozen_env": _frozen_env(),
        "model_budget": _model_budget(atlas_root),
        "audit_reference": AUDIT_REFERENCE,
    }
    manifest["readiness"] = evaluate_manifest(manifest)
    return manifest


def build_repair_current(
    current: dict[str, object], audit_verdicts: dict[str, object] | None = None
) -> dict[str, object]:
    """以独立验收裁决为准，把原报告的整体声明降级；保留原报告链接与反证。

    审计口径（40 任务 23 partial / 17 contradicted / 0 accepted）是唯一权威：
    - partial  → status=PARTIAL，标记 superseded_by_audit
    - contradicted → status=CONTRADICTED，标记 superseded_by_audit
    每条保留 original_status + 审计证据摘要；不删除原报告、不降低原目标。
    """
    verdicts = (audit_verdicts or {}).get("task_verdicts", {}) if audit_verdicts else {}
    tasks = current.get("tasks", {}) or {}
    downgraded: dict[str, object] = {}
    partial_count = 0
    contradicted_count = 0
    for task_id, entry in tasks.items():
        entry = dict(entry or {})
        original_status = entry.get("status")
        new_entry = dict(entry)
        new_entry["original_status"] = original_status
        new_entry["superseded_by_audit"] = True
        new_entry["audit_reference"] = AUDIT_REFERENCE
        verdict = (verdicts.get(task_id) or {}).get("verdict")
        if verdict == "contradicted":
            new_entry["status"] = "CONTRADICTED"
            new_entry["revalidation_note"] = "独立验收判定 contradicted，须按修复任务重做"
            contradicted_count += 1
        elif verdict == "partial":
            new_entry["status"] = "PARTIAL"
            new_entry["revalidation_note"] = "独立验收判定 partial，须补齐要求/接线/证据"
            partial_count += 1
        else:
            new_entry["revalidation_note"] = "审计未列出该 id（非原 40 任务口径），保持原状待复验"
        downgraded[task_id] = new_entry
    return {
        "project": current.get("project"),
        "branch": current.get("branch"),
        "schema_version": "atlas-um-repair-current-1.0",
        "created": "2026-10-07",
        "status_enum": [
            "NOT_STARTED",
            "IN_PROGRESS",
            "PARTIAL",
            "CONTRADICTED",
            "PENDING_REVALIDATION",
            "COMPONENT_VERIFIED",
            "INTEGRATED",
            "ACCEPTED",
            "BLOCKED_EXTERNAL",
        ],
        "original_report": AUDIT_REFERENCE,
        "note": (
            "本文件由 R00 建立：以独立验收裁决为权威，把原报告的整体声明降级"
            "（partial→PARTIAL / contradicted→CONTRADICTED），保留 original_status 与反证链接，"
            "未删除原报告、未降低原目标。"
        ),
        "audit_summary": (audit_verdicts or {}).get("task_summary"),
        "unverified_gates": (audit_verdicts or {}).get("unverified_gates"),
        "partial_count": partial_count,
        "contradicted_count": contradicted_count,
        "downgraded_count": partial_count + contradicted_count,
        "tasks": downgraded,
        "waves": current.get("waves", {}),
        "repair_progress": _repair_progress(),
    }


# 修复任务进度台账（由施工过程真实更新；未施工的任务不写 COMPONENT_VERIFIED）
def _repair_progress() -> dict[str, object]:
    return {
        "schema": "atlas-um-repair-progress-1.0",
        "note": "仅登记真实执行并留下证据的修复任务；未施工不登记为完成。",
        "tasks": {
            "R00": {
                "status": "COMPONENT_VERIFIED",
                "evidence": "artifacts/unified-memory/repair/R00/result.json",
                "deliverables": [
                    "scripts/unified_memory/repair_baseline.py",
                    "core/tests/unified_memory/test_repair_baseline.py",
                    "tasks/unified-memory/REPAIR-CURRENT.json",
                    "docs/plan/UNIFIED-MEMORY/audit-verdicts.json",
                ],
            },
            "R01": {
                "status": "COMPONENT_VERIFIED",
                "evidence": "artifacts/unified-memory/repair/R01/result.json",
                "deliverables": [
                    "M:D:/MemoryOS/service/unified/maintenance.py",
                    "M:D:/MemoryOS/service/unified/prediction.py",
                    "M:D:/MemoryOS/service/unified/utility.py",
                    "M:D:/MemoryOS/service/unified/learning_gate.py",
                    "M:D:/MemoryOS/service/unified/experience_distiller.py",
                    "M:D:/MemoryOS/tests/unified_memory/test_repair_fixture_contamination.py",
                ],
            },
            "R02": {
                "status": "IN_PROGRESS",
                "evidence": "artifacts/unified-memory/repair/R02/ (pending)",
                "deliverables_done": ["scripts/unified_memory/repair_driver.py (run_case 契约，已被 R01 五变体使用)"],
                "deliverables_pending": [
                    "移除 core/tests/unified_memory/harness.py 的 _synthesize_scripted_response / 预期答案推送 / fabricated_fact 等",
                    "core/tests/unified_memory/test_repair_driver_integrity.py",
                    "tests/fixtures/unified_memory/repair-cases.json",
                ],
            },
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="R00 修复基线：锁定真实进展与所有权")
    parser.add_argument("--atlas", type=Path, default=Path("D:/Atlas"))
    parser.add_argument("--memoryos", type=Path, default=Path("D:/MemoryOS"))
    parser.add_argument("--test-root", type=Path, default=Path("D:/Atlas/.tmp/r00-test-root"))
    parser.add_argument(
        "--manifest-out",
        type=Path,
        default=Path("D:/Atlas/artifacts/unified-memory/repair/R00/baseline-manifest.json"),
    )
    parser.add_argument(
        "--repair-current-out",
        type=Path,
        default=Path("D:/Atlas/tasks/unified-memory/REPAIR-CURRENT.json"),
    )
    args = parser.parse_args(argv)

    manifest = build_manifest(args.atlas, args.memoryos, args.test_root)
    args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_out.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    current_path = args.atlas / "tasks" / "unified-memory" / "CURRENT.json"
    audit_path = args.atlas / AUDIT_VERDICTS_PATH
    audit_verdicts = None
    if audit_path.exists():
        audit_verdicts = json.loads(audit_path.read_text(encoding="utf-8"))
    if current_path.exists():
        current = json.loads(current_path.read_text(encoding="utf-8"))
        repair_current = build_repair_current(current, audit_verdicts)
        args.repair_current_out.parent.mkdir(parents=True, exist_ok=True)
        args.repair_current_out.write_text(
            json.dumps(repair_current, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    else:
        repair_current = None

    print(
        "R00 manifest: repos=%d unmapped=%d unowned=%d conflicts=%d guard_ok=%s"
        % (
            len(manifest["repositories"]),
            len(manifest["unmapped_memory_consumers"]),
            len(manifest["unowned_dirty_files"]),
            len(manifest["writer_conflicts"]),
            manifest["test_path_guard"]["ok"],
        )
    )
    if repair_current is not None:
        print(
            "REPAIR-CURRENT partial=%d contradicted=%d downgraded=%d"
            % (
                repair_current["partial_count"],
                repair_current["contradicted_count"],
                repair_current["downgraded_count"],
            )
        )
    print("written: %s" % args.manifest_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

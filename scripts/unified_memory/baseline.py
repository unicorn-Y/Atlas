#!/usr/bin/env python3
"""T00.1 静态权威映射基线（Atlas 侧）。

对 core/atlas/memory/__init__.py 的 MemoryStore 做**纯静态**盘点：
  1. tables   —— 全部 CREATE TABLE / CREATE VIRTUAL TABLE 语句，逐表给出
                 RUNTIME_AUTHORITY / MEMORY_AUTHORITY / DERIVED_VIEW / AUDIT_OPERATION
                 四类归属；分类理由引用字段语义（含行号）与实际读写方法（含行号），
                 不按表名猜测。
  2. methods  —— MemoryStore 每个公开方法：file:line、职责、authority、
                 replacement（DELEGATE_TO_UNIFIED:<api> / KEEP_RUNTIME /
                 READONLY_DERIVED_VIEW / AUDIT_ONLY）、消费者列表（core/atlas 与
                 core/scripts 内属 memory 实例的全部 <recv>.<method>( 调用点）。
  3. unmapped_memory_consumers —— 必须为空；直摸 `._db` 之类的消费者单列在
                 direct_db_consumers 并附 replacement 计划。
  4. env_manifest —— 双仓库 HEAD、工作区脏文件（含 protected 标记）、解释器版本、
                 生产数据禁区与本次运行的数据目录守卫结果。
  5. decision —— MemoryOS unified_jobs 复用判定：复用 extraction_sessions 扩
                 job_type，理由引用其 lease/幂等语义（行号在构建时从源码重新定位）。

硬性约束（由测试 core/tests/unified_memory/test_baseline_inventory.py 把关）：
  - 只用标准库 ast/re/subprocess 等；**禁止 import sqlite3 / aiosqlite / atlas**，
    绝不连接或打开任何数据库（production_db_opened 恒为 False）。
  - 分类依据落盘为可核对的行号证据，而不是表名启发式。

用法：
  python scripts/unified_memory/baseline.py [--out <path>]
默认输出 docs/plan/UNIFIED-MEMORY/authority-map.json。
发现未映射消费者时进程退出码为 2。
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

TASK_ID = "T00.1"
SCHEMA_VERSION = "1.0"

REPO_ROOT = Path(__file__).resolve().parents[2]
MEMORY_FILE = REPO_ROOT / "core" / "atlas" / "memory" / "__init__.py"
MEMORYOS_ROOT = Path("D:/MemoryOS")
MEMORYOS_EXTRACTION_JOBS = MEMORYOS_ROOT / "service" / "extraction_jobs.py"
MEMORYOS_HEAD_EXPECTED = "702f702bf9c0c1fa552132930843aaca4923f139"

PRODUCTION_PATHS_FORBIDDEN = ["D:/Atlas/data", "D:/MemoryOSData"]

# 他人在途、本任务禁止触碰的工作区文件（env_manifest 中标 protected=true）。
PROTECTED_WORKSPACE_FILES = [
    "core/atlas/automation/engine.py",
    "core/atlas/capabilities/durable/dbos_backend.py",
    "core/atlas/capabilities/durable/dbos_compat.py",
    "core/tests/test_dbos_scheduler_wait_shim.py",
    "core/tests/test_k1_daily_paths_x2x4x5.py",
]

SCAN_ROOTS = ["core/atlas", "core/scripts"]

CATEGORIES = (
    "RUNTIME_AUTHORITY",
    "MEMORY_AUTHORITY",
    "DERIVED_VIEW",
    "AUDIT_OPERATION",
)
REPLACEMENT_KINDS = (
    "DELEGATE_TO_UNIFIED",
    "KEEP_RUNTIME",
    "READONLY_DERIVED_VIEW",
    "AUDIT_ONLY",
)

# ---------------------------------------------------------------------------
# 表分类判定表。
# category 依据总任务书 §5；why 引用字段语义，行号在构建时按 cite_cols 自动补上；
# 写入/读取方法与行号由 AST + SQL 文本扫描实际计算（written_by / read_by）。
# ---------------------------------------------------------------------------

TABLE_NOTES = {
    "conversations": {
        "category": "RUNTIME_AUTHORITY",
        "why": (
            "会话元数据携带任务执行状态：permission_mode/allowed_paths/sandbox 是执行"
            "权限面，executor/source 标明执行体，worktree_path/worktree_branch/"
            "base_branch/parent_conversation_id/fork_message_id 是分支执行状态。"
            "属总任务书 §5『conversations…及实际任务状态保留现有权威』；MemoryOS 只收来源记录与投影。"
        ),
        "cite_cols": ["permission_mode", "executor", "worktree_path", "parent_conversation_id"],
    },
    "messages": {
        "category": "RUNTIME_AUTHORITY",
        "why": (
            "对话原文逐条记录（role CHECK user/assistant/system/tool，content，"
            "FK→conversations）。会话原文权威留在 Atlas/Hermes；MemoryOS 仅保存带源定位的经历与内容快照。"
        ),
        "cite_cols": ["role", "content", "conversation_id"],
    },
    "conversation_rewinds": {
        "category": "RUNTIME_AUTHORITY",
        "why": (
            "rewind 快照是实际撤销执行状态：snapshot 存整份状态、removed_messages/"
            "restored_files/redone 记录已发生的外部副作用。总任务书 §2 效果 7 要求"
            "恢复中断任务时不重复外部副作用，该状态必须留在运行权威。"
        ),
        "cite_cols": ["snapshot", "removed_messages", "restored_files", "redone"],
    },
    "messages_fts": {
        "category": "RUNTIME_AUTHORITY",
        "why": (
            "external-content FTS5 索引（content=messages，content_rowid=rowid），"
            "由 messages_ai/ad/au 触发器同步、迁移路径可 'rebuild'（__init__.py:692-713）。"
            "它是 RUNTIME_AUTHORITY 表 messages 的重建型索引，源表留在 Atlas，"
            "故随运行库保留，不迁 MemoryOS（区别于 knowledge_fts：其源表 knowledge 迁移）。"
        ),
        "cite_cols": ["content"],
    },
    "facts": {
        "category": "MEMORY_AUTHORITY",
        "why": (
            "memory_type CHECK fact/identity/commitment（含 commitment_status "
            "active/fulfilled/cancelled 生命周期）表明这是可被模型当知识读取的当前事实。"
            "set_fact/promote_memory_candidate 写入，get_active_context/"
            "generate_user_knowledge 只取已批准事实作为行为依据。属 §5 MEMORY_AUTHORITY『facts、候选/修正/版本』，"
            "迁入统一记忆，旧写路径关闭或委托。"
        ),
        "cite_cols": ["memory_type", "commitment_status", "confidence", "source_message_id"],
    },
    "memory_candidates": {
        "category": "MEMORY_AUTHORITY",
        "why": (
            "自动抽取记忆的待审队列：status CHECK pending/approved/rejected/superseded，"
            "provenance CHECK user/agent/external，UNIQUE(source_message_id,key,value) 幂等。"
            "promote_memory_candidate 事务内把它晋升为 facts 并核对 user 消息证据"
            "（_session_evidence，__init__.py:1294-1299）。候选属 §5 MEMORY_AUTHORITY。"
        ),
        "cite_cols": ["status", "provenance", "source_message_id", "memory_type"],
    },
    "memory_fact_history": {
        "category": "MEMORY_AUTHORITY",
        "why": (
            "事实版本历史：event_type CHECK superseded/duplicate，promote_memory_candidate "
            "在覆盖旧值前先插入旧版本行（__init__.py:1307-1348）。§5 MEMORY_AUTHORITY 明确包含『版本』；"
            "迁移后旧备份不得悄悄复活（总任务书 §2 效果 11）。"
        ),
        "cite_cols": ["event_type", "candidate_id", "value"],
    },
    "memory_commitment_history": {
        "category": "MEMORY_AUTHORITY",
        "why": (
            "承诺状态迁移历史（previous_status/status CHECK active/fulfilled/cancelled、"
            "source_message_id 证据）。set_commitment_status 要求用户消息证据后才 UPDATE facts 并写本表"
            "（__init__.py:3902-3937）。承诺是 MEMORY_AUTHORITY 的版本/修正维度。"
        ),
        "cite_cols": ["previous_status", "status", "source_message_id"],
    },
    "memory_usage_events": {
        "category": "AUDIT_OPERATION",
        "why": (
            "记忆使用结果审计：outcome CHECK used/not_used/helpful/unhelpful。"
            "record_memory_usage 仅在 fact 已存在时追加事件（__init__.py:1431-1437），"
            "不改变事实本身。属 §5 AUDIT_OPERATION『使用记录可保留作审计，但不能绕过统一服务推广知识』。"
        ),
        "cite_cols": ["outcome", "memory_key", "conversation_id"],
    },
    "memory_feedback": {
        "category": "AUDIT_OPERATION",
        "why": (
            "纠正/拒绝信号审计：signal CHECK correction/rejected。record_memory_correction "
            "docstring 明确『Record a user correction without changing or promoting a memory』"
            "（__init__.py:1444）；真正的事实修正必须走统一 corrections 生命周期，本表只留审计。"
        ),
        "cite_cols": ["signal", "candidate_id", "source_message_id"],
    },
    "memory_evaluations": {
        "category": "AUDIT_OPERATION",
        "why": (
            "有用性评估记录：rating CHECK useful/not_useful/uncertain。"
            "record_memory_evaluation 只追加评分（__init__.py:1462-1477），供 get_memory_health "
            "聚合为建议性标记。属 §5 AUDIT_OPERATION『评估』。"
        ),
        "cite_cols": ["rating", "memory_key"],
    },
    "memory_optimization_reports": {
        "category": "DERIVED_VIEW",
        "why": (
            "report_json 快照，由 create_memory_optimization_report 从 get_memory_health 聚合"
            "确定性生成（__init__.py:2592-2615），可随时重建。§5 DERIVED_VIEW 明确列出『优化』报告。"
        ),
        "cite_cols": ["report_json", "created_at"],
    },
    "memory_maturity_reports": {
        "category": "DERIVED_VIEW",
        "why": (
            "知识成熟度 report_json 快照，由 evaluate_knowledge_maturity 确定性评估后落盘"
            "（create_knowledge_maturity_report，__init__.py:2675-2690）。§5 DERIVED_VIEW 明确列出『成熟度』。"
        ),
        "cite_cols": ["report_json", "created_at"],
    },
    "memory_self_steering_reports": {
        "category": "DERIVED_VIEW",
        "why": (
            "自引导报告 report_json + status/reviewed_at 审阅状态；内容由 "
            "evaluate_knowledge_self_steering 从既有事实/反馈确定性计算（__init__.py:2708-2728），可重建。"
            "属 §5 DERIVED_VIEW『优化』族。"
        ),
        "cite_cols": ["report_json", "status", "reviewed_at"],
    },
    "memory_optimization_candidates": {
        "category": "DERIVED_VIEW",
        "why": (
            "优化候选 candidate_json/evaluation_json，FK→memory_self_steering_reports，"
            "由 create_knowledge_optimization_candidates 从报告批量生成（__init__.py:2742-2771）。"
            "派生自报告而非用户经历，§5『优化』→ DERIVED_VIEW；其审批决定本身记入审计表。"
        ),
        "cite_cols": ["candidate_json", "evaluation_json", "source_report_id", "status"],
    },
    "memory_optimization_candidate_reviews": {
        "category": "AUDIT_OPERATION",
        "why": (
            "仅记录审批决定（decision CHECK approved/rejected、reviewed_at），"
            "候选内容在父表。review_knowledge_optimization_candidate 追加审计行（__init__.py:2807-2839）。"
            "属 §5 AUDIT_OPERATION；审批动词本身必须经统一生命周期，不得据本地行推广知识。"
        ),
        "cite_cols": ["decision", "candidate_id", "reviewed_at"],
    },
    "memory_consolidation_proposals": {
        "category": "DERIVED_VIEW",
        "why": (
            "整理建议 proposal_json（advisory_only=true，见 persist_reflection_proposals "
            "__init__.py:1258-1268），由候选/事实派生、可重建；activate 前不产生任何权威知识。"
            "§5 DERIVED_VIEW『consolidated insight』族。"
        ),
        "cite_cols": ["proposal_json", "status", "reviewed_at"],
    },
    "memory_consolidation_proposal_reviews": {
        "category": "AUDIT_OPERATION",
        "why": (
            "提案审批决定审计（decision CHECK approved/rejected）。activate_knowledge_consolidation_proposal "
            "要求最后一条 review 为 approved 才建激活快照（__init__.py:2966-2971）。决定流经统一生命周期，本表仅审计。"
        ),
        "cite_cols": ["decision", "proposal_id", "reviewed_at"],
    },
    "memory_knowledge_activations": {
        "category": "DERIVED_VIEW",
        "why": (
            "激活快照 activation_json（advisory_only=true、activation_status=active，"
            "__init__.py:2972-2991），是已批准提案的建议性投影，不写 facts/knowledge。"
            "active 读取必须回查统一生命周期（§5 DERIVED_VIEW）。"
        ),
        "cite_cols": ["activation_json", "proposal_id"],
    },
    "memory_knowledge_activation_history": {
        "category": "AUDIT_OPERATION",
        "why": (
            "append-only 激活事件（event CHECK 仅 'activated'）。list_knowledge_activations "
            "把它拼进快照 history（__init__.py:3008-3013）。纯事件审计。"
        ),
        "cite_cols": ["event", "activation_id"],
    },
    "memory_knowledge_verifications": {
        "category": "AUDIT_OPERATION",
        "why": (
            "验证快照 verification_json 记录『声称的使用是否有激活出处』的核对结果"
            "（verify_knowledge_activation_usage docstring，__init__.py:3026-3027；status CHECK "
            "verified/unverified）。它只记录核对、不改变任何记录生命周期 → 审计。"
        ),
        "cite_cols": ["status", "verification_json", "activation_id"],
    },
    "memory_knowledge_verification_history": {
        "category": "AUDIT_OPERATION",
        "why": (
            "append-only 验证事件（event CHECK 仅 'verification_recorded'，"
            "__init__.py:3078-3081）。纯事件审计。"
        ),
        "cite_cols": ["event", "verification_id"],
    },
    "memory_knowledge_health_reports": {
        "category": "DERIVED_VIEW",
        "why": (
            "知识健康 report_json 快照（create_knowledge_health_report，__init__.py:3179-3209），"
            "由 get_knowledge_health 从激活/验证/使用/反馈聚合，确定性可重建。§5 DERIVED_VIEW『健康』。"
        ),
        "cite_cols": ["report_json", "created_at"],
    },
    "memory_knowledge_health_report_reviews": {
        "category": "AUDIT_OPERATION",
        "why": (
            "健康报告审批决定审计（decision CHECK approved/rejected；"
            "review_knowledge_health_report __init__.py:3235-3250）。决定走统一生命周期，本表仅审计。"
        ),
        "cite_cols": ["decision", "report_id", "reviewed_at"],
    },
    "memory_knowledge_consolidated_insights": {
        "category": "DERIVED_VIEW",
        "why": (
            "consolidated insight 内容 insight_json，由 create_knowledge_consolidated_insights "
            "从激活提案派生（__init__.py:3251-3280）。§5 DERIVED_VIEW 明确列出『consolidated insight』。"
        ),
        "cite_cols": ["insight_json", "created_at"],
    },
    "memory_knowledge_insight_applications": {
        "category": "AUDIT_OPERATION",
        "why": (
            "洞察应用记录 application_json（apply_knowledge_consolidated_insights 追加，"
            "__init__.py:3294+）。§5 AUDIT_OPERATION『使用记录』：应用事实可审计，但不能据它推广知识。"
        ),
        "cite_cols": ["application_json", "created_at"],
    },
    "agent_reflections": {
        "category": "MEMORY_AUTHORITY",
        "why": (
            "失败观察与执行出处（category CHECK tool/model/runtime、source_run_id、recovered）。"
            "§5 MEMORY_AUTHORITY 点名 agent_reflections 迁入统一记忆；写入经密钥脱敏"
            "（record_agent_reflection __init__.py:1490-1515），读取只排序不激活 hint。"
        ),
        "cite_cols": ["category", "source_run_id", "resolution_hint", "recovered"],
    },
    "goal_outcomes": {
        "category": "MEMORY_AUTHORITY",
        "why": (
            "目标结局与评估（evaluation_json/steps_json、experience_status CHECK "
            "pending/approved/rejected）。§5 MEMORY_AUTHORITY『目标经验』；仅 approval 后才固化为 goal_knowledge。"
        ),
        "cite_cols": ["experience_status", "evaluation_json", "source_run_id"],
    },
    "goal_knowledge": {
        "category": "MEMORY_AUTHORITY",
        "why": (
            "已批准目标经验知识：source_approval_status CHECK = 'approved'、UNIQUE(source_outcome_id)，"
            "FK→goal_outcomes（__init__.py:441-456）。_consolidate_goal_outcome 仅在 approve 后写入。"
            "§5 MEMORY_AUTHORITY『目标经验』。"
        ),
        "cite_cols": ["source_approval_status", "evidence_json", "outcome_status"],
    },
    "goal_knowledge_usage_events": {
        "category": "AUDIT_OPERATION",
        "why": (
            "目标知识使用事件（context_type CHECK planning/execution，FK→goal_knowledge/goal_outcomes）。"
            "record_goal_knowledge_usage 仅追加（__init__.py:2433-2460）。§5 AUDIT_OPERATION『使用记录』。"
        ),
        "cite_cols": ["context_type", "knowledge_id", "recorded_at"],
    },
    "goal_knowledge_feedback_events": {
        "category": "AUDIT_OPERATION",
        "why": (
            "使用后反馈（signal CHECK helpful/failed，UNIQUE(usage_event_id) 保证一用一反馈）。"
            "由 _record_goal_knowledge_feedback_for_outcome 在新结局落地时追加（__init__.py:1621-1694）。"
            "§5 AUDIT_OPERATION『反馈』。"
        ),
        "cite_cols": ["signal", "usage_event_id", "execution_outcome_id"],
    },
    "goal_knowledge_proposals": {
        "category": "MEMORY_AUTHORITY",
        "why": (
            "失败经验触发的知识修订候选：proposed_guidance + status CHECK pending/approved/rejected、"
            "signal CHECK = 'failed'、UNIQUE(usage_event_id, execution_outcome_id)（__init__.py:493-512）。"
            "候选属 §5 MEMORY_AUTHORITY『候选/修正』，批准后经 refinements 更新知识。"
        ),
        "cite_cols": ["proposed_guidance", "status", "signal"],
    },
    "goal_knowledge_refinement_evaluations": {
        "category": "AUDIT_OPERATION",
        "why": (
            "修订资格评估记录：approved_candidate_count/required_candidate_count/eligible/"
            "decision_reason，UNIQUE(knowledge_id, input_signature)。evaluate_goal_knowledge_refinements "
            "落盘判定（__init__.py:1883-1970）。§5 AUDIT_OPERATION『评估』。"
        ),
        "cite_cols": ["eligible", "decision_reason", "approved_candidate_count"],
    },
    "goal_knowledge_refinements": {
        "category": "MEMORY_AUTHORITY",
        "why": (
            "由已批准提案合成的知识修订候选（proposed_guidance + status CHECK "
            "pending/approved/rejected，FK→evaluation）。候选/修正属 §5 MEMORY_AUTHORITY。"
        ),
        "cite_cols": ["proposed_guidance", "status", "evaluation_id"],
    },
    "goal_knowledge_governance_events": {
        "category": "AUDIT_OPERATION",
        "why": (
            "治理决定审计：entity_type CHECK proposal/refinement、decision CHECK approved/rejected、"
            "provenance_json、UNIQUE(entity_type, entity_id)（__init__.py:547-558）。"
            "review_* 写知识状态的同时在此留审计；决定必须经统一生命周期。"
        ),
        "cite_cols": ["entity_type", "decision", "provenance_json"],
    },
    "goal_knowledge_evolution_evaluations": {
        "category": "AUDIT_OPERATION",
        "why": (
            "演进资格评估：helpful_count/failed_count/decision/evidence_json，"
            "UNIQUE(knowledge_id, input_signature)（__init__.py:562-573）。§5 AUDIT_OPERATION『评估』。"
        ),
        "cite_cols": ["helpful_count", "failed_count", "decision"],
    },
    "goal_knowledge_evolution_recommendations": {
        "category": "DERIVED_VIEW",
        "why": (
            "由使用/反馈计数派生的演进建议（recommendation + evidence_json，FK→evaluation，"
            "__init__.py:574-584）。可从审计计数重建，未获批前不是知识 → §5 DERIVED_VIEW『派生视图』。"
        ),
        "cite_cols": ["recommendation", "evidence_json", "evaluation_id"],
    },
    "knowledge": {
        "category": "MEMORY_AUTHORITY",
        "why": (
            "用户/代理整理的知识条目（见 _ensure_knowledge_table __init__.py:4173-4216 与 "
            "add_knowledge/search_knowledge/list_knowledge/delete_knowledge）。§5 MEMORY_AUTHORITY "
            "点名 knowledge 迁入统一记忆；FTS 侧随迁重建。"
        ),
        "cite_cols": ["title", "content", "tags"],
    },
    "knowledge_fts": {
        "category": "DERIVED_VIEW",
        "why": (
            "external-content FTS5 索引（content=knowledge）。源表 knowledge 迁入 MemoryOS 后，"
            "检索由 MemoryOS FTS/向量索引承担，本索引可由 knowledge 全量 rebuild → DERIVED_VIEW。"
            "对比 messages_fts：其源表 messages 保留运行权威，索引随运行库不走。"
        ),
        "cite_cols": ["content"],
    },
}

# ---------------------------------------------------------------------------
# 方法 → (authority, replacement, api, note) 判定表。
# replacement 枚举：DELEGATE_TO_UNIFIED / KEEP_RUNTIME / READONLY_DERIVED_VIEW / AUDIT_ONLY。
# api 仅 DELEGATE_TO_UNIFIED 需要；lifecycle 路由的动词细分由 T01.1 契约最终定名。
# ---------------------------------------------------------------------------

_LIFECYCLE_API = "POST /v1/unified/records/{record_ref}/lifecycle（01_contracts.md §4 CANDIDATE→ACTIVE；动词路由由 T01.1 定名）"

METHOD_MAP = {
    # ----- 运行权威：会话 / 消息 / rewind（KEEP_RUNTIME） -----
    "init": ("RUNTIME_AUTHORITY", "KEEP_RUNTIME", "", "迁移后仅负责运行表初始化；记忆表初始化移交 MemoryOS。"),
    "create_conversation": ("RUNTIME_AUTHORITY", "KEEP_RUNTIME", "", ""),
    "save_conversation_metadata": ("RUNTIME_AUTHORITY", "KEEP_RUNTIME", "", ""),
    "fork_conversation_metadata": ("RUNTIME_AUTHORITY", "KEEP_RUNTIME", "", ""),
    "list_conversations": ("RUNTIME_AUTHORITY", "KEEP_RUNTIME", "", ""),
    "get_conversation_messages": ("RUNTIME_AUTHORITY", "KEEP_RUNTIME", "", ""),
    "save_message": ("RUNTIME_AUTHORITY", "KEEP_RUNTIME", "", "写消息时自动补会话行；运行权威保留。"),
    "save_message_first": ("RUNTIME_AUTHORITY", "KEEP_RUNTIME", "", ""),
    "save_branch_summary": ("RUNTIME_AUTHORITY", "KEEP_RUNTIME", "", ""),
    "search": ("RUNTIME_AUTHORITY", "KEEP_RUNTIME", "", "messages_fts 全文检索原文；原文留在 Atlas。"),
    "session_search": ("RUNTIME_AUTHORITY", "KEEP_RUNTIME", "", "原始历史回放路径；MemoryOS 只收投影，不成为第二会话权威。"),
    "get_conversation": ("RUNTIME_AUTHORITY", "KEEP_RUNTIME", "", ""),
    "update_conversation": ("RUNTIME_AUTHORITY", "KEEP_RUNTIME", "", ""),
    "update_conversation_title": ("RUNTIME_AUTHORITY", "KEEP_RUNTIME", "", ""),
    "truncate_conversation": ("RUNTIME_AUTHORITY", "KEEP_RUNTIME", "", ""),
    "fork_conversation": ("RUNTIME_AUTHORITY", "KEEP_RUNTIME", "", ""),
    "delete_conversation": ("RUNTIME_AUTHORITY", "KEEP_RUNTIME", "", ""),
    "get_messages_with_rowid": ("RUNTIME_AUTHORITY", "KEEP_RUNTIME", "", ""),
    "remove_messages_from": ("RUNTIME_AUTHORITY", "KEEP_RUNTIME", "", ""),
    "replace_messages": ("RUNTIME_AUTHORITY", "KEEP_RUNTIME", "", ""),
    "save_rewind": ("RUNTIME_AUTHORITY", "KEEP_RUNTIME", "", ""),
    "list_rewinds": ("RUNTIME_AUTHORITY", "KEEP_RUNTIME", "", ""),
    "get_rewind": ("RUNTIME_AUTHORITY", "KEEP_RUNTIME", "", ""),
    "mark_rewind_redone": ("RUNTIME_AUTHORITY", "KEEP_RUNTIME", "", ""),
    "update_rewind_restored_files": ("RUNTIME_AUTHORITY", "KEEP_RUNTIME", "", "T01.3：取代 conversations_router rewind_redo 直摸 _db 的 restored_files 回写（与 mark_rewind_redone 同型；direct_db replacement plan 已执行）。"),
    "list_conversation_ids": ("RUNTIME_AUTHORITY", "KEEP_RUNTIME", "", "T01.3：取代 engine/session_sync 迁移路径直摸 _db 的 DISTINCT 会话清单只读查询（direct_db replacement plan 已执行；迁移退役后随路径删除）。"),
    "close": ("RUNTIME_AUTHORITY", "KEEP_RUNTIME", "", "连接生命周期方法；保留于本地运行存储。"),
    # ----- 记忆权威：事实 / 候选 / 反思 / 目标经验 / 知识（DELEGATE_TO_UNIFIED） -----
    "set_fact": ("MEMORY_AUTHORITY", "DELEGATE_TO_UNIFIED", "POST /v1/unified/observe（显式事实作为来源事件经 formation 形成 ACTIVE/CANDIDATE 记录）", ""),
    "get_fact": ("MEMORY_AUTHORITY", "DELEGATE_TO_UNIFIED", "GET /v1/unified/records（facet 精确读取）", ""),
    "list_facts": ("MEMORY_AUTHORITY", "DELEGATE_TO_UNIFIED", "GET /v1/unified/records", ""),
    "delete_fact": ("MEMORY_AUTHORITY", "DELEGATE_TO_UNIFIED", "POST /v1/unified/corrections（删除经依赖失效传播，禁止旧库复活）", ""),
    "extract_memories": ("MEMORY_AUTHORITY", "DELEGATE_TO_UNIFIED", "POST /v1/unified/observe", ""),
    "extract_conversation_candidates": ("MEMORY_AUTHORITY", "DELEGATE_TO_UNIFIED", "POST /v1/unified/observe（候选队列 = CANDIDATE 生命周期）", ""),
    "list_memory_candidates": ("MEMORY_AUTHORITY", "DELEGATE_TO_UNIFIED", "GET /v1/unified/records（facet=candidate，status 过滤）", ""),
    "promote_memory_candidate": ("MEMORY_AUTHORITY", "DELEGATE_TO_UNIFIED", _LIFECYCLE_API, "现实现要求 user 消息证据（_session_evidence）；统一路径由 evidence/生命周期校验承接。"),
    "reject_memory_candidate": ("MEMORY_AUTHORITY", "DELEGATE_TO_UNIFIED", _LIFECYCLE_API, ""),
    "list_memory_conflicts": ("MEMORY_AUTHORITY", "DELEGATE_TO_UNIFIED", "POST /v1/unified/recall（返回 conflicts；候选与现值冲突由统一生命周期裁决）", ""),
    "list_memory_fact_history": ("MEMORY_AUTHORITY", "DELEGATE_TO_UNIFIED", "GET /v1/unified/records/{record_ref}（版本化 revisions）", ""),
    "record_agent_reflection": ("MEMORY_AUTHORITY", "DELEGATE_TO_UNIFIED", "POST /v1/unified/observe（经历来源事件）", ""),
    "retrieve_agent_reflections": ("MEMORY_AUTHORITY", "DELEGATE_TO_UNIFIED", "POST /v1/unified/recall", ""),
    "mark_agent_reflections_recovered": ("MEMORY_AUTHORITY", "DELEGATE_TO_UNIFIED", "POST /v1/unified/outcomes（恢复成功的结局证据）", ""),
    "record_goal_outcome": ("MEMORY_AUTHORITY", "DELEGATE_TO_UNIFIED", "POST /v1/unified/outcomes", ""),
    "list_goal_outcomes": ("MEMORY_AUTHORITY", "DELEGATE_TO_UNIFIED", "GET /v1/unified/records（facet=goal_outcome）", ""),
    "review_goal_experience": ("MEMORY_AUTHORITY", "DELEGATE_TO_UNIFIED", _LIFECYCLE_API, ""),
    "retrieve_approved_goal_knowledge": ("MEMORY_AUTHORITY", "DELEGATE_TO_UNIFIED", "POST /v1/unified/recall", ""),
    "retrieve_approved_goal_experiences": ("MEMORY_AUTHORITY", "DELEGATE_TO_UNIFIED", "POST /v1/unified/recall", ""),
    "list_goal_knowledge_proposals": ("MEMORY_AUTHORITY", "DELEGATE_TO_UNIFIED", "GET /v1/unified/records（facet=goal_knowledge_proposal）", ""),
    "evaluate_goal_knowledge_refinements": ("MEMORY_AUTHORITY", "DELEGATE_TO_UNIFIED", "POST /v1/unified/maintenance（job_type=REFINE_GOAL_KNOWLEDGE）", "判定算法随迁 MemoryOS；本地只留审计行。"),
    "list_goal_knowledge_refinements": ("MEMORY_AUTHORITY", "DELEGATE_TO_UNIFIED", "GET /v1/unified/records（facet=goal_knowledge_refinement）", ""),
    "evaluate_goal_knowledge_governance": ("MEMORY_AUTHORITY", "DELEGATE_TO_UNIFIED", _LIFECYCLE_API, "本地 goal_knowledge_governance_events 仅留审计副本。"),
    "review_goal_knowledge_refinement": ("MEMORY_AUTHORITY", "DELEGATE_TO_UNIFIED", _LIFECYCLE_API, ""),
    "review_goal_knowledge_proposal": ("MEMORY_AUTHORITY", "DELEGATE_TO_UNIFIED", _LIFECYCLE_API, ""),
    "get_agent_context": ("MEMORY_AUTHORITY", "DELEGATE_TO_UNIFIED", "POST /v1/unified/recall", "验证过的事实 + 可追溯知识视图统一由 recall 装配。"),
    "get_agent_context_with_trace": ("MEMORY_AUTHORITY", "DELEGATE_TO_UNIFIED", "POST /v1/unified/recall（trace_ref）", ""),
    "generate_user_knowledge_with_trace": ("MEMORY_AUTHORITY", "DELEGATE_TO_UNIFIED", "POST /v1/unified/recall（知识视图装配 + 决策 trace）", ""),
    "generate_user_knowledge": ("MEMORY_AUTHORITY", "DELEGATE_TO_UNIFIED", "POST /v1/unified/recall", ""),
    "retrieve_user_knowledge_with_trace": ("MEMORY_AUTHORITY", "DELEGATE_TO_UNIFIED", "POST /v1/unified/recall", ""),
    "retrieve_user_knowledge": ("MEMORY_AUTHORITY", "DELEGATE_TO_UNIFIED", "POST /v1/unified/recall", ""),
    "get_active_context": ("MEMORY_AUTHORITY", "DELEGATE_TO_UNIFIED", "POST /v1/unified/recall（working set 装配）", "现实现仅取已批准事实；统一路径按 lifecycle/applicability 过滤。"),
    "set_commitment_status": ("MEMORY_AUTHORITY", "DELEGATE_TO_UNIFIED", "POST /v1/unified/corrections（需用户消息 source）", ""),
    "list_commitment_history": ("MEMORY_AUTHORITY", "DELEGATE_TO_UNIFIED", "GET /v1/unified/records/{record_ref}（版本化状态历史）", ""),
    "add_knowledge": ("MEMORY_AUTHORITY", "DELEGATE_TO_UNIFIED", "POST /v1/unified/observe", ""),
    "search_knowledge": ("MEMORY_AUTHORITY", "DELEGATE_TO_UNIFIED", "POST /v1/unified/recall", ""),
    "list_knowledge": ("MEMORY_AUTHORITY", "DELEGATE_TO_UNIFIED", "GET /v1/unified/records（facet=knowledge）", ""),
    "delete_knowledge": ("MEMORY_AUTHORITY", "DELEGATE_TO_UNIFIED", "POST /v1/unified/corrections", ""),
    # ----- 派生视图：报告 / 成熟度 / 健康 / 提案 / 激活 / 图（READONLY 或 DELEGATE maintenance） -----
    "get_memory_health": ("DERIVED_VIEW", "READONLY_DERIVED_VIEW", "", "聚合审计计数给出建议性标记；active 读取回查统一生命周期。"),
    "create_memory_optimization_report": ("DERIVED_VIEW", "DELEGATE_TO_UNIFIED", "POST /v1/unified/maintenance（job_type=MEMORY_OPTIMIZATION_REPORT；重试同 snapshot 去重）", ""),
    "list_memory_optimization_reports": ("DERIVED_VIEW", "READONLY_DERIVED_VIEW", "", ""),
    "get_knowledge_maturity": ("DERIVED_VIEW", "READONLY_DERIVED_VIEW", "", ""),
    "create_knowledge_maturity_report": ("DERIVED_VIEW", "DELEGATE_TO_UNIFIED", "POST /v1/unified/maintenance（job_type=KNOWLEDGE_MATURITY_REPORT）", ""),
    "list_knowledge_maturity_reports": ("DERIVED_VIEW", "READONLY_DERIVED_VIEW", "", ""),
    "create_knowledge_self_steering_report": ("DERIVED_VIEW", "DELEGATE_TO_UNIFIED", "POST /v1/unified/maintenance（job_type=KNOWLEDGE_SELF_STEERING）", ""),
    "review_knowledge_self_steering_report": ("DERIVED_VIEW", "DELEGATE_TO_UNIFIED", _LIFECYCLE_API, ""),
    "list_knowledge_self_steering_reports": ("DERIVED_VIEW", "READONLY_DERIVED_VIEW", "", ""),
    "create_knowledge_optimization_candidates": ("DERIVED_VIEW", "DELEGATE_TO_UNIFIED", "POST /v1/unified/maintenance（job_type=KNOWLEDGE_OPTIMIZATION_CANDIDATES）", ""),
    "list_knowledge_optimization_candidates": ("DERIVED_VIEW", "READONLY_DERIVED_VIEW", "", ""),
    "review_knowledge_optimization_candidate": ("DERIVED_VIEW", "DELEGATE_TO_UNIFIED", _LIFECYCLE_API, ""),
    "create_knowledge_consolidation_proposals": ("DERIVED_VIEW", "DELEGATE_TO_UNIFIED", "POST /v1/unified/maintenance（job_type=KNOWLEDGE_CONSOLIDATION）", ""),
    "list_knowledge_consolidation_proposals": ("DERIVED_VIEW", "READONLY_DERIVED_VIEW", "", ""),
    "review_knowledge_consolidation_proposal": ("DERIVED_VIEW", "DELEGATE_TO_UNIFIED", _LIFECYCLE_API, ""),
    "activate_knowledge_consolidation_proposal": ("DERIVED_VIEW", "DELEGATE_TO_UNIFIED", _LIFECYCLE_API, "激活 = CANDIDATE→ACTIVE；advisory_only 语义在 UnifiedRecord.applicability 中保留。"),
    "list_knowledge_activations": ("DERIVED_VIEW", "READONLY_DERIVED_VIEW", "", ""),
    "get_knowledge_health": ("DERIVED_VIEW", "READONLY_DERIVED_VIEW", "", ""),
    "create_knowledge_health_report": ("DERIVED_VIEW", "DELEGATE_TO_UNIFIED", "POST /v1/unified/maintenance（job_type=KNOWLEDGE_HEALTH_REPORT）", ""),
    "list_knowledge_health_reports": ("DERIVED_VIEW", "READONLY_DERIVED_VIEW", "", ""),
    "review_knowledge_health_report": ("DERIVED_VIEW", "DELEGATE_TO_UNIFIED", _LIFECYCLE_API, ""),
    "create_knowledge_consolidated_insights": ("DERIVED_VIEW", "DELEGATE_TO_UNIFIED", "POST /v1/unified/maintenance（job_type=CONSOLIDATED_INSIGHTS）", ""),
    "list_knowledge_consolidated_insights": ("DERIVED_VIEW", "READONLY_DERIVED_VIEW", "", ""),
    "apply_knowledge_consolidated_insights": ("DERIVED_VIEW", "DELEGATE_TO_UNIFIED", "POST /v1/unified/recall（使用经 POST /v1/unified/applications 收据化）", "规划期注入洞察属读取；不得据本地应用行绕过统一服务推广知识。"),
    "generate_knowledge_graph": ("DERIVED_VIEW", "DELEGATE_TO_UNIFIED", "POST /v1/unified/maintenance（job_type=KNOWLEDGE_GRAPH_REBUILD）", "§5：图属派生视图，保存来源版本、可重建。"),
    "get_relevant_knowledge_graph": ("DERIVED_VIEW", "DELEGATE_TO_UNIFIED", "POST /v1/unified/recall（联想/图扩展段）", ""),
    "get_task_knowledge_graph": ("DERIVED_VIEW", "DELEGATE_TO_UNIFIED", "POST /v1/unified/recall", ""),
    "evaluate_goal_knowledge_evolution": ("DERIVED_VIEW", "DELEGATE_TO_UNIFIED", "POST /v1/unified/maintenance（job_type=GOAL_KNOWLEDGE_EVOLUTION）", "写评估审计与派生建议；判定算法随迁。"),
    "list_goal_knowledge_evolution_recommendations": ("DERIVED_VIEW", "READONLY_DERIVED_VIEW", "", ""),
    # ----- 审计操作：使用 / 反馈 / 评估 / 验证（AUDIT_ONLY） -----
    "record_memory_usage": ("AUDIT_OPERATION", "AUDIT_ONLY", "", "保留本地审计；反馈信号同步 POST /v1/unified/feedback，但反馈不得直接把记录 ACTIVE。"),
    "record_memory_correction": ("AUDIT_OPERATION", "AUDIT_ONLY", "", "纠正如实生效必须走 POST /v1/unified/corrections；本表只留 signal 审计。"),
    "record_memory_evaluation": ("AUDIT_OPERATION", "AUDIT_ONLY", "", ""),
    "list_memory_usage": ("AUDIT_OPERATION", "AUDIT_ONLY", "", ""),
    "list_memory_feedback": ("AUDIT_OPERATION", "AUDIT_ONLY", "", ""),
    "list_memory_evaluations": ("AUDIT_OPERATION", "AUDIT_ONLY", "", ""),
    "get_memory_quality": ("AUDIT_OPERATION", "AUDIT_ONLY", "", "只读聚合审计计数。"),
    "record_goal_knowledge_usage": ("AUDIT_OPERATION", "AUDIT_ONLY", "", "使用收据同步 POST /v1/unified/applications；审计保留本地。"),
    "list_goal_knowledge_feedback": ("AUDIT_OPERATION", "AUDIT_ONLY", "", ""),
    "list_goal_knowledge_refinement_evaluations": ("AUDIT_OPERATION", "AUDIT_ONLY", "", ""),
    "list_goal_knowledge_governance_history": ("AUDIT_OPERATION", "AUDIT_ONLY", "", ""),
    "list_goal_knowledge_evolution_evaluations": ("AUDIT_OPERATION", "AUDIT_ONLY", "", ""),
    "verify_knowledge_activation_usage": ("AUDIT_OPERATION", "AUDIT_ONLY", "", "验证记录仅审计『声称使用是否有出处』；使用收据以 POST /v1/unified/applications 为准。"),
    "list_knowledge_verifications": ("AUDIT_OPERATION", "AUDIT_ONLY", "", ""),
    "list_knowledge_insight_applications": ("AUDIT_OPERATION", "AUDIT_ONLY", "", ""),
    # advisory 提案入队：内容派生自候选/事实（DERIVED_VIEW），入队动作走统一 observe。
    "persist_reflection_proposals": (
        "DERIVED_VIEW",
        "DELEGATE_TO_UNIFIED",
        "POST /v1/unified/observe（advisory 提案入统一整理队列，不得直接 ACTIVE）",
        "确定性 proposal_id（sha256 of conversation/run/category/summary）已满足同内容 DUPLICATE_OK 幂等语义。",
    ),
}

# 无 docstring 方法的职责补注（其余方法职责自动取 docstring 首行）。
FALLBACK_RESPONSIBILITY = {
    "init": "连接 SQLite（惰性），建全部表并执行列级迁移。",
    "create_conversation": "新建会话元数据行。",
    "list_conversations": "按置顶/更新时间列出会话元数据。",
    "save_message": "追加消息并自动补建会话、刷新 updated_at。",
    "set_fact": "upsert 一条事实（fact/identity/commitment）。",
    "get_fact": "按键读取单条事实值。",
    "list_facts": "按类别列出全部事实。",
    "delete_fact": "删除一条事实。",
    "list_memory_candidates": "按状态/来源会话列出待审记忆候选。",
    "promote_memory_candidate": "事务内校验 user 证据后把候选晋升为事实并记版本历史。",
    "reject_memory_candidate": "拒绝候选并写 rejected 反馈审计。",
    "list_memory_usage": "列出某记忆的使用事件。",
    "list_memory_feedback": "列出某记忆的纠正/拒绝反馈。",
    "list_memory_evaluations": "列出某记忆的有用性评估。",
    "list_commitment_history": "列出某承诺的状态迁移历史。",
    "list_rewinds": "列出会话的 rewind 记录。",
    "get_rewind": "读取单条 rewind 记录。",
    "save_rewind": "写入 rewind 快照记录。",
    "get_messages_with_rowid": "按 rowid 顺序取全部消息（迁移用）。",
    "remove_messages_from": "删除某消息及之后全部消息。",
    "replace_messages": "整批替换会话消息（rewind 恢复用）。",
    "truncate_conversation": "截断会话于指定消息。",
    "add_knowledge": "写入一条知识条目并同步 FTS。",
    "search_knowledge": "知识条目全文检索。",
    "list_knowledge": "列出知识条目。",
    "delete_knowledge": "删除知识条目。",
    "close": "关闭数据库连接。",
}

DIRECT_DB_PLANS = {
    "core/atlas/api/conversations_router.py": (
        "直摸 memory._db 更新 conversation_rewinds.restored_files（rewind_redo 端点）。"
        "表为 RUNTIME_AUTHORITY，保留本地：在 MemoryStore 增加显式方法"
        " update_rewind_restored_files(rewind_id, count)（与 mark_rewind_redone 同型），"
        "路由改调公开方法后删除 _db 访问。归属 UM01（T01.3 全入口组成）执行。"
    ),
    "core/atlas/engine/session_sync.py": (
        "遗留会话迁移用 memory_store._db 做 DISTINCT 会话清单只读查询"
        "（SELECT DISTINCT c.id FROM conversations JOIN messages）。"
        "表为 RUNTIME_AUTHORITY：为 MemoryStore 增加 list_conversation_ids() 只读方法，"
        "migrate_legacy_sessions 改调它。迁移完成（deferred_startup has_legacy_transcripts=False）后该路径退役。"
    ),
}


# ---------------------------------------------------------------------------
# AST 解析：表与方法
# ---------------------------------------------------------------------------

def _statement_line(constant_lineno: int, text: str, offset: int) -> int:
    return constant_lineno + text.count("\n", 0, offset)


_CREATE_RE = re.compile(
    r"CREATE\s+(?P<virtual>VIRTUAL\s+)?TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?:\s+USING\s+[A-Za-z0-9_]+)?\s*\(",
    re.IGNORECASE,
)
_CONSTRAINT_START = re.compile(
    r"^\s*(PRIMARY|UNIQUE|CHECK|FOREIGN|CONSTRAINT)\b", re.IGNORECASE
)
_WRITE_RES = (
    re.compile(r"\bINSERT(?:\s+OR\s+(?:IGNORE|REPLACE))?\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE),
    re.compile(r"\bUPDATE\s+([A-Za-z_][A-Za-z0-9_]*)\s+SET\b", re.IGNORECASE),
    re.compile(r"\bDELETE\s+FROM\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE),
)
_READ_RES = (
    re.compile(r"\bFROM\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE),
    re.compile(r"\bJOIN\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE),
)


def _parse_tables(source: str, source_lines: list[str]) -> dict[str, dict]:
    """从模块字符串常量中抽取全部 CREATE TABLE / VIRTUAL TABLE。"""
    tree = ast.parse(source)
    found: dict[str, dict] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        text = node.value
        if "CREATE" not in text or "TABLE" not in text.upper():
            continue
        for match in _CREATE_RE.finditer(text):
            name = match.group("name")
            line = _statement_line(node.lineno, text, match.start())
            kind = "virtual" if match.group("virtual") else "table"
            entry = found.setdefault(
                name,
                {"name": name, "kind": kind, "definition_lines": [], "columns": []},
            )
            entry["definition_lines"].append(line)
            cols = _parse_columns(source_lines, line, kind)
            if cols and not entry["columns"]:
                entry["columns"] = cols
    for entry in found.values():
        entry["definition_lines"].sort()
        entry["canonical_line"] = entry["definition_lines"][0]
        entry["alternate_definition_lines"] = entry["definition_lines"][1:]
    return found


def _parse_columns(source_lines: list[str], create_line: int, kind: str) -> list[dict]:
    """从 CREATE 语句起始行向下收集列名与行号（直到右括号）。"""
    columns: list[dict] = []
    depth = 0
    started = False
    for idx in range(create_line - 1, min(create_line + 120, len(source_lines))):
        line = source_lines[idx]
        if not started:
            open_paren = line.find("(")
            if open_paren == -1:
                continue
            started = True
            line = line[open_paren:]
        for ch in line:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
        stripped = line.strip().rstrip(",")
        if stripped in {"", ");", ")"} or stripped.startswith("--"):
            if depth <= 0 and started:
                break
            continue
        if _CONSTRAINT_START.match(stripped):
            if depth <= 0:
                break
            continue
        token = re.match(r"[\"']?([A-Za-z_][A-Za-z0-9_]*)", stripped)
        if kind == "virtual" and token and token.group(1).lower() in {"fts5", "using"}:
            continue
        if token:
            columns.append({"name": token.group(1), "line": idx + 1})
        if depth <= 0:
            break
    if kind == "virtual":
        return columns[:1]
    return columns


def _parse_methods(source: str) -> tuple[list[dict], dict[str, list[str]]]:
    """返回 (MemoryStore 方法列表, 类内 self.<method>( 调用邻接表)。"""
    tree = ast.parse(source)
    store_cls = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "MemoryStore":
            store_cls = node
            break
    if store_cls is None:
        raise SystemExit("MemoryStore class not found in memory/__init__.py")

    methods: list[dict] = []
    for item in store_cls.body:
        if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        doc = ast.get_docstring(item)
        methods.append(
            {
                "name": item.name,
                "line": item.lineno,
                "end_line": item.end_lineno,
                "visibility": "public" if not item.name.startswith("_") else "private",
                "docstring": (doc or "").strip().splitlines()[0] if doc else "",
            }
        )

    adjacency: dict[str, list[str]] = {m["name"]: [] for m in methods}
    method_names = set(adjacency)
    for item in store_cls.body:
        if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for call in ast.walk(item):
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
                continue
            if isinstance(call.func.value, ast.Name) and call.func.value.id == "self":
                if call.func.attr in method_names and call.func.attr != item.name:
                    adjacency[item.name].append(call.func.attr)
    return methods, adjacency


def _table_usage(segment: str, known: set[str]) -> tuple[set[str], set[str]]:
    writes: set[str] = set()
    reads: set[str] = set()
    for pattern in _WRITE_RES:
        for match in pattern.finditer(segment):
            if match.group(1) in known:
                writes.add(match.group(1))
    for pattern in _READ_RES:
        for match in pattern.finditer(segment):
            name = match.group(1)
            if name in known and name not in writes:
                reads.add(name)
    return writes, reads


def _closure(tables_by_method: dict[str, tuple[set[str], set[str]]],
             adjacency: dict[str, list[str]]) -> None:
    """把被调方法的表读写传播给调用方（inherited），迭代到不动点。"""
    changed = True
    while changed:
        changed = False
        for caller, callees in adjacency.items():
            cw, cr = tables_by_method[caller]
            for callee in callees:
                ew, er = tables_by_method[callee]
                if not ew <= cw:
                    cw |= ew
                    changed = True
                if not er <= cr:
                    cr |= er
                    changed = True


# ---------------------------------------------------------------------------
# 消费者扫描（core/atlas + core/scripts）
# ---------------------------------------------------------------------------

def _is_memory_receiver_name(name: str) -> bool:
    return (
        name in {"memory", "_memory", "mem", "memory_store", "mem_store"}
        or name.startswith("memory")
        or name.endswith("_memory")
        or name == "memory"
    )


def _dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    # _server().memory.x / (await get_services()).memory.x / cfg["x"].memory
    if isinstance(node, ast.Call):
        base = _dotted(node.func)
        return f"{base}()" if base else "()"
    if isinstance(node, ast.Await):
        base = _dotted(node.value)
        return f"await({base})" if base else "await(...)"
    if isinstance(node, ast.Subscript):
        base = _dotted(node.value)
        return f"{base}[]" if base else "[]"
    return None


def _scan_consumers(repo_root: Path, method_names: set[str]) -> dict:
    consumers: list[dict] = []
    direct_db: list[dict] = []
    scanned: list[str] = []
    for scan_root in SCAN_ROOTS:
        root = repo_root / scan_root
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            rel = path.relative_to(repo_root).as_posix()
            scanned.append(rel)
            try:
                source = path.read_text(encoding="utf-8")
                tree = ast.parse(source)
            except (SyntaxError, UnicodeDecodeError) as exc:
                consumers.append({
                    "file": rel, "line": 0, "method": "", "receiver": "",
                    "kind": "parse_error", "detail": str(exc),
                })
                continue

            # 本文件内绑定到 MemoryStore(...) 或 *.memory 的名字。
            bound: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    value = node.value if isinstance(node, ast.Assign) else node.value
                    if value is None:
                        continue
                    dotted_value = _dotted(value)
                    is_store = (
                        isinstance(value, ast.Call)
                        and _dotted(value.func) in {"MemoryStore", "atlas.memory.MemoryStore"}
                    )
                    is_memory_attr = dotted_value is not None and _is_memory_receiver_name(
                        dotted_value.split(".")[-1]
                    )
                    if not (is_store or is_memory_attr):
                        continue
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for target in targets:
                        if isinstance(target, ast.Name):
                            bound.add(target.id)

            def receiver_is_memory(node: ast.AST) -> bool:
                dotted = _dotted(node)
                if not dotted:
                    return False
                # 归一化掉 ()/await/[] 等调用链标记，保留标识符段。
                normalized = re.sub(r"[^A-Za-z0-9_.]", "", dotted)
                parts = normalized.split(".")
                if not parts:
                    return False
                if _is_memory_receiver_name(parts[0]) or parts[0] in bound:
                    return True
                # 属性链尾部为 memory/_memory：services.memory、agent._memory、
                # _server().memory、self.memory。
                return len(parts) > 1 and _is_memory_receiver_name(parts[-1])

            for node in ast.walk(tree):
                # <memory>.<method>( ...) 调用点
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    attr = node.func.attr
                    if attr in method_names and receiver_is_memory(node.func.value):
                        consumers.append({
                            "file": rel,
                            "line": node.lineno,
                            "method": attr,
                            "receiver": _dotted(node.func.value) or "",
                            "kind": "call",
                        })
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "getattr"
                    and node.args
                    and receiver_is_memory(node.args[0])
                    and len(node.args) > 1
                    and isinstance(node.args[1], ast.Constant)
                    and isinstance(node.args[1].value, str)
                    and node.args[1].value in method_names
                ):
                    consumers.append({
                        "file": rel,
                        "line": node.lineno,
                        "method": node.args[1].value,
                        "receiver": _dotted(node.args[0]) or "",
                        "kind": "getattr_ref",
                    })
                # 直摸 _db / _db_path
                if isinstance(node, ast.Attribute) and node.attr in {"_db", "_db_path"}:
                    if receiver_is_memory(node.value):
                        direct_db.append({
                            "file": rel,
                            "line": node.lineno,
                            "receiver": _dotted(node.value) or "",
                            "attribute": node.attr,
                        })
    return {"consumers": consumers, "direct_db": direct_db, "scanned_files": scanned}


# ---------------------------------------------------------------------------
# 环境清单 / 判定记录
# ---------------------------------------------------------------------------

def _git(repo: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"<git failed: {exc}>"
    if proc.returncode != 0:
        return f"<git rc={proc.returncode}: {proc.stderr.strip()[:200]}>"
    # 只去掉尾部换行；porcelain 首行的前导空格是状态位，不能被 strip 吃掉。
    return proc.stdout.rstrip("\r\n")


def _python_version(interpreter: Path) -> dict:
    if not interpreter.exists():
        return {"path": str(interpreter).replace("\\", "/"), "exists": False, "version": None}
    try:
        proc = subprocess.run(
            [str(interpreter), "--version"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )
        version = (proc.stdout or proc.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"path": str(interpreter).replace("\\", "/"), "exists": True,
                "version": f"<failed: {exc}>"}
    return {"path": str(interpreter).replace("\\", "/"), "exists": True, "version": version}


def build_env_manifest(repo_root: Path) -> dict:
    protected_set = set(PROTECTED_WORKSPACE_FILES)

    def dirty_entries(repo: Path) -> list[dict]:
        out = []
        raw = _git(repo, "-c", "core.quotepath=false", "status", "--porcelain",
                   "--untracked-files=all")
        for line in raw.splitlines():
            if not line.strip() or line.startswith("<git"):
                out.append({"raw": line})
                continue
            status, path = line[:2], line[3:].strip().strip('"')
            entry = {
                "status": status.strip() or status,
                "path": path.replace("\\", "/"),
                "protected": path.replace("\\", "/") in protected_set,
            }
            out.append(entry)
        return out

    atlas_head = _git(repo_root, "rev-parse", "HEAD")
    memoryos_head = _git(MEMORYOS_ROOT, "rev-parse", "HEAD")
    atlas_data_dir = os.environ.get("ATLAS_DATA_DIR", "")
    normalized = atlas_data_dir.replace("\\", "/").rstrip("/").lower() if atlas_data_dir else ""
    forbidden_normalized = [p.lower().rstrip("/") for p in PRODUCTION_PATHS_FORBIDDEN]
    under_forbidden = any(
        normalized == f or normalized.startswith(f + "/") for f in forbidden_normalized
    ) if normalized else False

    return {
        "atlas": {
            "root": str(repo_root).replace("\\", "/"),
            "head": atlas_head,
            "branch": _git(repo_root, "rev-parse", "--abbrev-ref", "HEAD"),
            "dirty_files": dirty_entries(repo_root),
        },
        "memoryos": {
            "root": str(MEMORYOS_ROOT).replace("\\", "/"),
            "head": memoryos_head,
            "head_expected": MEMORYOS_HEAD_EXPECTED,
            "head_matches_research_snapshot": memoryos_head == MEMORYOS_HEAD_EXPECTED,
            "branch": _git(MEMORYOS_ROOT, "rev-parse", "--abbrev-ref", "HEAD"),
            "dirty_files": dirty_entries(MEMORYOS_ROOT),
        },
        "interpreters": {
            "atlas": _python_version(repo_root / "core" / ".venv" / "Scripts" / "python.exe"),
            "memoryos": _python_version(
                MEMORYOS_ROOT / "service" / ".venv" / "Scripts" / "python.exe"
            ),
            "current": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        },
        "production_paths_forbidden": PRODUCTION_PATHS_FORBIDDEN,
        "data_root_guard": {
            "atlas_data_dir_env": atlas_data_dir,
            "is_under_forbidden_root": under_forbidden,
            "allowed": not under_forbidden,
            "rule": "baseline.py 与其测试拒绝把 ATLAS_DATA_DIR 指向生产数据根（总任务书 §8 隔离环境）",
        },
        "protected_workspace_files": PROTECTED_WORKSPACE_FILES,
    }


def build_decision() -> dict:
    """unified_jobs 复用判定：复用 extraction_sessions，扩展 job_type。"""
    evidence: list[dict] = []
    cites: dict[str, int] = {}
    if MEMORYOS_EXTRACTION_JOBS.exists():
        text = MEMORYOS_EXTRACTION_JOBS.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        markers = [
            ("job_type_comment", r"用 job_type 区分"),
            ("job_types_tuple", r"^JOB_TYPES\s*="),
            ("active_states", r"^ACTIVE_STATES\s*="),
            ("def_lease_seconds", r"^def lease_seconds"),
            ("keyed_by_source_and_job_type", r"AND job_type = \?"),
            ("service_layer_validation", r"job_type not in JOB_TYPES"),
            ("claim_insert", r"INSERT INTO extraction_sessions"),
            ("expired_lease_reclaim", r"过期 lease 的 reclaim"),
        ]
        for key, pattern in markers:
            for idx, line in enumerate(lines, start=1):
                if re.search(pattern, line):
                    cites[key] = idx
                    evidence.append({
                        "cite": f"service/extraction_jobs.py:{idx}",
                        "marker": key,
                        "snippet": line.strip()[:160],
                    })
                    break

    def c(key: str) -> str:
        line = cites.get(key)
        return f"service/extraction_jobs.py:{line}" if line else key

    return {
        "question": (
            "MemoryOS 侧是否需要新建 unified_jobs 表来承载 UM01+ 的迁移/整理/维护后台任务？"
        ),
        "decision": "REUSE_EXTRACTION_SESSIONS_EXTEND_JOB_TYPE",
        "target": (
            "D:/MemoryOS/service/extraction_jobs.py 所管理的 extraction_sessions"
            "（EXTRACT_MEMORY 的 Durable Job Ledger）"
        ),
        "rationale": [
            f"extraction_sessions 已按 (source_id, job_type) 建行，同一 source 可并行多类 job"
            f"（{c('keyed_by_source_and_job_type')}）；扩 job_type 无 schema 变更："
            f"DB 不再 CHECK 单值、由 Service 层 JOB_TYPES 元组校验"
            f"（{c('job_type_comment')}、{c('job_types_tuple')}、{c('service_layer_validation')}）。",
            f"lease 语义完备：PENDING/LEASED/RUNNING/… 状态机，ACTIVE_STATES 且 "
            f"lease_expires_at 未过期不可抢、过期可 reclaim 且保留 job 自身模型绑定"
            f"（{c('active_states')}、{c('def_lease_seconds')}、{c('expired_lease_reclaim')}）——"
            f"迁移/整理 worker 崩溃后可安全接管。",
            f"幂等：同 (source_id, job_type) 首次 claim 才 INSERT（{c('claim_insert')}），"
            f"重复 claim 命中既有行；01_contracts.md:182 POST /v1/unified/maintenance "
            f"要求『重试同 snapshot 去重』，现有 ledger 直接满足。",
            f"CONSOLIDATE_EPISODE 已示范第二类 job 的接入方式（同文件 claim/INSERT 均带 job_type 维度），"
            f"新增 MIGRATE_LEGACY / CONSOLIDATE_* 等 job_type 复用同一 worker/lease 路径，"
            f"不需要第二套队列产品。",
        ],
        "consequence": (
            "不新建 unified_jobs 表；MemoryOS unified maintenance 队列复用 extraction_sessions，"
            "新增 job_type 在 Service 层 JOB_TYPES 注册并保持 lease/幂等语义不变。"
        ),
        "evidence": evidence,
    }


# ---------------------------------------------------------------------------
# 主构建
# ---------------------------------------------------------------------------

def build_baseline(repo_root: Path | None = None) -> dict:
    repo_root = repo_root or REPO_ROOT
    memory_path = repo_root / "core" / "atlas" / "memory" / "__init__.py"
    source = memory_path.read_text(encoding="utf-8")
    source_lines = source.splitlines()

    tables = _parse_tables(source, source_lines)
    methods, adjacency = _parse_methods(source)
    known_tables = set(tables)

    # 每个方法的表读写（含类内调用闭包）。
    tables_by_method: dict[str, tuple[set[str], set[str]]] = {}
    for method in methods:
        segment = "\n".join(source_lines[method["line"] - 1: method["end_line"]])
        tables_by_method[method["name"]] = _table_usage(segment, known_tables)
    _closure(tables_by_method, adjacency)

    # 消费者扫描。
    public_methods = [m for m in methods if m["visibility"] == "public"]
    public_names = {m["name"] for m in public_methods}
    scan = _scan_consumers(repo_root, public_names)
    consumers_by_method: dict[str, list[dict]] = {name: [] for name in public_names}
    unmapped: list[dict] = []
    for consumer in scan["consumers"]:
        entry = {
            "file": consumer["file"],
            "line": consumer["line"],
            "receiver": consumer["receiver"],
            "kind": consumer["kind"],
        }
        if consumer["kind"] == "parse_error":
            unmapped.append(consumer)
            continue
        if consumer["method"] in consumers_by_method:
            consumers_by_method[consumer["method"]].append(entry)
        else:
            unmapped.append(consumer)

    # 直摸 _db 消费者与替换计划（按 file+receiver+attribute 分组）。
    direct_db_consumers: list[dict] = []
    grouped: dict[tuple, dict] = {}
    for hit in scan["direct_db"]:
        key = (hit["file"], hit["receiver"], hit["attribute"])
        group = grouped.setdefault(
            key,
            {
                "file": hit["file"],
                "receiver": hit["receiver"],
                "attribute": hit["attribute"],
                "lines": [],
                "replacement_plan": DIRECT_DB_PLANS.get(hit["file"], ""),
            },
        )
        group["lines"].append(hit["line"])
    direct_db_consumers = list(grouped.values())
    for entry in direct_db_consumers:
        entry["lines"] = sorted(set(entry["lines"]))
        if not entry["replacement_plan"]:
            unmapped.append({
                "kind": "direct_db_without_plan",
                "file": entry["file"],
                "lines": entry["lines"],
            })

    # 表条目：分类 + 证据。
    table_entries: list[dict] = []
    classifications: dict[str, str] = {}
    warnings: list[str] = []
    for name in sorted(tables):
        info = tables[name]
        note = TABLE_NOTES.get(name)
        if note is None:
            warnings.append(f"table {name}: 缺少 TABLE_NOTES 判定，未分类")
            continue
        writers: list[dict] = []
        readers: list[dict] = []
        for method in methods:
            w, r = tables_by_method[method["name"]]
            if name in w:
                writers.append({"method": method["name"], "line": method["line"]})
            if name in r:
                readers.append({"method": method["name"], "line": method["line"]})
        col_cites = []
        col_index = {c["name"]: c["line"] for c in info["columns"]}
        for col in note["cite_cols"]:
            if col in col_index:
                col_cites.append(f"{col}(L{col_index[col]})")
            else:
                col_cites.append(col)
        reason = (
            f"{note['why']} 字段依据：{', '.join(col_cites)}。"
            f"实际写入方：{', '.join(w['method'] + '(L' + str(w['line']) + ')' for w in writers[:6]) or '（无）'}；"
            f"实际读取方：{', '.join(r['method'] + '(L' + str(r['line']) + ')' for r in readers[:6]) or '（无）'}。"
        )
        if note["category"] == "MEMORY_AUTHORITY" and not writers:
            warnings.append(f"table {name}: 分类 MEMORY_AUTHORITY 但未发现写入方法")
        classifications[name] = note["category"]
        table_entries.append({
            "name": name,
            "kind": info["kind"],
            "definition_lines": info["definition_lines"],
            "canonical_line": info["canonical_line"],
            "alternate_definition_lines": info["alternate_definition_lines"],
            "columns": info["columns"],
            "category": note["category"],
            "reason": reason,
            "written_by": writers,
            "read_by": readers,
        })

    # 方法条目：职责 + authority + replacement + consumers。
    method_entries: list[dict] = []
    for method in public_methods:
        name = method["name"]
        mapping = METHOD_MAP.get(name)
        w, r = tables_by_method[name]
        if mapping is None:
            unmapped.append({
                "kind": "unmapped_method",
                "method": name,
                "file": "core/atlas/memory/__init__.py",
                "line": method["line"],
            })
            authority, replacement, api, note = "", "", "", ""
        else:
            authority, replacement, api, note = mapping
        if replacement and replacement not in REPLACEMENT_KINDS:
            warnings.append(f"method {name}: 未知 replacement {replacement}")
        if authority and authority not in CATEGORIES:
            warnings.append(f"method {name}: 未知 authority {authority}")
        responsibility = method["docstring"] or FALLBACK_RESPONSIBILITY.get(name, "")
        entry = {
            "name": name,
            "file": "core/atlas/memory/__init__.py",
            "line": method["line"],
            "end_line": method["end_line"],
            "responsibility": responsibility,
            "tables_written": sorted(w),
            "tables_read": sorted(r),
            "authority": authority,
            "replacement": replacement,
            "delegate_api": api,
            "note": note,
            "consumers": sorted(
                consumers_by_method.get(name, []),
                key=lambda c: (c["file"], c["line"]),
            ),
        }
        method_entries.append(entry)

    method_entries.sort(key=lambda m: m["line"])

    construction_points = []
    for rel, line in [
        ("core/atlas/server.py", 248),
        ("core/atlas/cli.py", 77),
        ("core/atlas/runtime/hub.py", 135),
        ("core/scripts/baseline_metrics.py", 320),
    ]:
        path = repo_root / rel
        construction_points.append({
            "file": rel,
            "line": line,
            "exists": path.exists(),
            "note": "生产 MemoryStore 构造点（T01.3 统一 composition 的改造对象）",
        })

    result = {
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_of_truth": {
            "memory_store": {
                "file": "core/atlas/memory/__init__.py",
                "class_line": 108,
                "total_lines": len(source_lines),
                "create_tables_methods": {
                    "_create_tables": "L133-L714",
                    "_ensure_knowledge_table": "L4173-L4216",
                },
            },
            "spec": [
                "docs/plan/UNIFIED-MEMORY/00_master_task.md §5",
                "docs/plan/UNIFIED-MEMORY/02_wave_tasks.md T00.1",
            ],
        },
        "production_db_opened": False,
        "static_analysis": {
            "tool": "ast + re（纯标准库）",
            "sqlite3_imported": False,
            "atlas_package_imported": False,
            "scanned_files": scan["scanned_files"],
        },
        "tables": table_entries,
        "classifications": classifications,
        "methods": method_entries,
        "construction_points": construction_points,
        "direct_db_consumers": direct_db_consumers,
        "unmapped_memory_consumers": unmapped,
        "env_manifest": build_env_manifest(repo_root),
        "decision": build_decision(),
        "validation_warnings": warnings,
        "summary": {},
    }
    result["summary"] = {
        "table_count": len(table_entries),
        "category_counts": {
            cat: sum(1 for t in table_entries if t["category"] == cat)
            for cat in CATEGORIES
        },
        "public_method_count": len(public_methods),
        "replacement_counts": {
            kind: sum(1 for m in method_entries if m["replacement"] == kind)
            for kind in REPLACEMENT_KINDS
        },
        "consumer_call_site_count": sum(
            len(m["consumers"]) for m in method_entries
        ),
        "direct_db_consumer_count": len(direct_db_consumers),
        "unmapped_consumer_count": len(unmapped),
    }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T00.1 静态权威映射基线")
    default_out = REPO_ROOT / "docs" / "plan" / "UNIFIED-MEMORY" / "authority-map.json"
    parser.add_argument("--out", type=Path, default=default_out)
    parser.add_argument("--repo", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)

    data = build_baseline(args.repo)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    summary = data["summary"]
    print(
        f"tables={summary['table_count']} "
        f"methods={summary['public_method_count']} "
        f"consumers={summary['consumer_call_site_count']} "
        f"direct_db={summary['direct_db_consumer_count']} "
        f"unmapped={summary['unmapped_consumer_count']}"
    )
    for warning in data["validation_warnings"]:
        print(f"WARN: {warning}", file=sys.stderr)
    if summary["unmapped_consumer_count"]:
        print("FAIL: 存在未映射的记忆消费者", file=sys.stderr)
        return 2
    print(f"written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

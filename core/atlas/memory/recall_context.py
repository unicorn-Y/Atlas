"""S3 召回装配 (Recall Context Assembly) 与 意图闸门 (Intent Gate).

提供两块上下文输出供 run_phases._phase_context 调用:
1. 画像块 (Profile block):
   - 稳定、低频变化的内容 (我对用户的了解，facet=SUMMARY/scope=PROFILE)。
   - ≤ 600 token，放置在系统提示词靠前、稳定的位置以享受 LLM Prompt Cache (Mastra 模式)。
   - 在 S4 反思者 (Reflector) 阶段完成前，调用 GET /v1/unified/profile 输出代替。
2. 相关记忆块 (Relevant memories block):
   - 每轮按需动态检索: POST /v1/unified/recall (query = 当前用户消息 + 最近1-2轮摘要)。
   - 默认 top-k 8，总长 ≤ 1500 token。
   - 每条标注 [m:<短ref>]、日期、"当前/历史" 状态。
   - 若命中 CONFLICTED 或存在同名/歧义候选，明确标注 【有冲突/有多个候选】。

意图闸门 (Intent Gate):
- 结合 Embedding 向量相似度阈值 + 轻量规则过滤。
- 绝不在每轮额外调用大模型 (零额外 LLM 开销)。
- 纯技术问题 (如 "Python dict 怎么排序")、纯数学计算不召回私事，只提供画像块；
- 涉及偏好、排期、日程、历史、个人约束的问题放行并召回私事记忆。
- 阈值支持通过环境变量 ATLAS_MEMORY_INTENT_THRESHOLD 动态配置。

出处追踪 (Provenance & Attribution):
- 提供系统提示词出处说明 ([m:<ref>] 含义及引用纪律)。
- 仅允许引用本轮真正装配进上下文的 ref；输出中出现不存在或未装配的 ref 时标为 "未验证"。
- 整个装配过程具备完整结构化日志 (记录装配了哪些 ref、原因、闸门判定详情)，完全可复现。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
import os
import re
from typing import Any, Sequence

import structlog

log = structlog.get_logger("atlas.memory.recall_context")

# ---------------------------------------------------------------------------
# 常量与配置
# ---------------------------------------------------------------------------

DEFAULT_INTENT_THRESHOLD: float = float(
    os.getenv("ATLAS_MEMORY_INTENT_THRESHOLD", "0.35")
)
DEFAULT_TOP_K: int = 8
MAX_PROFILE_TOKENS: int = 600
MAX_MEMORY_TOKENS: int = 1500

# 个人与任务记忆向量锚点 (用于无 LLM 调用的本地嵌入相似度判决)
PERSONAL_INTENT_ANCHORS: tuple[str, ...] = (
    "用户的个人信息、背景经历与日常生活记录",
    "用户的个人偏好、工作习惯与输出格式要求",
    "用户的日程安排、工作计划、待办事项与时间提醒",
    "用户自定义的项目约束、业务规则与约定事项",
    "用户的人际关系、家庭成员、朋友与同事背景",
    "用户之前交代的事情、上次讨论的内容与历史背景",
)

TECH_GENERIC_ANCHORS: tuple[str, ...] = (
    "通用的算法实现、代码语法、编程语言库函数用法",
    "通用的数学计算、代数求值与数值运算",
    "通用的操作系统命令、网络协议与硬件知识",
    "标准计算机科学理论、数据结构与系统设计模式",
)

# ---------------------------------------------------------------------------
# Token 估算辅助
# ---------------------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    """估算文本所占用的 Token 数量。优先使用 tiktoken，降级为字数折算。"""
    if not text:
        return 0
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        # 中英文混合保守估算: 英文约 4 字符/token，中文约 1.5-2 字符/token
        # len(text) // 2 贴合混合语境
        return max(1, len(text) // 2)


# ---------------------------------------------------------------------------
# 本地轻量级稠密/稀疏向量嵌入 (无需外部模型/API，零网络与 LLM 开销)
# ---------------------------------------------------------------------------

def _hash_vector(text: str, dim: int = 512) -> list[float]:
    """使用字符 n-gram 与哈希投影计算局部文本向量 (Subword n-gram embedding)。"""
    vec = [0.0] * dim
    t = text.strip().lower()
    if not t:
        return vec

    # 提取 1-gram, 2-gram, 3-gram
    ngrams: list[str] = []
    # 词级别 (针对英文或空格分词)
    words = re.findall(r"\w+", t)
    ngrams.extend(words)
    # 字符级别 (针对中文与混合字符)
    for n in (1, 2, 3):
        for i in range(len(t) - n + 1):
            ngrams.append(t[i : i + n])

    for gram in ngrams:
        # 使用 sha256 确保跨平台完全确定性
        h = int(hashlib.sha256(gram.encode("utf-8")).hexdigest()[:8], 16)
        idx = h % dim
        vec[idx] += 1.0

    # L2 归一化
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


def _cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """计算两个归一化向量的余弦相似度。"""
    if len(v1) != len(v2):
        return 0.0
    return sum(a * b for a, b in zip(v1, v2))


# 预计算锚点向量
_PRECOMPUTED_PERSONAL_VECS = [_hash_vector(a) for a in PERSONAL_INTENT_ANCHORS]
_PRECOMPUTED_TECH_VECS = [_hash_vector(a) for a in TECH_GENERIC_ANCHORS]


# ---------------------------------------------------------------------------
# 意图闸门 (Intent Gate)
# ---------------------------------------------------------------------------

def is_personal_memory_relevant(
    query: str, threshold: float | None = None
) -> tuple[bool, float, str]:
    """判断查询是否需要检索个人记忆。

    返回: (is_relevant: bool, score: float, reason: str)
    特点:
      - 不在每轮额外调用大模型；
      - 结合轻量规则与嵌入相似度阈值；
      - 纯代码/纯数学/纯理论等无个人线索的问题返回 False (避免硬塞私事)；
      - 包含个人偏好、排期、项目约束或高相关度的问题返回 True。
    """
    eff_threshold = threshold if threshold is not None else DEFAULT_INTENT_THRESHOLD
    if not query or not isinstance(query, str):
        return False, 0.0, "rule:empty_query"

    q = query.strip()
    if not q:
        return False, 0.0, "rule:blank_query"

    # --- 1. 轻量规则快速拦截: 纯数学/算术计算 ---
    math_patterns = (
        r"(?:算一下|计算|求值|等于几).*(?:\d+|[\+\-\*\/]|乘以|除以|加上|减去)",
        r"\d+\s*(?:\+|加|减|\-|乘|\*|乘以|除|\/|除以)\s*\d+",
        r"^(?:帮我)?(?:算一下|计算)\b",
    )
    is_pure_math = any(re.search(pat, q) for pat in math_patterns)
    has_personal_cues_math = any(
        k in q for k in ("我的", "上次", "习惯", "偏好", "排期", "日程", "安排", "项目")
    )
    if is_pure_math and not has_personal_cues_math:
        return False, 0.05, "rule:pure_math_calculation"

    # --- 2. 轻量规则拦截: 纯通用代码/库函数用法 ---
    generic_code_patterns = (
        r"(?:python|java|c\+\+|golang|rust|javascript|typescript|sql|html|css|linux|bash)\b.*(?:怎么|如何|写法|排序|遍历|反转|用法|实现|报错)",
        r"^(?:怎么|如何|什么是|介绍一下)(?:使用|实现|排序|遍历|写)?\s*[a-zA-Z0-9_]+",
        r"^(?:如何|怎么)(?:实现|编写|运行).*(?:算法|函数|脚本|代码)$",
    )
    is_generic_code = any(re.search(pat, q, re.IGNORECASE) for pat in generic_code_patterns)
    has_personal_cues_code = any(
        k in q
        for k in (
            "我的", "我们", "上次", "项目", "格式", "按我", "习惯", "偏好",
            "之前", "约束", "约定", "老王", "女儿", "儿子", "同事"
        )
    )
    if is_generic_code and not has_personal_cues_code:
        return False, 0.1, "rule:pure_generic_code"

    # --- 3. 显式个人线索规则匹配 (强指示信号) ---
    personal_keywords = (
        "按我", "习惯", "偏好", "喜欢", "爱喝", "爱吃", "讨厌", "风格",
        "上次", "昨天", "明天", "日程", "计划", "提醒", "备忘", "记住",
        "约定", "约束", "要求", "住哪", "住在", "公司", "职位", "工作",
        "女儿", "儿子", "老婆", "老公", "老王", "多大", "几岁", "叫什么",
        "你对我", "关于我", "我的情况", "适合我", "前几天", "后来改成",
    )
    has_explicit_personal = any(k in q for k in personal_keywords)
    has_self_pronoun = any(p in q for p in ("我", "我的", "我们"))

    # --- 4. 向量嵌入相似度计算 (Vector Embedding Cosine Similarity) ---
    q_vec = _hash_vector(q)
    max_personal_sim = max(
        _cosine_similarity(q_vec, a_vec) for a_vec in _PRECOMPUTED_PERSONAL_VECS
    )
    max_tech_sim = max(
        _cosine_similarity(q_vec, a_vec) for a_vec in _PRECOMPUTED_TECH_VECS
    )

    # 综合相似度得分: 个人相似度 + 显式信号加权 - 纯技术干扰
    score = max_personal_sim
    if has_explicit_personal and has_self_pronoun:
        score += 0.40
    elif has_explicit_personal:
        score += 0.30
    elif has_self_pronoun and any(w in q for w in ("什么", "哪", "多", "谁", "几")):
        score += 0.30
    elif has_self_pronoun:
        score += 0.15

    if is_generic_code or is_pure_math:
        score -= 0.25

    score = max(0.0, min(1.0, score))

    if has_explicit_personal and score >= eff_threshold:
        return True, score, "rule_and_embedding:explicit_personal"

    if score >= eff_threshold:
        return True, score, f"embedding_similarity:{score:.3f}>={eff_threshold}"

    return False, score, f"embedding_similarity_below_threshold:{score:.3f}<{eff_threshold}"


# ---------------------------------------------------------------------------
# 出处说明与短 Ref 处理
# ---------------------------------------------------------------------------

PROVENANCE_SYSTEM_INSTRUCTION: str = (
    "【记忆出处与引用规范】\n"
    "在系统提示中带有形如 [m:<ref>] 的标记代表已验证的用户记忆出处条目。\n"
    "1. 当回答涉及用户的个人背景、过往事实、特定偏好或约定记录时，请务必在回答中引用对应的 [m:<ref>] 标号。\n"
    "2. 严禁凭空捏造不存在的记忆标号；只能引用本轮真正装配进上下文的 [m:<ref>]。\n"
    "3. 若记忆条目标注【有冲突/有多个候选】，说明记录存在歧义或不一致，回答前必须先向用户澄清确认。\n"
)


def to_short_ref(full_ref: str) -> str:
    """将完整 record_ref (如 memory:mem-123, episode:ep-456) 转换为短标记 ref。"""
    if not full_ref:
        return ""
    if ":" in full_ref:
        prefix, ident = full_ref.split(":", 1)
        return ident
    return full_ref


def verify_referenced_refs(
    text: str, assembled_refs: Sequence[str] | set[str]
) -> dict[str, Any]:
    """验证模型输出中引用的 [m:<ref>] 是否存在于本轮装配的记忆中。

    用于前端展示与合规校验: 不在 assembled_refs 中的引用将被标记为'未验证'。
    """
    found_refs = re.findall(r"\[m:([^\]]+)\]", text)
    valid_set = set()
    for r in assembled_refs:
        valid_set.add(r)
        valid_set.add(to_short_ref(r))

    valid: list[str] = []
    unverified: list[str] = []
    for ref in found_refs:
        clean = ref.strip()
        if clean in valid_set:
            valid.append(clean)
        else:
            unverified.append(clean)

    return {
        "all_found": found_refs,
        "valid_refs": valid,
        "unverified_refs": unverified,
        "has_unverified": len(unverified) > 0,
    }


# ---------------------------------------------------------------------------
# 结果模型
# ---------------------------------------------------------------------------

@dataclass
class RecallContextResult:
    """S3 召回装配统一返回结构体。"""

    profile_block: str
    relevant_memory_block: str
    assembled_refs: list[str]
    assembled_ref_map: dict[str, str]  # short_ref -> full_ref
    gate_passed: bool
    gate_score: float
    gate_reason: str
    conflicts_detected: list[dict[str, Any]] = field(default_factory=list)
    raw_profile: dict[str, Any] | None = None
    raw_recall: dict[str, Any] | None = None
    token_estimate: dict[str, int] = field(default_factory=dict)

    def format_system_prompt_prefix(self) -> str:
        """生成供系统提示词靠前位置注入的画像稳定块 (便于 Prompt Cache)。"""
        parts = [PROVENANCE_SYSTEM_INSTRUCTION]
        if self.profile_block:
            parts.append(self.profile_block)
        return "\n\n".join(parts)

    def format_advisory_context_block(self) -> str:
        """生成供建议块 (Advisory Context) 注入的相关记忆块。"""
        return self.relevant_memory_block

    def to_context_dict(self) -> dict[str, Any]:
        """转换为供 run_phases._phase_context 及 state.context 使用的上下文兼容字典。"""
        # 兼容原有 state.context["memories"] 格式
        memories_list = []
        if self.raw_recall and isinstance(self.raw_recall.get("context_items"), list):
            memories_list = self.raw_recall["context_items"]

        return {
            "profile_block": self.profile_block,
            "relevant_memory_block": self.relevant_memory_block,
            "assembled_refs": self.assembled_refs,
            "assembled_ref_map": self.assembled_ref_map,
            "memories": memories_list,
            "knowledge_trace": {
                "decisions": [
                    {
                        "gate_passed": self.gate_passed,
                        "gate_score": round(self.gate_score, 4),
                        "gate_reason": self.gate_reason,
                        "assembled_count": len(self.assembled_refs),
                    }
                ],
                "query_terms": [],
                "assembled_refs": self.assembled_refs,
                "conflicts": self.conflicts_detected,
            },
            "gate_passed": self.gate_passed,
            "token_estimate": self.token_estimate,
        }


# ---------------------------------------------------------------------------
# 画像块与相关记忆块的格式化装配
# ---------------------------------------------------------------------------

def _format_profile_block(
    profile_data: dict[str, Any] | None, max_tokens: int = MAX_PROFILE_TOKENS
) -> tuple[str, list[str], dict[str, str]]:
    """将 GET /v1/unified/profile 的输出格式化为紧凑稳定的画像文本块。"""
    if not profile_data or not isinstance(profile_data, dict):
        return "", [], {}

    lines: list[str] = ["【用户画像 (我对用户的了解)】"]
    assembled_refs: list[str] = []
    ref_map: dict[str, str] = {}

    sections = (
        ("偏好", profile_data.get("preferences") or []),
        ("状态", profile_data.get("states") or []),
        ("习惯", profile_data.get("habits") or []),
        ("人际", profile_data.get("relations") or []),
    )

    for sec_name, items in sections:
        if not items:
            continue
        lines.append(f"- {sec_name}:")
        for item in items:
            if not isinstance(item, dict):
                continue
            ref = str(item.get("record_ref") or item.get("id") or "")
            short = to_short_ref(ref) if ref else ""
            if ref and short:
                assembled_refs.append(ref)
                ref_map[short] = ref

            tag = f"[m:{short}] " if short else ""
            content = item.get("content") or {}
            text = (
                item.get("value")
                or content.get("value")
                or item.get("summary")
                or content.get("text")
                or item.get("title")
                or ""
            )
            key = item.get("key") or content.get("key")
            prefix = f"{key}: " if key and key not in text else ""
            lines.append(f"  * {tag}{prefix}{text}".strip())

    text_block = "\n".join(lines)
    # Token 超限截断
    if estimate_tokens(text_block) > max_tokens:
        text_lines = text_block.split("\n")
        truncated: list[str] = []
        for line in text_lines:
            cand = "\n".join(truncated + [line])
            if estimate_tokens(cand) > max_tokens:
                break
            truncated.append(line)
        text_block = "\n".join(truncated)

    return text_block, assembled_refs, ref_map


def _format_relevant_memories_block(
    recall_resp: dict[str, Any] | None, max_tokens: int = MAX_MEMORY_TOKENS
) -> tuple[str, list[str], dict[str, str], list[dict[str, Any]]]:
    """将 POST /v1/unified/recall 的输出格式化为带 [m:<短ref>]、日期、当前/历史与冲突标注的记忆块。"""
    if not recall_resp or not isinstance(recall_resp, dict):
        return "", [], {}, []

    items = recall_resp.get("context_items") or []
    conflicts = recall_resp.get("conflicts") or []
    conflicted_refs: set[str] = set()
    for conf in conflicts:
        for cr in conf.get("record_refs") or []:
            conflicted_refs.add(cr)
            conflicted_refs.add(to_short_ref(cr))

    if not items:
        return "", [], {}, conflicts

    lines: list[str] = ["【本轮相关记忆】"]
    assembled_refs: list[str] = []
    ref_map: dict[str, str] = {}

    for item in items:
        ref = str(item.get("record_ref") or "")
        short = to_short_ref(ref) if ref else "item"
        if ref:
            assembled_refs.append(ref)
            ref_map[short] = ref

        # 状态: 当前 / 历史
        lifecycle = str(item.get("lifecycle") or "ACTIVE").upper()
        content = item.get("content") or {}
        valid_time = item.get("valid_time") or content.get("valid_time") or {}
        time_status = valid_time.get("time_status") or "KNOWN"

        # 判断是否为历史
        is_historical = (lifecycle != "ACTIVE")
        valid_to = valid_time.get("valid_to")
        if valid_to and valid_to < datetime.now(timezone.utc).isoformat():
            is_historical = True

        status_label = "历史" if is_historical else "当前"

        # 日期
        date_str = (
            valid_time.get("valid_from")
            or item.get("recorded_at")
            or item.get("occurred_at")
            or content.get("occurred_at")
            or ""
        )
        if date_str and len(date_str) >= 10:
            date_clean = date_str[:10]
        else:
            date_clean = "未知日期"

        # 冲突标注
        conflict_tag = ""
        if ref in conflicted_refs or short in conflicted_refs or lifecycle == "CONFLICTED":
            conflict_tag = " | 【有冲突/有多个候选】"

        # 正文
        text = (
            content.get("text")
            or content.get("summary")
            or content.get("title")
            or item.get("summary")
            or json.dumps(content, ensure_ascii=False)
        )

        lines.append(
            f"- [m:{short}] ({date_clean} | {status_label}{conflict_tag}): {text}"
        )

    text_block = "\n".join(lines)
    # Token 超限截断
    if estimate_tokens(text_block) > max_tokens:
        text_lines = text_block.split("\n")
        truncated: list[str] = []
        for line in text_lines:
            cand = "\n".join(truncated + [line])
            if estimate_tokens(cand) > max_tokens:
                break
            truncated.append(line)
        text_block = "\n".join(truncated)

    return text_block, assembled_refs, ref_map, conflicts


def _build_recall_query(
    user_message: str, recent_history: Sequence[dict[str, Any]] | None
) -> str:
    """构建用于 POST /v1/unified/recall 的检索查询词 (当前用户消息 + 最近1-2轮摘要)。"""
    query = user_message.strip()
    if not recent_history:
        return query

    # 提取最近 1-2 轮的关键文本作为上下文摘要补充
    snippets: list[str] = []
    tail = recent_history[-4:]  # 最多看最近 2 轮对答
    for msg in tail:
        c = (msg.get("content") or "").strip()
        if c and c != query:
            # 截取前 80 字符作为语境
            snippets.append(c[:80].replace("\n", " "))

    if snippets:
        context_hint = "；".join(snippets)
        return f"{query} (最近语境: {context_hint})"

    return query


# ---------------------------------------------------------------------------
# 主装配入口 (供 run_phases._phase_context 调用)
# ---------------------------------------------------------------------------

async def assemble_recall_context(
    client: Any,
    user_message: str,
    recent_history: Sequence[dict[str, Any]] | None = None,
    *,
    subject: str = "subject-default",
    session_id: str | None = None,
    top_k: int = DEFAULT_TOP_K,
    max_profile_tokens: int = MAX_PROFILE_TOKENS,
    max_memory_tokens: int = MAX_MEMORY_TOKENS,
    intent_threshold: float | None = None,
    environment_id: str = "windows-default",
    purpose: str = "CONVERSATION",
) -> RecallContextResult:
    """供 run_phases._phase_context 调用的统一记忆上下文装配核心函数。

    参数:
      client: UnifiedMemoryClient、UnifiedMemoryFacade 或支持 HTTP 调用的 client
      user_message: 当前轮用户输入
      recent_history: 最近对话历史记录列表 (用于拼接 1-2 轮语境摘要)
      subject: 记忆主体 ID (默认 subject-default)
      session_id: 当前会话 ID
      top_k: 相关记忆条数上限 (默认 8)
      max_profile_tokens: 画像块 Token 上限 (默认 600)
      max_memory_tokens: 相关记忆块 Token 上限 (默认 1500)
      intent_threshold: 意图闸门阈值 (为 None 时读取环境变量或默认值 0.35)
      environment_id: 环境标识
      purpose: 召回意图模式 (默认 CONVERSATION)

    返回:
      RecallContextResult 实例，包含画像块、相关记忆块、装配的 refs、闸门判决详情及 token 估算。
    """
    start_time = datetime.now(timezone.utc)
    conv_id = session_id or "session-recall"

    # 1. 意图闸门判决 (本地计算，无 LLM 调用)
    gate_passed, gate_score, gate_reason = is_personal_memory_relevant(
        user_message, threshold=intent_threshold
    )

    # 2. 获取稳定画像块 (S4 反思者完成前，使用 GET /v1/unified/profile 输出代替)
    raw_profile: dict[str, Any] | None = None
    try:
        if hasattr(client, "_request"):
            raw_profile = await client._request(
                "GET", "/v1/unified/profile", params={"memory_subject_id": subject}
            )
        elif hasattr(client, "client") and hasattr(client.client(), "_request"):
            raw_profile = await client.client()._request(
                "GET", "/v1/unified/profile", params={"memory_subject_id": subject}
            )
        elif hasattr(client, "get"):
            resp = await client.get(
                "/v1/unified/profile", params={"memory_subject_id": subject}
            )
            raw_profile = resp.json() if hasattr(resp, "json") else None
    except Exception as exc:
        log.warning(
            "memory.recall_context.profile_fetch_failed",
            subject=subject,
            error=str(exc),
        )

    profile_text, profile_refs, profile_map = _format_profile_block(
        raw_profile, max_tokens=max_profile_tokens
    )

    # 3. 按意图闸门判定是否加载动态相关记忆块
    relevant_memories_text = ""
    recall_refs: list[str] = []
    recall_map: dict[str, str] = {}
    conflicts: list[dict[str, Any]] = []
    raw_recall: dict[str, Any] | None = None

    if gate_passed:
        recall_query = _build_recall_query(user_message, recent_history)
        recall_body = {
            "context": {
                "owner_id": "owner-local",
                "memory_subject_id": subject,
                "client_id": "atlas-desktop",
                "actor_id": "atlas-main",
                "runtime_session_id": conv_id,
                "task_id": None,
                "project_id": None,
                "environment_id": environment_id,
                "model_deployment_id": None,
            },
            "query": recall_query,
            "purpose": purpose,
            "budget": {
                "max_records": top_k,
                "max_tokens": max_memory_tokens,
            },
        }

        try:
            if hasattr(client, "recall"):
                raw_recall = await client.recall(recall_body)
            elif hasattr(client, "recall_for_conversation"):
                raw_recall = await client.recall_for_conversation(
                    recall_query,
                    budget={"max_records": top_k, "max_tokens": max_memory_tokens},
                    purpose=purpose,
                    context=recall_body["context"],
                )
            elif hasattr(client, "_request"):
                raw_recall = await client._request(
                    "POST", "/v1/unified/recall", json_body=recall_body
                )
            elif hasattr(client, "client") and hasattr(client.client(), "recall"):
                raw_recall = await client.client().recall(recall_body)
            elif hasattr(client, "post"):
                resp = await client.post("/v1/unified/recall", json=recall_body)
                raw_recall = resp.json() if hasattr(resp, "json") else None
        except Exception as exc:
            log.warning(
                "memory.recall_context.recall_fetch_failed",
                query=recall_query,
                error=str(exc),
            )

        (
            relevant_memories_text,
            recall_refs,
            recall_map,
            conflicts,
        ) = _format_relevant_memories_block(raw_recall, max_tokens=max_memory_tokens)

    # 4. 汇总装配的所有 ref 与短名映射
    all_refs = list(dict.fromkeys(profile_refs + recall_refs))
    merged_map = {**profile_map, **recall_map}

    token_est = {
        "profile_tokens": estimate_tokens(profile_text),
        "relevant_memory_tokens": estimate_tokens(relevant_memories_text),
        "total_advisory_tokens": estimate_tokens(profile_text)
        + estimate_tokens(relevant_memories_text),
    }

    # 5. 必须的装配过程日志 (每轮装配了哪些 ref、为什么、闸门判定结果，可从日志复现)
    log.info(
        "memory.recall_context.assembled",
        conversation_id=conv_id,
        user_message_snippet=user_message[:60],
        gate_passed=gate_passed,
        gate_score=round(gate_score, 4),
        gate_reason=gate_reason,
        assembled_refs=all_refs,
        profile_refs_count=len(profile_refs),
        recall_refs_count=len(recall_refs),
        conflicts_count=len(conflicts),
        token_estimate=token_est,
    )

    return RecallContextResult(
        profile_block=profile_text,
        relevant_memory_block=relevant_memories_text,
        assembled_refs=all_refs,
        assembled_ref_map=merged_map,
        gate_passed=gate_passed,
        gate_score=gate_score,
        gate_reason=gate_reason,
        conflicts_detected=conflicts,
        raw_profile=raw_profile,
        raw_recall=raw_recall,
        token_estimate=token_est,
    )

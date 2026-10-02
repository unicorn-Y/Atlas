"""E2 能力差异分类（确定性关键词 + 路径映射，无模型调用）。

映射表按 ``docs/plan/CORE-PARITY.md`` 的能力行（L/T/X/S/I/A/E/M/P）播种，
另补 SOURCE-MAP 里与上游追踪相关的少数行（浏览器 / MCP Apps / 渠道 / 语音 / 电脑操作）。
每个能力行携带：Atlas 现状（have / partial / missing）、Atlas 实现说明、
命中关键词与上游路径片段。

分类规则（全部确定性）：

1. 用标题（+3）、正文（+1）、变更路径（+3）给能力打分，最高分 < 2 判 IRRELEVANT。
2. 命中的能力若被上游 **移除/废弃** → ``REGRESSION_REMOVED``，``advisory=False``
   ——上游删功能永远只记录，绝不建议 Atlas 跟着删。
3. 否则按 Atlas 现状：missing → ``NEW``；partial → ``BETTER_THAN_ATLAS``；have → ``ALREADY_HAVE``。
"""

from __future__ import annotations

import re
from typing import Any

# 分值：标题命中 +3，正文命中 +1，路径命中 +3；低于该阈值视为不相关。
SCORE_TITLE, SCORE_BODY, SCORE_PATH = 3, 1, 3
MATCH_THRESHOLD = 2

#: 上游“移除/废弃”信号（对命中能力才生效）。
REMOVAL_PATTERN = re.compile(
    r"\b(remov\w+|drop\w+|deprecat\w+|retire\w+|delet\w+|uninstall\w*)\b|no longer|移除|删除|废弃",
    re.IGNORECASE,
)

#: Atlas 现状：have=已有且不差；partial=有但明显弱；missing=没有。
AtlasState = str  # "have" | "partial" | "missing"

#: 能力 → 关键词/路径映射表（播种自 docs/plan/CORE-PARITY.md 的能力行）。
CAPABILITY_MAP: tuple[dict[str, Any], ...] = (
    # --- Agent 循环（L）---
    {"id": "L1", "name": "不限轮数与预算控制", "state": "have",
     "impl": "Hermes iteration_budget 控预算，子 Agent 共享",
     "keywords": ["iteration budget", "turn limit", "max turns", "unlimited turns", "budget"],
     "paths": ["iteration_budget", "agent_loop"]},
    {"id": "L2", "name": "出错恢复", "state": "have",
     "impl": "限流/超时/空回复/截断/超长恢复（test_c1_recovery）",
     "keywords": ["rate limit", "retry", "timeout", "empty response", "truncat", "recovery",
                  "transcript repair", "overflow"],
     "paths": ["turn_recovery", "empty_response_guard", "turn_truncation", "turn_overflow",
               "transcript_repair", "error_classifier", "retry_utils"]},
    {"id": "L3", "name": "防原地打转", "state": "have",
     "impl": "Hermes repetition guard + 同文件计数提醒",
     "keywords": ["repetition", "spinning", "loop detection"],
     "paths": ["repetition_guard"]},
    {"id": "L4", "name": "完成前自检", "state": "have",
     "impl": "完成前验证闸门，未验证完成触发修正",
     "keywords": ["verification", "stop gate", "self check", "self-check", "evidence"],
     "paths": ["verification_stop", "turn_stop_gates", "verify_hooks"]},
    {"id": "L5", "name": "并行工具调用", "state": "have",
     "impl": "只读并行、写串行（Hermes tool_executor）",
     "keywords": ["parallel tool", "concurrent tool", "tool executor"],
     "paths": ["tool_executor"]},
    {"id": "L6", "name": "运行中插话/转向", "state": "have",
     "impl": "排队默认；立即转向走 Hermes redirect",
     "keywords": ["steer", "interrupt", "barge-in", "redirect", "message queue"],
     "paths": ["steer", "instant_interrupt"]},
    # --- 上下文（X）---
    {"id": "X1", "name": "自动上下文压缩", "state": "have",
     "impl": "Hermes ContextCompressor：先删工具输出再总结中段",
     "keywords": ["compact", "compaction", "compression", "summariz", "context window"],
     "paths": ["context_compressor", "micro_compaction", "conversation_compression", "tokenjuice"]},
    {"id": "X3", "name": "提示缓存/前缀稳定", "state": "have",
     "impl": "三层提示词组装，按模型族缓存标记",
     "keywords": ["prompt cache", "prefix cache", "cache prefix", "caching", "cache hit"],
     "paths": ["prompt_caching", "prompt_cache_boundary", "prompt_cache_scope"]},
    {"id": "X7", "name": "上下文构成透视", "state": "have",
     "impl": "系统提示/工具/规则/历史/余量分解展示",
     "keywords": ["context breakdown", "context remaining", "context usage"],
     "paths": ["context_breakdown"]},
    # --- 工具（T）---
    {"id": "T1", "name": "读文件（行号/分页）", "state": "have",
     "impl": "Hermes read_file：行号、分页、续读位置",
     "keywords": ["read file", "read_file", "pagination", "line number", "file paging"],
     "paths": ["read_file", "file_tools"]},
    {"id": "T2", "name": "读文档", "state": "have",
     "impl": "Hermes 文件工具集转文本（Office/PDF/EPUB…）",
     "keywords": ["pdf", "office", "docx", "xlsx", "epub", "document extract"],
     "paths": ["document", "extract"]},
    {"id": "T4", "name": "写文件防覆盖", "state": "have",
     "impl": "写保护经 Atlas 策略/快照桥接，写后哈希校验",
     "keywords": ["overwrite", "write guard", "hash check", "lint after write"],
     "paths": ["file_tools_write_guards", "file_operations_lint", "file_state"]},
    {"id": "T5", "name": "容错编辑", "state": "have",
     "impl": "Hermes 9 级放宽匹配 + OpenCode 唯一锚点匹配",
     "keywords": ["fuzzy match", "patch", "edit anchor", "apply_patch", "edit tool"],
     "paths": ["fuzzy_match", "patch_parser", "apply-patch", "edit.ts"]},
    {"id": "T8", "name": "LSP 诊断", "state": "have",
     "impl": "C6A LSP 核心接真实写/编辑链，只报新增诊断",
     "keywords": ["lsp", "diagnostic", "language server"],
     "paths": ["lsp", "diagnostics"]},
    {"id": "T9", "name": "代码搜索", "state": "have",
     "impl": "Hermes search_files（ripgrep，正则/过滤/分页）",
     "keywords": ["search", "ripgrep", "regex search", "grep", "glob"],
     "paths": ["search_files", "ripgrep"]},
    {"id": "T10", "name": "终端与后台进程", "state": "have",
     "impl": "前后台、结束通知、notify/watch/heartbeat 参数",
     "keywords": ["terminal", "background process", "heartbeat", "process registry"],
     "paths": ["terminal_tool", "process_registry", "unified_exec"]},
    {"id": "T11", "name": "真终端 PTY", "state": "have",
     "impl": "stdin 写入、Windows PTY、handoff",
     "keywords": ["pty", "stdin", "interactive shell", "repl"],
     "paths": ["pty", "unified_exec"]},
    {"id": "T13", "name": "网页搜索与抓取", "state": "have",
     "impl": "Atlas 网络工具（保留内网防护）",
     "keywords": ["web search", "web fetch", "web extract", "scrape", "crawler"],
     "paths": ["web_tools", "web_search", "web_read"]},
    {"id": "T14", "name": "待办清单", "state": "have",
     "impl": "Hermes todo 压缩后自动重注入",
     "keywords": ["todo", "task list", "checklist"],
     "paths": ["todo_tool", "todo"]},
    {"id": "T15", "name": "向用户提问", "state": "have",
     "impl": "clarify 接 Atlas 输入回调（选项预览）",
     "keywords": ["ask user", "clarify", "question tool", "askuserquestion"],
     "paths": ["clarify", "ask_user"]},
    {"id": "T17", "name": "工具按需加载", "state": "have",
     "impl": "Hermes tool search/toolset",
     "keywords": ["tool search", "on-demand tool", "tool catalog", "toolset"],
     "paths": ["tool_search"]},
    {"id": "T18", "name": "工具输出落盘/上限", "state": "have",
     "impl": "部分搬入（W06），输出过长截断+落盘",
     "keywords": ["tool output", "output limit", "truncate output", "result storage"],
     "paths": ["tool_output_limits", "tool_output_truncate", "tool_result_storage"]},
    # --- 会话（S）---
    {"id": "S2", "name": "会话分叉树", "state": "partial",
     "impl": "界面有分叉树；分支摘要与完整记录待补",
     "keywords": ["session tree", "fork session", "branch summar"],
     "paths": ["session_tree", "sessions"]},
    {"id": "S4", "name": "自动起标题", "state": "have",
     "impl": "新会话生成标题、延迟升级、手动改名保留",
     "keywords": ["title generat", "auto title", "rename conversation"],
     "paths": ["title_generator"]},
    {"id": "S5", "name": "搜历史会话", "state": "have",
     "impl": "Hermes session_search（FTS）",
     "keywords": ["session search", "history search", "conversation search"],
     "paths": ["session_search"]},
    # --- 交互（I）---
    {"id": "I1", "name": "权限档位", "state": "have",
     "impl": "ask_each/ask_writes/auto_file/plan/full_access/read_only",
     "keywords": ["permission mode", "approval mode", "auto approve", "yolo mode"],
     "paths": ["permission", "approval"]},
    {"id": "I2", "name": "计划模式", "state": "have",
     "impl": "只读探索后交计划，批准回执行",
     "keywords": ["plan mode", "exit plan", "read-only plan"],
     "paths": ["plan_prompt", "plan-enter", "plan_mode"]},
    {"id": "I3", "name": "持续目标", "state": "have",
     "impl": "GoalManager/SessionDB 同源，暂停恢复替换续跑",
     "keywords": ["goal", "subgoal", "standing objective"],
     "paths": ["goal_manager"]},
    # --- 子 Agent（A）---
    {"id": "A1", "name": "子 Agent 委派", "state": "have",
     "impl": "全链路子 Agent：模型/上下文策略、只读限制、进度清理",
     "keywords": ["delegate", "subagent", "sub-agent", "sub agent", "agent tool"],
     "paths": ["delegate_tool", "subagent", "async_delegation"]},
    {"id": "A3", "name": "自定义子 Agent 定义", "state": "have",
     "impl": "W07 已落地定义文件",
     "keywords": ["agent definition", "agent role", "agent frontmatter", ".claude/agents"],
     "paths": ["agents/", "agent_roles", "codex/agents"]},
    {"id": "A5", "name": "多模型会诊", "state": "have",
     "impl": "/moa 并发参考咨询",
     "keywords": ["moa", "mixture of agents", "multi model", "consult", "second opinion"],
     "paths": ["moa_"]},
    # --- 扩展（E）---
    {"id": "E1", "name": "MCP 客户端", "state": "partial",
     "impl": "Hermes MCP client（HTTP/OAuth 未实测）",
     "keywords": ["mcp", "model context protocol", "mcp oauth", "mcp health"],
     "paths": ["mcp_tool", "mcp_oauth", "mcp_schema"]},
    {"id": "E2", "name": "技能", "state": "have",
     "impl": "SKILL.md 渐进加载，目录合一的 SkillManager",
     "keywords": ["skill", "skills hub", "skill market"],
     "paths": ["skills", "skill_"]},
    {"id": "E3", "name": "Hooks", "state": "have",
     "impl": "兼容 .claude/settings.json hooks 全事件",
     "keywords": ["hook", "pre_tool_call", "post_tool_call", "lifecycle hook"],
     "paths": ["hooks"]},
    {"id": "E4", "name": "插件", "state": "partial",
     "impl": "CC 插件格式兼容；mcpb 打包未做",
     "keywords": ["plugin", "marketplace", "claude-plugin", "mcpb"],
     "paths": ["plugin", "marketplace"]},
    {"id": "E5", "name": "自定义命令", "state": "have",
     "impl": "兼容 .claude/commands + 五来源合并",
     "keywords": ["slash command", "custom command", "prompt template", "command template"],
     "paths": ["commands", "command/template"]},
    {"id": "E6", "name": "从别家导入配置", "state": "have",
     "impl": "扫描清单勾选导入，源目录零写入",
     "keywords": ["import settings", "import config", "migrate config"],
     "paths": ["import"]},
    # --- 模型（M）---
    {"id": "M1", "name": "模型服务商覆盖", "state": "partial",
     "impl": "16 家目录 + 原生直传 + models.dev 元数据",
     "keywords": ["provider", "model gateway", "model registry", "openrouter", "ollama"],
     "paths": ["provider_registry", "model-providers", "providers"]},
    {"id": "M2", "name": "多密钥轮换与冷却", "state": "have",
     "impl": "AtlasCredentialPool：keyring 存储、429 冷却",
     "keywords": ["credential pool", "key rotation", "cooldown", "api key pool"],
     "paths": ["credential_pool", "rate_limit_tracker", "fallback_cooldown"]},
    {"id": "M3", "name": "出错切换模型", "state": "have",
     "impl": "Hermes fallback model 配置传递",
     "keywords": ["fallback model", "model fallback", "failover"],
     "paths": ["fallback"]},
    {"id": "M5", "name": "用量与费用", "state": "partial",
     "impl": "W06 账本 + 缓存未命中原因（C5）",
     "keywords": ["usage", "pricing", "billing", "cost", "cache miss"],
     "paths": ["usage_pricing", "billing", "turn_usage"]},
    # --- 编程（P）---
    {"id": "P1", "name": "生成 AGENTS.md", "state": "have",
     "impl": "/init 确定性扫描 + 托管区段合并",
     "keywords": ["agents.md", "init command", "repo onboarding", "initialize"],
     "paths": ["init_command", "initialize"]},
    {"id": "P2", "name": "审查当前改动", "state": "have",
     "impl": "/review 结构化审查员子代理 + findings 卡片",
     "keywords": ["code review", "reviewer", "auto-review", "guardian", "review finding"],
     "paths": ["review_engine", "review", "guardian"]},
    {"id": "P3", "name": "worktree 隔离", "state": "have",
     "impl": "隔离分支 worktree 已接",
     "keywords": ["worktree", "git worktree"],
     "paths": ["worktree"]},
    # --- SOURCE-MAP 相关（上游追踪关心的少数行）---
    {"id": "B1", "name": "浏览器工具", "state": "have",
     "impl": "CDP/快照/视觉/对话框/多帧已接",
     "keywords": ["browser", "cdp", "playwright", "chromium"],
     "paths": ["browser"]},
    {"id": "B2", "name": "后台电脑操作（不抢鼠标）", "state": "partial",
     "impl": "前台 computer-use；CUA 后台驱动未接",
     "keywords": ["computer use", "uia", "postmessage", "background control", "cua"],
     "paths": ["cua", "computer_use"]},
    {"id": "F1", "name": "MCP Apps（对话内交互界面）", "state": "missing",
     "impl": "未实现（依赖 @mcp-ui/client）",
     "keywords": ["mcp app", "mcp-ui", "app renderer", "ext-apps"],
     "paths": ["ext-apps", "mcp-ui"]},
    {"id": "F2", "name": "连接器目录", "state": "missing",
     "impl": "未实现",
     "keywords": ["connector", "integration catalog", "one-click connect"],
     "paths": ["connectors"]},
    {"id": "F3", "name": "聊天渠道", "state": "partial",
     "impl": "仅 Telegram；飞书/钉钉/企微/邮件未接",
     "keywords": ["feishu", "lark", "dingtalk", "wecom", "slack", "discord", "email platform",
                  "whatsapp"],
     "paths": ["platforms", "gateway"]},
    {"id": "V1", "name": "本地语音识别", "state": "missing",
     "impl": "未实现（sherpa-onnx / SenseVoice 未接）",
     "keywords": ["sensevoice", "vad", "wake word", "local transcription", "sherpa", "asr"],
     "paths": ["transcription_local", "wake_word", "sherpa"]},
)


def _score_text(text: str, keywords: list[str]) -> int:
    low = text.lower()
    return sum(1 for kw in keywords if kw.lower() in low)


def _score_paths(paths: list[str], files: list[str]) -> int:
    if not files:
        return 0
    hits = 0
    for file_path in files:
        low = file_path.lower().replace("\\", "/")
        for pattern in paths:
            if pattern.lower() in low:
                hits += 1
                break
    return hits * SCORE_PATH


def match_capabilities(
    entry: dict[str, Any], capability_map: tuple[dict[str, Any], ...] | None = None,
) -> list[dict[str, Any]]:
    """返回按分数降序的命中能力（含分数），空列表即 IRRELEVANT。"""
    capability_map = capability_map or CAPABILITY_MAP
    subject = str(entry.get("subject") or entry.get("title") or "")
    body = str(entry.get("body") or "")
    files = [str(f) for f in (entry.get("files") or [])]
    scored: list[dict[str, Any]] = []
    for capability in capability_map:
        score = SCORE_TITLE * _score_text(subject, capability["keywords"])
        score += SCORE_BODY * _score_text(body, capability["keywords"])
        score += _score_paths(capability["paths"], files)
        if score >= MATCH_THRESHOLD:
            scored.append({"id": capability["id"], "name": capability["name"], "score": score})
    scored.sort(key=lambda row: (-row["score"], row["id"]))
    return scored


def _get_capability(
    capability_id: str, capability_map: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    for capability in capability_map:
        if capability["id"] == capability_id:
            return capability
    return {}


def classify_entry(
    entry: dict[str, Any], capability_map: tuple[dict[str, Any], ...] | None = None,
) -> dict[str, Any]:
    """单条上游更新的确定性分类（见模块 docstring 的规则）。"""
    capability_map = capability_map or CAPABILITY_MAP
    matches = match_capabilities(entry, capability_map)
    files = [str(f) for f in (entry.get("files") or [])]
    text = " ".join([
        str(entry.get("subject") or entry.get("title") or ""),
        str(entry.get("body") or ""),
    ])
    base = {
        "source": entry.get("source") or entry.get("repo"),
        "repo": entry.get("repo"),
        "entry_id": entry.get("id"),
        "kind": entry.get("kind"),
        "title": entry.get("title") or entry.get("subject"),
        "published_at": entry.get("published_at"),
        "capabilities": matches[:3],
        "advisory": True,
    }
    if not matches:
        return {**base, "cls": "IRRELEVANT", "advisory": False,
                "reason": "未命中任何能力关键词或路径，暂与 Atlas 无关"}
    top = _get_capability(matches[0]["id"], capability_map)
    name = top.get("name") or matches[0]["id"]
    matched_files = [
        f for f in files
        if any(p.lower() in f.lower().replace("\\", "/") for p in top.get("paths", []))
    ]
    base["matched_files"] = matched_files
    if REMOVAL_PATTERN.search(text):
        return {**base, "cls": "REGRESSION_REMOVED", "advisory": False,
                "reason": f"上游移除/废弃了「{name}」相关内容；仅记录，不建议 Atlas 跟随移除"}
    state = str(top.get("state") or "partial")
    if state == "missing":
        return {**base, "cls": "NEW",
                "reason": f"Atlas 尚无「{name}」，上游提供了实现，可评估引入"}
    if state == "partial":
        return {**base, "cls": "BETTER_THAN_ATLAS",
                "reason": f"上游在「{name}」上有 Atlas 没有的强化，建议对照升级"}
    return {**base, "cls": "ALREADY_HAVE",
            "reason": f"Atlas 已实现「{name}」，此更新与现状重叠，保持关注即可"}


#: 全部类别（供路由/前端枚举）。
CLASSES = ("NEW", "BETTER_THAN_ATLAS", "ALREADY_HAVE", "REGRESSION_REMOVED", "IRRELEVANT")


def diff_entries(
    entries: list[dict[str, Any]], capability_map: tuple[dict[str, Any], ...] | None = None,
) -> list[dict[str, Any]]:
    """批量分类；默认过滤 IRRELEVANT 也可以传 include_irrelevant=True。"""
    return [classify_entry(entry, capability_map) for entry in entries]


def summarize_classes(diffs: list[dict[str, Any]]) -> dict[str, int]:
    """按类别计数（中文界面用它显示徽标）。"""
    counts = {cls: 0 for cls in CLASSES}
    for diff in diffs:
        counts[diff["cls"]] = counts.get(diff["cls"], 0) + 1
    return counts

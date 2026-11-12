"""Deterministic tool-schema pruning for Atlas's model-facing tool pool.

The kernel advertises ~100 function schemas plus the agent catalog layer on every
turn. Most of them cannot possibly matter for the message at hand, and every
unused schema is permanent prompt weight. This module ranks the pool against the
current message and returns a bounded subset.

Contract (enforced by ``tests/test_tool_pruning.py``):

* **Pure.** No file IO, no environment reads, no logging, no module-level cache.
  Every public function returns a new list or dict.
* **Deterministic.** The same inputs always produce byte-identical output.
  Ties break on the tool name, never on ``set`` iteration order.
* **Total.** Malformed entries are skipped instead of raising, because callers
  feed it live registry output.

Two selection modes
-------------------
``select_tools`` re-ranks against each message. It is the sharper cut, but it
also produces a *different prompt prefix every turn*, which defeats provider
prefix caching. A 13k-token tool block is worth far more as a cache hit than as
a slimmer block, so production callers should prefer the tier mode:

``tier_key``            map a message onto one coarse, stable bucket.
``select_tools_for_tier`` the pool for a bucket, independent of the message.

In tier mode a conversation keeps one bucket, so the prompt prefix stays
byte-identical turn after turn and still lands near ``budget`` schemas.

Public API
----------
``select_tools``          rank + cut a schema pool down to ``budget`` entries.
``explain_selection``     the same computation plus per-tool scores and reasons.
``select_tools_for_tier`` the deterministic pool for a stable tier.
``tier_key``              the coarse tier a message belongs to.
``normalize_tier``        coerce an arbitrary string onto a known tier.
``merge_schemas``         first-wins de-duplication by function name.
``tokenize``              the light bilingual tokenizer used for scoring.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

# --- scoring weights -------------------------------------------------------
# Every weight is a plain additive constant so an explanation can be audited by
# summing the reported per-signal scores.
NAME_MATCH_WEIGHT = 3.0  # a message term appears in the tool name
DESC_MATCH_WEIGHT = 1.0  # a message term appears in the description
NAME_EXACT_WEIGHT = 4.0  # the tool is named verbatim in the message
RECENT_TOOL_WEIGHT = 6.0  # used in the last few turns of this run
RECENT_FAMILY_WEIGHT = 2.0  # same family as a recently used tool
CORE_PRIOR_WEIGHT = 1.0  # baseline priors for the tools every turn needs
WORKSPACE_FAMILY_WEIGHT = 1.0  # multiplier for the workspace extension profile
ROLE_FAMILY_WEIGHT = 1.0  # multiplier for the agent-role profile
MAX_NAME_HITS = 4
MAX_DESC_HITS = 6
MIN_OFFERED = 15  # floor: a turn never sees an under-provisioned pool
DEFAULT_BUDGET = 24
DEFAULT_MAX_PER_FAMILY = 4  # one family may not monopolise the budget

_STOPWORDS = frozenset({
    "a", "about", "after", "all", "also", "an", "and", "any", "are", "as", "at",
    "be", "been", "before", "but", "by", "can", "do", "does", "for", "from",
    "get", "had", "has", "have", "if", "in", "into", "is", "it", "its", "just",
    "like", "may", "me", "my", "not", "of", "on", "only", "or", "other", "our",
    "so", "some", "such", "than", "that", "the", "their", "them", "then",
    "there", "these", "they", "this", "to", "up", "use", "used", "useful",
    "using", "was", "we", "were", "what", "when", "which", "who", "will",
    "with", "you", "your", "returns", "return", "call", "called", "tool",
    "optional", "active", "current", "workspace",
})

_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")
_EXT_RE = re.compile(r"\.([A-Za-z0-9]{1,8})(?![A-Za-z0-9])")

# --- family assignment -----------------------------------------------------
# A family is the unit used for recency/workspace/role boosts and for the
# consolidation plan in the report. Explicit names beat prefix rules.
_FAMILY_BY_NAME = {
    "local_shell": "shell", "local_exec": "shell", "local_process": "shell",
    "exec_command": "shell", "powershell": "shell", "write_stdin": "shell",
    "terminal": "shell", "read_terminal": "shell",
    "TaskOutput": "shell", "TaskStop": "shell",
    "TaskCreate": "planning", "TaskGet": "planning", "TaskList": "planning",
    "TaskUpdate": "planning", "TodoWrite": "planning", "todo_list": "planning",
    "update_plan": "planning", "goal_subgoal": "planning",
    "EnterPlanMode": "planning", "ExitPlanMode": "planning",
    "browser_use": "browser",
    "notebook_edit": "notebook",
    "image_generate": "media", "image_edit": "media",
    "text_to_speech": "media", "music_generate": "media",
    "video_generate": "media", "video_edit": "media", "video_extend": "media",
    "video_analyze": "media", "video_job_status": "media",
    "visualization_artifact": "visual",
    "canvas_update": "visual",
    "push_component": "visual",
    "memory_search": "memory", "memory_supersede": "memory",
    "agent_memory_read": "memory",
    "agent_memory_write": "memory", "session_search": "memory",
    "project_note": "memory",
    "workflow": "workflow", "workflow_run_manage": "workflow",
    "web_fetch": "web", "web_search": "web", "web_extract": "web",
    "x_search": "web", "deep_research": "web",
    "build_repo_map": "code_intel", "focused_call_graph": "code_intel",
    "glob": "files", "grep": "files", "read_file": "files", "read": "files",
    "local_file": "files", "search_files": "files", "list_directory": "files",
    "write": "files", "edit": "files", "apply_patch": "files",
    "local_edit": "files", "local_edit_batch": "files",
    "read_office": "office", "create_document": "office",
    "create_spreadsheet": "office", "create_presentation": "office",
    "export_pdf": "office", "office_recalculate": "office", "office_render": "office",
    "run_checks": "checks",
    "security_scan": "checks",
    "lsp_diagnostics": "code_intel", "lsp_hover": "code_intel",
    "lsp_definition": "code_intel", "lsp_references": "code_intel",
    "lsp_document_symbols": "code_intel",
    "git_pr_create": "git", "git_pr_comment": "git",
    "create_checkpoint": "git", "list_checkpoints": "git",
    "restore_checkpoint": "git",
    "list_mcp_resources": "mcp", "list_mcp_resource_templates": "mcp",
    "read_mcp_resource": "mcp",
}

_FAMILY_BY_PREFIX = (
    ("android_", "android"),
    ("browser_", "browser"),
    ("lsp_", "code_intel"),
    ("video_", "media"),
    ("image_", "media"),
    ("subtask_", "delegation"),
    ("kanban_", "kanban"),
    ("Cron", "schedule"),
    ("clock.", "utility"),
    ("list_available_plugins", "plugins"),
    ("request_plugin", "plugins"),
)

# Tools needed on essentially every turn, with a tiered prior so the floor
# fills with defensible choices instead of whatever sorts first alphabetically.
# Tier 3 = the model cannot do anything useful without it; 2 = commonly needed;
# 1 = occasionally needed. A tool absent here starts at 0.0 and needs a real
# message/context signal to be offered at all.
_PRIORS: dict[str, float] = {
    # files + shell: the irreducible core of any coding turn
    "read_file": 3.0, "read": 3.0, "local_file": 3.0,
    "edit": 3.0, "write": 3.0, "local_edit": 3.0, "apply_patch": 3.0,
    "exec_command": 3.0, "local_shell": 3.0, "local_exec": 3.0,
    "powershell": 3.0, "local_process": 3.0,
    "glob": 3.0, "grep": 3.0,
    # turn plumbing
    "ask_user": 2.0, "request_user_input": 2.0, "AskUserQuestion": 2.0,
    "update_plan": 2.0, "todo_list": 2.0, "tool_search": 2.0,
    "memory_search": 2.0, "memory_supersede": 1.5,
    # everyday lookups
    "web_search": 2.0, "web_fetch": 2.0, "view_image": 2.0,
    "read_terminal": 2.0, "write_stdin": 2.0,
    "run_checks": 2.0, "local_edit_batch": 2.0,
    # occasionally useful, never to be guessed at
    "workflow": 1.0, "build_repo_map": 1.0, "lsp_diagnostics": 1.0,
    "notebook_edit": 1.0, "read_office": 1.0,
}
_CORE_TOOLS = frozenset(_PRIORS)

# Bilingual bridge: the schemas are English while users often write Chinese.
# Each Chinese surface form maps to canonical English terms that appear in the
# tool names/descriptions, so 2-grams from the message can hit them.
_CONCEPTS = {
    "测试": ("test", "tests", "pytest", "checks"),
    "跑": ("run", "exec", "command"),
    "运行": ("run", "exec", "command"),
    "执行": ("run", "exec", "command"),
    "命令": ("command", "shell", "terminal"),
    "终端": ("terminal", "shell", "command"),
    "构建": ("build", "compile"),
    "编译": ("build", "compile"),
    "报错": ("error", "diagnostics", "diagnostic"),
    "错误": ("error", "diagnostics"),
    "诊断": ("diagnostics", "lsp"),
    "检查": ("check", "checks", "lint"),
    "类型": ("type", "typecheck", "lsp"),
    "样式": ("style", "css", "component", "react"),
    "组件": ("component", "react", "jsx", "tsx"),
    "前端": ("frontend", "react", "css", "browser"),
    "页面": ("page", "browser", "html"),
    "网页": ("web", "page", "browser", "fetch"),
    "浏览器": ("browser", "navigate", "click"),
    "截图": ("screenshot", "image", "vision"),
    "图片": ("image", "vision", "generate"),
    "视频": ("video", "analyze"),
    "语音": ("speech", "voice", "audio"),
    "音乐": ("music", "audio"),
    "搜索": ("search", "grep", "glob"),
    "查找": ("search", "grep", "glob"),
    "文件": ("file", "read", "write"),
    "目录": ("directory", "list", "glob"),
    "读取": ("read", "file"),
    "读": ("read", "file"),
    "修改": ("edit", "modify", "write"),
    "改": ("edit", "modify", "fix"),
    "重构": ("refactor", "edit"),
    "修复": ("fix", "edit", "error"),
    "记忆": ("memory", "remember"),
    "记住": ("memory", "remember", "write"),
    "记一下": ("memory", "remember"),
    "喜欢": ("preference", "memory"),
    "偏好": ("preference", "memory"),
    "历史": ("history", "session", "memory"),
    "会话": ("session", "conversation"),
    "对话": ("conversation", "session"),
    "计划": ("plan", "planning", "todo"),
    "规划": ("plan", "planning", "todo"),
    "任务": ("task", "todo"),
    "待办": ("todo", "task"),
    "提醒": ("reminder", "automation", "schedule"),
    "定时": ("cron", "schedule"),
    "每天": ("cron", "schedule", "daily"),
    "工作流": ("workflow", "graph"),
    "子任务": ("subtask", "delegate"),
    "委派": ("delegate", "subtask"),
    "安卓": ("android", "gradle", "emulator"),
    "手机": ("android", "device", "emulator"),
    "模拟器": ("emulator", "simulator", "android"),
    "文档": ("document", "docx", "office"),
    "表格": ("spreadsheet", "xlsx", "table"),
    "幻灯片": ("presentation", "pptx", "slides"),
    "笔记": ("notebook", "note"),
    "笔记本": ("notebook", "jupyter", "cells"),
    "图表": ("chart", "visualization", "plot"),
    "画": ("draw", "chart", "visualization"),
    "总结": ("summarize", "summary"),
    "摘要": ("summarize", "summary"),
    "提交": ("commit", "git"),
    "分支": ("branch", "git"),
    "推送": ("push", "git"),
    "拉取": ("pull", "fetch", "git"),
    "安装": ("install", "setup"),
    "依赖": ("dependency", "install"),
    "插件": ("plugin", "marketplace"),
    "安全": ("security", "scan"),
    "扫描": ("scan", "security"),
    "令牌": ("token", "context"),
    "上下文": ("context", "compact"),
    "压缩": ("compact", "context"),
    "权限": ("permission", "approve"),
    "许可": ("permission", "approve"),
    "预览": ("preview", "view"),
    "看": ("view", "read", "snapshot"),
    "问题": ("question", "ask"),
    "问": ("ask", "question"),
    "确认": ("confirm", "ask"),
}

# Workspace/message extension profiles: (extra query terms, family weights).
_EXT_PROFILES: dict[str, tuple[tuple[str, ...], dict[str, float]]] = {
    ".py": (("python", "script", "pytest"), {"code_intel": 2.0, "shell": 1.5, "checks": 1.5}),
    ".pyi": (("python", "stub"), {"code_intel": 2.0}),
    ".ipynb": (("notebook", "jupyter", "cells"), {"notebook": 4.0}),
    ".tsx": (("react", "typescript", "component", "frontend", "css"),
             {"browser": 1.5, "checks": 1.0}),
    ".ts": (("typescript", "frontend"), {"browser": 1.0, "checks": 1.0}),
    ".jsx": (("react", "javascript", "component", "frontend", "css"),
             {"browser": 1.5, "checks": 1.0}),
    ".js": (("javascript", "frontend"), {"browser": 1.0, "checks": 1.0}),
    ".css": (("css", "style", "component"), {"browser": 1.5}),
    ".html": (("html", "page", "browser"), {"browser": 1.5, "visual": 1.0}),
    ".vue": (("vue", "component", "frontend"), {"browser": 1.0}),
    ".java": (("java", "gradle", "android"), {"android": 3.0}),
    ".kt": (("kotlin", "gradle", "android"), {"android": 3.0}),
    ".gradle": (("gradle", "android", "build"), {"android": 3.0}),
    ".rs": (("rust", "cargo"), {"code_intel": 2.0, "shell": 1.0}),
    ".go": (("golang", "go"), {"code_intel": 2.0, "shell": 1.0}),
    ".md": (("markdown", "docs", "notes"), {"memory": 1.0}),
    ".docx": (("docx", "document"), {"office": 4.0}),
    ".xlsx": (("xlsx", "spreadsheet", "table"), {"office": 4.0}),
    ".pptx": (("pptx", "presentation", "slides"), {"office": 4.0}),
    ".png": (("image", "screenshot", "vision"), {"media": 2.0}),
    ".jpg": (("image", "screenshot", "vision"), {"media": 2.0}),
    ".svg": (("svg", "chart", "visualization"), {"visual": 2.0}),
    ".mp4": (("video", "analyze"), {"media": 2.0}),
    ".sql": (("sql", "database", "query"), {"shell": 1.0, "code_intel": 1.0}),
}

# Agent-role profiles: (extra query terms, family weights).
_ROLE_PROFILES: dict[str, tuple[tuple[str, ...], dict[str, float]]] = {
    "reviewer": (("review", "findings", "diagnostics"), {"checks": 3.0, "code_intel": 1.5}),
    "review": (("review", "findings", "diagnostics"), {"checks": 3.0, "code_intel": 1.5}),
    "explore": (("search", "grep", "glob", "read"), {"files": 2.0, "code_intel": 1.5}),
    "researcher": (("search", "fetch", "research"), {"web": 3.0}),
    "plan": (("plan", "todo", "architecture"), {"planning": 2.5, "files": 1.0}),
    "leaf": ((), {"delegation": -3.0, "workflow": -1.5}),
    "verifier": (("test", "check", "diagnostics"), {"checks": 3.0}),
    "android": (("android", "gradle", "emulator"), {"android": 4.0}),
}

# --- stable tiers ----------------------------------------------------------
# Per-message re-ranking gives the smallest pool but a different prompt prefix
# on every turn, so the provider re-charges the whole tool block instead of
# serving it from cache. Caching wins by a wide margin: a 6.2x hit is worth
# more than the 1.08x saved by trimming. So the pool is keyed by a *coarse*
# tier instead of by the exact message.
#
# Only three tiers carry a real profile; "chat" and "default" deliberately
# share one (empty) profile so a short acknowledgement and an unfocused request
# resolve to the same bytes rather than adding a fourth cached prefix.
TIER_CODE = "code"
TIER_MEMORY = "memory"
TIER_DISCUSS = "discuss"
TIER_CHAT = "chat"
TIER_DEFAULT = "default"

# Fixed order. Also the tie-break order for ``tier_key``: the earlier tier wins
# a tie, so equal evidence can never flip the bucket between two turns.
TIER_ORDER = (TIER_CODE, TIER_MEMORY, TIER_DISCUSS, TIER_CHAT, TIER_DEFAULT)
TIER_KEYS = frozenset(TIER_ORDER)

# Vocabulary that pulls a message toward a tier. Chinese surface forms are
# listed alongside English because ``tokenize`` emits CJK bigrams as-is.
_TIER_SIGNALS: dict[str, frozenset[str]] = {
    TIER_CODE: frozenset({
        "test", "tests", "pytest", "checks", "check", "lint", "type", "typescript",
        "javascript", "python", "rust", "golang", "react", "component", "style",
        "css", "html", "sql", "build", "compile", "refactor", "fix", "edit",
        "modify", "write", "read", "run", "exec", "command", "shell", "terminal",
        "file", "files", "directory", "grep", "glob", "diagnostics", "error",
        "测试", "跑", "运行", "执行", "命令", "终端", "构建", "编译", "报错",
        "错误", "诊断", "检查", "类型", "样式", "组件", "前端", "页面", "文件",
        "目录", "读取", "修改", "重构", "修复", "代码",
    }),
    TIER_MEMORY: frozenset({
        "memory", "remember", "recall", "preference", "prefer", "note", "notes",
        "history", "session", "conversation", "记忆", "记住", "记", "喜欢",
        "偏好", "历史", "会话", "对话", "笔记",
    }),
    TIER_DISCUSS: frozenset({
        "plan", "planning", "todo", "task", "design", "explain", "why", "how",
        "compare", "review", "architecture", "decide", "approach", "question",
        "计划", "规划", "方案", "设计", "解释", "为什么", "怎么", "对比",
        "评审", "讨论", "任务", "待办", "架构", "选择",
    }),
    TIER_CHAT: frozenset(),
    TIER_DEFAULT: frozenset(),
}

# Evidence that the workspace is source code, used as a single extra vote.
_CODE_EXTS = frozenset({
    ".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".vue", ".svelte", ".rs",
    ".go", ".java", ".kt", ".gradle", ".c", ".h", ".cc", ".cpp", ".hpp",
    ".cs", ".rb", ".php", ".swift", ".scala", ".css", ".scss", ".html", ".sql",
    ".sh", ".ps1",
})

# Fixed query/family profile per *bucket*. There are five tier keys but only
# three buckets, because the number of distinct pools is what costs cache:
# ``memory`` and ``discuss`` are both non-code conversational turns, so they
# share one profile, and ``chat`` shares ``default``'s empty profile. Three
# distinct byte-images, not five.
BUCKET_CODE = "code"
BUCKET_TALK = "talk"
BUCKET_DEFAULT = "default"

_TIER_BUCKET: dict[str, str] = {
    TIER_CODE: BUCKET_CODE,
    TIER_MEMORY: BUCKET_TALK,
    TIER_DISCUSS: BUCKET_TALK,
    TIER_CHAT: BUCKET_DEFAULT,
    TIER_DEFAULT: BUCKET_DEFAULT,
}

# Bucket profile = family weights only, NEVER query terms. A bucket is a prior,
# not a query: generic terms like "build"/"run"/"edit" would name-match
# android_build_app, image_edit and video_edit and drag them into every code
# turn. With weights alone a family only scores if it is genuinely part of the
# job, and unrelated families stay at zero and get cut in pass 2.
_BUCKET_PROFILES: dict[str, dict[str, float]] = {
    BUCKET_CODE: {
        "files": 1.5, "shell": 1.5, "code_intel": 2.0, "checks": 1.5, "git": 1.0,
    },
    BUCKET_TALK: {
        "memory": 3.0, "planning": 3.0, "web": 1.0,
        # A conversational turn is where code tooling is *least* likely to be
        # the job. Negative weights here are what keep talk from collapsing
        # onto the default pool, so the bucket earns its separate prefix.
        "files": -1.0, "shell": -1.5, "code_intel": -1.5, "checks": -1.5,
    },
    BUCKET_DEFAULT: {},
}


def bucket_of(tier: str) -> str:
    """Return the pool bucket a tier resolves to (``code``/``talk``/``default``)."""
    return _TIER_BUCKET[normalize_tier(tier)]


def normalize_tier(tier: str) -> str:
    """Map an unknown or empty tier onto a known one (``default``)."""
    value = str(tier or "").strip().lower()
    return value if value in TIER_KEYS else TIER_DEFAULT


# --- tokenization ----------------------------------------------------------

def tokenize(text: str) -> list[str]:
    """Split text into lowercase search terms (ASCII words + CJK bigrams).

    The result is order-preserving and de-duplicated, so callers can compare
    token lists for equality instead of relying on sets.
    """
    value = str(text or "").lower()
    out: list[str] = []
    seen: set[str] = set()

    def add(token: str) -> None:
        if token and token not in seen:
            seen.add(token)
            out.append(token)

    for word in _WORD_RE.findall(value):
        add(word)
        for part in re.split(r"[._/-]+", word):
            if len(part) >= 2 and part not in _STOPWORDS:
                add(part)
    for run in _CJK_RE.findall(value):
        if len(run) == 1:
            add(run)
            continue
        for index in range(len(run) - 1):
            add(run[index:index + 2])
    return out


def _expand_concepts(tokens: Sequence[str]) -> list[str]:
    """Append the English terms a Chinese 2-gram stands for."""
    out: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if token not in seen:
            seen.add(token)
            out.append(token)
        for term in _CONCEPTS.get(token, ()):
            if term not in seen:
                seen.add(term)
                out.append(term)
    return out


def _extensions(text: str) -> list[str]:
    """Return the file extensions mentioned in a path or message, in order."""
    out: list[str] = []
    for match in _EXT_RE.finditer(str(text or "").lower()):
        ext = "." + match.group(1)
        if ext in _EXT_PROFILES and ext not in out:
            out.append(ext)
    return out


def _context_profile(
    message: str, workspace: str, role: str,
) -> tuple[list[str], dict[str, float]]:
    """Derive extra query terms and family weights from context."""
    terms: list[str] = []
    families: dict[str, float] = {}
    seen: set[str] = set()

    def add_term(term: str) -> None:
        if term and term not in seen:
            seen.add(term)
            terms.append(term)

    def add_family(family: str, weight: float) -> None:
        families[family] = families.get(family, 0.0) + weight

    for ext in [*_extensions(workspace), *_extensions(message)]:
        ext_terms, ext_families = _EXT_PROFILES[ext]
        for term in ext_terms:
            add_term(term)
        for family, weight in ext_families.items():
            add_family(family, weight * WORKSPACE_FAMILY_WEIGHT)

    profile = _ROLE_PROFILES.get(str(role or "").strip().lower())
    if profile is not None:
        role_terms, role_families = profile
        for term in role_terms:
            add_term(term)
        for family, weight in role_families.items():
            add_family(family, weight * ROLE_FAMILY_WEIGHT)
    return terms, families


def family_of(name: str) -> str:
    """Return the consolidation family for a tool name (``""`` when unknown)."""
    key = str(name or "")
    explicit = _FAMILY_BY_NAME.get(key)
    if explicit:
        return explicit
    for prefix, family in _FAMILY_BY_PREFIX:
        if key.startswith(prefix):
            return family
    return ""


# --- tier selection --------------------------------------------------------

# A role is a weak tier vote: it describes the kind of turn, not the topic.
_TIER_BY_ROLE = {
    "reviewer": TIER_CODE, "review": TIER_CODE, "verifier": TIER_CODE,
    "explore": TIER_CODE, "plan": TIER_DISCUSS, "researcher": TIER_DISCUSS,
    "android": TIER_CODE, "leaf": TIER_CODE,
}


def _tier_hits(tier: str, tokens: set[str], text: str) -> set[str]:
    """Return the tier's signals present in a message.

    ASCII signals match token-wise. CJK signals must match as substrings,
    because :func:`tokenize` emits 2-grams and most Chinese keywords here are
    three characters (``为什么``), which no single bigram can ever equal.
    """
    hits: set[str] = set()
    for signal in _TIER_SIGNALS[tier]:
        if signal.isascii():
            if signal in tokens:
                hits.add(signal)
        elif signal in text:
            hits.add(signal)
    return hits


def tier_key(message: str, workspace: str = "", role: str = "") -> str:
    """Return the coarse, STABLE tier a message belongs to.

    The point of this function is that it changes *rarely*. Two different
    messages about the same kind of work must land on the same tier, because
    the tier decides the tool block and therefore the cached prompt prefix.
    Only the dominant vocabulary decides; nothing here depends on turn history,
    ``recent_tools``, or the size of the pool.

    Tiers, in tie-break order:

    ``code``     editing, running, testing, searching a codebase.
    ``memory``   remembering / recalling preferences and notes.
    ``discuss``  planning, design, review, questions about approach.
    ``default``  no evidence either way. ``chat`` is an accepted alias and
                 shares the ``default`` bucket, so both give identical bytes.
    """
    # Only the message votes on vocabulary; the workspace contributes a single
    # extension vote below. ``_extensions`` yields extensions, not terms, so it
    # must not be mixed into the term list.
    tokens = set(_expand_concepts(tokenize(message)))
    text = str(message or "").lower()
    votes: dict[str, int] = {}
    for tier in (TIER_CODE, TIER_MEMORY, TIER_DISCUSS):
        hits = _tier_hits(tier, tokens, text)
        if hits:
            votes[tier] = len(hits)

    if any(ext in _CODE_EXTS for ext in _extensions(workspace)):
        votes[TIER_CODE] = votes.get(TIER_CODE, 0) + 1

    role_tier = _TIER_BY_ROLE.get(str(role or "").strip().lower())
    if role_tier is not None:
        votes[role_tier] = votes.get(role_tier, 0) + 1

    best = TIER_DEFAULT
    best_votes = 0
    for tier in TIER_ORDER:  # fixed order breaks ties deterministically
        count = votes.get(tier, 0)
        if count > best_votes:
            best, best_votes = tier, count
    return best


# --- schema helpers --------------------------------------------------------

def _function_of(schema: Any) -> dict[str, Any]:
    if not isinstance(schema, dict):
        return {}
    function = schema.get("function")
    if isinstance(function, dict):
        return function
    return schema


def schema_name(schema: Any) -> str:
    """Return a schema's function name, tolerating flat legacy entries."""
    return str(_function_of(schema).get("name") or "")


def merge_schemas(*lists: Sequence[dict], sort: bool = True) -> list[dict]:
    """De-duplicate schemas by function name, keeping the first occurrence.

    This matches the first-wins rule the kernel already applies when it layers
    :func:`atlas.engine.kernel.tools.kernel_tool_schemas` on top of the agent catalog.
    Pair order is the precedence order: the left-most list wins.

    ``sort=True`` (the default) returns names in sorted order, which keeps the
    prompt prefix byte-stable across turns. ``sort=False`` preserves first-seen
    order for callers that must reproduce a legacy ordering exactly.
    """
    merged: dict[str, dict] = {}
    for schemas in lists:
        if not schemas:
            continue
        for schema in schemas:
            name = schema_name(schema)
            if name and name not in merged:
                merged[name] = schema
    names = sorted(merged) if sort else list(merged)
    return [merged[name] for name in names]


def _describe(name: str, function: dict[str, Any]) -> str:
    parts = [str(function.get("description") or "")]
    parameters = function.get("parameters")
    if isinstance(parameters, dict):
        properties = parameters.get("properties")
        if isinstance(properties, dict):
            parts.extend(str(key).replace("_", " ") for key in properties)
    return " ".join(parts)


def _rollup(schemas: Sequence[dict]) -> int:
    return len(json.dumps(list(schemas), ensure_ascii=False, default=str))


# --- scoring ---------------------------------------------------------------

def _score_all(
    schemas: Sequence[dict],
    *,
    message: str,
    workspace: str,
    recent_tools: Sequence[str],
    role: str,
    always_keep: Sequence[str],
    family_weights_override: dict[str, float] | None = None,
) -> tuple[list[dict[str, Any]], list[str], dict[str, float], dict[str, float]]:
    """Score every schema. Returns (entries, query_tokens, family_weights, meta)."""
    if family_weights_override is None:
        context_terms, family_weights = _context_profile(message, workspace, role)
    else:
        # Tier mode: family weights are fixed constants and there are no extra
        # query terms, so the result cannot vary with the live message.
        context_terms, family_weights = (), family_weights_override
    query_tokens = _expand_concepts([*tokenize(message), *context_terms])

    recent_names = [str(name) for name in recent_tools if str(name)]
    recent_set = set(recent_names)
    recent_families = {family_of(name) for name in recent_names} - {""}
    keep_set = {str(name) for name in always_keep if str(name)}

    def _kept(name: str) -> bool:
        """Match a protected primitive literally or past an ``mcp__tool`` prefix.

        The live pool interleaves the kernel's own schemas with MCP tools named
        ``<server>__<tool>``, so a bare ``read_file`` in ``always_keep`` would
        never match ``filesystem__read_file`` — and the kernel ships no
        ``read_file`` of its own, so the primitive would be dropped from every
        tier while the list above looked like it protected it.
        """
        if name in keep_set:
            return True
        return name.rsplit("__", 1)[-1] in keep_set

    entries: list[dict[str, Any]] = []
    for index, schema in enumerate(schemas):
        name = schema_name(schema)
        if not name:
            continue
        function = _function_of(schema)
        name_tokens = set(tokenize(name))
        name_tokens.update(family_of(name).split("_"))
        desc_tokens = set(tokenize(_describe(name, function)))
        family = family_of(name)

        score = 0.0
        reasons: list[str] = []
        signals: dict[str, float] = {}

        if _kept(name):
            signals["always_keep"] = 0.0
            reasons.append("always_keep")

        if name.lower() in {token for token in query_tokens}:
            score += NAME_EXACT_WEIGHT
            signals["name_exact"] = NAME_EXACT_WEIGHT
            reasons.append("named_in_message")

        name_hits = [token for token in query_tokens if token in name_tokens]
        if name_hits:
            weight = NAME_MATCH_WEIGHT * min(len(name_hits), MAX_NAME_HITS)
            score += weight
            signals["name_match"] = weight
            reasons.append("name:" + ",".join(name_hits[:MAX_NAME_HITS]))

        desc_hits = [token for token in query_tokens if token in desc_tokens]
        if desc_hits:
            weight = DESC_MATCH_WEIGHT * min(len(desc_hits), MAX_DESC_HITS)
            score += weight
            signals["desc_match"] = weight
            reasons.append("desc:" + ",".join(desc_hits[:MAX_DESC_HITS]))

        if name in recent_set:
            score += RECENT_TOOL_WEIGHT
            signals["recent_tool"] = RECENT_TOOL_WEIGHT
            reasons.append("recent")
        elif family and family in recent_families:
            score += RECENT_FAMILY_WEIGHT
            signals["recent_family"] = RECENT_FAMILY_WEIGHT
            reasons.append("recent_family:" + family)

        prior = _PRIORS.get(name, 0.0)
        if prior:
            score += prior
            signals["prior"] = prior
            reasons.append(f"prior:{prior:g}")

        family_weight = family_weights.get(family, 0.0) if family else 0.0
        if family_weight:
            score += family_weight
            signals["context_family"] = family_weight
            reasons.append(("context:" if family_weight > 0 else "context_penalty:") + family)

        entries.append({
            "name": name,
            "schema": schema,
            "score": round(score, 6),
            "signals": signals,
            "reasons": reasons,
            "family": family,
            "always_keep": _kept(name),
            "kept": False,
            "reason": "",
            "index": index,
        })

    # Deterministic order: score, then name. Never set iteration.
    entries.sort(key=lambda entry: (-entry["score"], entry["name"]))
    meta = {"query_tokens": query_tokens, "recent_families": sorted(recent_families)}
    return entries, query_tokens, family_weights, meta


def _plan(
    schemas: Sequence[dict],
    *,
    message: str,
    workspace: str,
    recent_tools: Sequence[str],
    role: str,
    budget: int,
    always_keep: Sequence[str],
    max_per_family: int,
    family_weights_override: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Compute the kept/dropped split once; shared by both public entry points."""
    deduped = merge_schemas(schemas, sort=False)
    entries, query_tokens, family_weights, meta = _score_all(
        deduped,
        message=message,
        workspace=workspace,
        recent_tools=recent_tools,
        role=role,
        always_keep=always_keep,
        family_weights_override=family_weights_override,
    )
    limit = max(0, int(budget))
    floor = min(MIN_OFFERED, len(entries), limit)
    cap = max(1, int(max_per_family))

    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    used: dict[str, int] = {}

    def take(entry: dict[str, Any], reason: str) -> None:
        entry["kept"] = True
        entry["reason"] = reason
        kept.append(entry)
        family = entry["family"]
        if family:
            used[family] = used.get(family, 0) + 1

    def reject(entry: dict[str, Any], reason: str) -> None:
        entry["kept"] = False
        entry["reason"] = reason
        dropped.append(entry)

    # Pass 1: explicit passthrough. Never displaced by a scoring favourite, but
    # still bounded by the hard budget so ``budget`` remains a true ceiling.
    for entry in entries:
        if len(kept) >= limit:
            reject(entry, "over_budget")
        elif entry["always_keep"]:
            take(entry, "always_keep")
        else:
            continue
    # Keep `kept` in score order even after the passthrough pass.
    kept.sort(key=lambda entry: (-entry["score"], entry["name"]))

    # Pass 2: positive scores, at most `cap` tools per family so one large
    # family (android_*, browser_*) cannot swallow the whole budget.
    for entry in entries:
        if entry["kept"]:
            continue
        if entry["score"] <= 0:
            reject(entry, "no_signal")
            continue
        family = entry["family"]
        if family and used.get(family, 0) >= cap:
            reject(entry, "over_family_cap")
            continue
        if len(kept) >= limit:
            reject(entry, "over_budget")
            continue
        take(entry, "matched")

    # Pass 3: floor. A short message must not yield an under-provisioned pool,
    # so lift the family cap for the best remaining entries until MIN_OFFERED.
    if len(kept) < floor:
        for entry in entries:
            if len(kept) >= floor:
                break
            if entry["kept"]:
                continue
            take(entry, entry["reason"] + "+floor")
        dropped = [entry for entry in dropped if not entry["kept"]]
        kept.sort(key=lambda entry: (-entry["score"], entry["name"]))

    # Recompute reasons for anything still marked kept but rejected later.
    selected = [entry["schema"] for entry in kept]
    return {
        "entries": entries,
        "kept": kept,
        "dropped": dropped,
        "selected": selected,
        "limit": limit,
        "floor": floor,
        "cap": cap,
        "query_tokens": query_tokens,
        "family_weights": family_weights,
        "meta": meta,
    }


# --- public API ------------------------------------------------------------

def select_tools(
    schemas: list[dict],
    *,
    message: str,
    workspace: str = "",
    recent_tools: Sequence[str] = (),
    role: str = "",
    budget: int = DEFAULT_BUDGET,
    always_keep: Sequence[str] = (),
    max_per_family: int = DEFAULT_MAX_PER_FAMILY,
) -> list[dict]:
    """Return the subset of ``schemas`` worth sending for ``message``.

    Ranking is additive and deterministic:

    * name/description overlap with the message (Chinese is bridged through a
      small concept lexicon because the schemas themselves are English),
    * ``recent_tools`` (exact name, then same family),
    * ``always_keep`` (kept regardless of score, but still budget-visible),
    * workspace extension profile (``.py`` -> coding/LSP/terminal, ``.tsx`` ->
      frontend/browser, ``.kt``/``.java`` -> android, ...),
    * agent ``role`` profile (reviewer, explore, leaf, ...),
    * a core prior for the tools every turn needs.

    ``budget`` is the ceiling and ``MIN_OFFERED`` the floor, so a healthy pool
    yields 15-24 schemas per turn. Output order is score-descending, then name.
    """
    plan = _plan(
        schemas,
        message=message,
        workspace=workspace,
        recent_tools=recent_tools,
        role=role,
        budget=budget,
        always_keep=always_keep,
        max_per_family=max_per_family,
    )
    return plan["selected"]


def select_tools_for_tier(
    schemas: list[dict],
    tier: str,
    budget: int = DEFAULT_BUDGET,
    always_keep: Sequence[str] = (),
    max_per_family: int = DEFAULT_MAX_PER_FAMILY,
) -> list[dict]:
    """Return the deterministic tool pool for ``tier``.

    Unlike :func:`select_tools`, this takes no message and no per-turn context:
    the pool is a pure function of ``(schemas, tier, budget, always_keep)``. That
    is what makes it cacheable — the caller computes :func:`tier_key` once per
    conversation (or once per topic change) and reuses the result, so the tool
    block stays byte-identical across turns and the provider can serve it from
    the prefix cache.

    Two tiers that share a bucket produce byte identical pools by construction:
    ``memory`` and ``discuss`` both resolve to ``talk``, and ``chat`` shares
    ``default``. Unknown tiers normalize to ``default`` rather than raising, so
    a stale tier string can never drop the tool block.
    """
    profile = _BUCKET_PROFILES[bucket_of(tier)]
    plan = _plan(
        schemas,
        message="",
        workspace="",
        recent_tools=(),
        role="",
        budget=budget,
        always_keep=always_keep,
        max_per_family=max_per_family,
        family_weights_override=profile,
    )
    return plan["selected"]


def explain_selection(
    schemas: list[dict],
    *,
    message: str,
    workspace: str = "",
    recent_tools: Sequence[str] = (),
    role: str = "",
    budget: int = DEFAULT_BUDGET,
    always_keep: Sequence[str] = (),
    max_per_family: int = DEFAULT_MAX_PER_FAMILY,
) -> dict[str, Any]:
    """Return the selection plus every score and the reason it was kept.

    Answering "why can't the model see ``android_build_app``?" should need only
    this dict: ``tools[name]["reason"]`` is ``always_keep``, ``matched``,
    ``over_budget``, ``no_signal``, or one of those with ``+floor`` appended.
    """
    plan = _plan(
        schemas,
        message=message,
        workspace=workspace,
        recent_tools=recent_tools,
        role=role,
        budget=budget,
        always_keep=always_keep,
        max_per_family=max_per_family,
    )
    kept_names = [entry["name"] for entry in plan["kept"]]
    dropped_names = [entry["name"] for entry in plan["dropped"]]
    tools: dict[str, dict[str, Any]] = {}
    for rank, entry in enumerate(plan["entries"], start=1):
        tools[entry["name"]] = {
            "rank": rank,
            "score": entry["score"],
            "family": entry["family"],
            "kept": entry["kept"],
            "reason": entry["reason"],
            "signals": dict(entry["signals"]),
            "detail": list(entry["reasons"]),
            "bytes": len(json.dumps(entry["schema"], ensure_ascii=False, default=str)),
        }
    return {
        "budget": plan["limit"],
        "floor": plan["floor"],
        "total": len(plan["entries"]),
        "selected": kept_names,
        "dropped": dropped_names,
        "selected_count": len(kept_names),
        "selected_bytes": _rollup(plan["selected"]),
        "dropped_count": len(dropped_names),
        "query_tokens": list(plan["query_tokens"]),
        "family_weights": dict(plan["family_weights"]),
        "recent_families": list(plan["meta"]["recent_families"]),
        "schemas": plan["selected"],
        "tools": tools,
    }

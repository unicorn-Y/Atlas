"""Built-in categories shared by the skill library and the tool library.

The ids match the collection taskbook (tasks/taskbooks/LIBRARY-WEBGPT-COLLECT.md),
so imported entries land in the same buckets the collector used. Keywords drive
the free rule-based pass of "一键整理"; only items the rules cannot place go to
the model.
"""

from __future__ import annotations

from typing import Any

# (id, 中文名, 说明, 关键词)
_BUILTIN: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("coding", "编程开发", "写代码、语言/框架专长、重构、调试", (
        "code", "coding", "refactor", "debug", "python", "typescript", "javascript", "rust", "golang",
        "java", "kotlin", "swift", "react", "vue", "next.js", "django", "fastapi", "compiler", "lsp",
        "repo", "edit", "patch", "apply_patch", "write_file", "read_file", "grep", "glob", "repomap",
        "编程", "代码", "重构", "调试", "开发",
    )),
    ("testing-review", "测试与审查", "单测、E2E、代码审查、静态检查", (
        "test", "testing", "pytest", "jest", "vitest", "e2e", "review", "lint", "typecheck", "coverage",
        "qa", "findings", "测试", "审查", "评审", "单测",
    )),
    ("git-platform", "代码托管", "Git、GitHub、GitLab、PR、CI", (
        "git", "github", "gitlab", "bitbucket", "pull request", "pr", "commit", "branch", "ci",
        "actions", "gitea", "代码托管",
    )),
    ("devops-cloud", "运维与云", "部署、容器、K8s、各家云、监控告警", (
        "deploy", "docker", "kubernetes", "k8s", "terraform", "aws", "azure", "gcp", "cloudflare",
        "vercel", "netlify", "server", "monitor", "grafana", "prometheus", "sentry", "datadog",
        "devops", "ssh", "nginx", "部署", "运维", "容器", "监控", "云",
    )),
    ("database", "数据库", "SQL/NoSQL、向量库、数据仓库", (
        "database", "sql", "postgres", "postgresql", "mysql", "sqlite", "mongodb", "redis", "supabase",
        "bigquery", "snowflake", "clickhouse", "vector", "qdrant", "pinecone", "milvus", "数据库",
    )),
    ("data-analysis", "数据分析", "清洗、统计、可视化、Notebook", (
        "data", "analysis", "analytics", "pandas", "csv", "chart", "plot", "visualization", "notebook",
        "jupyter", "statistics", "dashboard", "数据分析", "可视化", "统计", "图表",
    )),
    ("ai-ml", "AI 与模型", "训练、推理、提示词、评测、模型平台", (
        "llm", "model", "prompt", "embedding", "fine-tune", "finetune", "training", "inference",
        "huggingface", "openai", "anthropic", "ollama", "eval", "rag", "machine learning", "模型", "提示词",
    )),
    ("research", "调研检索", "网页搜索、论文、学术、深度研究", (
        "search", "research", "arxiv", "paper", "papers", "scholar", "academic", "citation", "wikipedia",
        "news", "web_search", "exa", "tavily", "perplexity", "调研", "论文", "搜索", "检索", "学术",
    )),
    ("web-browser", "网页与浏览器", "浏览器自动化、抓取、网页阅读", (
        "browser", "playwright", "puppeteer", "selenium", "chrome", "devtools", "scrape", "crawl",
        "crawler", "web_fetch", "web_extract", "html", "url", "firecrawl", "网页", "浏览器", "爬虫", "抓取",
    )),
    ("office-docs", "办公文档", "Word/Excel/PPT/PDF、表格、文档转换", (
        "docx", "word", "xlsx", "excel", "spreadsheet", "pptx", "powerpoint", "presentation", "slides",
        "pdf", "office", "document", "markdown", "pandoc", "文档", "表格", "幻灯片", "办公",
    )),
    ("writing", "写作与内容", "文案、翻译、编辑、博客、营销内容", (
        "write", "writing", "copywriting", "blog", "article", "translate", "translation", "edit",
        "proofread", "seo", "marketing", "content", "写作", "文案", "翻译", "润色", "营销",
    )),
    ("design-frontend", "设计与前端", "UI 设计、Figma、前端组件、设计系统", (
        "design", "figma", "ui", "ux", "css", "tailwind", "frontend", "component", "canva", "theme",
        "icon", "design system", "设计", "前端", "界面",
    )),
    ("media", "图像音视频", "生图、修图、视频剪辑、语音、音乐", (
        "image", "photo", "video", "audio", "music", "speech", "tts", "asr", "voice", "ffmpeg",
        "comfyui", "stable diffusion", "midjourney", "youtube", "图片", "图像", "视频", "音频", "语音", "音乐",
    )),
    ("knowledge-notes", "知识与笔记", "Notion、Obsidian、知识库、记忆", (
        "notion", "obsidian", "note", "notes", "knowledge", "wiki", "memory", "remember", "zotero",
        "logseq", "confluence", "笔记", "知识库", "记忆",
    )),
    ("communication", "通讯协作", "邮件、Slack、飞书、钉钉、Telegram、日历", (
        "email", "mail", "gmail", "outlook", "slack", "discord", "telegram", "wechat", "feishu",
        "lark", "dingtalk", "teams", "calendar", "message", "sms", "邮件", "飞书", "钉钉", "微信", "日历", "消息",
    )),
    ("productivity", "效率与项目", "待办、项目管理、Linear/Jira、自动化流程", (
        "todo", "task", "project", "kanban", "linear", "jira", "asana", "trello", "automation",
        "workflow", "zapier", "n8n", "reminder", "schedule", "plan", "待办", "项目管理", "提醒", "效率", "自动化",
    )),
    ("system-desktop", "系统与电脑操作", "文件系统、终端、桌面/GUI 操控、Windows 工具", (
        "filesystem", "file", "terminal", "shell", "powershell", "bash", "command", "exec", "process",
        "desktop", "computer", "gui", "screenshot", "windows", "macos", "clipboard", "checkpoint",
        "文件", "终端", "命令", "桌面", "电脑", "系统",
    )),
    ("security", "安全", "安全审计、漏洞扫描、密钥管理（仅防御向）", (
        "security", "vulnerability", "audit", "cve", "secret", "pentest", "owasp", "semgrep",
        "安全", "漏洞",
    )),
    ("business-finance", "商业与金融数据", "支付、电商、CRM、行情数据（不含投资建议）", (
        "stripe", "payment", "invoice", "shopify", "ecommerce", "crm", "salesforce", "hubspot",
        "finance", "stock", "accounting", "支付", "电商", "财务", "金融",
    )),
    ("maps-life", "地图与生活", "地图、出行、天气、购物、健康生活", (
        "map", "maps", "amap", "location", "weather", "travel", "flight", "hotel", "recipe", "health",
        "fitness", "地图", "天气", "出行", "生活", "健康",
    )),
    ("mobile", "移动端", "iOS/Android 开发、模拟器、App 自动化", (
        "ios", "android", "mobile", "simulator", "emulator", "xcode", "flutter", "react native",
        "adb", "移动端", "手机",
    )),
    ("agent-meta", "Agent 自身能力", "写技能、写子代理、规划、记忆、多代理编排", (
        "skill", "skills", "agent", "subagent", "delegate", "mcp", "plugin", "hook", "context",
        "orchestrat", "multi-agent", "tool_search", "技能", "子代理", "编排",
    )),
    ("learning", "学习教育", "教学、刷题、语言学习、知识讲解", (
        "learn", "learning", "tutor", "teach", "education", "course", "quiz", "flashcard",
        "leetcode", "学习", "教学", "教育",
    )),
    ("games-fun", "游戏娱乐", "游戏开发、娱乐", (
        "game", "games", "unity", "godot", "unreal", "minecraft", "fun", "游戏", "娱乐",
    )),
)

OTHER_ID = "other"

# Declared categories seen in the wild (Atlas repo folders, Hermes, aggregators).
ALIASES: dict[str, str] = {
    "dev": "coding", "development": "coding", "software-development": "coding", "programming": "coding",
    "code": "coding", "github": "git-platform", "git": "git-platform", "web": "web-browser",
    "browser": "web-browser", "messaging": "communication", "creative": "media", "image": "media",
    "video": "media", "audio": "media", "productivity": "productivity", "research": "research",
    "data": "data-analysis", "data-science": "data-analysis", "devops": "devops-cloud", "cloud": "devops-cloud",
    "documents": "office-docs", "document": "office-docs", "office": "office-docs", "docs": "office-docs",
    "design": "design-frontend", "frontend": "design-frontend", "notes": "knowledge-notes",
    "knowledge": "knowledge-notes", "memory": "knowledge-notes", "email": "communication",
    "communication": "communication", "testing": "testing-review", "review": "testing-review",
    "security": "security", "finance": "business-finance", "business": "business-finance",
    "mobile": "mobile", "ai": "ai-ml", "ml": "ai-ml", "meta": "agent-meta", "agents": "agent-meta",
    "education": "learning", "games": "games-fun", "gaming": "games-fun", "system": "system-desktop",
    "filesystem": "system-desktop", "os": "system-desktop", "database": "database", "databases": "database",
    "writing": "writing", "marketing": "business-finance", "maps": "maps-life", "lifestyle": "maps-life",
    # Long-tail labels seen in the web GPT collection (2026-10-11, 3409 entries).
    "ai-research": "research", "web-development": "design-frontend", "workflow-automation": "productivity",
    "python-development": "coding", "creative-design": "design-frontend", "utilities": "system-desktop",
    "developer-essentials": "coding", "llm-finetuning": "ai-ml", "backend-development": "coding",
    "ui-design": "design-frontend", "cloud-infrastructure": "devops-cloud", "llm-application-dev": "ai-ml",
    "web-data": "web-browser", "agent-teams": "agent-meta", "security-scanning": "security",
    "document-processing": "office-docs", "pptx-deck-creation": "office-docs",
    "startup-business-analyst": "business-finance", "javascript-typescript": "coding",
    "framework-migration": "coding", "incident-response": "devops-cloud", "cicd-automation": "devops-cloud",
    "observability-monitoring": "devops-cloud", "kubernetes-operations": "devops-cloud",
    "reverse-engineering": "security", "data-engineering": "data-analysis", "payment-processing": "business-finance",
    "frontend-mobile-development": "mobile", "documentation-generation": "writing", "shell-scripting": "system-desktop",
    "systems-programming": "coding", "documentation-standards": "writing", "accessibility-compliance": "design-frontend",
    "machine-learning-ops": "ai-ml", "quantitative-trading": "business-finance", "business-analytics": "business-finance",
    "hr-legal-compliance": "business-finance", "game-development": "games-fun", "database-design": "database",
    "file-conversion": "office-docs", "social-publishing": "communication", "api-scaffolding": "coding",
    "dotnet-contribution": "coding", "agent-orchestration": "agent-meta", "llm": "ai-ml",
    "ai-maestro": "agent-meta", "conductor": "agent-meta", "skill-forge-essentials": "agent-meta",
    "dgx-spark-ops": "ai-ml", "blockchain-web3": "business-finance", "git": "git-platform",
}


def builtin_categories() -> list[dict[str, Any]]:
    """Fresh copies of the built-in categories (callers may mutate them)."""
    rows = [
        {"id": cid, "name": name, "description": desc, "keywords": list(words), "builtin": True}
        for cid, name, desc, words in _BUILTIN
    ]
    rows.append({"id": OTHER_ID, "name": "其他", "description": "暂时放不进任何分类的", "keywords": [],
                 "builtin": True})
    return rows

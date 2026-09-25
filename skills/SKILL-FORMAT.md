# Atlas 技能格式规范 (Skill Format Specification)

> **版本**: 1.0.0  
> **最后更新**: 2026-09-25

---

## 1. 概述

一个 Atlas 技能 (Skill) 是一个**独立目录**，包含：

```
skills/<category>/<skill-name>/
├── SKILL.md              # 必需 — 技能定义文件（frontmatter + 指令正文）
├── scripts/              # 可选 — 辅助脚本（Python/Bash/Node）
│   └── *.py / *.sh
└── references/           # 可选 — 参考文档（给 Agent 读的额外上下文）
    └── *.md
```

**SKILL.md** 是唯一的入口文件，Agent 通过读取它来理解和执行技能。

---

## 2. SKILL.md 格式

### 2.1 Frontmatter (YAML)

```yaml
---
name: skill-name                    # 必需 — kebab-case，全局唯一
description: "一句话描述技能做什么"     # 必需 — 用于列表展示和意图匹配
version: 1.0.0                      # 必需 — semver
category: productivity              # 必需 — 见 §3 分类表

# 触发条件（Agent 自动激活用）
triggers:                           # 可选 — 数组，任一匹配即激活
  - pattern: "搜索论文|arxiv|学术"     # 正则或关键词模式
  - pattern: "pdf.*合并|合并.*pdf"
  - command: "/arxiv"                # 斜杠命令触发

# MCP 工具依赖（声明需要哪些 MCP server 的工具）
dependencies:                       # 可选
  mcp_servers:                      # 需要的 MCP server 列表
    - filesystem                    # server name（对应 atlas.toml 中的 [tools.servers.*]）
  python_packages:                  # 需要的 Python 包
    - reportlab
    - pdfplumber
  commands:                         # 需要的系统命令
    - ffmpeg

# 元数据
author: Atlas                       # 可选
tags: [pdf, documents, merge]       # 可选 — 用于搜索和分类
related_skills: [docx, xlsx]        # 可选 — 推荐相关技能
---
```

### 2.2 Frontmatter 字段详解

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `name` | string | ✅ | 全局唯一标识符，kebab-case，如 `github-pr-workflow` |
| `description` | string | ✅ | 一行描述，50字以内，用于意图匹配和列表展示 |
| `version` | string | ✅ | 语义化版本号 `MAJOR.MINOR.PATCH` |
| `category` | string | ✅ | 见 §3 分类表 |
| `triggers` | array | — | 自动激活条件，每项含 `pattern`(正则) 或 `command`(斜杠命令) |
| `triggers[].pattern` | string | — | 匹配用户输入的正则表达式（大小写不敏感） |
| `triggers[].command` | string | — | 斜杠命令，如 `/arxiv`、`/pdf`，精确匹配 |
| `dependencies.mcp_servers` | array | — | 所需 MCP server 名称列表 |
| `dependencies.python_packages` | array | — | 所需 Python 包 |
| `dependencies.commands` | array | — | 所需系统命令 |
| `author` | string | — | 作者 |
| `tags` | array | — | 标签，用于搜索 |
| `related_skills` | array | — | 相关技能的 name 列表 |

### 2.3 校验规则

技能发现器按以下规则校验 frontmatter；无效技能会记录 `skills.invalid_metadata` 警告并跳过，扫描会继续处理其他技能：

1. YAML frontmatter 必须可解析为 mapping。
2. `name` 必须是非空的小写 kebab-case 字符串；同名按扫描优先级保留一个条目。
3. `description` 必须是非空字符串。
4. `version` 如提供，必须是 `MAJOR.MINOR.PATCH` 语义化版本字符串；旧技能缺省时使用 `0.0.0`。
5. `category` 如提供必须是字符串；缺省时从目录结构推断，也兼容 `metadata.hermes.category`。
6. `triggers` 如提供必须是列表，每项为非空字符串（兼容旧格式）或含非空 `pattern` / `command` 字符串的 mapping。
7. `dependencies` 必须是 mapping；`mcp_servers`、`python_packages` 和 `commands` 如提供必须是非空字符串列表。
8. `tags`、`related_skills` 如提供必须是非空字符串列表；Hermes 兼容字段从 `metadata.hermes` 读取。
9. `author` 如提供必须是字符串。

发现器只扫描规范目录 `skills/<category>/<skill-name>/SKILL.md`，忽略 Cowork 注入的其他目录布局。规范目录中的技能按相对路径忽略大小写排序；重复 name 保留路径排序最前的文件，并记录冲突路径。

### 2.4 正文结构 (Markdown)

Frontmatter 之后是 Markdown 正文，结构推荐但不强制：

```markdown
# 技能标题

简要说明这个技能做什么、什么场景使用。

## When to Use

- 场景1
- 场景2
- NOT for: 反面场景

## Prerequisites

前置条件、安装依赖。

## Instructions

具体操作指令，Agent 按此执行。
可以包含代码块、步骤列表、决策树。

## Examples

用法示例。

## Troubleshooting

常见问题和解决方案。
```

**正文规范**：

1. **面向 Agent 写作**：正文是给 AI Agent 读的指令，不是给人看的文档。用祈使句，明确、具体。
2. **工具调用用 qualified name**：引用 MCP 工具时用 `server__tool` 格式，如 `filesystem__read_file`。
3. **脚本引用用相对路径**：`scripts/pdf_create.py`，不要用绝对路径。
4. **保持独立**：每个技能应该自包含，不要假设 Agent 了解上下文。
5. **中英文均可**：根据内容选择合适的语言，中文技能用中文写，通用技能用英文写。

---

## 3. 分类表 (Categories)

| category | 说明 | 示例 |
|----------|------|------|
| `github` | GitHub 相关操作 | PR 管理、Issue 跟踪、Code Review |
| `creative` | 创意内容生成 | ComfyUI、图片生成、音乐、视频 |
| `productivity` | 生产力工具 | PDF、Word、Excel、日历、笔记 |
| `research` | 研究和信息收集 | 论文搜索、RSS 监控、竞品分析 |
| `dev` | 软件开发 | 代码审查、调试、测试、部署 |
| `devops` | 运维和安全 | 网络诊断、容器管理、安全审计 |
| `media` | 媒体处理 | 语音合成、视频处理、音乐识别 |
| `messaging` | 即时通讯 | Telegram、微信 |
| `email` | 邮件处理 | 收件箱分流、邮件撰写 |
| `memory` | 记忆和知识管理 | 对话存档、知识库 |
| `automation` | 自动化流程 | 定时任务、工作流编排 |
| `web` | 网页操作 | 爬虫、网页恢复、内容提取 |

分类允许新增。一个技能只属于一个 category。

---

## 4. 技能加载和激活机制

### 4.1 技能索引

Atlas 启动时扫描 `skills/` 目录，解析所有 SKILL.md 的 frontmatter，构建内存索引：

```python
# 索引结构
{
    "github-pr-workflow": {
        "name": "github-pr-workflow",
        "description": "GitHub PR lifecycle: branch, commit, open, CI, merge.",
        "category": "github",
        "triggers": [...],
        "path": "skills/github/github-pr-workflow/SKILL.md",
        "dependencies": {...},
    },
    ...
}
```

### 4.2 自动激活

当用户发送消息时，Agent 检查所有技能的 triggers：

1. **斜杠命令**：用户输入以 `/` 开头 → 精确匹配 `triggers[].command`
2. **模式匹配**：用户输入匹配 `triggers[].pattern` 正则 → 候选激活
3. **LLM 判断**：候选技能 >1 个时，把候选的 name + description 给 LLM 选择最相关的
4. **激活**：读取完整 SKILL.md 正文，注入到当前对话的 system prompt 中

### 4.3 手动激活

- `/skill <name>` — 强制激活指定技能
- `/skills` — 列出所有可用技能
- `/skills <category>` — 列出某分类下的技能

### 4.4 依赖检查

激活技能前检查 `dependencies`：
- `mcp_servers`：对应的 MCP server 是否已连接
- `python_packages`：尝试 import，失败则提示安装
- `commands`：`which` 检查，失败则提示安装

依赖不满足时告知用户，不直接失败（技能可能部分可用）。

---

## 5. 从 Hermes 迁移指南

Hermes SKILL.md → Atlas SKILL.md 的字段映射：

| Hermes 字段 | Atlas 字段 | 处理 |
|-------------|-----------|------|
| `name` | `name` | 直接保留 |
| `description` | `description` | 直接保留 |
| `version` | `version` | 直接保留 |
| `metadata.hermes.category` | `category` | 提升为顶层字段 |
| `metadata.hermes.tags` | `tags` | 提升为顶层字段 |
| `metadata.hermes.related_skills` | `related_skills` | 提升为顶层字段 |
| `prerequisites.commands` | `dependencies.commands` | 移到 dependencies 下 |
| `platforms` | *(删除)* | Atlas 只跑 Windows，不需要 |
| `license` | *(删除)* | 个人项目，不需要 |
| `author` | `author` | 保留但可选 |
| `compatibility` | *(删除)* | 写在正文 Prerequisites 里 |
| `setup` | *(删除)* | 写在正文 Prerequisites 里 |

**迁移时需额外做的**：
1. 添加 `triggers` — 根据技能内容定义触发模式
2. 添加 `dependencies.mcp_servers` — 如果技能需要文件系统、搜索等工具
3. 移除 Hermes 特有引用 — `$HERMES_HOME`、`hermes` 等路径和概念
4. 调整脚本路径 — 确保用相对路径 `scripts/`
5. 验证 category — 按 §3 分类表归类

---

## 6. 示例技能

### 最小示例

```yaml
---
name: quick-search
description: "用 Brave Search 快速搜索网页信息"
version: 1.0.0
category: research
triggers:
  - pattern: "搜索|搜一下|查一下|search"
  - command: "/search"
dependencies:
  mcp_servers:
    - brave-search
---

# Quick Search

通过 Brave Search MCP 搜索网页信息。

## Instructions

1. 提取用户的搜索意图，构造简洁的英文搜索词
2. 调用 `brave-search__brave_web_search` 搜索
3. 从结果中提取最相关的 3-5 条，用中文摘要回复
4. 附上原始链接
```

### 完整示例

```yaml
---
name: github-pr-workflow
description: "GitHub PR lifecycle: branch, commit, open, CI, merge."
version: 1.0.0
category: github
triggers:
  - pattern: "pr|pull.?request|合并请求"
  - pattern: "开.*分支|创建.*分支"
  - command: "/pr"
dependencies:
  mcp_servers:
    - git
  commands:
    - gh
tags: [github, pr, git, ci]
related_skills: [github-code-review, github-issues]
author: Atlas
---

# GitHub Pull Request Workflow

Manage the full PR lifecycle: create branch, commit, open PR, monitor CI, merge.

## When to Use

- 用户要创建 PR 或合并代码
- 用户要查看 PR 状态或 CI 结果
- NOT for: 创建 issue（用 github-issues 技能）

## Prerequisites

- `gh` CLI authenticated (`gh auth status`)
- Inside a git repo with GitHub remote

## Instructions

### 创建 PR

1. 确认当前分支不是 main/master
2. Push 当前分支到 remote
3. 用 `gh pr create --title "..." --body "..."` 创建
4. 返回 PR URL

### 查看 PR 状态

1. `gh pr status` 查看当前仓库的 PR 概览
2. `gh pr view <number>` 查看具体 PR
3. `gh pr checks <number>` 查看 CI 状态

### 合并 PR

1. 确认 CI 全部通过
2. 确认无冲突
3. `gh pr merge <number> --squash --delete-branch`
```

---

## 7. 技能系统后端接口 (预定义)

```python
class SkillManager:
    """管理技能索引和激活。"""

    async def scan_skills(self) -> None:
        """扫描 skills/ 目录，构建索引。"""

    def list_skills(self, category: str | None = None) -> list[SkillInfo]:
        """列出所有/某分类的技能。"""

    def get_skill(self, name: str) -> SkillInfo | None:
        """按 name 获取技能元信息。"""

    def match_triggers(self, user_input: str) -> list[SkillInfo]:
        """匹配用户输入的触发条件，返回候选技能列表。"""

    async def activate(self, name: str) -> str:
        """激活技能：读取完整 SKILL.md，返回正文内容。"""

    def check_dependencies(self, name: str) -> dict[str, bool]:
        """检查技能依赖是否满足。"""
```

```python
@dataclass
class SkillInfo:
    name: str
    description: str
    version: str
    category: str
    path: str  # SKILL.md 的完整路径
    triggers: list[dict]
    dependencies: dict
    tags: list[str]
    related_skills: list[str]
```

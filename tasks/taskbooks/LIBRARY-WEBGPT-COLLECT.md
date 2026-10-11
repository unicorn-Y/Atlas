# 任务书：为 Atlas 搜罗最新的技能和工具（交给网页 GPT）

> 用法：整份复制给网页 GPT（开深度研究 / 联网 + 代码解释器）。它分批交付 JSONL 文件，你下载后放进
> Atlas 的 `data/library/inbox/`，在「技能与工具库」页面点「导入」→「一键整理」即可入库归类。
> 一轮做不完就回它一句「继续下一批」。

---

## 0. 你是谁、要做什么

你在为一个个人桌面 AI Agent（Atlas，Windows 11，Python + Electron）搭建**技能库**和**工具库**。
请尽可能**多、全、新**地搜罗当前（2026 年 10 月）公开可用的：

1. **技能（Agent Skills）**：带 `SKILL.md`（YAML frontmatter：`name`、`description`，正文是给模型看的操作说明）的技能目录。
   这是 Anthropic 提出、现已被 Claude Code、Codex、Hermes、OpenClaw、OpenCode、Cursor 等通用的开放格式。
2. **工具（MCP 服务器为主）**：Model Context Protocol 服务器，能用 `npx` / `uvx` / `docker` 本地启动，或者是远程 HTTP 端点。
   另外可以收少量**能被 Agent 直接调用的命令行工具**（单独标 `kind: "cli"`）。

**越多越好，越全越好，但必须是新的、活着的、真实存在的。** 编造一个条目比漏掉十个更糟：
所有链接、仓库、包名都必须是你真的查到的。查不到就别写。

---

## 1. 必须遍历的来源（逐个过，最后报告每个来源收了多少条）

### 技能来源
- `github.com/anthropics/skills`（官方）以及 Anthropic 文档里列出的技能
- `github.com/openai/skills`、Codex 文档里的技能目录
- Hermes Agent 自带技能（`NousResearch/hermes-agent` 仓库的 `skills/`、`optional-skills/`）以及 Hermes 技能中心
- OpenClaw / ClawHub（`clawhub.ai` 或当前域名）上的技能
- `skills.sh`、`skillsmp.com`、`agentskills.io` 等技能聚合站（以当时实际存在的为准）
- GitHub 搜索：`filename:SKILL.md`、topic `agent-skills` / `claude-skills` / `claude-code-skills` / `codex-skills`，按最近更新排序
- awesome 列表：`awesome-claude-skills`、`awesome-agent-skills`、`awesome-claude-code` 等（**顺着列表进到原仓库核实**，别只抄列表）
- 大厂和知名团队发布的技能仓库（Vercel、Cloudflare、Supabase、Stripe、Notion、Figma、Microsoft、Google、Hugging Face 等，有就收）

### 工具来源
- MCP 官方注册表 `registry.modelcontextprotocol.io`（API：`/v0/servers`，能翻页就全部翻完）
- `github.com/modelcontextprotocol/servers`（官方参考实现 + README 里的第三方列表）
- Smithery（`smithery.ai`）、Glama（`glama.ai/mcp/servers`）、mcp.so、PulseMCP（`pulsemcp.com`）
- `awesome-mcp-servers`（punkpeye 版，以及其他高星版本）
- Docker MCP Catalog（`hub.docker.com/u/mcp`）
- 各大厂官方 MCP：GitHub、GitLab、Atlassian、Notion、Linear、Slack、Stripe、Cloudflare、Vercel、Supabase、
  AWS、Azure、Google Cloud、Figma、Playwright、Microsoft（含 Office/Windows 相关）、Sentry、Grafana 等
- 中文生态：高德 / 百度地图 MCP、飞书 / 钉钉 / 企业微信 MCP、魔搭（ModelScope）MCP 广场、阿里云百炼 MCP 等

---

## 2. 筛选标准（硬性）

1. **够新**：最近一次提交 / 发布在 **2026-04-01 之后**。官方出品可以放宽到 2025-10-01 之后。
2. **活着**：仓库没被 archived，没标 deprecated，README 没写「已迁移到 xxx」（迁移了就收新地址）。
3. **能用**：技能必须真有 `SKILL.md`；工具必须给得出启动方式（包名 + 版本，或远程 URL）。
4. **质量**：满足任一即可——官方出品；GitHub ≥ 50 星；在两个以上聚合站出现；被知名项目引用。
   不满足但很独特的，可以收，标 `quality: "niche"`。
5. **去重**：同一个技能 / 服务器在多个来源出现，只留一条，`also_listed_in` 写其他来源。
   同名不同实现的，都留，用 `name` 区分（比如 `github-official`、`github-community-xxx`）。
6. **Windows**：明确只支持 macOS / Linux 的也收，但 `windows` 字段写 `false`。
7. **不收**：恶意、刷星、内容只有一行的空壳技能；只能付费用、又没有免费额度的工具（有免费额度的收，标 `pricing`）。

---

## 3. 统一分类表（技能和工具共用）

请给每一条打 `category`（用下面的 id）。实在放不进任何一类，`category` 写 `"new:<英文短 id>"`，并在
`category_suggestion_zh` 写中文名和一句话说明，汇总时列出所有新分类及其条目数。

| id | 中文名 | 放什么 |
|---|---|---|
| coding | 编程开发 | 写代码、语言/框架专长、重构、调试 |
| testing-review | 测试与审查 | 单测、E2E、代码审查、静态检查 |
| git-platform | 代码托管 | Git、GitHub、GitLab、PR、CI |
| devops-cloud | 运维与云 | 部署、容器、K8s、各家云、监控告警 |
| database | 数据库 | SQL/NoSQL、向量库、数据仓库 |
| data-analysis | 数据分析 | 清洗、统计、可视化、Notebook |
| ai-ml | AI 与模型 | 训练、推理、提示词、评测、模型平台 |
| research | 调研检索 | 网页搜索、论文、学术、深度研究 |
| web-browser | 网页与浏览器 | 浏览器自动化、抓取、网页阅读 |
| office-docs | 办公文档 | Word/Excel/PPT/PDF、表格、文档转换 |
| writing | 写作与内容 | 文案、翻译、编辑、博客、营销内容 |
| design-frontend | 设计与前端 | UI 设计、Figma、前端组件、设计系统 |
| media | 图像音视频 | 生图、修图、视频剪辑、语音、音乐 |
| knowledge-notes | 知识与笔记 | Notion、Obsidian、知识库、记忆 |
| communication | 通讯协作 | 邮件、Slack、飞书、钉钉、Telegram、日历 |
| productivity | 效率与项目 | 待办、项目管理、Linear/Jira、自动化流程 |
| system-desktop | 系统与电脑操作 | 文件系统、终端、桌面/GUI 操控、Windows 工具 |
| security | 安全 | 安全审计、漏洞扫描、密钥管理（仅防御向） |
| business-finance | 商业与金融数据 | 支付、电商、CRM、行情数据（不含投资建议） |
| maps-life | 地图与生活 | 地图、出行、天气、购物、健康生活 |
| mobile | 移动端 | iOS/Android 开发、模拟器、App 自动化 |
| agent-meta | Agent 自身能力 | 写技能、写子代理、规划、记忆、多代理编排 |
| learning | 学习教育 | 教学、刷题、语言学习、知识讲解 |
| games-fun | 游戏娱乐 | 游戏开发、娱乐 |

---

## 4. 交付格式（严格遵守，Atlas 会自动导入）

**用代码解释器生成文件让我下载**，别把几千行贴在对话里。

- 技能：`skills-001.jsonl`、`skills-002.jsonl` ……（每个文件 ≤ 500 行）
- 工具：`tools-001.jsonl`、`tools-002.jsonl` ……（每个文件 ≤ 500 行）
- 汇总：`summary.md`（每个来源收了几条、每个分类几条、新分类列表、被你剔除的典型例子和原因）

每行一个 JSON 对象，UTF-8，不要注释，不要尾逗号。

### 4.1 技能一行的字段

```json
{
  "type": "skill",
  "name": "pdf-forms",
  "title_zh": "PDF 表单填写",
  "description": "Fill, extract and flatten PDF forms with pypdf.",
  "description_zh": "用 pypdf 填写、提取、拍平 PDF 表单。",
  "when_to_use_zh": "用户要填 PDF 表单、提取表单字段时",
  "category": "office-docs",
  "category_suggestion_zh": "",
  "tags": ["pdf", "forms"],
  "source": "github",
  "repo": "anthropics/skills",
  "skill_path": "skills/pdf",
  "raw_url": "https://raw.githubusercontent.com/anthropics/skills/<commit-sha>/skills/pdf/SKILL.md",
  "commit": "<40 位 sha，拿不到就写分支名 main>",
  "homepage": "https://github.com/anthropics/skills/tree/main/skills/pdf",
  "license": "Apache-2.0",
  "stars": 12345,
  "last_updated": "2026-09-20",
  "official": true,
  "quality": "high",
  "windows": true,
  "dependencies": {"python_packages": ["pypdf"], "commands": [], "mcp_servers": []},
  "also_listed_in": ["skills.sh"],
  "verified": true
}
```

要求：
- `name`：小写短横线（kebab-case），只含 `a-z0-9-`。原名不合规就转换，原名写进 `tags`。
- `raw_url`：**必须能直接下载到 SKILL.md 原文**。优先用钉死 commit 的 raw 地址。
- `verified`：你亲自打开过 `raw_url`、确认内容存在就写 `true`，没核实写 `false`（但还是要给）。
- `quality`：`high`（官方或高星）/ `good` / `niche`。
- 技能目录里除了 SKILL.md 还有脚本、模板等文件的，在 `tags` 里加 `"has-files"`。

### 4.2 工具一行的字段

```json
{
  "type": "tool",
  "kind": "mcp",
  "name": "github-official",
  "title_zh": "GitHub 官方 MCP",
  "description": "GitHub's official MCP server: repos, issues, PRs, actions, code search.",
  "description_zh": "GitHub 官方 MCP：仓库、Issue、PR、Actions、代码搜索。",
  "when_to_use_zh": "需要读写 GitHub 仓库、Issue、PR 时",
  "category": "git-platform",
  "category_suggestion_zh": "",
  "tags": ["github", "pr", "issues"],
  "transport": "stdio",
  "install": {"command": "docker", "args": ["run", "-i", "--rm", "-e", "GITHUB_PERSONAL_ACCESS_TOKEN", "ghcr.io/github/github-mcp-server:v1.2.3"]},
  "package": "ghcr.io/github/github-mcp-server",
  "version": "v1.2.3",
  "remote_url": "https://api.githubcopilot.com/mcp/",
  "env_required": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
  "auth": "api_key",
  "pricing": "free",
  "tool_names": ["search_repositories", "create_issue", "create_pull_request"],
  "repo": "github/github-mcp-server",
  "homepage": "https://github.com/github/github-mcp-server",
  "license": "MIT",
  "stars": 20000,
  "last_updated": "2026-09-28",
  "official": true,
  "quality": "high",
  "windows": true,
  "also_listed_in": ["registry.modelcontextprotocol.io", "smithery", "docker-mcp-catalog"],
  "verified": true
}
```

要求：
- `install`：本地启动命令，**版本号钉死**（`npx -y pkg@1.2.3`、`uvx pkg==1.2.3`、docker 镜像带 tag）。
  只有远程端点的，`install` 写 `null`，`transport` 写 `"http"`，填 `remote_url`。
- `env_required`：只写环境变量**名字**，绝不写任何真实密钥。
- `auth`：`none` / `api_key` / `oauth`。
- `pricing`：`free` / `freemium` / `paid`。
- `tool_names`：能查到就列出它暴露的工具名（前 30 个即可），查不到写 `[]`。
- 命令行工具：`kind: "cli"`，`install` 写安装命令（如 `{"command": "winget", "args": ["install", "..."]}`），`tool_names` 写主要子命令。

---

## 5. 分批节奏

每一轮做完一批就停下，告诉我「本批 X 条，累计 Y 条，下一批打算覆盖哪些来源 / 分类」。
建议顺序：

1. 第 1 批：所有**官方**技能 + 所有**官方**MCP（Anthropic、OpenAI、MCP 官方仓库、各大厂官方）
2. 第 2 批：MCP 官方注册表全量翻页
3. 第 3 批：Hermes / OpenClaw / ClawHub / skills.sh 等技能聚合站
4. 第 4 批：Smithery、Glama、PulseMCP、mcp.so、Docker Catalog 去重补全
5. 第 5 批：GitHub 搜索 + awesome 列表兜底（按最近更新、星数排序，扫到收益很低为止）
6. 第 6 批：中文生态 + 按分类查漏（哪个分类少于 20 条就专门补）
7. 最后：`summary.md` + 抽查 5% 的 `raw_url` / 包名确认真实，把核实结果回填 `verified`

---

## 6. 自检清单（每批交付前过一遍）

- [ ] 每行都是合法 JSON，字段齐全，`name` 是 kebab-case
- [ ] 没有编造的仓库 / 包名 / 链接；拿不准的写 `verified: false`
- [ ] `last_updated` 都在 2026-04-01 之后（官方条目放宽到 2025-10-01）
- [ ] 同一条没在多个文件里重复
- [ ] 没写任何真实密钥、token
- [ ] `category` 都在分类表里，或者是 `new:xxx` 且写了中文说明

# 全网发现（追新升级）

旧的追新只做两件事：`core/atlas/upstream/` 把 Atlas 依赖的组件追到最新版本，`core/atlas/evolution/watcher.py` 盯几个仓库的提交并按能力表给建议。这次加了第三件：**在全网找新出的 agent、功能、MCP、技能、工具，判断值不值得 Atlas 吸收，直接产出报告和移植任务书草稿。** 按用户决定，这是 Atlas 自己的功能，不依赖 Claude 的定时任务。

代码：`core/atlas/evolution/discovery/`（`sources.py` 抓取、`judge.py` 筛选、`service.py` 报告/草稿/定时）；接口 `GET /api/evolution/discovery`、`POST /api/evolution/discovery/run`、`GET /api/evolution/discovery/reports/{name}`；界面在「自动追新」页的「全网发现」区（`components/evolution/DiscoveryPanel.tsx`）。

## 信息源

| 类别 | 源 | 取法 |
|---|---|---|
| 已跟踪产品的新版本 | Claude Code、Codex、Hermes、OpenClaw、OpenCode、Pi、Goose、Gemini CLI、Cline、browser-use、ZCode、OpenHands、MCP 规范 | GitHub Releases API（有 `GITHUB_TOKEN` 或 `gh auth token` 就带上） |
| 更新日志聚合页 | code.claude.com changelog、releasebot（Codex）、aiagentstore 周报、gradually.ai | Atlas 自己的网页读取（`atlas.websearch` extract），正文交给模型提炼 |
| 新项目 | GitHub 最近 N 天新建、按星排序（ai-agents / mcp-server / claude-code / agent-skills / coding-agent / computer-use 等主题）；GitHub Trending 周榜 | Search API；trending 页解析 |
| 社区 | Hacker News（Algolia，30 分以上）；Reddit（LocalLLaMA、ClaudeAI、ChatGPTCoding、AI_Agents、mcp、OpenAI 周榜） | 公开 JSON 接口 |
| 生态 | MCP 官方注册表（最近更新的服务器）；skills.sh 技能市场（与 Atlas 技能中心同一提供方） | 公开接口 |
| 国内与小平台 | V2EX 热帖、linux.do 周榜；X、产品博客、国内媒体用网页搜索兜底（含 `site:x.com`、`site:linux.do`、`site:v2ex.com`、中文关键词） | 公开 JSON；Atlas 网页搜索服务 |

源列表都在 `sources.py` 顶部的常量里，加源就是加一行。单源失败只记错误、不影响别的源；走代理的连接失败会换连接重试一次。

## 筛选

1. 去重（同一 URL 多源出现会合并并加分）、跳过以前报过的条目（`state.json` 的 `seen`）。
2. 规则分 = 相关度关键词 × 热度（对数）× 新鲜度 × 类型加权；技能市场的安装量是历史累计，权重压低；每个源最多占候选的 40%。
3. 前 60 条交给 Atlas 当前模型，按「Atlas 现状摘要」逐条判断：absorb / watch / skip、一句话说明是什么能力怎么做的、Atlas 差在哪、从哪移植、工作量、价值。模型不可用时退回规则判断，并在报告里写明。

## 产出

- 报告：`<data>/evolution/discovery/reports/<日期-时分>.md`（同名 `.json` 存原始判断），界面可直接看。
- 任务书草稿：价值最高的若干条 absorb（默认 6 份）写成 `tasks/taskbooks/ATLAS-AUTO-<日期>-disc-<slug>.draft.md`，登记进原有草稿索引，在「任务书草稿」区出现；批准后走原来的隔离分支流程，合并永远要人工。草稿正文按「拿来主义」写：先找最强开源实现、翻译成 Atlas 自己的代码、写 `Ported from` 头、登记 PORTED.md。

## 定时

服务启动 5 分钟后开始，每 30 分钟检查一次是否到期；配置 `evolution.discovery.enabled`（默认开）、`evolution.discovery.interval_hours`（默认 24）、`evolution.discovery.days`（默认 7）。界面上「现在跑一次」随时手动触发。

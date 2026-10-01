# ATLAS-W12-SELF-EVOLUTION（第十二波：自我进化）

STATUS: READY（W11 交付后）
PROTOCOL: +1
先读：`docs/plan/00-MASTER-PLAN.md`（用户目标第 4 条）、`docs/plan/VENDORED.md`、`docs/research/2026-09-30-landscape/10-tracking-sources.md`
主要来源：H `agent/background_review.py`、`agent/curator.py`、`agent/learning_graph.py`；论文《Skill Misevolution》（arXiv 2608.12851）的安全阀建议

## 本波目标

用户原话：「可以每天找各种更新的东西，然后加上、升级，节省我自己开发」。用户明确要求做成 **Atlas 自己的功能**，不要外部定时任务。

两件事：
1. **跟上游**：Atlas 搬过来的每一段代码都登记在 `VENDORED.md`，来源项目每天都在更新。Atlas 定期看这些来源的新提交，找出「我们搬过的文件改了什么」「有什么新能力值得搬」，生成任务书草稿。
2. **跟各家产品**：按信息源清单定期抓各家的更新日志，提炼新能力，对照对标表，生成建议。

外加：技能自学（Atlas 在用的过程中自己沉淀和改进技能），带安全阀。

---

## 1. 上游跟踪（后端，自己写）

1. 解析 `docs/plan/VENDORED.md`（改成同时维护一份机器可读的 `docs/plan/vendored.json`：`[{atlas_path, repo, source_path, commit, license, method}]`）。
2. 定时任务（走 Atlas 自己的调度器，默认每周一次，可改）：
   - 对每个来源仓库，用 GitHub API（`gh api` 或 HTTP，带用户的 GitHub 令牌更好，没有也能跑但会限流）取 `commit..HEAD` 之间改到 `source_path` 的提交和 diff。
   - 同时取来源仓库的 release 说明（`/releases`）。
   - 交给一个 `researcher` 子 Agent（W07）总结：哪些改动是修 bug（建议同步）、哪些是新能力（建议搬）、哪些和 Atlas 无关。
3. 产出：`docs/evolution/upstream-<日期>.md`（每条：来源、改了什么、对 Atlas 的建议、对应的 Atlas 文件），和一份任务书草稿 `tasks/taskbooks/drafts/ATLAS-UPSTREAM-<日期>.md`（按本计划任务书的格式写）。
4. 用户在界面上看报告，勾选要做的，点「生成任务书」；**不自动改代码**。

## 2. 产品动态跟踪（后端，自己写）

1. 信息源：`docs/research/2026-09-30-landscape/10-tracking-sources.md` 里的清单，改成可在设置里编辑的列表（数据目录 `evolution/sources.json`）：汇总站、官方更新日志、GitHub releases、关键词搜索。
2. 定时（默认每周）抓取：网页用 `web_extract`（带 SSRF 防护）；GitHub 用 releases API；和上次抓的内容比较，只处理新增部分。
3. `researcher` 子 Agent 提炼：产品、日期、新能力是什么、**怎么做的**、有没有开源实现可以搬（去 GitHub 搜）。
4. 对照 `docs/PARITY.md` 和本计划：Atlas 有没有、差多少。
5. 产出：`docs/evolution/landscape-<日期>.md` 和建议清单；用户勾选后生成任务书草稿。
6. 抓来的内容不进长期记忆。

## 3. 技能自学 + 安全阀（后端，从 H 搬 + 自己加）

**来源**：H `agent/background_review.py`（1342 行：每轮结束后在后台线程里用对话快照分叉一个 Agent，问「有没有技能该保存或更新」；**主对话和提示缓存不受影响**）、`agent/review_engine.py`、`agent/curator.py`（1212 行：空闲时维护技能，按使用情况标过期 / 归档 / 合并；只动自己管理的技能）、`agent/learning_graph.py`、`tools/skill_manager_tool.py`。

**做法**：
1. 搬后台复盘：默认每 10 轮复盘一次（H 的默认值），复盘 Agent 只能动技能（**记忆冻结，不动记忆**）。
2. 搬 curator：30 天没用标过期，90 天归档（可恢复）。
3. **安全阀**（安全审查由用户亲自负责，本计划不做）。保留下面不属于安全审查的部分（论文《Skill Misevolution》提醒过自我进化的风险）：
   - 新技能和技能改动先进「待确认」，不直接生效；用户在技能页确认。
   - 技能被使用时记录结果；失败率高的自动降级为待确认。

## 4. 前端

1. 新页面「进化」（侧栏入口）：
   - 「上游更新」：最近一次报告，每条可以展开看 diff 摘要，勾选「要做」→「生成任务书」→ 显示草稿，可复制或保存。
   - 「各家动态」：按产品分组的新能力，标「Atlas 已有 / 部分 / 没有」，勾选 →「生成任务书」。
   - 「信息源」：列表编辑、上次抓取时间、手动「现在检查」。
   - 「自学的技能」：待确认列表（技能内容、来源对话、扫描结果），确认 / 拒绝 / 编辑。
2. 设置：检查频率、GitHub 令牌（存系统凭据库）。

## 5. 验收

- 手动把 `vendored.json` 里某个 Hermes 文件的提交号改成一个月前，跑一次上游检查，报告里能正确列出这一个月它改了什么，并给出建议。
- 跑一次产品动态检查，报告里至少包含 Claude、ChatGPT、Cursor、Hermes、OpenClaw 最近一周的更新。
- 生成的任务书草稿格式和 `ATLAS-W06` 一致，能直接交给 Codex。
- 对话里解决一个问题后，技能页出现一条待确认的技能；从网页内容学来的技能被标出。

## 6. 交付

同 W06。

# START HERE — Atlas Agent 竞品实物深度逆向分会话派工

**更新：2026-10-19。当前仅完成派工和包采集，尚未完成本轮逆向研究。**
**仓库：** `unicorn-Y/Atlas`
**派工分支：** `research/agent-reverse-dispatch-20261019`
**原包集合：** `research/agent-client-packages-20261019`
**归档 Release：** https://github.com/unicorn-Y/Atlas/releases/tag/agent-client-packages-20261019
**包目录：** `docs/research/agent-clients/2026-10-19/`
**总协议：** [PROTOCOL.md](PROTOCOL.md)
**最终统一验收：** [FINAL-REVIEW.md](FINAL-REVIEW.md)

## 使用方法——一个新会话只干一个产品
1. 自选下方产品，在 ChatGPT **新建独立会话**。将对应任务书最下面的“新会话启动语”粘贴进新会话；或者直接使用本 README 下方的通用启动模板，仅替换 slug。
2. 该会话先经 GitHub 读取**指定任务书和 PROTOCOL**，查询对应原包及源码，开始真实拆包/追踪引擎；不能仅重写项目介绍/用户举例。每会话可借助本机 Codex 做机械提取，不将研究责任随意丢给它。
3. 该会话从**本派工分支**创建自己的 `research/agent-reverse-20261019-<slug>`，只提交到自己的 `docs/research/agent-reverse/2026-10-19/<slug>/`，随后提供 commit+入口。**不并发写 main，同一个 slug 不要开多个写入会话。**
4. 对无法直接取得的二进制，在对应分支提交 `EXTRACTION-REQUEST.md`，让本机 Codex 精确按要求提取并 push；会话再继续阅读真实文件，不能仅凭文件名推断功能。
5. Wave 1 是最优先研究，但 **Wave 2/3 可同时启动**；互相独立，完成后再依据 [FINAL-REVIEW.md](FINAL-REVIEW.md) 开一个总审会话。
6. 不因某项素材缺失堵住其他产品；未确认与证据盲点明确标记。Claude Consumer Setup 仍缺但有官方企业 MSIX；Codex Desktop 官方 MSIX 已补齐。

## Wave 1：核心八份，建议先开
| 单独新会话研究产品 | 唯一提交分支 | 唯一报告目录 |
|---|---|---|
| [Claude Desktop / Cowork](sessions/claude-desktop.md) | `research/agent-reverse-20261019-claude-desktop` | `docs/research/agent-reverse/2026-10-19/claude-desktop/` |
| [Claude Code CLI](sessions/claude-code.md) | `research/agent-reverse-20261019-claude-code` | `docs/research/agent-reverse/2026-10-19/claude-code/` |
| [Codex Desktop / ChatGPT](sessions/codex-desktop.md) | `research/agent-reverse-20261019-codex-desktop` | `docs/research/agent-reverse/2026-10-19/codex-desktop/` |
| [Codex CLI / Code Mode](sessions/codex-cli.md) | `research/agent-reverse-20261019-codex-cli` | `docs/research/agent-reverse/2026-10-19/codex-cli/` |
| [OpenCode Desktop + CLI](sessions/opencode.md) | `research/agent-reverse-20261019-opencode` | `docs/research/agent-reverse/2026-10-19/opencode/` |
| [ZCode Desktop / Runtime](sessions/zcode.md) | `research/agent-reverse-20261019-zcode` | `docs/research/agent-reverse/2026-10-19/zcode/` |
| [DeepSeek Harness 官方核心](sessions/dsh-core.md) | `research/agent-reverse-20261019-dsh-core` | `docs/research/agent-reverse/2026-10-19/dsh-core/` |
| [DSH 社区桌面双项目](sessions/dsh-desktop.md) | `research/agent-reverse-20261019-dsh-desktop` | `docs/research/agent-reverse/2026-10-19/dsh-desktop/` |

## Wave 2：IDE Agent 与核心开源运行时
| 单独新会话研究产品 | 唯一提交分支 | 唯一报告目录 |
|---|---|---|
| [Cursor](sessions/cursor.md) | `research/agent-reverse-20261019-cursor` | `docs/research/agent-reverse/2026-10-19/cursor/` |
| [Windsurf / Devin](sessions/windsurf.md) | `research/agent-reverse-20261019-windsurf` | `docs/research/agent-reverse/2026-10-19/windsurf/` |
| [Cline](sessions/cline.md) | `research/agent-reverse-20261019-cline` | `docs/research/agent-reverse/2026-10-19/cline/` |
| [Roo Code](sessions/roo-code.md) | `research/agent-reverse-20261019-roo-code` | `docs/research/agent-reverse/2026-10-19/roo-code/` |
| [Kilo Code](sessions/kilo-code.md) | `research/agent-reverse-20261019-kilo-code` | `docs/research/agent-reverse/2026-10-19/kilo-code/` |
| [Continue](sessions/continue.md) | `research/agent-reverse-20261019-continue` | `docs/research/agent-reverse/2026-10-19/continue/` |
| [Hermes Agent](sessions/hermes-agent.md) | `research/agent-reverse-20261019-hermes-agent` | `docs/research/agent-reverse/2026-10-19/hermes-agent/` |
| [Goose](sessions/goose.md) | `research/agent-reverse-20261019-goose` | `docs/research/agent-reverse/2026-10-19/goose/` |

## Wave 3：独立运行时、工作台、扩展生态
| 单独新会话研究产品 | 唯一提交分支 | 唯一报告目录 |
|---|---|---|
| [Pi](sessions/pi.md) | `research/agent-reverse-20261019-pi` | `docs/research/agent-reverse/2026-10-19/pi/` |
| [Zed](sessions/zed.md) | `research/agent-reverse-20261019-zed` | `docs/research/agent-reverse/2026-10-19/zed/` |
| [OpenHands Agent Canvas](sessions/openhands-canvas.md) | `research/agent-reverse-20261019-openhands-canvas` | `docs/research/agent-reverse/2026-10-19/openhands-canvas/` |
| [Squad](sessions/squad.md) | `research/agent-reverse-20261019-squad` | `docs/research/agent-reverse/2026-10-19/squad/` |
| [ccusage](sessions/ccusage.md) | `research/agent-reverse-20261019-ccusage` | `docs/research/agent-reverse/2026-10-19/ccusage/` |
| [Claude HUD](sessions/claude-hud.md) | `research/agent-reverse-20261019-claude-hud` | `docs/research/agent-reverse/2026-10-19/claude-hud/` |
| [Agent Skills / MCP](sessions/skills-mcp.md) | `research/agent-reverse-20261019-skills-mcp` | `docs/research/agent-reverse/2026-10-19/skills-mcp/` |

**总计 23 份独立任务书**（其中 DSH Desktop 特例：两个同生态的社区桌面封装由同一会话独立区分；Skills/MCP 特例为底层扩展生态）。每个会话彼此隔离，避免混写、模型上下文膨胀。任务划分不是功能发现边界。

## 通用启动消息（仅替换 <slug>）

```text
开始 Atlas 竞品的独立拆包研究。仓库 unicorn-Y/Atlas。
先从分支 research/agent-reverse-dispatch-20261019 读取
tasks/research/agent-reverse/2026-10-19/sessions/<slug>.md
与 tasks/research/agent-reverse/2026-10-19/PROTOCOL.md。
严格只研究该任务书产品，真实查看归档发行包与源码，发现未知功能、深挖前后端运行机制，与 Atlas main 代码对照。
研究过程分段提交到 research/agent-reverse-20261019-<slug>，
报告目录 docs/research/agent-reverse/2026-10-19/<slug>/。
不要改 Atlas 正式代码，不能凭网上功能介绍冒充拆包。
无法直接读取大型资产时提交精确 EXTRACTION-REQUEST.md 交本机 Codex 机械抽取后继续。
完成后直接 push 并回报 commit + START-HERE.md + 未查明部分。
```

## 所有研究完成以后的总审

另开**一个**“Atlas 逆向总审”新会话，加载本分支 [FINAL-REVIEW.md](FINAL-REVIEW.md)，按所有分支真实输出做跨产品对照、底层机制挖漏和 Atlas 真代码审查。

最终对标采用**每项机制行为和执行实际质量**，不是“有一个按钮/接口/用例成功”就标记完整。此前任何调研文档不能作为穷尽性证据。

## 派工本身的状态
- 已完成：23 份分会话任务书、共享协议、最终总审任务书。
- 已有：55 个包资产与源码快照（按包采集文档申报），Codex Desktop 官方 MSIX 已补齐；Claude consumer Setup 仍受区域限制。
- 尚未完成：独立会话实际深度拆包、逐个源码机制证据、Atlas 对照、总审和施工。

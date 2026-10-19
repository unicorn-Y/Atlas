# 证据索引：原始材料、源码锚点与覆盖边界

## 身份与来源

官方上游：`https://github.com/deepseek-ai/deepseek-harness`；固定提交 `687f282e8625c6b8d11ff58211a90524be2e4317`。源码 ZIP `dcc4cf8df9c3cbb3d57726b7a1ad5a52c16a754dcdbc2c0a0836788976090d9f` 已直接下载、完整 SHA 验证并解包。解包 tree index 有 9,485 条文件记录；GitHub Tree API 对 commit 的 **18,758** tracked paths 且 `truncated=false` 包含 Git 未跟踪文件表/目录记录，两计数语义不同。**仍不代表逐文件读取所有源码文件**。审查内容来自本地 ZIP 与固定提交源码（S），不是第三方博客摘要。

Atlas：`unicorn-Y/Atlas` `main@aa6196f550098cc46081dc6db2c376cb87ddffa5`，树 **1,412** paths，`truncated=false`；已读其中若干关键 Python 文件，未读完全部。派工分支 `research/agent-reverse-dispatch-20261019` 有 `docs/research/agent-clients/2026-10-19/manifest.json` 和 `indexes/dsh-index.txt`，原收集报告明确静态机械清单不代表功能验收。

归档三项：
| 发行品 | 提取对象 | SHA256 | 状态 |
|---|---|---|---|
| CLI npm 0.2.0-rc.2, 24,265 B | `deepseek-harness-npm-cli-bd27847c44.tgz` | `bd27847c445cd68a565ac1f91c06bbbcc7639ef93071f678bb59c5ebaff38859` | 已校验并解包；`extracted/cli-tree.txt`, package JSON 与 launcher JS；静态 REA Evidence `ev_4f652c791174bde9e4c3bf71a5f96e04d591c88d34c15af6e25db57e55c10011` |
| 固定源码 ZIP root 0.2.1-rc.2, 44,386,184 B | `deepseek-harness-source-dcc4cf8df9.zip` | `dcc4cf8df9c3cbb3d57726b7a1ad5a52c16a754dcdbc2c0a0836788976090d9f` | SHA 已验证并逐文件解包/哈希索引；GitHub API/固定源码锚点见下 |
| Web npm 0.0.1-rc.5, 1,428,754 B | `deepseek-harness-web-frontend-ccadad6dcb.tgz` | `ccadad6dcbb6f9a3c7a57802c3c2bb5958c2104ca33e9fb88135634b6d7b1516` | 已校验并解包；`web-tree.txt`, package/index, per-chunk symbol offsets; static REA Evidence `ev_1e00377639a62d192bba484dd31eb34df1b6130601cb2e5089c400510a559c6c` (partial; main entry heap limit) |

发布物机器证据：`extracted/manifest-verified.json`, `source-tree.txt`, `source-versions.json`, `command-endpoints.txt` (1,039 source rows), `web-assets-map.json`, `web-chunk-symbols.jsonl`, `version-diff.md`。没有复制整份 9,485-file source tree 到报告目录，只有列表/size/SHA index。REA 对未执行源码/Bundle 静态解析，不能作为 R。

CLI dependency closure: `work/dsh-cli-runtime` 是只读分析临时安装，不进 Git；使用 npm 从已验证 CLI manifest 解析确切 `0.2.0-rc.2` registry archives（不运行 install scripts）。为可复核且不携带庞大 `node_modules`，`extracted/published-runtime-packages.json` 记录 Agent loop、Session、JSONL persistence、Web app、Session controller、Subagent、preset registry 及 child UI 包的 name/version/registry integrity/入口 SHA-256。实际 Node launcher `--version`、`--help` exit 0；此动作没有 boot profile。

## 官方源码关键可复核锚点（S）

所有链接指向固定 SHA，不是会变化的 main：

| 证据范围 | 路径与符号 / 相关 ID |
|---|---|
| React loop phase + durable turn | [`packages/core/agent-loop/src/agent.ts#L97-L150`](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/core/agent-loop/src/agent.ts#L97-L150), `turn/step` 298-395，`prepareRequest` 563-684；001-003、006 |
| assistant stream | `packages/core/agent-loop/src/assistant-stream.ts:18-107`；004 |
| inbox projection | `packages/core/agent-loop/src/inbox.ts:20-55`；002 |
| bounded rolling pool | [`packages/core/agent-loop/src/tool-calls.ts#L122-L246`](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/core/agent-loop/src/tool-calls.ts#L122-L246)；005 |
| child manager | [`packages/subagent/subagent/src/manager.ts#L373-L465`](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/subagent/subagent/src/manager.ts#L373-L465)、533-628，739-761；007-012 |
| child meta/depth | `packages/subagent/subagent/src/child-agent.ts:49-118,135-160`；011 |
| lifecycle + stop reason | `packages/subagent/subagent/src/lifecycle.ts:63-170`；010 |
| delegate tool/control | `packages/subagent/tool-subagent/src/index.ts:193-379`、`packages/subagent/tool-subagent-control/src/index.ts:27-111`；007、009 |
| browser child Remote | `packages/subagent/subagent/src/index.ts:425-527`，`control.ts:16-28`；012 |
| Session RPC | `packages/api/session-controller/src/index.ts:118-176,275-603`、`history.ts:120-220`、`control.ts:17-79`；014 |
| Web mux | `packages/api/gateway/src/stream-protocol.ts:6-19`、`stream-server.ts:44-127`、`client/stream-client.ts:52-105,241-380`；015 |
| child UI | [`packages/client/ui-subagent/src/client/index.ts#L52-L101`](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/client/ui-subagent/src/client/index.ts#L52-L101)、`SubagentHeaderLineage.tsx:196-395`、`sidebar-chat/index.tsx:18-201`；013 |
| child client mutation | `packages/api/session-controller/src/client/sessions/session.ts:240-357`；013-014 |
| transient/durable event model | `packages/api/session-controller/src/client/contract/events.ts:6-35,97-120`；014 |
| Session JSONL and writer lease | `packages/session/session-persistence-jsonl/src/storage.ts:35-60,186-224,270-339`、`lease.ts:1-28`、`format.ts:1-43`；016 |
| token meter | `packages/llm/token-meter/src/turn-usage.ts:6-35,81-139,170-275`；017 |
| compaction | `packages/compaction/compaction-basic/src/index.ts:148-233`、`summarizer.ts:110-179`、`compaction-tool-result-pruner/src/index.ts:128-170`；018 |
| MCP hot tools | `packages/mcp/mcp-client/src/index.ts:154-192`、`tools.ts:81-158`；019 |
| agent team DAG | `packages/experimental/agent-team/src/index.ts:55-109,129-211`、`task-board.ts:28-255`、`task-graph.ts:20-70`、`journal.ts:55-70`；020 |
| jobs nonconsuming follow | `packages/api/job-controller/src/index.ts:75-115`、`packages/jobs/jobs-local/src/pump.ts:53-86`；021 |
| trajectory | `packages/client/ui-trajectory/src/client/TrajectoryView.tsx:132-380`、`TrajectoryTable.tsx:2080-2257,3170-3194`；022 |
| CLI profiles | `apps/cli/src/args.ts:1-14,143-210`、`apps/cli/src/bin.ts:26-79`；023 |
| Profile layering / templates | `apps/cli/src/profile-boot.ts:202-245,306-337`；`packages/boot/app-boot/src/profile.ts:89-120,169-237,740-840`；`profile-resolution/resolver.ts:86-120`；031 |
| Host startup environment / shutdown | `apps/cli/src/profile-boot.ts:271-341`；`apps/cli/src/process-shutdown.ts:1-72`；032 |
| schedule/goal/PTC | `packages/schedule/schedule/src/index.ts:90-118`、`packages/goal/goal-round-driver/src/index.ts:77-103,173-255`、`packages/ptc-runtime/ptc-runtime-node/src/index.ts:36-105`；024-025 |
| dynamic plugin lifecycle | `packages/boot/plugin-manager/src/operations.ts:285-450`；026 |
| old npm runtime package anchors (`0.2.0-rc.2`) | Actual registry package identities + main bundle hashes in `extracted/published-runtime-packages.json`; `IMPLEMENTATION-TRACE.md` section 0 records inspected compiled JS call-path line ranges for agent loop, tool recovery, persistence, session RPC, and child cold resume; 034 |
| License | [`LICENSE`](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/LICENSE) 为 MIT，Copyright 2026 DeepSeek |

## Atlas 实际源码锚点（main SHA）

- `core/atlas/agent/run_phases.py:1-24,146-174,698-920`：单执行路径/异步事件桥。
- `core/atlas/engine/hermes_runtime.py:1-11,869-908,1024-1040,1390-1564`：Hermes 引擎与运行事件。
- `core/atlas/engine/tool_registry.py:43-53,290-493,586-650`：包括 `delegate_task` 的工具注册和调度入口。
- `core/atlas/agent/planning.py:10-73`、`subagent_worktree.py:237-344`、`results.py:45-95`。
- `core/atlas/api/runtime.py:108-146`：重启主动将运行中状态置失败（独立确认）。
- `core/atlas/api/runtime_ws_router.py:18-60,123-150`：`/ws/chat`、resume/cancel/pause/steer。
- `core/atlas/runtime/hub.py:1-15,119-160`：长时后台主机及 DBOS。
- `core/atlas/engine/session_sync.py:1-14,41-145`：Hermes SessionDB 真源。
- `core/atlas/models/router.py:1-11,53-73,254-341`：provider 路由与 token 回调。

## U / 尚未调查或未验证

1. 已通过 CLI manifest 安装并校验关键 CLI 0.2.0-rc.2 runtime dependencies，且静态核对旧版编译 JS；仍未逐项审完完整 82 direct dependency packages，亦未动态验证 profile composition / default bundle mount 与损坏配置启动行为。CLI launcher tar 自身不包含这些 runtime packages。
2. Web 0.0.1-rc.5 的源 TypeScript 对应关系、SourceMap、main JS 静态图剩余 unknowns；已确认包不含 `.map`，REA main entry semantic 分析 partial。
3. 全部 Cordis profile 的 default plugin composition、实验开关是否启动；同源码中的 `apps/desktop` 不在本次发行样本的实物验证范围。
4. 每个 Tool/Agent provider 真实动态生命周期（包括 ACP/Claude Code/Codex/DSH SDK），功能细分、参数兼容性、OS 级 process kill。
5. 实际启动/浏览器 UI 演练、WebSocket 丢连重建后完整日志无洞、运行中的取消/竞争、子代理冷恢复/错误恢复实测。
6. 全命令/快捷键/菜单/文件上传以及所有 UI Slot 使用并未穷尽；第三方依赖许可证与生成文件告知需单独对照。
7. Atlas 未打开的核心子代理内部主循环、更新分支的改动、UI 全组件及完整权限链；本次仅限 main 上的已核文件。

**不得将本索引中的静态证据改写为“二进制已解包/行为已跑通”。**

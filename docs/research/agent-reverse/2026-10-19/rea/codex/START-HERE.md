# START HERE — OpenAI Codex 全量逆向（Desktop / CLI / Code Mode Host）

**一句话结论**：Codex 不是一个"聊天客户端 + 命令行工具"，而是一套**四外壳共用同一 Rust 内核**的 Agent 平台；其真正的差异化在协议层（172 个 RPC）、多 Agent mailbox 机制、以及把工具调用变成代码执行的 Code Mode。

| 项 | 值 |
|---|---|
| 产品 | OpenAI Codex（Desktop 26.1013.4894.0 / CLI rust-v0.163.0 / Code Mode Host 0.163.0） |
| 研究分支 | `research/zcode-rea-20261019-codex` |
| 本地完整资料 | `D:\Atlas-Reverse-Lab\codex\` |
| 本地图鉴 | `D:\Atlas-Reverse-Lab\codex\viewer\index.html`（用 `start-viewer.ps1` 一键打开） |
| 执行 | ZCode + DeepSeek V4.1 Flash + REA 6.4.0 |
| 完成日期 | 2026-10-19 |

---

## 1. 版本核对结果（先验门禁）

| 组件 | 认定版本 | 依据 | 是否最新 |
|---|---|---|---|
| Codex Desktop | `26.1013.4894.0`（releaseVersion `26.1013.40934`） | 官方 CDN `persistent.oaistatic.com/codex-app-prod/ChatGPT-x64.msix`；`windows-store-update.json` 返回同版本 | ✅ 是（2026-10-19 实测） |
| code CLI | `rust-v0.163.0` | GitHub `openai/codex` latest release，2026-10-15 发布 | ✅ 是稳定版（存在 `rust-v0.164.0-alpha.1~4` 预发布，未采用） |
| Code Mode Host | `0.163.0` | 同 release assets | ✅ |
| 源码快照 | `rust-v0.163.0` | tag archive | ✅ 与二进制同版本 |

SHA256 全部重算并与采集清单一致（`indexes/SHA256SUMS.txt`）。

## 2. 材料与规模

| 项 | 数值 |
|---|---|
| MSIX 文件数 | 3,651 |
| MSIX 解压 | 2,346,419,207 B |
| app.asar 条目 | 21,073（593,720,176 B） |
| Rust workspace | 155 crate / 5,276 .rs / 约 190 万行 |
| 登记文件总数 | 12,875（100% 登记，含 SHA256） |

## 3. 本轮真正拆出来的东西

### 3.1 协议层（最硬证据）
- **172 个 app-server RPC 方法**（`PROTOCOL-METHODS.md`）
- **85 类服务端通知**（`PROTOCOL-NOTIFICATIONS.md`）
- **810 个协议数据模型定义**（`decompiled/app-server-schema/`，由官方二进制自生成）

这些不是推断，是 `codex app-server generate-json-schema --experimental` 直接导出的官方协议定义。

### 3.2 未公开能力清单
| 能力 | 证据 |
|---|---|
| 多 Agent V1/V2 + 9 个协作工具（spawn/send_input/send_message/followup_task/resume/wait/list/close/interrupt） | `core/src/tools/handlers/multi_agents_spec.rs` |
| Remote Control（他机遥控本机） | RPC `remoteControl/*` 6 个方法 |
| Realtime 语音（WebRTC + SDP + 音频增量） | RPC `thread/realtime/*` 9 个方法 |
| Agent Jobs（CSV 批量任务） | `state/migrations/0014_agent_jobs.sql` |
| Thread Queue（运行中排队追加） | RPC `thread/queue/*` 6 个 + CLI `codex queue` |
| Goal 目标系统（token 预算/六态） | `goals_migrations/0001_thread_goals.sql` |
| Memory 两阶段 | `memory_migrations/0001_memories.sql` |
| Marketplace / Plugin 分享 | RPC `marketplace/*`、`plugin/share/*` |
| External Agent 配置迁移 | RPC `externalAgentConfig/detect|import` |
| Guardian 审批层 | `GuardianRiskLevel` + `thread/approveGuardianDeniedAction` |
| Code Mode | `exec`/`wait` 双工具 + gRPC 6 方法 + V8 cell 资源限制 |
| 隐藏彩蛋 Play Snake | 解包副本登录页实拍 |

### 3.3 机制级解释
- Agent 主循环完整时序（`02-Agent主循环与工具系统.md`，带行号）
- 三种压缩路径、三个触发点
- 六种工具暴露面
- 多 Agent mailbox 语义
- 六库表结构（来自 migration SQL）

## 4. 图鉴入口

**本地**：`D:\Atlas-Reverse-Lab\codex\viewer\start-viewer.ps1` → 浏览器打开 `http://127.0.0.1:8848/viewer/index.html`

图鉴包含 15 个分区：总览与证据、架构与进程、155 crate 目录、Agent 主循环、28 工具、多 Agent、上下文压缩、Code Mode、app-server 协议（257 项）、本地持久化、桌面端与 IPC、2,176 前端组件、185 功能开关、模型目录、界面截图、未解与盲点。

支持：搜索、勾选收藏、导出 `SELECTIONS.json` / `SELECTIONS.md`。

**GitHub 浏览器版**：本目录下的 Markdown 报告 + `viewer/index.html`（本地可开；GitHub 上可直接看报告）。

## 5. 诚实边界

| 项 | 状态 | 原因 |
|---|---|---|
| 文件登记 | **100%**（12,875/12,875） | |
| 内容解析 | ~12%（按字节）/ ~35%（按承载逻辑字节） | 1.4 GB 是 Chromium 框架资源 |
| 符号枚举 | ~85% | 协议/工具/crate/UI chunk 100%，原生函数 0% |
| 机制解释 | ~45% | 核心链路完整，MCP/Hooks/Guardian/Realtime 仅协议层 |
| 界面可视化 | ~15% | 仅登录页与彩蛋；登录后界面需要账号 |
| 端到端验证 | ~20% | CLI 全部实测；对话/工具/子代理未跑 |

**明确未做**：
1. `codex.exe`（341 MB，strip 过的 Rust）**未做函数级反编译**，REA/Ghidra 对该体量超时，只有字符串级证据。
2. **未使用个人已安装实例截图**——已安装版本包含真实邮箱、会话与项目名，这类截图被隔离在 `evidence/_quarantine_private/`，不进入本目录、不进入 Git。
3. 登录后界面、子代理面板、设置页等**无截图**。
4. 服务端（模型网关、Statsig 后台、Marketplace、Remote Control 配对）不可得，标为 U 级。
5. 74 个匿名 Statsig gate 只有 ID，用途未知（这是 Statsig 的设计目的）。

## 6. 建议下一位接手者优先做什么

1. 用**有额度的账号**跑通一次完整对话，抓 app-server 的 JSON-RPC 实测报文（对照 `indexes/rpc-methods.json`）。
2. 实测多 Agent：让主代理 `spawn_agent`，观察 `subAgentActivity` 通知与 mailbox 行为。
3. 用 `codex app-server` 起一个本地 server，接自写客户端，验证 Desktop 与 CLI 是否是同一后端。
4. 对 `codex-command-runner.exe`（仅 8 MB）做完整函数级反编译——它小到可以做完，且是沙箱安全的关键。

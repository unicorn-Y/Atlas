# 证据索引（EVIDENCE-INDEX）

所有结论的证据来源、等级与可复现方式。

---

## 一、原始材料

| ID | 文件 | 版本 | 大小 | SHA256 | 等级 |
|---|---|---|---|---|---|
| M1 | `ChatGPT-x64.msix` | 26.1013.4894.0 | 948,993,815 | `e2d892e6c22310e4b1a2928b0d3a29a066e0863d3a333754d6585c77cdafbe7f` | S |
| M2 | `openai-codex-cli-x64-dabdb4d16a.zip` | 0.163.0 | 167,080,091 | `dabdb4d16aaf10fea40b74811c96efddcd9138f122163b69ed604fcb3eb704c3` | S |
| M3 | `openai-codex-code-mode-host-x64-bc82fa6d8f.zip` | 0.163.0 | 28,217,604 | `bc82fa6d8f449c818292eac35bd7400c4f7dae08908fc9bc67bfbad8c4a3de68` | S |
| M4 | `openai-codex-source-36fda4e61c.zip` | rust-v0.163.0 | 22,647,697 | `36fda4e61c251d805c2d68203c3a34b0f6881a88846e12776ca02fb13d6e67c7` | S |

**版本核对（R）**
- `curl -s https://api.github.com/repos/openai/codex/releases/latest` → `rust-v0.163.0`（2026-10-15T21:30:38Z）
- `curl -s https://persistent.oaistatic.com/codex-app-prod/windows-store-update.json` → `buildVersion 26.1013.4894.0`
- 上游存在 `rust-v0.164.0-alpha.1~4`，均为预发布

## 二、解包产物

| ID | 路径 | 内容 | 等级 |
|---|---|---|---|
| E1 | `extracted/desktop-msix/` | 3,651 文件 / 2.35 GB | S |
| E2 | `extracted/desktop-asar/` | 21,073 条目 / 593.7 MB | S |
| E3 | `extracted/cli/` | 47 文件（含 codex.exe 341 MB、voice 组件） | S |
| E4 | `extracted/code-mode-host/` | 1 文件（74.9 MB） | S |
| E5 | `extracted/source/codex-rust-v0.163.0/` | 9,176 文件 / 5,276 .rs | S |

## 三、机器生成的协议与索引

| ID | 产物 | 生成方式 | 等级 |
|---|---|---|---|
| P1 | `decompiled/app-server-schema/`（5.3 MB） | `codex app-server generate-json-schema -o ... --experimental` | **S（官方二进制自生成）** |
| P2 | `indexes/rpc-methods.json` | 从 P1 的 ClientRequest/ServerNotification 提取 | S |
| P3 | `indexes/protocol-key-types.json` | 从 P1 的 v2 schema 提取 37 个关键类型 | S |
| P4 | `indexes/tool-definitions.json` | grep `core/src/tools/handlers/` 的 `name:` 字面量 | S |
| P5 | `indexes/crates.json` | `Cargo.toml` members + 逐 crate 统计 | S |
| P6 | `indexes/ui-chunks.json` | 扫描 `webview/assets/` 2,176 个 chunk | S |
| P7 | `indexes/statsig-gates.json` | grep `checkGate(` | S |
| P8 | `indexes/files.jsonl` | 12,875 个文件全量登记（含 SHA256） | S |
| P9 | `indexes/key-functions.json` | 10 个核心文件的 266 个符号 | S |

## 四、运行时证据

| ID | 命令 / 操作 | 产物 | 等级 |
|---|---|---|---|
| R1 | `codex-x86_64-pc-windows-msvc.exe --version` | `codex-cli 0.163.0` | R |
| R2 | `codex --help` 及 25 个子命令 `--help` | `evidence/cli-help/*.txt`（27 文件） | R |
| R3 | `codex features list` | `evidence/cli-features.txt`（175 条） | R |
| R4 | `codex doctor` | 完整环境诊断（含 CODEX_HOME 磁盘不足、rollout 缺失告警） | R |
| R5 | `codex debug models` | `decompiled/model-catalog.json`（11 模型 + 系统提示片段） | R |
| R6 | `codex app-server generate-json-schema` | P1 | R |
| R7 | 启动解包副本（全新 profile） | `screenshots/100_extracted_signin.png` | R |
| R8 | 点击 Play Snake | `screenshots/101_easter_egg_snake.png` | R |
| R9 | `Get-Process` 进程树 | ChatGPT / codex / code-mode-host 三层 | R |
| R10 | CDP `Emulation.setDeviceMetricsOverride` | 1400×900 / 1600×1000 稳定截图 | R |

## 五、二进制字符串证据

| ID | 文件 | 提取内容 | 等级 |
|---|---|---|---|
| B1 | `decompiled/strings-command-runner.txt` | 158 条：`spawn_request`/`spawn_ready`/`output`/`stdin`/`resize`/`exit`/`error`、`Local\CodexSandboxReadAcl`、`cap_sids`、`network_proxy_restricting_sid` | S |
| B2 | `decompiled/strings-code-mode-host.txt` | 426 条：`code_mode_host.grpc.{open_session,execute,wait,close_session}`、`ExecuteRequest` 字段、`HeapLimitExceeded` 等 | S |
| B3 | `decompiled/strings-cli-codex.txt` | 1,850 条协议关键词（Rust 符号已 strip） | S（但函数级缺失） |
| B4 | PE 节表 | codex.exe：`.text` 262,688,256 B / `.rdata` 65,897,984 B / `.pdata` 11,839,488 B | S |

## 六、源码证据（按主题）

| 主题 | 关键文件:行 |
|---|---|
| Turn 主循环 | `core/src/session/turn.rs:166`、`:454`、`:1372`、`:1507`、`:1666`、`:1707`、`:2618` |
| 工具注册 | `core/src/tools/registry.rs:59`、`router.rs:44-50`、`spec_plan.rs:628`、`:714`、`:730` |
| 工具定义 | `core/src/tools/handlers/*.rs`（28 处 `name:`） |
| 多 Agent | `core/src/tools/handlers/multi_agents_spec.rs:92,193,222,255,275,292,325,346,370`、`multi_agent_tool.rs` |
| 压缩 | `core/src/compact.rs:63`、`compact_token_budget.rs:24-60`、`config/src/config_toml.rs:180-191` |
| Code Mode | `code-mode-protocol/src/lib.rs`（exec/wait）、`session.rs:27`、`runtime.rs:15-17` |
| 沙箱策略 | `protocol/src/protocol.rs:1178-1204`（SandboxPolicy 四态） |
| 命令执行 | `exec-server/src/process_sandbox.rs:60-78` |
| 数据库 | `state/migrations/0001..0020*.sql`、`goals_migrations/`、`memory_migrations/`、`logs_migrations/` |
| 桌面 IPC | `.vite/build/preload.js`、`sandbox-preload.js`、`browser-page-preload.js` |

## 七、未查 / 未验证（与 UNKNOWNS 对应）

| 项 | 状态 | ID |
|---|---|---|
| codex.exe 函数级反编译 | 未做 | U1 |
| 74 个匿名 gate 含义 | 未知 | U2 |
| 服务端实现 | 不可得 | U3 |
| 对话/工具/子代理端到端 | 未验证 | U4 |
| 登录后界面截图 | 未做（隐私） | U5 |
| 完整函数枚举 | 部分 | U6 |
| MCP/Hooks/Guardian 细节 | 部分 | U7 |
| Chromium 框架层 | 未查 | U8 |
| 服务端最终提示 | 部分 | U9 |
| 版本漂移 | 风险 | U10 |

## 八、隐私处理声明

- 研究过程中曾启动过本机**已安装**的 Codex 实例用于确认界面可用性，产生了包含个人邮箱、会话标题、项目名的截图。
- 这些截图已全部移入 `D:\Atlas-Reverse-Lab\codex\evidence\_quarantine_private\`，**未进入**本目录、**未进入** viewer、**未进入** Git。
- 本目录内所有截图均来自**自建解包副本**的干净 profile。
- 未采集、未上传任何 Cookie、Token、聊天记录。

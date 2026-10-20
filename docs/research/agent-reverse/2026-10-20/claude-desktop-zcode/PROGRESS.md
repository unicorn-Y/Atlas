# PROGRESS — Claude Desktop 全量静态解剖

**分支**：`research/zcode-claude-desktop-anatomy-20261020`  
**报告目录**：`docs/research/agent-reverse/2026-10-20/claude-desktop-zcode/`  
**本地研究目录**：`D:\Atlas\_research\claude-desktop\2026-10-20\`  
**固定样本**：Claude Desktop Windows x64 enterprise **2.42304.0**  
**MSIX SHA256**：`2bf309665f0de4eaa76a7e64033594e6f73ceb6413c60080f72f3ce640fa24ee`  
**执行模式**：纯静态离线逆向（任务书 commit `3e2b27b9` 纠偏后）  
**总体状态**：**PARTIAL（静态可拆部分已到边界）**

| 未解项状态 | 数量 |
|---|---:|
| RESOLVED | 23 |
| PARTIAL（已解释主体，剩细节） | 8 |
| CLOUD-UNAVAILABLE（物理不可得） | 2 |
| DEFERRED（构建形态限制） | 1 |
| U（完全未知） | 1（macOS 版差异，无实物） |

---

## 阶段状态

| 阶段 | 状态 | 产出 |
|---|---|---|
| P0 包/版本/哈希/文件总账 | ✅ DONE | `P0-PACKAGE-AUTHENTICITY.md`、`VERSION-MATRIX.md`、8 份机器账 |
| P1 静态代码全覆盖 | ✅ DONE | `P1-STATIC-CODE-INVENTORY.md`、`MODULE-CLASSIFICATION.tsv`(506/506)、`SYMBOLS.tsv`(59,658) |
| **P1b 内置 SPA 修正** | ✅ DONE | `P1B-ION-DIST-CORRECTION.md`、`ION-MODULES.tsv`(3,588)、`ION-ROUTES.tsv`(716) |
| P2 前端/窗口/交互 | ✅ DONE | `P2-UI-AND-WINDOWS.md`、`UI-SURFACES.tsv`(26)、`MENUS.tsv`(99)、`HOTKEYS.tsv`(57) |
| P3 IPC/RPC/事件配对 | ✅ DONE | `P3-IPC-RPC-EVENTS.md`、`RPC-REGISTRY.tsv`(1,332/1,332)、`NETWORK-ENDPOINTS.tsv`(405) |
| P4 Chat/Cowork/Agent | ✅ DONE | `P4-AGENT-RUNTIME.md`、`FEATURE-FLAGS.tsv`(380) |
| P5 原生宿主/cowork-svc | ✅ DONE | `P5-NATIVE-SERVICE-VM.md`、`GO-FUNCTIONS.tsv`(23,018)、`GO-DEPENDENCIES.tsv` |
| P6 扩展/技能/worker/环境 | ✅ DONE | `P6-EXTENSIONS-TOOLS-SKILLS.md`、`ENV-VARS.tsv`(1,062)、`WORKERS.tsv`(8) |
| P7 静态生命周期/状态 | ✅ DONE | `P7-STATIC-LIFECYCLE.md`、`P7-STATIC-STATE-AND-EVENTS.md`、`UNRESOLVED-CALL-EDGES.tsv` |
| P8 目录/viewer/审计 | ✅ DONE | `00-START-HERE.md`、`01-LAYER-ATLAS.md`、`02-CAPABILITY-CATALOG.md`、`13-COVERAGE-AND-ACCEPTANCE.md`、`viewer/index.html`、`AUDIT-P8.json` |
| P7 旧版运行时取证 | ⛔ 降级 | 已移入 `out-of-scope/`，不计入完成率 |

---

## 关键数字（全部可复算）

| 指标 | 数值 |
|---|---:|
| MSIX 条目登记 | 4,443 / 4,443 |
| 哈希独立复验 | 4,443，0 不符 |
| ASAR 路径 / 文件 / 目录 | 548 / 506 / 42 |
| ASAR 文件分类 | 506 / 506 |
| 主进程 JS 解析 | 435 ok / 437（2 个 `.d.ts` 已解释） |
| 内置 SPA JS 解析 | 3,588 / 3,588，0 失败 |
| 内置 SPA 容量 | 4,224 文件 / 199,562,129 B（MSIX 条目 95%） |
| Go 函数 | 23,018（cowork-svc 15,181） |
| PE 二进制 | 18 |
| 技能内部文件 | 188 |
| eipc 服务 / 方法 / 事件 | 97 / 1,170 / 162 |
| RPC 配对 | 1,332 / 1,332（0 未配对） |
| 界面对象 | 26 |
| 菜单 / 快捷键 | 99 / 57 |
| 路由（外壳 / SPA） | 64 / 716 |
| Feature flags | 380 条 / 186 唯一键 |
| 环境变量 | 1,062 |
| 网络端点 | 405 |
| 未解项 | 24（3 RESOLVED / 14 PARTIAL / 2 CLOUD-UNAVAILABLE / 5 UNKNOWN） |

---

## 本轮重大发现（相对上一轮基线新增）

1. **`ion-dist` 199.5 MB 完整 Chat 前端**（此前被归为"资源"）。3,554 JS 全部解析，716 路由。
2. **部署模式二义**：`getMainWindowUrl()` 在 1P 返回 `claude.ai`、在 3P 返回 `app://localhost`；由 `deploymentMode` 键决定。推翻"UI 全在云上"的简化说法。
3. **3 个 WASM 身份**：`clarkdown_editor`（Rust 编辑器内核）、`tree-sitter`、`c2pa`（内容溯源签名）。
4. **VM 网络架构**：Hyper-V HCS + HVSocket + `gvisor-tap-vsock` + gVisor + 第一方 `win-httpproxy` + PAC + 宿主 CA 注入。
5. **EDR 接入**：`edrgate` / `edrpolicy` 包 + `handleRunEdrExtension`，对应 `coworkEDRIntegration` flag。
6. **7 路推理后端**：Anthropic / Bedrock / Vertex / Foundry / Gateway / Mantle / Anthropic-AWS-Google（均由环境变量切换）。
7. **1,062 个环境变量**，含 mTLS（`CLAUDE_CODE_CLIENT_CERT`）、子代理模型（`CLAUDE_CODE_SUBAGENT_MODEL`）、上下文上限覆盖。
8. **技能执行者错位**：Desktop 只打包并通过环境变量交给 CLI，不自己执行。

---

## 剩余明确可做项（未做，不隐藏）

| 项 | 状态 |
|---|---|
| `ion-dist` 3,588 文件的 React 组件树展开 | 未做（仅模块级索引） |
| `cowork-svc` 关键 handler 指令级反汇编（帧字节序、10 MiB 上限） | 未做 |
| 2.42304.0 MSIX vs 2.42304.2 nupkg 逐文件 diff | 未做 |
| `nodeHost` vs `directMcpHost` 逐行 diff | 未做 |
| 5 个代号服务的调用方追踪 | 未做 |
| 3P 模式完整 UI → RPC 映射 | 未做（SPA 已在包内，可静态完成） |

## 硬阻塞（物理不可得）

| ID | 阻塞 |
|---|---|
| B-01 | 服务端 agent loop 实现（`CLOUD-UNAVAILABLE`） |
| B-02 | 1P 模式远程 UI 组件代码（不在包内） |
| B-03 | Consumer（Squirrel）线最新版本（`region_unavailable`） |
| B-04 | macOS 版实物 |
| B-05 | Claude Code CLI 本体（由 `downloads.claude.ai` 分发，不在包内） |

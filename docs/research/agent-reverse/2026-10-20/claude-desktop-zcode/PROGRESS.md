# PROGRESS — Claude Desktop 全量解剖（ZCode 执行）

**分支**：`research/zcode-claude-desktop-anatomy-20261020`  
**报告目录**：`docs/research/agent-reverse/2026-10-20/claude-desktop-zcode/`  
**本地研究目录**：`D:\Atlas\_research\claude-desktop\2026-10-20\`  
**固定样本**：Claude Desktop Windows x64 enterprise **2.42304.0**，MSIX SHA256 `2bf309665f0de4eaa76a7e64033594e6f73ceb6413c60080f72f3ce640fa24ee`  
**总体状态**：IN-PROGRESS

---

## 阶段状态

| 阶段 | 状态 | 本轮实际产出 |
|---|---|---|
| P0 包/版本/哈希/文件总账 | ✅ DONE | `P0-PACKAGE-AUTHENTICITY.md`, `VERSION-MATRIX.md`, 8 份机器账 |
| P1 静态代码全覆盖 | ⬜ TODO | — |
| P2 前端/窗口/交互 | ⬜ TODO | — |
| P3 IPC/RPC/事件配对 | ⬜ TODO | — |
| P4 Chat/Cowork/Agent 运行机制 | ⬜ TODO | — |
| P5 Windows 原生宿主/cowork-svc | ⬜ TODO | — |
| P6 旁支/扩展/技能/flag | ⬜ TODO | — |
| P7 运行时取证 | ⏸ BLOCKED | 本机未安装 Claude Desktop（无 Appx/进程/服务） |
| P8 解剖目录/viewer/独立审计 | ⬜ TODO | — |

---

## P0 实际完成内容

1. 从原包重新计算（不继承旧结论）：
   - MSIX 297,191,037 B / SHA `2bf30966…fa24ee` → 与任务书基线完全一致；三份独立副本同哈希。
   - MSIX 内 `app.asar` 49,338,428 B / SHA `8f4d3dec…da9db`；`cowork-svc.exe` 13,761,360 B / SHA `934e5b67…663ba8f`。
   - zip 4,443 条目全部读取 + CRC 通过；解包后逐文件重算 SHA 与 SIZE，**mismatch=0**。
2. 独立解析 ASAR 头（electron asar pickle 格式），得 **548 路径 = 506 文件 + 42 目录**，每条含 offset/size/SHA256/unpacked 标记。
3. 与 2026-10-19 基线 4,443 行逐行 diff：**added 0 / removed 0 / changed 0**。
4. 嵌套容器：MSIX → asar → 6 个 `.skill`（ZIP）→ 188 个内部文件，全部哈希登记（`ARCHIVE-NESTING.tsv` 202 行）。
5. PE 18 个全部登记：架构 x64、PE32+、子系统、版本资源、Authenticode（全部 `Valid`，签名主体 `CN="Anthropic, PBC"`）。
6. Go 二进制识别：`cowork-svc.exe`、`claude-ssh-{broker,proxy,askpass}.exe` 均为 **Go 1.25.14**，含 `Go buildinf:`。
7. 发行通道实测：Squirrel `nest-win-x64/RELEASES` = 0.14.10（131,185,172 B，与本地 nupkg 一致）；`claude.ai` 两条下载端点均 `region_unavailable`。
8. AppxManifest 全部语义登记：3 个 Application 入口、`CoworkVMService`（localSystem/auto/ETW trigger）、11 个注册表虚拟化排除键、4 个文件系统排除目录、防火墙规则、能力声明。

## 下一轮待办（按序）

1. **P1**：入口链 `AppxManifest → claude.exe → package.json → .vite/build/index.pre.js → main chunks/preloads/workers → renderer HTML/chunks`；对 369 个 main chunk + 6 套 renderer 建立 `MODULES.tsv` / `SYMBOLS.tsv` / `CALL-EDGES.tsv` / `DYNAMIC-IMPORTS.tsv` / `UNRESOLVED-SYMBOLS.tsv`。
2. **P3**：重点补旧账缺口（旧 `ipc-map.tsv` 仅 8 行 vs 声称 1,535 条操作）。从 `contextBridge.exposeInMainWorld`、`ipcRenderer`、`ipcMain`、动态 channel builder、utilityProcess、MessagePort 全量枚举。
3. **P5**：`cowork-svc.exe` Go pclntab 全量函数表 + `\\.\pipe\cowork-vm-service` 帧协议 + Hyper-V 生命周期。
4. **P2**：6 套 renderer 的窗口/路由/动作；`UI-SURFACES.tsv` 等。
5. **P6**：6 个 `.skill` 内部（188 文件）语义；github-mcp / office365-mcp；`mcp-runtime`。
6. **P7**：需先安装 2.42304.0 MSIX 才能采集 R 级证据。

## 阻塞清单

| ID | 阻塞 | 具体条件 |
|---|---|---|
| B-01 | Consumer MSIX 最新版不可得 | `claude.ai/api/desktop/win32/x64/msix/latest/redirect` → 403 `region_unavailable`；`claude.ai/download` → 302 到 `app-unavailable-in-region` |
| B-02 | 无运行时证据 | 本机无 Appx 安装、无 `claude*` 进程、无 `CoworkVMService` |
| B-03 | macOS 平台 | 未取得实物，不做任何跨平台推断 |
| B-04 | 服务端实现 | 不可得，仅按客户端可观察协议分析，标 CLOUD-UNKNOWN |

## 已登记但需在后续阶段解释的数字差异

- 旧记录称“437 个 JS parse success”；本轮 ASAR 内实测 `.js` = 431，另有 `.mjs` 4、`.jsc` 3、`.ts` 2。两者口径不同，**不视为一致**，列入 P1 复核项。

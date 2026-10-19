# OpenCode v2.0.32 / v1.19.3 → Atlas 独立逆向研究

**状态：PARTIAL — 已验证并拆解精确 v2.0.32 Windows 桌面包与 CLI，完成多条前端→桌面 IPC→Agent/Browser/服务端的源码链；REA 完整 ASAR 分析超时，桌面与已认证 server API 动态链未完成。不得称为所有能力已穷尽。**

- 对照基线：Atlas `main@aa6196f550098cc46081dc6db2c376cb87ddffa5`；派工源 `research/agent-reverse-dispatch-20261019@51894bbcc3dfe1ea18a6e4be25483290cbc5a0e1`。
- 上游 v2 源码 tag：`v2.0.32@843a6c514e606b436a7fe713422ace0a93ad3d61`，归档 SHA256 `0c4dfbc2f94c15e0e94bc1b2b4a8524c3474f5fb6c682d6f96c505ca58a55554`。
- 上游 v1 源码 tag：`v1.19.3@60c9be092129745688bb3c3a752affc6cbd66ede`，归档 SHA256 `662ef890f51c49c364bc8e91ab04f25c8a3abf8833c86d42d9d0e5c31df34b0b`。
- 主要发现：v2 是包职责迁移与运行时重构，不应沿用 v1 `packages/opencode/src/session/*` 解释 v2。v2 由 `packages/core`（会话/执行/工具/Job/插件）、`packages/server`（HTTP/Event API）、`packages/cli`（命令/服务）、`packages/desktop`（Electron + 本地 CLI sidecar）、`packages/app`（Solid 前端、多服务器状态）、`packages/schema`/`protocol`/`session-ui`/`plugin` 等组成。
- 有严格源码链的高价值机制：持久化 Inbox + steer/queue；执行 claim + 启动恢复；background subagent job + 父会话通知；流式 provider/tool fiber + 不可中断事件结算；动态插件监督器；独立 CLI sidecar + Electron MessagePort RPC；前端事件连接同步与虚拟化时间线。
- **不建议把全部 v2 架构一次移植 Atlas**。应优先借用状态机与数据契约，融入 Atlas 当前 Hermes SessionDB、Python FastAPI、React/Electron，不做双数据库双主引擎。

## 研究入口
1. [DISCOVERY-LEDGER.md](DISCOVERY-LEDGER.md)：OPENCODE-001～019（证据类型和未知状态）。
2. [IMPLEMENTATION-TRACE.md](IMPLEMENTATION-TRACE.md)：入口→后端→存储→恢复的代码链。
3. [UI-AND-WORKFLOWS.md](UI-AND-WORKFLOWS.md)：界面交互、命令、跨端同步边界。
4. [ATLAS-GAP.md](ATLAS-GAP.md)：只对照当前 main 代码，不用旧矩阵。
5. [EVIDENCE-INDEX.md](EVIDENCE-INDEX.md)：准确快照与路径、未验证边界。
6. [EXTRACTION-REQUEST.md](EXTRACTION-REQUEST.md)：本地 Codex 只做机械抽取，上传证据后由本研究会话继续判读。
7. [REUSE-CANDIDATES.md](REUSE-CANDIDATES.md)：重用点、许可证、依赖/代价。

**已确认**仅意为“v2 标签源码存在此调用链（S）”，不意味着本会话运行过 Windows v2.0.32 安装包（R）。目录为实质性阶段成果，不是最终无遗漏审计。


新增高价值结论：OpenCode 桌面 GUI Extensions 是有类型的内置桌面扩展宿主，与 Agent 插件 hooks 分离；BrowserPlugin 将该桌面 pane 作为 Agent Browser 工具目标，按 session attach 临时授予 browser 权限，并经 RPC 事件/有界 TCP 隧道桥接 Chromium/CDP 能力。Atlas 已有 Playwright/X2 browser automation 与人工检查 pane；差异是缺少证据表明其把同一 session 的桌面浏览器以 attach lease、完整 Browser 工具 RPC 和 CDP tunnel 暴露给 Agent，而不是“Atlas 没有浏览器”。发行包索引见 [evidence-extracted/PACKAGE-ARTIFACTS.md](evidence-extracted/PACKAGE-ARTIFACTS.md)。

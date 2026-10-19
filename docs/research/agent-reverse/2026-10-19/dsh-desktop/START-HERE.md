# DSH 社区 Desktop 双项目逆向研究 — 入口

**状态：真实发布源码归档已独立下载、核 SHA/CRC、完整解包并静态拆解；研究报告已据实物补充。动态应用运行仍 NOT-RUN，故整体保持 PARTIAL，不能视为完整 runtime acceptance。**
**研究分支：research/agent-reverse-20261019-dsh-desktop**
**Atlas main 基线：aa6196f550098cc46081dc6db2c376cb87ddffa5**

## 两个独立研究对象

- A：anywhere-labs/dsh-desktop 固定提交 6a63b9730b82cf4e858b9a11ac9783da9a5a0c3a，Next 子产品版本 2.0.19-next；Electron + Node 独立 Host + 官方 DSH Cordis Web Profile。Legacy stable、beta、market 和 AA bridge 均在多包工作区，但不能与 Next 混为一谈。
- B：dongdong-agent/DSH-Desktop 固定提交 0aea85f01acd4583bb3fcebaa8c51586b08833a1，0.1.15；Tauri/Rust + React 管理壳启动或复用外部 dsh web，随后顶层导航，管理 React 页面被替换。
- O：官方 deepseek-ai/deepseek-harness 固定提交 687f282e8625c6b8d11ff58211a90524be2e4317，源码根版本 0.2.1-rc.2（另有 CLI npm 归档 0.2.0-rc.2，严禁混版）。
- 对照对象：Atlas 上述 main 固定 SHA 的实际后端、UI、WebSocket、delegation 与 Hub 代码。

## 关键结论

1. A 的实质社区能力是桌面宿主、Profile + Cordis 补丁、插件市场与 remote-control 装配、浏览器权限/HTTPS、进程 IPC、诊断、升级锁、Safe Mode/配置恢复。真正 DSH Agent loop 与 Session/子代理模型来自官方。
2. B 的实质社区能力是引擎发现/安装/版本、鉴权 Cookie、业务就绪门槛、Tauri 托盘与原生宿主；它不自研子代理会话树，导航后 TitleBar/StatusBar 等管理 React 组件已不常驻。
3. 官方 DSH ui-subagent 实有父子 Session address、递归子代理目录、tokenUsage 与 subagentTiming 投影、主窗口与右侧栏打开子会话、one-shot 只读/continuable 后续输入模型。官方 ui-trajectory 根据持久 Session 事件形成轨迹。这些不能统统计为社区新增。
4. Atlas 不是没有子代理：main 已有 delegate_task、delegate_parallel、subtask_message/steer、子任务取消、usage 事件、WS sequence replay 与 Hub。与官方 DSH 子代理体验最明显的未证等价处是具有父子地址的独立子会话树和侧栏 continuation，不是再堆一个空按钮。
5. A/B MIT 且官方 DSH MIT；复制代码须保留版权及 third-party notices。不能直接搬 vendor AA 远程服务或把 B 强杀外部引擎的实现照抄。

## 本轮证据与边界

已从 Atlas Release 取得两份任务书指定 ZIP：A 222,488,979 bytes / SHA-256 `03d18d13bb4a5bbfe79e3cd340d465d415a24f69968828c045efb5ea234b0a31`；B 5,400,611 bytes / SHA-256 `1dd3b7ded3646abf5245f46b76e214d33908ac563d1c796d1a9baf592a9f5dc6`。ZIP CRC、路径与重复名检查通过并完整解包；A 包内 DSH 0.2.1-rc.2 runtime 清单的 343 个 tarball SHA 全部匹配。本轮因此新增已发布包中官方 Agent Inbox durable queue 和 `session/updateQueue` 冷恢复/编辑删除 steer 的静态实物证据，以及 Atlas main renderer follow-up queue 的实际差异。**S=实物包中静态源码，D=仓库说明，I=推断，U=尚未核实；没有 R=运行证据。** 归档与符号证据见 `extracted/`；ZIP 与解包树仅在 worktree 外 scratch，没有提交 upstream payload。

## 报告入口

- DISCOVERY-LEDGER.md：A、B、官方分离的能力和证据状态。
- IMPLEMENTATION-TRACE.md：从 React/Electron 到 Host 和 Session 的完整核心调用链。
- UI-AND-WORKFLOWS.md：两套不同的导航、菜单、子代理 UI 归属。
- ATLAS-GAP.md：按 main 源码检索的已有能力、差距和待查项。
- EVIDENCE-INDEX.md：固定版本源码锚点、原资产 SHA、许可证、不可验证环节。
- REUSE-CANDIDATES.md：借用具体结构与依赖 / 许可证。
- EXTRACTION-REQUEST.md：本机 Codex 对两份原始归档的精确后续机械提取任务。

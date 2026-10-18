# DSH 社区 Desktop 双项目逆向研究 — 入口

**状态：静态源码研究已有实质结果；仍为 PARTIAL（归档 ZIP 本地二进制回读及动态运行未完成）。**
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

已经读取派工任务书、PROTOCOL、采集 manifest/index，且通过 GitHub 工具以固定 commit 读取两个项目主入口/宿主/调用/IPC/状态/恢复源文件、官方子代理真实 UI TSX 与 Atlas main 对照路径。**S=源码证据，D=仓库说明，I=推断，U=尚未核实；本轮没有 R=运行证据。** 两份 ZIP 虽已归档，因当前 GitHub 接口仅可提取文本，未在本会话独立下载原二进制、校验 SHA 或解包，故需按 EXTRACTION-REQUEST 补采；更不能假称实时实测。

## 报告入口

- DISCOVERY-LEDGER.md：A、B、官方分离的能力和证据状态。
- IMPLEMENTATION-TRACE.md：从 React/Electron 到 Host 和 Session 的完整核心调用链。
- UI-AND-WORKFLOWS.md：两套不同的导航、菜单、子代理 UI 归属。
- ATLAS-GAP.md：按 main 源码检索的已有能力、差距和待查项。
- EVIDENCE-INDEX.md：固定版本源码锚点、原资产 SHA、许可证、不可验证环节。
- REUSE-CANDIDATES.md：借用具体结构与依赖 / 许可证。
- EXTRACTION-REQUEST.md：本机 Codex 对两份原始归档的精确后续机械提取任务。
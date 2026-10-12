# D-TC-04 Browser DOM、标签与 Computer Use

分支：`card-d-tc-04`（基于任务开始时 `origin/memory-v1`）  
实施提交号：`1410aec20557fc1c949d5772d57d4af8a30deeba`（本卡结果记录另有后续提交）。  

## 条目结果

- **D029 Computer Use — 已实现低层授权与停止。** 新增 `computer_request_access`、`computer_stop`；用户可在活动 run 的 ComputerEdgeBar 查看请求并 Allow/Deny。批准会签发绑定 run 的 `grant_id`，电脑动作必须携带该 token；拒绝、5 分钟未处理、30 分钟到期或 Stop 会阻止/撤销授权。新增 run 级停止 API；Windows 输入路径会在注入动作前检查 stop latch。停止当前 SDK I/O 属 best-effort，若系统调用已进入不可中断阶段需等待返回；只有安装的 CUA driver 明确提供 stop/cancel handler 时才向其发停止请求。
- **D030 Browser 标签页/预览/导航 — 部分实现。** `browser.panel.sync` 现在由 BrowserPanel 消费，按 run/序号同步 URL 与标题；已有 tab Stop、handoff 确认与 workspace 文件预览路径继续复用，Browser runtime 增加 `tab.stop`。Atlas 尚无统一 pane owner/finalize registry，故不能实现与上游相同的 pane handoff 生命周期。
- **D031 Browser 文档/DOM 操作 — 部分实现。** BrowserUse 兼容层增加 locator `press`、单值 `selectOption` 和按顺序执行并报告部分进度的 `fill_form`（text/select/check）。当前 CLI adapter 不支持单次 locator 的多值 select；本轮按要求没有执行浏览器端到端动作验证。
- **D033 Browser console/network/trace/CPU/heap/Lighthouse — 未实现新增采集操作。** capability descriptor 明确将这些能力报告为不可用。当前 runtime 没有请求/响应采集器、Chromium trace 录制和 artifact 管线、CPU/heap profiler 管线，也没有 Lighthouse runner/依赖；只暴露现有 console/evaluation，不伪造性能数据。
- **D097 Browser Use runtime 选择 — 未实现 provider 切换/持久化。** Atlas 当前只有 Hermes/X2 一个 browser provider，没有可切换 provider registry 或持久化 selector。原 `runtime.select` no-op 现改为明确返回 unsupported，不再报告虚假成功。
- **D098 Browser tabs 生命周期与用户 tab claim — 未实现用户 tab claim。** 当前 tabs 来自 Hermes 当前 task/session 的受控 browser session。Electron/IAB 没有用户 tab 枚举接口、稳定 owner ID 或 claim token 来源，因此无法安全区分并 claim 用户拥有的 tab，也不能实现对应 finalize 语义。
- **D100 Browser DOM snapshot 与 locator — 部分实现。** 保留现有 snapshot/locator，并补 D031 所列操作；Atlas 当前 snapshot/ref 仍是 Hermes `@eN` evidence，并非上游完整 ARIA evidence，未声称证据格式等价。
- **D101 Browser frame/JS/wait — 部分实现，既有能力边界保留。** 现有 evaluate/wait/frame 路径继续通过 Hermes/CDP supervisor，受 Atlas evaluation policy 约束；跨进程 frame 路由要求活动 supervisor，fallback 只覆盖同页 iframe。此卡未替换 Hermes supervisor，因此不能声称在无 supervisor 时具备完整 frame/JS/wait 行为。
- **D104 Browser 截图与视口 — workspace artifact 已接通。** 有可信活动 workspace 时，截图写入 `artifacts/browser/<uuid>.png`（本地路径经 `_workspace_path` 校验；SSH 路径限定在 workspace 内），并发出 `browser.artifact` 事件。BrowserPanel 只接收活动 run、workspace 相符且路径格式匹配的事件，通过现有 workspace raw-file URL 显示截图。没有可信 workspace 时仍只返回原 cache path/data URL；已有 viewport 操作保持原状。
- **D112 Codex App Computer Use — 已实现 Atlas 可提供的授权生命周期和 Stop。** 与 D029 共用 run-scoped `computer_request_access`、Allow/Deny、grant 校验和 Stop UI/API；停止后锁住该 run 的后续电脑动作。Windows host 控制的是当前可见前台桌面，Atlas 不能承诺后台窗口控制；若底层 SDK 不支持取消，UI 显示停止已锁存/等待系统调用返回，而不声称已强制中断。

## 上游与移植边界

- OpenCode Browser RPC 参考 commit `7b3d4ce3a7dbd2a6d3637722a0d5f22a7d086937` 的 `packages/plugin-browser/src/rpc.ts`；实际移植边界见 `core/atlas/tools/browser_use_compat.py` 文件头。其 MIT notice 已追加到 `THIRD_PARTY_NOTICES.md`。
- ZCode Browser Use contract 核对固定 commit `aac4755666d09fdcd70272fcf063c077a639015f` 的 `apps/zcode-cli/packages/browser-use-plugin/docs/overview.md`。ZCode Computer Use 源码也在同一 commit 定向核对：`packages/zcode-cua` 自述为 unavailable placeholder、fail-closed package；`apps/zcode-cli/packages/zcode-cua-plugin/scripts/computer-use-client.mjs` 列出 `request_access` 与 `stop_computer_control` 的模型面，但实际桌面驱动由 host 提供。因此本卡没有复制其 placeholder 或第三方 driver 代码。
- Codex / Claude Computer Use 行为参考任务卡所列官方文档。Atlas 将显式用户授权绑定当前 run 并提供可见 Stop；Windows 仍控制当前前台桌面，平台驱动未提供的后台/强制中断能力明确保留为 host 限制。

## 验收范围

- 未新增或运行测试套件。
- `npm --prefix frontend run build`：通过。工作树初始无依赖；从根锁文件恢复依赖后构建完成。
- 后端启动：当前 Hermes Python 环境缺少 `tomli_w`，首次启动在 import 阶段失败。将 `tomli-w>=1.0.0` 安装到系统临时目录并通过临时 `PYTHONPATH` 提供后，以 `ATLAS_UPSTREAM_AUTO=0` 在 `core` 启动 `python -m uvicorn atlas.server:app --port 28790`；`/api/health` 返回 `status: ok`，组件均 ready，随后已关闭服务。
- 启动同时输出 Hermes isolated-runtime dependency preparation 日志，指向机器级 Hermes home；没有审计其在该外部 runtime 中的文件变化。
- 未进行真实浏览器 session DOM 操作、Computer Use 桌面动作或真实 CUA driver 中断验收；此卡结果标注为代码接入状态，不把未运行的交互路径写成运行验收。


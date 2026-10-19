# 证据索引与证据限制

## 实际归档核验与新增队列证据

指定 A/B 归档已在本地独立 SHA/size 核验并完整 ZIP CRC 检查；证据表、ZIP tree、代码摘要、符号索引和许可清单位于 `extracted/`。重点官方 DSH runtime 包及 SHA/内部路径/line anchors 见 `extracted/A-runtime-symbol-index.md`：`dsh-agent-loop@0.2.1-rc.2`、`dsh-api-session-controller@0.2.1-rc.2`、`dsh-session-persistence-jsonl@0.2.1-rc.2` 和 `dsh-client-ui-chat@0.2.1-rc.2`。A `2.0.19-next` ZIP 内完整 343 包 runtime 清单均 SHA 匹配。资产字节只证明包身份，不能代替 R=运行观察；`extracted/RUNTIME-OBSERVATIONS.md` 明确 NOT-RUN。

## 固定资产身份

| 来源 | 真实 git /版本 | 压缩包 SHA-256（采集 manifest 宣告，非本会话独立计算） |
|---|---|---|
| A anywhere-labs/dsh-desktop | 6a63b9730b82cf4e858b9a11ac9783da9a5a0c3a / Next 2.0.19-next | 03d18d13bb4a5bbfe79e3cd340d465d415a24f69968828c045efb5ea234b0a31；222488979 bytes |
| B dongdong-agent/DSH-Desktop | 0aea85f01acd4583bb3fcebaa8c51586b08833a1 / 0.1.15 | 1dd3b7ded3646abf5245f46b76e214d33908ac563d1c796d1a9baf592a9f5dc6；5400611 bytes |
| O deepseek-ai/deepseek-harness | 687f282e8625c6b8d11ff58211a90524be2e4317 / source root 0.2.1-rc.2 | source zip dcc4cf8df9c3cbb3d57726b7a1ad5a52c16a754dcdbc2c0a0836788976090d9f |
| Official CLI independently captured | npm 0.2.0-rc.2, Web UI npm 0.0.1-rc.5 | CLI bd27847c445cd68a565ac1f91c06bbbcc7639ef93071f678bb59c5ebaff38859；Web frontend ccadad6dcbb6f9a3c7a57802c3c2bb5958c2104ca33e9fb88135634b6d7b1516 |
| Atlas comparison | main aa6196f550098cc46081dc6db2c376cb87ddffa5 | git SHA, not artifact digest |

A 归档：https://github.com/unicorn-Y/Atlas/releases/download/agent-client-packages-20261019/dsh-desktop-anywhere-labs-03d18d13bb.zip  
B 归档：https://github.com/unicorn-Y/Atlas/releases/download/agent-client-packages-20261019/dsh-desktop-dongdong-agent-1dd3b7ded3.zip  
Manifest：https://github.com/unicorn-Y/Atlas/blob/research/agent-reverse-dispatch-20261019/docs/research/agent-clients/2026-10-19/manifest.json

## S：已真正按 pinned ref 读取的精确代码入口

**A Next**：
- [package/version](https://github.com/anywhere-labs/dsh-desktop/blob/6a63b9730b82cf4e858b9a11ac9783da9a5a0c3a/dsh-desktop-next/package.json)
- [Node Host runProfile](https://github.com/anywhere-labs/dsh-desktop/blob/6a63b9730b82cf4e858b9a11ac9783da9a5a0c3a/dsh-desktop-next/src/host/index.ts#L28-L138)
- [child spawn/IPC](https://github.com/anywhere-labs/dsh-desktop/blob/6a63b9730b82cf4e858b9a11ac9783da9a5a0c3a/dsh-desktop-next/src/host-process.ts#L228-L319)；[update tasks and shutdown](https://github.com/anywhere-labs/dsh-desktop/blob/6a63b9730b82cf4e858b9a11ac9783da9a5a0c3a/dsh-desktop-next/src/host-process.ts#L395-L466)
- [BackendController](https://github.com/anywhere-labs/dsh-desktop/blob/6a63b9730b82cf4e858b9a11ac9783da9a5a0c3a/dsh-desktop-next/src/backend-controller.ts)
- [Profile conditions and loadNextProfile](https://github.com/anywhere-labs/dsh-desktop/blob/6a63b9730b82cf4e858b9a11ac9783da9a5a0c3a/dsh-desktop-next/src/profiles.ts)
- [Cordis plugin injection](https://github.com/anywhere-labs/dsh-desktop/blob/6a63b9730b82cf4e858b9a11ac9783da9a5a0c3a/dsh-desktop-next/cordis.patch.yml)；[WebServer replacement](https://github.com/anywhere-labs/dsh-desktop/blob/6a63b9730b82cf4e858b9a11ac9783da9a5a0c3a/dsh-desktop-next/host.cordis.patch.yml)
- [HTTP/WS policy](https://github.com/anywhere-labs/dsh-desktop/blob/6a63b9730b82cf4e858b9a11ac9783da9a5a0c3a/dsh-desktop-next/src/webserver.ts)
- [Client Slot UI](https://github.com/anywhere-labs/dsh-desktop/blob/6a63b9730b82cf4e858b9a11ac9783da9a5a0c3a/dsh-desktop-next/src/client/index.ts)；[IPC](https://github.com/anywhere-labs/dsh-desktop/blob/6a63b9730b82cf4e858b9a11ac9783da9a5a0c3a/dsh-desktop-next/src/ipc.ts)；[commands](https://github.com/anywhere-labs/dsh-desktop/blob/6a63b9730b82cf4e858b9a11ac9783da9a5a0c3a/dsh-desktop-next/src/desktop-contract.ts)
- [Recovery](https://github.com/anywhere-labs/dsh-desktop/blob/6a63b9730b82cf4e858b9a11ac9783da9a5a0c3a/dsh-desktop-next/src/recovery.ts)；[MIT](https://github.com/anywhere-labs/dsh-desktop/blob/6a63b9730b82cf4e858b9a11ac9783da9a5a0c3a/LICENSE)

**B**：
- [React App lifecycle/navigation](https://github.com/dongdong-agent/DSH-Desktop/blob/0aea85f01acd4583bb3fcebaa8c51586b08833a1/src/App.tsx#L140-L320)
- [engine discovery/probes/spawn/restart](https://github.com/dongdong-agent/DSH-Desktop/blob/0aea85f01acd4583bb3fcebaa8c51586b08833a1/src/lib/dshEngine.ts)
- [engineAuth HMAC cookie](https://github.com/dongdong-agent/DSH-Desktop/blob/0aea85f01acd4583bb3fcebaa8c51586b08833a1/src/lib/engineAuth.ts)；[patch](https://github.com/dongdong-agent/DSH-Desktop/blob/0aea85f01acd4583bb3fcebaa8c51586b08833a1/src/lib/enginePatch.ts)；[updater](https://github.com/dongdong-agent/DSH-Desktop/blob/0aea85f01acd4583bb3fcebaa8c51586b08833a1/src/lib/updater.ts)
- [Rust navigation/session probe](https://github.com/dongdong-agent/DSH-Desktop/blob/0aea85f01acd4583bb3fcebaa8c51586b08833a1/src-tauri/src/lib.rs#L158-L293)；[Tray](https://github.com/dongdong-agent/DSH-Desktop/blob/0aea85f01acd4583bb3fcebaa8c51586b08833a1/src-tauri/src/lib.rs#L295-L465)
- [Tauri capabilities](https://github.com/dongdong-agent/DSH-Desktop/blob/0aea85f01acd4583bb3fcebaa8c51586b08833a1/src-tauri/capabilities/default.json)；[store](https://github.com/dongdong-agent/DSH-Desktop/blob/0aea85f01acd4583bb3fcebaa8c51586b08833a1/src/stores/engineStore.ts)；[MIT](https://github.com/dongdong-agent/DSH-Desktop/blob/0aea85f01acd4583bb3fcebaa8c51586b08833a1/LICENSE)

**官方 O**：
- [subagent UI Slot and navigation](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/client/ui-subagent/src/client/index.ts)
- [child catalog/token/duration](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/client/ui-subagent/src/client/SubagentHeaderLineage.tsx)
- [Sidebar Chat SessionReference](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/client/ui-subagent/src/client/sidebar-chat/index.tsx)
- [TrajectoryView](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/client/ui-trajectory/src/client/TrajectoryView.tsx)
- [License](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/LICENSE)

**Atlas main**：
- [delegation](https://github.com/unicorn-Y/Atlas/blob/aa6196f550098cc46081dc6db2c376cb87ddffa5/core/atlas/agent/tool_node.py#L604-L720)
- [WebSocket control](https://github.com/unicorn-Y/Atlas/blob/aa6196f550098cc46081dc6db2c376cb87ddffa5/core/atlas/api/runtime_ws_router.py)
- [ConversationActivity](https://github.com/unicorn-Y/Atlas/blob/aa6196f550098cc46081dc6db2c376cb87ddffa5/frontend/src/renderer/components/ConversationActivity.tsx)；[ForkTree](https://github.com/unicorn-Y/Atlas/blob/aa6196f550098cc46081dc6db2c376cb87ddffa5/frontend/src/renderer/components/ForkTree.tsx)
- [Runtime events/cache](https://github.com/unicorn-Y/Atlas/blob/aa6196f550098cc46081dc6db2c376cb87ddffa5/frontend/src/renderer/services/runtimeEvents.ts)；[store](https://github.com/unicorn-Y/Atlas/blob/aa6196f550098cc46081dc6db2c376cb87ddffa5/frontend/src/renderer/store/useAtlasStore.ts)
- [backend process](https://github.com/unicorn-Y/Atlas/blob/aa6196f550098cc46081dc6db2c376cb87ddffa5/frontend/src/main/backendProcess.ts)；[Hub](https://github.com/unicorn-Y/Atlas/blob/aa6196f550098cc46081dc6db2c376cb87ddffa5/core/atlas/runtime/hub.py)

## 证据缺口（显式 U）

已对指定 ZIP 实际 hash/unzip，并抽取 A runtime manifest 343 个 tarball hash；但没有启动 Electron GUI，也未抓 WS frame/真实 Session UI；Node host 有限生命周期已观察，Agent/UI 仍 **R=0**。未将所有历史 stable/beta profile 的每包 tarball 内容全部反编译，也未追官方 Agent Host 所有 prompt/interrupt 权限边。A 中具体 edit/remove/steer 图标到 RPC 的控件调用点未定位。Atlas 子代理 persistent mapping 的全仓完整性仍有 U。详见 `RUNTIME-OBSERVATIONS.md` 及 `EXTRACTION-REQUEST.md` 状态追记。

**This continuation's runtime and UI evidence:** A Next `package.json:209` pins `@deepseek-ai/dsh-web-frontend@0.2.1-rc.2`; its embedded tarball SHA-256 is `c797fa5fce3375c78b2afe7458864bb5b23814eef80013e510ad9a1f8bfbfbda`. The exact frontend contained 61 JS assets (4,798,411 bytes). `updateQueue` appears 55 times in only `index-CN7NIWNw.js` (921,071 bytes; SHA-256 `4bc914bfbb6addd63953a29f63835eb7127defd2a973149d64cdab489f1a9a5`), in React internal update queue code; DSH queue action names/RPC are absent. Build/host/Electron outcomes and limits are recorded in `extracted/RUNTIME-OBSERVATIONS.md`.
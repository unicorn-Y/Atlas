# Implementation trace：分层调用链和未证实边界

> **实物静态增量（S，2026-10-19）**：固定 MSIX SHA/size、包身份、ASAR 主 bundle/preload、`CoworkArtifactBridge`、IPC 统计与 cowork-svc Go/Hyper-V 字符串已核验。它们没有闭合 cloud agent、完整 IPC、状态恢复或 app→service 连接链。细节见 `evidence/README.md`、`evidence/entrypoints.md` 与结构化索引。

## A. Claude 当前产品级链路（**D，官方资料**，非本 MSIX 源码）
```
用户输入（Chat / 旧版 Cowork selector）
  -> 官方声明：判别快速回复或可执行任务（逐步 rollout 的 Unified）
  -> 普通聊天 / cloud Cowork session（账号级 session）
  -> 云 sandbox（独立任务环境；官方声称 agent loop + code execution）
  -> 工具调用
       ├─ 云端 connector（server side token handling）
       ├─ web/浏览器工具（客户端内置浏览器、Chrome 或云端依据能力选择）
       └─ 需要本机访问 -> Anthropic-brokered Desktop bridge
              -> Desktop 设备在线 / 权限检查
              -> 本机 file / app / local MCP 执行
              -> 返回任务结果
  -> 云持久化会话/文件/工件 -> Desktop/Web/Mobile 统一呈现
```
证据：<https://support.claude.com/en/articles/14479288-claude-cowork-architecture-overview>；<https://support.claude.com/en/articles/17444462-set-up-and-manage-the-new-unified-claude-experience-for-your-enterprise-organization>。**推断限制：未见 service RPC 或客户端 JS，不能据文档命名真实协议字段。**

Enterprise unified beta 官方更明确描述：会话转换时启用隔离 cloud VM；空闲停 VM、保存加密磁盘快照；生命周期并非“Desktop 子进程永远存活”。Cloud Cowork 与“旧本地 Cowork”并存，不可混写。

## B. Claude 旧本地链路（**D**）
```
Desktop 本地 Cowork 会话
  -> 本机 agent loop（本地文件/MCP/web fetch）
  -> shell / code -> Hyper-V 管理的隔离 Linux VM
  -> 会话数据与工具状态（存储格式未知）
```
官方仅确认旧部署的结构；`cowork-svc.exe` 是否承担主循环、生命周期管理或只是边车需要反编包内代码。**不能把本地 service 的存在直接等价为当前 cloud agent 运行在本机。**

## C. Atlas main 的真实可追踪路径（**S：本库源码**）
```
frontend/src/renderer/App.tsx
  -> useAtlasStore.ts:startRun (975+)
  -> backend-adapter/src/client.ts:startRun/WS connect (553+)
      onopen: run.start / resume(after_sequence)
      onmessage: agent_event; sequence cursor -> localStorage
      onclose: 退避重连 -> resume
  -> core/atlas/api/runtime_ws_router.py:/ws/chat (18+)
      start / resume / cancel / pause / approval / steer / subtask.message
  -> core/atlas/api/run_drive.py:_handle_resume (2040+)
      当前进程 run.events 内存队列重放
     _execute_run (2132+) -> agent run -> envelope
  -> core/atlas/api/runtime.py:RuntimeManager
      runtime_runs SQLite (run_id, conversation_id, model, status, sequence,
      recovery_event, plan_state)
  -> Hermes SessionDB (engine/session_sync.py) 持久 transcript
  -> frontend/src/renderer/services/runtimeEvents.ts
      解码已知事件; MAX_RUN_EVENTS=800
```
**关键非等价点：** `runtime.py:108-156` 将服务重启时 running/paused/waiting 的 run 标记 failed，文字明确“execution was not resumed”；`run_drive.py:2040-2067` 的重放只遍历 `run.events`，该列表未见完整 SQLite event ledger 持久化；`run_drive.py:1420-1428` 虽有 `resume_from` 保存计划入口，但只有在显式传入且计划存在时继续，不是透明恢复原 tool 执行现场。`backend-adapter/src/client.ts:553-615` 的 WS 断开重连只在**原服务仍保留事件和正在运行**时保证延续。

## D. Atlas 进程与后台执行（**S**）
- `frontend/src/main/electron.ts:205-242` 初始化后台 `ensureBackendRunning`，退出进程 `before-quit -> stopManagedBackend`；`frontend/src/main/backendProcess.ts:303-391` 先探测、附着外部服务，否则 spawn 自管后端。即默认 Desktop 自管后端与窗口生命周期耦合。
- **不是“Atlas 无后台运行”**：`core/atlas/runtime/hub.py:119-176` 有独立 Hub scheduler + agent callback，`core/atlas/runtime/hub_control.py:83-134` 有 start/stop/list_task/run_task；`core/atlas/api/run_drive.py:219+` 也有 durable-first scheduler。是否满足“同一个交互式 run 离线持续 + 接管”另需检查 Hub 与主 runtime 的身份、共享事件和隔离。
- 客户端已存在 `ConversationActivity.tsx:132-188` 子任务停止/补充要求；`runtime_ws_router.py:84+` 有 subtask.message；不可笼统标“没有子任务”。

## E. 仍待从 Claude 包证明的核心链路
1. `app.asar` Electron main / preload / renderer 的实际路径、所有 window webContents、IPC register/invoke/send 与校验。
2. `cowork-svc.exe` 启动命令、父子进程、IPC/RPC transport、HTTP/gRPC/WebSocket/stdio pipe、重启/backoff/关闭语义。
3. Chat 与 Cowork 共享或分离的 session schema，云 session→本机设备→前端 task card 的关联 key。
4. 任务事件的增量流协议、client cursor、错误类别、服务重启/网络断开/客户端退出恢复方式。
5. Cloud VM 与 local VM 的 capability negotiation / eligibility / feature flags；是否存在本地 DB、SQLite、LevelDB、IndexedDB。
6. Tools、MCP extension、browser、Computer Use 的权限协议及失败重试分类。
7. 从后台服务的所有 command/tool registrations 反推界面隐藏入口和不可见能力。

在采集前上述都维持 U，不填写猜测性的模块名、事件名或 storage schema。
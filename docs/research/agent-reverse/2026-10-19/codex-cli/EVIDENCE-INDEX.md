# EVIDENCE INDEX — 可复核证据、来源分级与盲区

## 版本与归档清单

派工原始清单：`unicorn-Y/Atlas@research/agent-reverse-dispatch-20261019:docs/research/agent-clients/2026-10-19/manifest.json`；目录树证据：`indexes/claude-codex-index.txt`（仅机械采集，不是功能验证）。

| 组件 | Archive asset | manifest SHA256 | 大小 |
|---|---|---|---:|
| Windows CLI | `openai-codex-cli-x64-dabdb4d16a.zip` | `dabdb4d16aaf10fea40b74811c96efddcd9138f122163b69ed604fcb3eb704c3` | 167080091 |
| Code Mode Host | `openai-codex-code-mode-host-x64-bc82fa6d8f.zip` | `bc82fa6d8f449c818292eac35bd7400c4f7dae08908fc9bc67bfbad8c4a3de68` | 28217604 |
| Rust fixed snapshot | `openai-codex-source-36fda4e61c.zip` | `36fda4e61c251d805c2d68203c3a34b0f6881a88846e12776ca02fb13d6e67c7` | 22647697 |

Download URLs（GitHub Release，需有相应仓库访问权限）：
- https://github.com/unicorn-Y/Atlas/releases/download/agent-client-packages-20261019/openai-codex-cli-x64-dabdb4d16a.zip
- https://github.com/unicorn-Y/Atlas/releases/download/agent-client-packages-20261019/openai-codex-code-mode-host-x64-bc82fa6d8f.zip
- https://github.com/unicorn-Y/Atlas/releases/download/agent-client-packages-20261019/openai-codex-source-36fda4e61c.zip

tag `rust-v0.163.0` 的 annotated git tag object `129b8ec7ee6f4511557a4856279f529025c25af4`，target commit `83086188ae0614bd882818ff1aa23f3194962012`，由 GitHub tag API 返回： https://api.github.com/repos/openai/codex/git/tags/129b8ec7ee6f4511557a4856279f529025c25af4

上游源码： https://github.com/openai/codex/tree/83086188ae0614bd882818ff1aa23f3194962012/codex-rs
许可证（上游根 LICENSE）： Apache License 2.0。局部第三方文件仍需查看其自己的 NOTICE/许可。
Atlas main 检查 SHA：`aa6196f550098cc46081dc6db2c376cb87ddffa5`； https://github.com/unicorn-Y/Atlas/tree/aa6196f550098cc46081dc6db2c376cb87ddffa5

## 源文件直接取证索引（全部固定版本，S）

下表路径均加前缀 `codex-rs/`。每行在固定 tag 源码中直接拉取了文件内容；部分为精确行段，部分按函数/类型签名索引抽查。

| 模块 | 文件位置与符号 | 关键 IDs |
|---|---|---|
| Turn loop | `core/src/session/turn.rs:166 run_turn; 1707 run_sampling_request; 1666 build_prompt` | 001,017,018 |
| Tool dispatch | `core/src/tools/router.rs:246,257,313,336`; `parallel.rs:46,78,126,385` | 002,025 |
| Approval/runtime | `core/src/tools/orchestrator.rs:1-180 ToolOrchestrator`; `registry.rs:55,305,417,458` | 003,004 |
| Host process | `core/src/code_mode_host.rs:23-154 ProcessOwnedGrpcCodeModeSessionProvider / HostConnection` | 006 |
| Model→JS cell | `core/src/tools/code_mode/execute_handler.rs:39-174` | 005,009 |
| Callback broker | `core/src/tools/code_mode/delegate.rs:36-240` | 008 |
| Host entry | `code-mode-host/src/main.rs:15-58`; `code-mode-host/src/lib.rs:45-198` | 007,010 |
| gRPC requests | `code-mode-host/src/grpc/mod.rs:45-289` | 007—010 |
| Host state | `code-mode-host/src/grpc/session.rs:39-207,210-430` | 007,008 |
| JS runtime | `code-mode-runtime/src/runtime/module_loader.rs:8-89`; `code-mode-runtime/src/service.rs:65-198` | 009 |
| Multi-agent tree | `core/src/agent/control.rs:75-250`; `agent/control/runtime.rs:37-184` | 011,013,016 |
| Spawn/fork/resume | `core/src/agent/control/spawn.rs:81-159,676-1014,1015-1460` | 011,014 |
| Subagent LRU | `core/src/agent/control/residency.rs:23-331` | 012 |
| Mailbox | `core/src/agent/control/mailbox.rs:15-112` | 013 |
| Child completion | `core/src/agent/control/completion.rs:25-156` | 016 |
| MA V2 tools | `core/src/tools/handlers/multi_agents_v2/spawn.rs:18-271; send_message.rs:9-58; wait.rs:12-221` | 015 |
| Context snapshots | `core/src/context_manager/history.rs:93-129`; `session/world_state.rs:43-414` | 017 |
| Background compact | `core/src/session/async_compaction.rs:1-203` | 018 |
| Tool discovery | `core/src/tools/handlers/tool_search.rs:38-350` | 019 |
| Thread history | `core/src/thread_manager.rs:184-250`; `session/session.rs:950-967` | 020 |
| Recovery | `core/src/session/daemon_recovery.rs:1-57`; `session/turn_input.rs:90-230,328-689` | 021,022 |
| TUI | `tui/src/slash_command.rs:12-321`; `tui/src/multi_agents.rs:1-189,287-460`; `tui/src/session_queue_commands.rs:1-130` | 023,024 |
| App-server typed RPC | `app-server-protocol/src/protocol/common.rs:128-139,208-287`; `app-server/src/message_processor.rs:966-1067`; `request_serialization.rs:24-108,160-306`; `turn_admission.rs:1-83` | 026,034 |

## Atlas main 实证文件

已直接读取文件正文及类型/方法：
`core/atlas/agent/__init__.py:310-~1059`、`agent/run_phases.py:146-~924`、`agent/planning.py:11-88`、`agent/tool_node.py:58-~489`、`agent/checkpoints.py:24-208`、`agent/subagent_worktree.py:237-344`、
`engine/hermes_runtime.py:162-1571`、`engine/session_sync.py:517-618`、`engine/steer_dispatch.py:36-120`、`engine/tool_registry.py:290-~558`、
`runtime/backends.py:17-187`、`runtime/external_process.py:17-154`、`runtime/external_agents.py:21-98`、`api/runtime.py:17-212`、`models/router.py:114-~340`、`tools/mcp_client.py:171-~568`、`tools/node_runtime.py:19-119`。均使用 `main` pinned SHA；完整比较见 ATLAS-GAP。

## 无法确认、具体需要什么

- **受限 R 证据**：只启动 CLI `--version`、CLI `--help` 和 Host `--help`。没有登录后 turn、TUI 交互、代码单元、RPC/gRPC transport、重连/故障恢复、实时语音或外部调用权限观察。
- **固定包 SHA 已独立复核**：三份原始归档均匹配 manifest，记录见 `extractions/ARCHIVE-HASHES.json`；EXE 发布字节与 source tag 的可重复构建关系仍未知。
- **运行功能可用性**：不少源码功能依配置、feature flag、平台、认证、服务端协议开关；本轮只是 S，绝不冒称 Windows CLI 0.163.0 全部默认开放。
- **代码路径 vs 服务端**：本轮没有接入 OpenAI 服务端，也不解读远程模型调度/服务端内部。OpenAI 后台实现为 U。
- **未穷尽**：CLI commands 各分支、TUI 子界面所有行为、App-server JSON-RPC 事件全谱、voice/realtime/guardian/message-board/graph-store 全面闭环、Source ZIP/EXE 编译一致性，以及性能数值对照。

后续无需重复搜索旧文档；以这些原始证据文件继续补链路即可。

## 新增固定 tag 实证文件（028—033）

- 028: `codex-rs/agent-graph-store/src/store.rs:13-61`; `codex-rs/agent-graph-store/src/local.rs:10-112`; `codex-rs/core/src/agent/control/spawn_guard.rs:80-99`. AgentGraphStore + SQLite local impl; child edge status, BFS descendants; cancelled spawn closes edge. (S; no runtime verification.)
- 029: `codex-rs/core/src/agent_message_board.rs:38-121`. Requires MultiAgentV2 and AgentMessageBoard feature flags or explicit connection; remote board supports token. (S; no runtime verification.)
- 030: `codex-rs/core/src/agent/control/spawn_guard.rs:1-105`. Drop removes child runtime and persistence, waits for Open edge write, then writes Closed. (S; no runtime verification.)
- 031: `codex-rs/app-server/src/daemon_thread_recovery.rs:1-51`. snapshot uses dedicated OS thread; start_recovery reads+removes snapshot, spawns restore_daemon_threads without blocking readiness. (S; no runtime verification.)
- 032: `codex-rs/core/src/session/mcp_refresh.rs:1-57`. AtomicBool pending + Semaphore gate; unpublished cancelled refresh guard re-invalidates. (S; no runtime verification.)
- 033: `codex-rs/core/src/session/retained_context.rs:145-205`. persistence lock aligns retained context with checkpoint suffix; TaskTracker waits for cell-generated message recording. (S; no runtime verification.)

- Codex main x64 CLI EXE SHA-256: `2692c8c7bb2cf8b0aefe638741fc90236f4b824c59578ce84994f9de58200993`, 341,270,320 bytes, PE32+ AMD64; COFF timestamp 2026-10-15T19:43:40Z. Main CLI `--version` and CLI/Host `--help` are bounded R observations only; exact stdout is preserved in `extractions/`.
- Package component linkage: CLI ZIP root `codex-code-mode-host.exe` and standalone Host ZIP contain identical SHA-256 `07f3869f0849cd54b31cec1f86ec796f004501bd3a215135c1facc883a2b9988`; bundled `codex-command-runner.exe` copies share SHA `fc89dc66c806f25675b9be1e7dafb226807d22761e9741a3bb24b667b803d46c`. Voice manifest build commit equals pinned tag target. These are exact packaged byte/metadata links, not reproducible-build proof.
- Code Mode Host help enumerates stdio, grpc+stdio, grpc://IP:PORT and OTEL listener/exporter options. This proves accepted CLI syntax in help output, not a successful transport session.
- App-server static sources: `app-server-protocol/src/protocol/common.rs:128-139,208-287`; `app-server/src/message_processor.rs:966-1067`; `app-server/src/request_serialization.rs:24-108,160-306`; `app-server/src/turn_admission.rs:1-83`; daemon client `app-server-daemon/src/client.rs:63-92`.
- Voice static sources: `realtime-webrtc/src/client.rs:130-245`; `protocol.rs:1-120`; `session.rs:140-175,274-326`; `voice-host/src/main.rs:43-180`; TUI `tui/src/chatwidget/realtime.rs:301-395`; app-server route `app-server/src/request_processors/turn_processor.rs:1212-1306`. Audio media and service-side semantics not dynamically observed.
- Atlas voice comparison at exact main SHA: `frontend/src/renderer/App.tsx:350-355,1108-1115`; `frontend/src/renderer/components/VoiceOverlay.tsx:63-190`. Browser SpeechRecognition feeds regular `store.sendMessage`; browser SpeechSynthesis speaks streamed text; microphone stream is used for visualization. This is an existing browser voice path, not Codex's native full-duplex WebRTC helper architecture.

## G0–G7 continuation evidence

- `COVERAGE.md`: scoped executable crate inventory (file counts and bytes) and explicit uncovered modules/registration surfaces; counts do not imply semantic coverage.
- `SURFACE-MAP.tsv`: CLI/TUI/action-to-JSON-RPC/Host protocol-to-handler/state/event chain. Unknown or not dynamically observed endpoints are labeled.
- `END-TO-END-TRACES.md` R1: actual package app-server over stdio JSON-RPC; isolated home/workspace, successful initialize/thread/start, turn admission plus user-message streaming/persistence; no assistant/model/tool completion.
- `END-TO-END-TRACES.md` R2: actual release Host framed stdio session/open, V8 cell execute, synthetic tool callback and returned output. This uses legacy transport and is not Core gRPC transport verification.
- `ATLAS-IMPLEMENTATION-BACKLOG.md`: read-only comparison at Atlas main SHA `990d0ccdeed9604b027e74ef152cb0004c4d9375` with candidate implementation paths and unresolved traces.
- `FINISH-GATES.md`: G0 package identity PASS only; G1–G6 remain PARTIAL and G7 unmet.

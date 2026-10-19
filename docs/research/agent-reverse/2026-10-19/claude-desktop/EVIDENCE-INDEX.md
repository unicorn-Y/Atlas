# Evidence index / 确认等级 / coverage

## 2026-10-19 shipped-package checkpoint

- `evidence/README.md`: exact hashes, identity, analyzer counts, service observations, integrity mismatch and boundaries.
- `evidence/msix-tree.tsv`, `identity.json`, `asar-tree.txt`: verified MSIX extraction/index and manifest identity.
- `evidence/entrypoints.md`, `ipc-map.tsv`, `ui-route-action.tsv`, `runtime-map.tsv`, `event-schema.tsv`, `summary-counts.tsv`: partial structured package map; unresolved joins are explicitly blank/U.
- `evidence/svc-identity.json`, `svc-imports.txt`, `svc-symbols.tsv`: PE/Go/service static metadata; strings are not reachability proof.
- `evidence/trace-snippets/renderer-ipc.md`: short, hash-bound locations, no full vendor bundle.
- Static only: no app/service launch, no R evidence. Declared/observed node-pty hash mismatch and `%40ant` extraction path issue unresolved.

## 原始包与索引
- `research/agent-reverse-dispatch-20261019:tasks/research/agent-reverse/2026-10-19/sessions/claude-desktop.md`、`PROTOCOL.md`。
- `research/agent-reverse-dispatch-20261019:docs/research/agent-clients/2026-10-19/manifest.json` 记录 `Claude Desktop | Windows desktop package | 2.42304.0 | x64`。
- Release: <https://github.com/unicorn-Y/Atlas/releases/download/agent-client-packages-20261019/claude-desktop-x64-2bf309665f.msix>
- 上游 URL: <https://downloads.claude.ai/releases/win32/x64/2.42304.0/Claude-e7f60e658f15cfece9efa384a78a39aec3c12845.msix>
- Hash: `2bf309665f0de4eaa76a7e64033594e6f73ceb6413c60080f72f3ce640fa24ee`；Length: `297191037`；格式 `MSIX`；归档目录索引记录 `4443` 个提取条目（采集方记录，不代表本会话解包已核验）。
- `docs/research/agent-clients/2026-10-19/indexes/claude-codex-index.txt` 包含原采集电脑本地路径 `metadata/claude-desktop-x64-tree.txt`，**该本地树文件没有作为可读 GitHub 文件提供**。
- `docs/research/agent-clients/2026-10-19/DOWNLOAD-LOG.md` 记录 consumer Setup/MSIX 403 `region_unavailable`，消费版与 Enterprise 一致性未知。
- 包内 `app/resources/app.asar`、`cowork-svc.exe` 的名称来自任务书；**未在可下载文本中检验这两个文件的实际 hash、导入、字节内容或完整路径**。

## Anthropic 官方行为证据（D，不是包源码 S）
- 2026-09-16 Chat/Cowork Unified: <https://claude.com/blog/cowork-is-now-claude> → ID 001, 010, 011, 020。
- Cloud vs Local、2026-10-06 历史本地会话边界、设备桥、local MCP: <https://support.claude.com/en/articles/14479288-claude-cowork-architecture-overview> → 002–005, 013。
- Unified Enterprise VM idle snapshot/expiry: <https://support.claude.com/en/articles/17444462-set-up-and-manage-the-new-unified-claude-experience-for-your-enterprise-organization> → 006。
- Built-in browser: <https://claude.com/blog/cowork-built-in-browser> → 007。
- Computer use fallback: <https://support.claude.com/en/articles/14128542-let-claude-use-your-computer-in-cowork> → 008, 012。
- Scheduled UI: <https://support.claude.com/en/articles/13854387-schedule-recurring-tasks-in-claude-cowork> → 009。
- Cross-surface matrix: <https://support.claude.com/en/articles/15520349-use-claude-cowork-on-web-desktop-and-mobile> → 003, 010。
- Projects: <https://support.claude.com/en/articles/14116274-organize-your-tasks-with-projects-in-claude-cowork> → 021。
- Subtask/parallel public docs: <https://support.claude.com/en/articles/13345190-get-started-with-claude-cowork> → 022。

## Atlas main 源码检视清单（S）
Pinned HEAD: `aa6196f550098cc46081dc6db2c376cb87ddffa5`。
- `https://github.com/unicorn-Y/Atlas/blob/aa6196f550098cc46081dc6db2c376cb87ddffa5/frontend/src/main/electron.ts#L205-L242` 启动/退出进程。
- `https://github.com/unicorn-Y/Atlas/blob/aa6196f550098cc46081dc6db2c376cb87ddffa5/frontend/src/main/backendProcess.ts#L303-L395` external backend attach vs spawn。
- `https://github.com/unicorn-Y/Atlas/blob/aa6196f550098cc46081dc6db2c376cb87ddffa5/frontend/src/preload/index.cts#L1-L30` Electron Desktop IPC 面。
- `https://github.com/unicorn-Y/Atlas/blob/aa6196f550098cc46081dc6db2c376cb87ddffa5/frontend/src/shared/ipc.ts#L1-L46` preload 类型。
- `https://github.com/unicorn-Y/Atlas/blob/aa6196f550098cc46081dc6db2c376cb87ddffa5/backend-adapter/src/client.ts#L553-L615` runtime WS、cursor/reconnect。
- `https://github.com/unicorn-Y/Atlas/blob/aa6196f550098cc46081dc6db2c376cb87ddffa5/core/atlas/api/runtime_ws_router.py#L18-L157` WS server controls。
- `https://github.com/unicorn-Y/Atlas/blob/aa6196f550098cc46081dc6db2c376cb87ddffa5/core/atlas/api/runtime.py#L98-L212` runtime_runs metadata/restart/replay。
- `https://github.com/unicorn-Y/Atlas/blob/aa6196f550098cc46081dc6db2c376cb87ddffa5/core/atlas/api/run_drive.py#L1420-L1428` resume_from 条件。
- `https://github.com/unicorn-Y/Atlas/blob/aa6196f550098cc46081dc6db2c376cb87ddffa5/core/atlas/api/run_drive.py#L2040-L2067` in-memory event replay。
- `https://github.com/unicorn-Y/Atlas/blob/aa6196f550098cc46081dc6db2c376cb87ddffa5/core/atlas/api/run_drive.py#L2132-L2186` execute+emit。
- `https://github.com/unicorn-Y/Atlas/blob/aa6196f550098cc46081dc6db2c376cb87ddffa5/core/atlas/engine/session_sync.py#L1-L90` Hermes transcript。
- `https://github.com/unicorn-Y/Atlas/blob/aa6196f550098cc46081dc6db2c376cb87ddffa5/core/atlas/api/conversations_router.py#L64-L150` list/messages/branches。
- `https://github.com/unicorn-Y/Atlas/blob/aa6196f550098cc46081dc6db2c376cb87ddffa5/frontend/src/renderer/store/useAtlasStore.ts#L975-L1037` start request/control wiring。
- `https://github.com/unicorn-Y/Atlas/blob/aa6196f550098cc46081dc6db2c376cb87ddffa5/frontend/src/renderer/services/runtimeEvents.ts#L1-L94` event normalize + 800 event cap。
- `https://github.com/unicorn-Y/Atlas/blob/aa6196f550098cc46081dc6db2c376cb87ddffa5/frontend/src/renderer/components/ConversationActivity.tsx#L132-L188` subtask card interaction。
- `https://github.com/unicorn-Y/Atlas/blob/aa6196f550098cc46081dc6db2c376cb87ddffa5/core/atlas/runtime/hub.py#L119-L176` independent hub agent scheduler。
- `https://github.com/unicorn-Y/Atlas/blob/aa6196f550098cc46081dc6db2c376cb87ddffa5/core/atlas/runtime/hub_control.py#L83-L134` hub control。
- `https://github.com/unicorn-Y/Atlas/blob/aa6196f550098cc46081dc6db2c376cb87ddffa5/frontend/src/renderer/App.tsx#L1017-L1033` separate views。

## 本次未检查 / 原因
- Claude MSIX 内文件哈希、`app.asar`、asar.unpacked、源码地图、`cowork-svc.exe` 和它关联的 dll：**二进制仅作为 297 MB Release asset，当前 GitHub connector 不支持二进制返回，执行环境无法外连该官方 CDN**。
- consumer Setup：采集日志显示 403，尚无字节。
- Claude 实际 UI / 动态 WS / 本地文件权限 / 云 sandbox 实际行为：本会话无 Windows 实测会话/账号，未声称 R。
- 云端服务端私有代码：未取得，官方仅给公开体系说明。
- Atlas 工程全域自动审计：只抽查本次需求相关文件及实际链路，不将未审查路径等同功能缺失。

验收数字：本包 S 0 / R 0；官方公开 D 条目 15+；Atlas S 18 文件/链路锚点（有限覆盖）。下一步根据 `EXTRACTION-REQUEST.md` 取得代码片段后更新。
- vidence/module-traces.md: exact bundle hashes/offsets and bounded static traces for DXT/MCPB trust, Node host, PTY logging, file indexing, cloud/local branch, migration telemetry, Computer Use preview; all source-only.

- `evidence/module-traces.md`: includes the closed artifact scheduled-task IPC/handler chain and per-tool policy/approval path; still static-only.

# 证据索引与验证边界

## 固定材料
| 项 | 文件/大小/ SHA256 |
|---|---|
| Windows Desktop v2 | `opencode-desktop-v2.0.32-c6beba4a54.exe`; 236735200 B; `c6beba4a54ce5daf2c7cc4017aee61c4af2bfb89b377a3a3f059917d263aea2e` |
| CLI v2 wrapper | `opencode-cli-npm-wrapper-2.0.32-3395134eec.tgz`; 2958 B; `3395134eec1cf24f91e8d2c660843a851e933794172a13c2507d9a9805ed5760` |
| CLI v2 windows | `opencode-cli-npm-windows-x64-2.0.32-bbc00de2c5.tgz`; 100022170 B; `bbc00de2c5cdbb6c11649e7c6e2c094e8b55d16d4bfab41577d3cdbe5d36c90d` |
| 源码 v2 | `opencode-source-v2.0.32-0c4dfbc2f9.zip`; 84041220 B; `0c4dfbc2f94c15e0e94bc1b2b4a8524c3474f5fb6c682d6f96c505ca58a55554`; commit `843a6c514e606b436a7fe713422ace0a93ad3d61` |
| Desktop v1 | `opencode-desktop-v1.19.3-eb2554ab54.exe`; 126269464 B; `eb2554ab5484886db78fd861008a2a2db985bfa3dc3720ce7d1cda027ce99174` |
| CLI v1 | `opencode-cli-release-v1.19.3-e4ce9117f5.zip`; 62204138 B; `e4ce9117f55fc068414513789f8c7d1049f855d7518bb4e350b9170a3a20d8c3` |
| 源码 v1 | `opencode-source-v1.19.3-662ef890f5.zip`; 77886321 B; `662ef890f51c49c364bc8e91ab04f25c8a3abf8833c86d42d9d0e5c31df34b0b`; commit `60c9be092129745688bb3c3a752affc6cbd66ede` |

档案：[Manifest](https://github.com/unicorn-Y/Atlas/blob/research/agent-reverse-dispatch-20261019/docs/research/agent-clients/2026-10-19/manifest.json)、[包索引](https://github.com/unicorn-Y/Atlas/blob/research/agent-reverse-dispatch-20261019/docs/research/agent-clients/2026-10-19/indexes/opencode-zcode-index.md)、[Release](https://github.com/unicorn-Y/Atlas/releases/tag/agent-client-packages-20261019)。本轮仅通过 GitHub 读取标签源码/Atlas 私库，未真正下载 EXE/TGZ 或启动程序；“快照 SHA256”是采集 manifest 的哈希而不是本研究会话重新计算。

## v2 标签实际读取（S）
- `packages/core/src/session/{execution.ts,execution/restart.ts,run-coordinator.ts,inbox.ts,session.ts,store.ts,sql.ts,projector.ts,context.ts,compaction.ts,subagent-job.ts,subagent-completion.ts,usage.ts,revert.ts}`
- `packages/core/src/session/runner/{llm.ts,step.ts,retry.ts,index.ts,to-llm-message.ts}`
- `packages/core/src/tool/{runtime.ts,plugin/subagent.ts}`, `packages/core/src/codemode/tool.ts`
- `packages/core/src/config/plugin/source.ts`, `packages/core/src/plugin/{module.ts,supervisor.ts,host.ts}`, `packages/plugin/src/effect/*`（目录结构核对）
- `packages/server/src/{event-feed.ts,handlers/session.ts,handlers/message.ts,handlers/pty.ts,handlers/plugin.ts}`, `packages/protocol/src/groups/session.ts`
- `packages/desktop/src/{main/desktop.ts,main/ipc-transport.ts,main/service/background-service.ts,main/service/desktop-cli.ts,renderer/desktop-app.tsx}`
- `packages/app/src/{runtime/server/client.tsx,runtime/server/server-sync/connection.ts,session/composer/queue.ts,session/requests/session-question-dock.tsx,session/timeline/message-timeline.tsx,session/timeline/virtualizer.tsx,session/commands/use-session-commands.tsx,servers/registry/add-menu.tsx}`。
- v1 通过固定 tag 的完整文件树确认旧 session 源路径；**未完成逐行语义 diff**。v2 根 `LICENSE` 是 MIT，详情见 REUSE。
- Atlas：`core/atlas/{agent/run_phases.py,agent/tool_node.py,engine/hermes_runtime.py,engine/session_sync.py,engine/local_runtime_adapter.py,tools/mcp_client.py,engine/tool_registry.py,agent/checkpoints.py}`; `frontend/src/{main/backendProcess.ts,renderer/store/useAtlasStore.ts,renderer/services/runtimeEvents.ts,renderer/components/Composer.tsx,renderer/shell/panels/TerminalPanel.tsx}`。

## 关键源码直接浏览
- [v2 Execution](https://github.com/anomalyco/opencode/blob/v2.0.32/packages/core/src/session/execution.ts#L65-L160)
- [v2 Restart](https://github.com/anomalyco/opencode/blob/v2.0.32/packages/core/src/session/execution/restart.ts#L17-L225)
- [v2 Subagent](https://github.com/anomalyco/opencode/blob/v2.0.32/packages/core/src/tool/plugin/subagent.ts#L110-L260)
- [v2 Plug-ins](https://github.com/anomalyco/opencode/blob/v2.0.32/packages/core/src/plugin/supervisor.ts#L150-L245)
- [Atlas Queue](https://github.com/unicorn-Y/Atlas/blob/aa6196f550098cc46081dc6db2c376cb87ddffa5/frontend/src/renderer/store/useAtlasStore.ts#L670-L726)
- [Atlas Runtime](https://github.com/unicorn-Y/Atlas/blob/aa6196f550098cc46081dc6db2c376cb87ddffa5/core/atlas/agent/run_phases.py#L1-L170)

## 仍未调查的区域
二进制可执行包中的实际资源与完整 entrypoint；v1/v2 细粒度迁移 commit 归因；全量 TUI/GUI 菜单与 shortcut registry；多平台 PTY/SSH 实操；真实长会话崩溃恢复、缓存命中率、跨服务器同步和插件运行验证；特定 Windows installer 是否内置完整一致的 CLI；用户权限下实际运行行为。以上皆 U，不能假扮 S/R。

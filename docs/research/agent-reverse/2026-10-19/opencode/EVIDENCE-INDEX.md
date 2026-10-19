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

档案：[Manifest](https://github.com/unicorn-Y/Atlas/blob/research/agent-reverse-dispatch-20261019/docs/research/agent-clients/2026-10-19/manifest.json)、[包索引](https://github.com/unicorn-Y/Atlas/blob/research/agent-reverse-dispatch-20261019/docs/research/agent-clients/2026-10-19/indexes/opencode-zcode-index.md)、[Release](https://github.com/unicorn-Y/Atlas/releases/tag/agent-client-packages-20261019)。本 lane 后续已在 `evidence-extracted/PACKAGE-ARTIFACTS.md` 核对本地原始 bytes/SHA，并在 `END-TO-END-TRACES.md` 记录 UI 与合成 API R 结果。

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


## 发行物 / browser 扩展补证

精确 asset bytes/SHA、解包根、ASAR package metadata、bundle SHA/byte anchors、CLI run scope、v1→v2 tree count 与 integrity mismatch 均见 [evidence-extracted/PACKAGE-ARTIFACTS.md](evidence-extracted/PACKAGE-ARTIFACTS.md)。关键 Browser 源码 anchors：v2.0.32 packages/plugin-browser/src/connection.ts:24-53,76-155,203-225；tools.ts:11-58；rpc.ts:404-494；tunnel.ts:9-125；packages/gui-extensions/src/browser/{main.ts,ipc.ts,model.ts,pane.ts,chromium.ts}。GUI extension host/renderer anchors：packages/gui-extensions/src/main.ts:1-33 与 builtins.typecheck.ts；packages/desktop/src/main/extension/host.ts:105-108,599-710；packages/desktop/src/main/ipc-handlers/extensions.ts:39-60；packages/desktop/src/renderer/extensions.ts:10-64。

REA ASAR analyzer: first run halted on app.asar.unpacked OpenConsole.exe integrity mismatch; second run with record-and-continue timed out after 300 seconds. Observed manifest SHA256 7f68c840226505004215c0b82d4e502c24b5bc3f4b93c4baaaa19bd679c0def8 vs extracted SHA256 c2216ab94daaa4f6e6da636da7296487fe8629c29d564fa4893fe1a0ea17d2fa. Cause unknown. REA Electron capture subsequently observed visible `OpenCode` window at `oc://renderer/index.html` (Electron 44.4.5) but returned `hook_conflict`, no IPC events, and cleanup uncertainty; captured PIDs were checked and absent after capture. The local API synthetic session/inbox and persistence across CLI server restart and synthetic model/tool/subagent run are recorded in `END-TO-END-TRACES.md`. No Browser attach, CDP tool call, hosted-model run, or active execution recovery is marked R.

## G1 segmented REA syntax analysis (shipped extracted JS)

Analysis provider: REA `analyze_javascript_application` with `format=directory`, summary retention, one directory per batch. `out/main` evidence `ev_baeb6128d36bc6d81291a2120d170bca31c0acbe01f6379d1ae9e846d52df0ee`, artifact tree SHA256 `c0cc2962f3e6ee58e980511e0ed6c823f4d0349e043b7e407b2d040a9f15c799`: parsed JavaScript files 645, parse failures 0, text 2,677,049 B, AST nodes 566,679, findings 2,340; semantic output partial/truncated, 846 limitations. `out/renderer` evidence `ev_3aa76e8883bf73c9503175b9bfad4413099228b733969bfd4419b6b4e047c12e`, artifact tree SHA256 `3db2b5467e055fd5e4c7f4492cf42374a27293aafb2ef5105686a71cf7e8d7c8`: parsed JavaScript files 1,648, parse failures 0, text 36,535,169 B, AST nodes 2,942,342, findings 7,136; semantic output partial/truncated, 2,974 limitations. Both evidence IDs refer to extracted artifact directories, not authored source.

## G4 synthetic execution log (no private data)

`END-TO-END-TRACES.md` records synthetic session IDs and outcomes. Test environment was isolated under `D:\temp\opencode-g4`; all server/model connections stayed loopback; the mock's four-call metadata log was `provider-subagent-requests.jsonl` during execution and records only request number, HTTP method, path, model, and byte count. The process and port were closed after capture. No provider request/response body, credential, or user session is retained in this repository. The deterministic provider helper is [evidence-extracted/runtime/mock-openai-provider.ps1](evidence-extracted/runtime/mock-openai-provider.ps1).

Actionable one-file renderer bundle batch: analysis evidence `ev_a9f0d9f9b8a616244f250d8e0b85c71b01045e1f3ce40d9117017ff8c56f4f92` (retained parent `ev_c5b6d3c899a7839be38d473d14ca6cd23eb251ba8d0e4a68a352c15e4e58bb3d`), copied bundle SHA256 `f18077265e25625819bcc88aba89b30a7097fa9c89fd5628b9ecf9a559912654` (same selected shipped renderer bundle bytes); 1/1 JavaScript parsed, 363,244 AST nodes, 1,202 findings, zero parse failures; semantic relations were empty/partial under the analyzer resource profile. Batch copy path `D:\temp\opencode-g4\batch-renderer-main`; original shipped bundle identity and SHA are in `evidence-extracted/PACKAGE-ARTIFACTS.md`.

Additional actionable module batches:
- Desktop main `desktop-CiR2Cmvk.js`: 1/1 JavaScript parsed, 53,488 AST nodes, 23 findings, zero parse failures; REA extracted 1 BrowserWindow and 2 explicit webPreferences objects. Analysis evidence `ev_1925f347e65786036810504f81d9a189b85651e6fe1d1269579e1198940c9d49`; retained parent `ev_0547a17c29d7d37517c55492712eafcb9624f93512e6adc8049785a193983a1e`; subset tree SHA256 `1f44d1a197c8ad9b64d5ef5b509b62b41b5780807e4ffa46fec6d6f9d2d8e80d`.
- Browser host `host-R1JTLSvD.js`: 1/1 parsed, 15,208 AST nodes, 738 findings, zero parse failures; partial relations include 431 call-flow, 6,497 data-flow, 669 object-flow, 125 promise-ownership. Evidence `ev_23cfd1a4dcbf653df016e452143b6f0161a466966780f5dc80dcdf1f170cb561`; retained parent `ev_f32d858ceb71d469177daea404ccb3962d0533662954f4427fa715f0d3e19a6c`; subset tree SHA256 `4e4a84a1a751f4bdfd714bdb34411be146eb4f3617a616bf0be0a2a5ec694a7b`.

Actionable desktop main bundle batch `desktop-CiR2Cmvk.js`: evidence `ev_1925f347e65786036810504f81d9a189b85651e6fe1d1269579e1198940c9d49`, retained parent `ev_0547a17c29d7d37517c55492712eafcb9624f93512e6adc8049785a193983a1e`, copied batch tree SHA256 `1f44d1a197c8ad9b64d5ef5b509b62b41b5780807e4ffa46fec6d6f9d2d8e80d`; 1/1 parsed, 53,488 AST nodes, 23 findings, zero parse failures; Electron extraction noted 1 BrowserWindow and 2 explicit webPreferences objects, but relationship semantics remain partial/empty.

Browser host bundle batch `host-R1JTLSvD.js`: evidence `ev_23cfd1a4dcbf653df016e452143b6f0161a466966780f5dc80dcdf1f170cb561`, retained parent `ev_f32d858ceb71d469177daea404ccb3962d0533662954f4427fa715f0d3e19a6c`, copied batch tree SHA256 `4e4a84a1a751f4bdfd714bdb34411be146eb4f3617a616bf0be0a2a5ec694a7b`; 1/1 parsed, 15,208 AST nodes, 738 findings, zero parse failures; partial semantic relations include 431 call-flow, 6,497 data-flow, 669 object-flow, and 125 promise-ownership, with extensive unresolved edges. The summary is partial and does not prove runtime reachability.

# W4：工具、扩展、Computer Use、浏览器与网络搜索审查

## 审查边界与结论

- 基线为 `ui-redesign@0b1ba4114e25643369c95bfac85d37563788444f`，在 `D:\atlas-luna-w4-20261017` detached worktree 中只读检查。主仓 `D:\Atlas` 的 dirty/untracked 内容未修改。
- 逐链核对 AtlasKernel 当前调用主路：模型 schema 组装 `core/atlas/kernel/loop.py:1010-1040` → 统一调度/并行分类 `core/atlas/kernel/tools.py:325-493` → hook/权限审批/dispatch `core/atlas/kernel/loop.py:525-635` → `_dispatch` backend（从 `:1666` 起）。另核对 agent 的工具 schema/dispatch 分支 `core/atlas/agent/tool_catalog.py:30-45,132-153`、`core/atlas/agent/tool_node.py:1214-1277`；两者不是替代 kernel 主路的唯一依据。
- 代码存在、schema 注册、dispatch/backend 链均按源码证据记录；没有调用任何工具，没有启动服务/浏览器/MCP/SSH/Android，不进行 CDP、CUA/UIA/SendInput 或真实设备输入，不跑 tests/build。以下可达性仅为静态可达，不等于本机配置下成功运行。
- 修正初稿：Android 并非缺失。基线有 Android Emulator 与 UI Automator 的 schema、kernel 注册、mutating approval 和 `adb input` backend，因此撤销“无 Android 工具”缺口。没有发现需要新增的 P0/P1 工具安全缺陷；仅保留可由源码直接证明的 SSH workspace LSP 诊断缺失。

## 当前基线调用链与关键核验

### Kernel 调度、批量审批、结果/错误和并行

- `kernel_tool_schemas()` 为 kernel 工具添加 schema：`core/atlas/kernel/tools.py:41-80,167-180,197-222`；主 loop 合并 agent 与 kernel schema，并受 `tool_allowed` allow/deny 限制：`core/atlas/kernel/loop.py:1010-1031`。
- 每个 tool call 先跑 `PreToolUse`/`PermissionRequest`；拒绝、审批缺失及审批取消均返回明确 denied 错误，批准后才调用 `_dispatch`：`core/atlas/kernel/loop.py:525-630`。因此批次中各调用分别进入此回调，不存在只对首个 call 审批的源码证据。
- 并行只让允许的 read-only call 入队；computer/browser、terminal/process/stdin 与文件写入固定串行；`local_file` 只并行 read/list/glob/search/stat：`core/atlas/kernel/tools.py:337-349`。每个 call 都经过 `tool_allowed`，异常和取消转成 `ToolExecutionResult`/`ToolReceipt`：`:351-400`；并行任务取消后收敛逐项结果，且为所有 model-issued call 生成终态 receipt：`:405-492`。
- 外层 stream 转发与停止会处理活动工具 task 并读取 scheduler receipt：`core/atlas/kernel/loop.py:1496-1535`。静态看审批、错误/结果保留、batch cancellation 没有可确认漏洞；没有用实际并行批次实测。

### shell 子进程、stdin、文件路径及 worktree 隔离

- local subprocess 使用 stdin/stdout/stderr pipes 并保留可选 stdin：`core/atlas/tools/local_execution.py:1114-1122,1146-1161`；stdin 写入通过 process 工具路径：`:1394-1416`；run cancel/shutdown 针对所属非 detached 进程：`:1418-1437,1474-1490`。Kernel 把 `write_stdin` 串行处理：`core/atlas/kernel/tools.py:337-344`，再由 `core/atlas/kernel/loop.py:2247-2271` 解析到 local process manager。没有实际启动/取消子进程。
- worktree create/remove 要求可用的 conversation scoped service，拒绝 SSH 与 read-only/plan mode；创建前审批，限制到预期目录并检查 symlink；删除限于登记目录、经审批且 clean-only/保留 branch：`core/atlas/tools/workspace_workflows.py:587-639,640-663`。未实际创建/删除 worktree。
- Kernel 串行化可能副作用工具；本轮静态检查未确认路径越界或 worktree 隔离失效。对于完整文件路径策略，仍以 `engine/tool_registry.py` 的 `local_file`/native handler 路由与 `agent/tool_node.py:87-92,211-247` 路径守卫作为分别存在的代码，不将单文件检查表述为实测隔离保证。

### Computer Use、Browser/CDP、MCP、Skills、Plugins、LSP

- Computer Use schema 由 `core/atlas/tools/x2/computer.py:608-625` 对 legacy 名称注册到共享 handler；runtime 的 request-access/stop、run-bound grant 检查在 `core/atlas/tools/computer_use.py:48-64,379-408`。另一个 X2 computer adapter 在 `core/atlas/tools/x2/computer.py:340-360` 有单独 permission_mode gate；未确认两 adapter 的所有运行配置绑定关系，不能合并描述成已实测的单一路径。
- Browser schemas/action map 和 runtime dispatch 位于 `core/atlas/tools/x2/browser.py:386-420,558-580`；AtlasKernel审批回调位于 `kernel/loop.py:525-630`。兼容层明确支持 locator press/select、fill_form、tab.stop，同时明确不支持 tab claim、deliverable、WebM、network/trace/CPU：`core/atlas/tools/browser_use_compat.py:124-158,360-393,450-455,630-650`。Browser pane UI 的权限/自动预览验收未覆盖。
- MCP tool schema 与实际工具索引由 `core/atlas/tools/mcp_client.py:442-448` 产生；调用含未连接、协议错误、timeout 的返回分支位于 `:450-515`，agent tool node 对 MCP write 读取 `read_only` 并调用 backend：`core/atlas/agent/tool_node.py:293-295,346,1274-1277`。kernel MCP resources schema `kernel/tools.py:64-77`。本基线没有发现 OAuth router/provider 接线（见分支比较中的 f2-c 候选）；未连接或调用 MCP server。
- Skills/commands 与 plugins 的模型 callable 不等于目录完整：`agent/tool_catalog.py:132-153` 有 `use_skill`/`skill_search` schema，`agent/tool_node.py:1220-1235` dispatch；Marketplace list/install schemas 在 `kernel/tools.py:170-176`，安装经审批并调用 PluginRuntime：`kernel/loop.py:1936-1988`。未加载插件/激活 skill。
- X2 Browser Use compatibility 层有 descriptor 对 capability 的明确支持/不支持标记，报告中的 D097-D108 逐项证据另列在 `W4-FEATURE-SUPPLEMENT.json`。未启动 LSP。SSH workspace 的 native file handler 明确跳过 LSP pre/post edit；`core/atlas/engine/tool_registry.py:447-481` 中 `:470` 的分支仅在非 `ssh://` workspace 建立 LSP snapshot/report。此为唯一 W4 finding（W4-001）。

### Android 模拟器/UIA

- Android schema 包括 preflight/build/device/emulator、UIA describe/resolve/tap/swipe/type/keyevent：`core/atlas/tools/mobile_simulator.py:77-134`。`mobile_tool_schemas()` 按平台筛选并将 schema 暴露给 kernel：`mobile_simulator.py:197-207`、`core/atlas/kernel/tools.py:215-217`。
- `AtlasKernel._dispatch` 识别 `android_*`/`ios_*`，对 `MOBILE_MUTATING_TOOLS` 要求 approval 后再调用 `call_mobile_tool`：`core/atlas/kernel/loop.py:2308-2321`（之后调用位于相邻行）。UIA 操作使用 adb input，举例 tap/swipe/text：`mobile_simulator.py:637-652`。未调用设备，因此仅证实源码入口链，不声称 Android SDK/设备可用。

### Web search / fetch

- `web_search`/`web_fetch` 的模型工具 dispatch 见 `core/atlas/tools/web.py:32-54`；模式 `balanced/strict/long` 影响请求结果数：`:56-68`。Search service 按配置 provider chain 搜索、缓存、fallback、去重及 domain filter：`core/atlas/websearch/service.py:96-154`；extract TTL cache 与字符上限：`:158-180`。
- 因此 Ledger D021 的“mode 不改变检索、仅 DDG”不是当前基线的准确缺口；D022 已存在 TTL cache 与字符限制，但本轮未确认 redirect-hop/响应字节数所有限制，故保持部分/需复查。未联网调用 provider。

## Branch 与 host dirty 对照

- `origin/websearch@1581b4f84ca7dd9f3ef0b35eff0127026f9b2bde` 是基线祖先（`HEAD...origin/websearch` 为 `19 0`）；当前 provider chain 已在基线，不存在 branch-only 实现可移植。`origin/f1-d`、`zcode/c6a-lsp-parallel`、`zcode/c5-models-parallel` 为基线祖先；`wip/f4-bc-20261009` 的独有改动不改变工具注册/审批；`sol/x-prep-wip-2026-10-05` 为研究/taskbook；`absorb-all` 未发现 W4 工具 backend 独有实现。
- 对 `D:\atlas-f1-d` 额外只读复核：HEAD `69d56d2443f1c32df899869085b31667e17013a5`，`HEAD...origin/f1-d = 0 2`；dirty/untracked 包括 `kernel/loop.py`、`kernel/tools.py`、`tools/browser_use_compat.py`、`tools/mcp_client.py`、`tools/web.py`、`tools/workspace_workflows.py`、`tools/x2/registration.py`、未跟踪 `tools/workspace_move_state.py`。dirty 统计约 +1,643/-111 行，涉及 browser compatibility 扩展、MCP/auth、web bounded TTL/HTTP 控制和 workspace workflows；这些未提交改动不属于当前基线，未当作可用功能，也未读取配置/secret。
- `f2-c@132a95d88606defa79421d15523427a592bd0053` 相对 `track-upstream@5450a35af461af5743afff283e9ba4b6be162492` 有一个 branch-only commit，新增 `api/mcp_oauth.py`、`mcp_settings_router.py`、`settings_audit_router.py`、MCP 设置 UI 并更新 `tools/mcp_client.py`。比较当前基线可见这些 OAuth/settings router 路径不存在，`application.py` 未 include；当前 MCP client 只有 stdio/SSE/Streamable HTTP，无 OAuthClientProvider/PKCE。因此这是可补 D035 OAuth/PKCE/credential storage 缺口的候选，不是当前已注册功能；基点较旧且提交同时删除旧 MCP resources/liveness 路径，不可直接 cherry-pick，应按依赖逐项移植并做安全/生命周期复核。本审查只读了源码，没有执行 OAuth。提交中 OAuth 实现来源代码路径已从 GitHub 读取确认：`NousResearch/hermes-agent@c9e076b41f2163445b506b1cb79862d0dab0eecd/agent/web_search_provider.py`；Atlas 当前 websearch 适配已有本地 provider 文件，不建议平行重写。
- host `D:\Atlas` 当前 dirty 的 `tool_catalog.py`/`tool_node.py`/`kernel/loop.py`/`kernel/tools.py`/`tools/web.py` 含 untracked expert/research 集成候选；它们不在干净 baseline。报告只记录源代码存在，不将其注册/运行效果作为确认结论，也未改动。

## LEDGER 映射

- D021：部分，但 Ledger 旧症状需刷新；见 `tools/web.py:56-68` 与 `websearch/service.py:96-154`。
- D022：部分；缓存/字符限制存在，redirect/response-byte 上限未覆盖，见 `websearch/service.py:158-180`。
- D029、D112：部分/原有低层入口；`computer_use.py:48-64,379-408`。
- D030、D031、D033、D035、D038、D039、D040、D043、D046：既有逐项状态与 backend 证据在 `W4-FEATURE-SUPPLEMENT.json`。
- D065-D129：本轮补齐 65 条逐项当前状态与 schema/dispatch/backend path:line 证据，见 `W4-FEATURE-SUPPLEMENT.json`。D097-D108 中 Browser UI 权限/可见性仍按代码支持边界判定；pane UI 与真实浏览器动作未实测。D129 kernel 有 `wait_for_environment` (`kernel/tools.py:167-169`)，未发现 wait-for-MCP callable。
- B060、B098、B099：仅提供后端事实；对应 UI/浏览器内开发服务/自动验证不在 W4 实际 UI 覆盖范围，见 supplement 的待核实状态。

## 成熟复用来源

- MCP OAuth 候选复用：在 [NousResearch/hermes-agent 固定版本 `agent/web_search_provider.py`](https://github.com/NousResearch/hermes-agent/blob/c9e076b41f2163445b506b1cb79862d0dab0eecd/agent/web_search_provider.py) 已通过 GitHub 文件读取确认路径/目标存在；这仅确认官方仓库文件可读，不说明它包含 Atlas 所需 OAuth 功能。OAuth 具体候选源码为本仓 `f2-c@132a95d88606defa79421d15523427a592bd0053:core/atlas/api/mcp_oauth.py`，应按上段说明做依赖审查，不直接移植。
- LSP 远端能力如列入后续需求，应复用 Atlas 现有 LSP seam `core/atlas/engine/lsp_bridge.py` 与 `core/atlas/engine/tool_registry.py:129-230`，再单独引入 remote transport；协议入口可参考已通过 GitHub 文件读取确认的 [Microsoft LSP protocol repository `protocol.md`](https://github.com/microsoft/language-server-protocol/blob/main/protocol.md)，该文件说明规范现已迁移到 specification site。

## 核验限制

报告中涉及 GitHub 的 taskbook 与固定版本 source path 是远程读取核验；其余均为源码/branch 静态审查。没有任何实时浏览器、CDP、MCP、provider、SSH、LSP server 或 Android 设备调用，没有真实电脑输入，没有 tests/build，也未读取/输出任何 credential/config secret。所有 runtime success 均未观察。


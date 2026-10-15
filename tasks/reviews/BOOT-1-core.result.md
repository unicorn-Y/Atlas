# BOOT-1 后端执行结果

## 范围与提交

- 按要求先 fetch，并以 `origin/memory-v1` 的 `8036b2bc05e9b6bc8afc7a0ecd9e8b31aece774d` 为基线建立 `D:\atlas-boot-core` / `boot-1-core` 工作树；`D:\Atlas` 原工作树未改动。
- 阶段 A：`cea683c7 feat(boot): port Atlas engine runtime`
- 阶段 B2 + 快速关闭：`perf(boot): defer backend startup and bound shutdown`（分支第二提交）
- `core/atlas/engine_core/PORTED.md` 记录 70 条上游源码到 Atlas 目标路径映射；目录目前有 105 个 Python 文件（agent 30、state 41、tools 29，其余为共享适配与包入口）。

## 运行时普查

- 检查启动入口 `desktop_entry.py` → `atlas.server`、HTTP/WebSocket 路由、服务装配、kernel/model 调用、会话状态存储、工具注册、插件/MCP、记忆、后台组件启动及关闭路径。
- 实际冷启动日志确认 ModelManager 和 MemoryStore 在 app startup 阶段创建；DBOS、MCP、skills、plugins、engine registrations、channels、automation、scheduler、Telegram、extensions、session migration 均由组件状态跟踪。MCP 等后台任务尚在 `starting` 时，`GET /api/health` 已返回 `status:"ok"`，并保留逐组件状态；符合约定的“能聊天即就绪”。
- `atlas.server` import-time 报告总计约 2.08 秒（Python import-time 累积），Atlas 自身约 0.90 秒；`atlas.agent` 累积约 0.38 秒，其余时间主要由 FastAPI 路由模块、Pydantic 等依赖分摊。`desktop_entry` 的真实冷启动单次测量见下文。

## 移植与自有运行路径

- 移入 `engine_core/agent`：hooks、plan/title/context、provider、session 生命周期、压缩辅助、脱敏、usage、SSL 与代理辅助等。
- 移入 `engine_core/state`：SessionDB 拆分模块、SQLite 状态/迁移/健康/检索/压缩/回滚/导入导出，以及时间戳与安全读取模块。
- 移入 `engine_core/tools`：工具注册、文件/视觉工具、浏览器 CDP/会话/策略/生命周期/快照/扩展路由及 computer-use 平台适配。
- 另有 Atlas 配置、goals、共享 helpers 与 adapter；`PORTED.md` 中逐行注明上游 commit 和本地目标。
- `HermesRuntime` 的有效对话路径要求 Atlas agent/context 并调用 `AtlasKernel`；压缩经 `atlas.kernel.model_call` 和 SessionDB 租约/提交路径处理。工具、会话同步、浏览器和模型调用改用 Atlas namespace。
- 更新监视逻辑基于已移植上游 hash 输出差异报告；删除原有 Hermes 分支合并/覆盖工作区流程。

## 删除项

- 删除 `core/scripts/setup_hermes.py`、`core/atlas/hermes_pin.py` 及 `[tool.atlas.hermes]` 包配置；`start-atlas.bat` 不再执行 Hermes setup。
- 删除模型/子代理路径上的 `engine.kernel=hermes` 回落；移除通过 `run_agent.AIAgent` 执行对话的工厂路径。
- 卸载验收解释器中的 `hermes-agent 0.0.0` editable package。卸载后 `agent` 和 `tools` 均无法从该解释器导入；桌面入口残留的 Hermes 顶层 `utils` 导入及状态端口的 `from utils` 引用也已移除/改为 `atlas.engine_core.utils`。
- 修正一项旧模型路由测试对已卸载 `agent.anthropic_message_convert` 的 monkeypatch；没有新增测试套件。

## 验收结果

- 卸载 Hermes 后，定向回归：`84 passed`，覆盖模型路由、health、延迟启动、MCP 启动诊断与 desktop shutdown；`compileall` 和 `git diff --check` 通过。
- 桌面入口在独立临时数据根启动成功，`GET /api/health` 返回 `status:"ok"`。最终单次冷启动从启动 `desktop_entry` 到首次 health 为 **3.818 秒**；服务冷启动 probe（直接启动 `atlas.server`）为 **3.328 秒**。先前基线对照记录为约 **7.6 秒**，启动有明显改善，但 **未达到任务要求的 ≤1.5 秒**。因此该性能验收未通过；模块 import 仍是主要限制。
- 实际 WebSocket 对话已从 `/ws/chat` 进入 `AtlasKernel` 并发出 Anthropic `/v1/messages` 请求；一次调用收到 **401 Unauthorized**，没有模型回复。随后用脱敏副本中的 Atlas provider 设置复试，但运行时仍选到 `claude-sonnet-4`，75 秒内没有收到任何对话事件，随后停止。两次均未得到回复，真实对话验收失败。凭据没有输出；临时服务只用独立数据根，未使用或修改 `D:\Atlas` 的数据库和配置。
- shutdown 改动将 DBOS destroy/join 限为 1.5 秒，超时后记录错误且不阻塞主关闭流程；对应 shutdown 测试通过。

## CTX-1 协调与遗留

- 未修改 `core/atlas/kernel/context.py`。CTX-1 与本分支共享 kernel 边界，尤其需要集成时关注 `kernel/model_call.py`、`kernel/loop.py` 的本分支变更；CTX-1 若触及这些文件应按行为合并，不覆盖对方改动。
- `desktop_entry` 到 ready 的 ≤1.5 秒目标尚未完成；应优先继续拆分启动 import 关键路径，并用同一 `desktop_entry` 冷启动测量复验。
- 真实模型对话仍受 API 401 阻塞，需要可用于 Atlas API 的 provider 凭据后重验。
- 原始工作树 `D:\Atlas` 未动；当前工作树有启动探测产生的未跟踪 `data/cache/`、`data/startup-*` 目录，均未加入提交。

## BOOT-1 补齐复核（2026-10-15，boot-1-int）

### 保护提交与补齐项

- 中断后先将已有核心移植提交为 `e711aa55 fix(boot): complete Hermes runtime import ports` 并推送到 `origin/boot-1-int`，防止未提交代码丢失。
- 本轮真实调用暴露的延迟路径已补齐：`tool_catalog` 暴露现有 X2 浏览器 schema，`tool_node` 用 run-scoped X2 context 执行浏览器调用；Bot Desktop 无法用的放置路径明确拒绝，默认 Atlas host/gateway 路径保留。
- 修正 `browser_tool_real_profile` 对拆分后模块的错误访问；X2 兼容配置写入 `DATA_ROOT/config.yaml`，不覆盖 Atlas TOML；Hermes PM 不在验收虚拟环境时，浏览器使用宿主环境和已安装的 agent-browser，并识别 Windows 的 Edge/Chrome 路径；修复 X2 日志 `LogRecord.module` 保留字段冲突。
- 浏览器调用曾发现并纠正 Atlas 测试副本 `config/atlas.toml` 被 YAML 覆盖的问题：从 `D:\Atlas\config\atlas.toml` 只读恢复到 `D:\atlas-boot-int\config\atlas.toml`。两份文件 SHA-256 相同；`D:\Atlas` 未写入。当前工作树中的 `engine/config.yaml` 以及 data 下探测文件仍为测试环境配置/产物，不纳入提交。
- 既有移植模块与删除项清单见本目录 `core/atlas/engine_core/PORTED.md`（Hermes `c9e076b` 来源映射及 Atlas 不支持项）；本轮浏览器接线和延迟路径修复也已追加在该文件。

### 静态导入检查

执行：`python scripts/diag/import_check.py core`

```text
TOTAL 0
```

针对本轮触及的 Python 模块运行 `compileall -q`，退出码 0。

### 真实对话逐项结果

| 验收项 | 结果与证据 |
|---|---|
| 普通问答 | 通过（此前 run `ff1a6df1-c5e1-40fe-8a21-7511b8928d12`，模型回复 `56`，收到 `run.completed`）。 |
| 终端命令 | 通过：`cmd /c echo BOOT1_TERMINAL_OK` 返回 `BOOT1_TERMINAL_OK`。 |
| 文件读/写/编辑 | 通过：测试文件写入 `BOOT1_ALPHA`、编辑为 `BOOT1_BETA`，再读回 `BOOT1_BETA`。 |
| MCP 工具 | 通过：真实对话调用 `filesystem__list_allowed_directories`，返回允许目录 `D:\Atlas`。MCP 文件写入因服务器边界拒绝工作树外路径；文件改写由已验收的 Atlas `local_shell` 完成。 |
| 浏览器打开网页 | 通过：run `9865a083-8376-45e6-b868-ec1a035764ea` 调用真实 `browser_navigate`，导航到 `https://example.com/`，工具返回成功、标题 `Example Domain`，对话随后 `run.completed`。 |
| 看图 | 通过：run `91e6d84b-9dbf-4164-8c4e-ba30bc07f254` 附加 `data/runtime/boot-repair-current.png`；模型回答了图中 Atlas 窗口的 MCP 加载提示及可见 UI 内容，随后 `run.completed`。 |
| 触发压缩 | 通过：对旧会话调用 `POST /api/conversations/091006a8-9b94-438d-8bb8-35ad6be0cfe4/compact`，HTTP 200，返回 `compressed`、`before_tokens`、`after_tokens`、`summary` 和 `estimated_after_tokens`；摘要长度 1933 字符。 |
| 自动生成标题 | 通过：真实消息运行收到 `session.title` 事件（旧会话与图片对话均观察到），消息正常完成。 |
| 打开旧会话继续聊 | 通过：会话 `091006a8-9b94-438d-8bb8-35ad6be0cfe4` 的 run `802751e1-f0f9-4d9d-8bab-ff2af279c7c6` 完成，返回“旧会话继续成功”。先前限制工具的探路 run 在加载许多无关上下文后主动取消，不作为通过证据。 |

### 旧 HTTP 400 根因结论

- 已证实的直接故障是会话读取导入失败：旧 run `e6ee9222-b392-4d57-b2f1-89ee92edcb73` 的 `_rows_to_conversation -> index_tool_call_uids` 延迟导入缺少 `tool_call_id_variants`；`tool_result_id_variants` 同属缺失项。错误触发 `kernel.session_read_failed`，随后 loop 回退到 `request.history` 而继续发起模型调用。
- 同一旧 run 的请求包含约 80 个工具，`provider=custom` 返回 HTTP 400 `invalid_request`，输入记录约 26,847 tokens。保留日志没有 provider 响应体或完整请求快照，因此无法证明 400 是缺失 ID helper 的直接后果，也无法确定被代理拒绝的具体字段；可能相关的回退 history/tool-call 配对和大型工具 schema 都没有证据定论。
- 补齐后，原旧会话的短续聊成功；另一个旧会话探路 run 在被取消前连续进行 38 次 model request，没有 400，也没有 `kernel.*_failed`。因此原始 400 当前未复现；结论保持为“已确认读取根因，400 因果未能从旧代理日志还原”。

### 日志、就绪与剩余边界

- 测试后端 `GET /api/health` 返回 `status:"ok"`，后台 components 最终均为 `ready`。
- 扫描 `D:\atlas-boot-int\data\logs\backend-stdio.log`：417 行；`kernel.*_failed` 命中 **0**，`ImportError` 命中 **0**。该文件最后写入时间为本轮 12:44；12:44 后成功对话的 run JSONL（含旧会话、图片、压缩前后及浏览器 run）也未记录 kernel failure 或 ImportError。`backend-stdio.stderr.log` 同样为 0/0，但其最后写入时间仍是较早的启动/关闭记录。
- 本次浏览器访问使用测试工作树中配置的真实 `agent-browser` 与本地 Chrome；Bot Desktop terminal placement 仍明确不支持。`browser_navigate` 实际导航已通过。
- `core/atlas/kernel/context.py` 未改；本轮新增修改只涉及 agent tool catalog/dispatch、X2 配置同步与浏览器兼容模块。原工作树 `D:\Atlas` 未被写入。

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

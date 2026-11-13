# WAVE 2 V5 — X2 / X4 / X8 / X9

## 结果摘要

| Row | 状态 | 本轮证据 |
|---|---|---|
| X2 | CLOSED（插件卸载路径） | PluginRuntime 已有逐项 disposer stack；新增回归实际 load 插件并 disable，验证 async `disconnect_server` 被 await 且 MCP 连接移除。 |
| X4 | PARTIAL | 新增 profile、bundle、row patch 有序持久化/合并 API 与 `atlas plugins dump-config --profile … --bundle …`；定向测试覆盖重载后的持久化、row-id 替换/删除和字段合并。暂无 profile/bundle 管理 API 或 CLI 写入命令。 |
| X8 | PARTIAL | Agent preset 持久化插件行 allowlist 与 allow-all 语义，支持 revision 化快照；run setup 建立 `PluginRealm` 并挂到本次 `AgentRunContext`。当前 Atlas run 的模型工具消费点尚未读取这个 realm，不能声称模型侧隔离已生效。 |
| X9 | PARTIAL | ACP `session/new` 校验 `agentPresetId` / `permissionPreset`，解析 capabilities 并存入会话；`session/prompt` 将同一 preset 和权限模式传给 AgentOrchestrator。没有执行 ACP JSON-RPC 端到端会话测试；WAVE2 的真实模型脚本走 `/ws/chat`，不覆盖 ACP。 |

## 改动

- `core/atlas/plugins/runtime.py`：profile/bundle/patch 持久化到插件 runtime state；按 profile → bundle → patch 顺序组合，支持 `row:<id>` 替换/删除；现有异步 disposer 卸载行为加入回归覆盖。
- `core/atlas/cli.py`：新增 `plugins dump-config`，输出先经过 `secrets_store.scrub`。
- `core/atlas/task_artifacts.py`：Agent preset 规范化 plugin row allowlist，增加 `resolve_versioned` 返回 revision 与 capabilities 快照。
- `core/atlas/agent/run_phases.py`：为每次 run 构造 preset-scoped `PluginRealm`。
- `core/atlas/tools/app_server.py`：ACP session 创建时解析并绑定两个 preset；prompt 时向 orchestrator 传递绑定值。
- `core/atlas/engine/kernel/loop.py`：真实运行暴露 request/profile/configured output limit 同时缺失时会对 `None` 执行 `int()` 的既有崩溃；添加 8192 的最终默认值，避免验证在模型请求前失败。

## 验证

定向测试与相关 preset/automation 回归：

```text
python -m pytest -q -p no:cacheprovider tests/test_agent_preset_capabilities.py tests/test_plugins.py tests/test_plugin_disable_withdraws.py tests/test_agent_policy_context_wiring.py tests/test_automation_capability_binding.py
19 passed, 5 warnings in 6.76s
```

Python `compileall` 与 `git diff --check` 通过。`python -m atlas.cli plugins dump-config --help` 显示 profile 和 bundle 选项。

真实模型验证使用 8835、后端启动 shell 中的 `http_proxy=http://127.0.0.1:7897` 与 `https_proxy=http://127.0.0.1:7897`，以及隔离数据目录中的 Atlas 配置副本（endpoint 为 `https://d1api.xin/v1`）。真实输出：

```text
{"default": "deepseek-v4.1-flash", "api_base": "https://d1api.xin/v1", "source": "atlas.toml", "event": "model_manager.init"}
[event] run.usage
[event] message.completed
[terminal] run.completed ... "model": "deepseek-v4.1-flash" ... "output_tokens": 1
[reply] 'OK'
[result] terminal=run.completed chars=2
```

该真实回合证明 Atlas DeepSeek 通道可用；它是普通 `/ws/chat` 回合，不覆盖 ACP，也不证明 X8 realm 的模型侧消费。

## 未关闭项

- X4 缺少 profile/bundle 层的公开写入和列举入口；本轮可通过 `PluginRuntime.put_config_layer` 持久化，但还没有管理命令/API。
- X8 的 realm 已进入每次 run 的 context，但 kernel/model tool assembly 仍需消费 `runtime.plugin_realm` 才能执行真实隔离。
- X9 的 session/prompt 接线有源码证据，尚无独立 ACP JSON-RPC 集成验证。
- 未运行完整 core 测试套件。

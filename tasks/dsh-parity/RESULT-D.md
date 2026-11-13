# Batch D — Extension

## 结果

关闭：X17（skill invocation flags 已在用户 slash 与模型调用两条路径执行）、X29（typed webhook provider/HMAC adapter）。

部分完成：X2（plugin skill/command/hook disposer 可逆；async MCP lifecycle disposer 未覆盖）、X4（patch row_id/order 已有；profile/bundle merge 和预览未做）、X8（revisioned capability preset 已保存并应用；ledger 的 isolate realm/子插件行能力未实现）、X9（automation webhook preset 已接线；ACP 入口未接）、X13（plugin `.codex/hooks.json` 支持若干事件；repo/user 通用来源与 trust surface 未接）、X16（durable digest/retirement/revisioned available-skills 已接；`/name` 内联和摘要 diff 交付未实现）、X23（scope facade 有测试但 agent/session 尚未使用）、X27（注册表支持自定义扩展节点；内置 renderer switch 仍保留）、X28（backend registry/event log 与 invocation gate 已有，但 plugin/runtime/frontend dispatch 未接）。

## 改动文件

- `core/atlas/plugins/patch_layer.py`
- `core/atlas/plugins/runtime.py`
- `core/atlas/skills/__init__.py`
- `core/atlas/skills/registry.py`
- `core/atlas/tools/mcp_client.py`
- `core/atlas/library/runtime.py`
- `core/atlas/task_artifacts.py`
- `core/atlas/api/automation_router.py`
- `core/atlas/automation/engine.py`
- `core/atlas/automation/store.py`
- `core/atlas/automation/webhooks.py`
- `core/atlas/runtime/commands.py`
- Frontend: `ConversationActivity.tsx`, `MessageThread.tsx`, `timeline.ts`
- 新增测试覆盖 plugin dispose/patch row IDs、Codex hooks、MCP scope、skill catalog/invocation、agent preset、automation preset、webhook provider、command registry 与 ConversationNode registry。

## 测试

核心 extension 回归：

```text
rtk python -m pytest -q -p no:cacheprovider tests/test_plugin_reload_idempotent.py tests/test_plugin_patch_row_ids.py tests/test_agent_skill_model_invocation.py tests/test_codex_plugin_hooks.py tests/test_mcp_client_scope.py tests/test_skill_discovery_catalog.py tests/test_skill_invocation_flags.py tests/test_agent_preset_capabilities.py tests/test_automation_capability_binding.py tests/test_webhook_provider_contract.py tests/test_u11_webhooks.py tests/test_automation_store.py tests/test_c4_skills_commands.py tests/test_slash_command_registry.py

58 passed, 5 warnings in 6.31s
```

Frontend registry/timeline 及 Batch E 组件：

```text
rtk npm test -- --run src/renderer/components/ConnectionRecovery.test.tsx src/renderer/services/runtimeEvents.test.ts src/renderer/shell/panels/trajectory.test.ts src/renderer/components/ConversationNodeRegistry.test.tsx src/renderer/components/timeline.test.ts

Test Files  5 passed (5)
Tests       32 passed (32)
```

```text
rtk npx tsc -p tsconfig.renderer.json --noEmit
TypeScript: No errors found
```

曾运行较广的 component suite：119 pass、2 项 `x2.test.tsx` 失败（旧 BROWSER_MODES 期望值与 `window` 未定义，属于既有测试问题）；`test_c4_plugin_e2e.py` 的 mojibake assertion 也曾失败，未修改相关行为。

## 真实模型回合

命令：`rtk python scripts/dsh_live_ws_check.py 8811 "Reply with exactly the word: OK"`

```text
[reply] 'OK'
[result] terminal=run.completed chars=2
```

终止事件的 runner 输出为 `run.completed`，模型为 `deepseek-v4.1-flash`，input 9794/output 2，cached input 9600。

## 未完成项与原因

其余 partial 行见上方逐行状态。真实回合只验证 model/provider、后端和事件流基础链路，不证明各插件 hook、webhook 或 preset 分支均已运行。

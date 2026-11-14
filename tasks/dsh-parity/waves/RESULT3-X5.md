# WAVE 3 — X5 结果（扩展层）

日期：2026-11-14  
分支：`wave3`  
基线：`2bc3a626`  
提交：本批提交后补录

## 逐条结论

| Row | 状态 | 依据 / 未完成项 |
|---|---|---|
| X2 | PARTIAL | 异步 MCP disposer 已由 plugin lifecycle 单测覆盖；没有真实模型通过插件 MCP 触发并观察卸载行为。 |
| X3 | PARTIAL | 重载会清理旧 capability 与 hook，已有幂等回归；本批插件 E2E 中文断言失败，且没有真实模型 enable/disable 观测。 |
| X4 | PARTIAL | patch row-id/order 已实现与测试；profile/bundle 配置组合、持久管理/预览仍不完整。 |
| X8 | PARTIAL | revision 化 capability preset 和 PluginRealm 基础存在；realm 未贯穿模型工具消费链，不能证明隔离生效。 |
| X9 | PARTIAL | webhook/automation preset 已绑定；ACP 生命周期仍不完整。 |
| X10 | PARTIAL | kernel 有 list/request-install 子集，缺 plugin manager 全部动作与要求的审批策略。 |
| X11 | PARTIAL | 插件 discovery 有基础清单字段，availability/覆盖行语义不完整。 |
| X21 | PARTIAL | MCP instructions 已成为独立 prompt section 并有单测；没有真实模型行为观测。 |
| X27 | PARTIAL | timeline node registry、definition 与 disposer 有组件单测；整个 client 的 slots/plugin loading 尚未贯通。 |
| X24 | PARTIAL | ACP 仅部分 session lifecycle，自动批准工具、缺 resume/config option 和 per-session MCP 注入。 |
| X12 | PRESENT-PARITY | Claude Code hooks 已有 28 事件桥与 run 接线；本批只复核，没有实测真实模型 hook 行为。 |
| X13 | PARTIAL | Codex plugin hooks 支持范围内的事件；repo/user 通用来源与 trust surface 仍缺。 |
| X15 | PRESENT-PARITY | skill 发现根阶梯按优先级映射；本批未改变实现。 |
| X18 | PARTIAL | `SkillSource` 与请求作用域副本存在；仍同步递归扫描，provider invalidation 不完整。 |
| X19 | PARTIAL | 读时 mtime/size 指纹能发现变化；缺文件监听和写路径即时失效。 |
| X20 | PRESENT-STRONGER | Atlas 已有依赖与生命周期 gate；本批不改强于目标的实现。 |
| X25 | PARTIAL | app-server 已有 JSON-RPC v1；缺 settle barrier、wait 与完整 SDK lifecycle。 |
| X26 | NOT-DONE | 未找到 typed Client↔Host Remote gateway 生成层。 |
| X30 | PARTIAL | SSH 可代理若干工具；完整 filesystem/subprocess/sandbox execution world 未迁移。 |
| X31 | PARTIAL | 当前有 APScheduler synthetic session 与 DBOS automation，未证明到期回到原 session。 |
| X32 | PARTIAL | runtime introspection 可查当前组合状态；缺配置逐层来源追踪。 |
| X33 | PRESENT-PARITY | 多格式 agent discovery 与 backend adapter seam 存在；本批未改实现，真实模型 provider 行为未验证。 |
| HARD X5 | HARD(reason) | 插件依赖解析、lockfile 快照回滚和取消需要包管理器语义；按计划不派工。 |
| HARD X6 | HARD(reason) | peer range、profile compatibility exception 与持久 risk acceptance 需要版本兼容/风险契约；按计划不派工。 |
| HARD X7 | HARD(reason) | Atlas 不执行 package build scripts，因此没有 pending/allow-build approval 生命周期；按计划不派工。 |

`PRESENT-PARITY` / `PRESENT-STRONGER` 是账本能力判断，不等于本轮 `CLOSED`；本批没有 X 行达到新的 CLOSED 证据标准，故没有声称真实模型行为验收通过。

## 定向测试及实际输出

```powershell
cd D:\Atlas\core
python -m pytest -q -p no:cacheprovider tests/test_plugin_reload_idempotent.py tests/test_plugin_disable_withdraws.py tests/test_office_pdf_and_hooks.py tests/test_c4_plugin_e2e.py tests/test_plugin_patch_row_ids.py tests/test_plugin_patch_layer.py tests/test_mcp_instructions_section.py tests/test_mcp_client_scope.py tests/test_mcp_lifecycle_shutdown.py tests/test_codex_plugin_hooks.py tests/test_hook_bus_modes.py tests/test_skill_registry.py tests/test_skill_registry_api.py tests/test_skill_dependency_distribution.py tests/test_skill_discovery_catalog.py tests/test_skill_discovery.py tests/test_skills_hot_reload.py tests/test_skill_lifecycle.py tests/test_automation_capability_binding.py tests/test_automation_engine.py tests/test_scheduler.py tests/test_introspect_providers.py
```

```text
................................s...................F................................... [ 32%]
....FFF................................................................. [ 64%]
........................................................................ [ 97%]
......                                                                   [100%]
4 failed, 217 passed, 1 skipped, 12 deselected, 5 warnings in 26.15s
```

失败项：

- `test_installed_plugin_crosses_real_runtime_paths`：Windows 输出中的中文 hook 错误文本与断言字符串均显示为乱码，子串断言未通过；未改编码或弱化断言。
- `test_stdio_session_shutdown_exits_its_real_child`、`test_cancelled_mcp_discovery_stops_its_real_stdio_child`、`test_cancelled_owner_does_not_skip_other_server_cleanup`：MCP stdio owner/child startup 与 cancellation/cleanup 断言未通过。

为区分 suite interaction 与可重现失败，独立重跑 MCP lifecycle 文件：

```powershell
python -m pytest -q -p no:cacheprovider tests/test_mcp_lifecycle_shutdown.py
```

```text
FFF                                                                      [100%]
3 failed, 5 warnings in 4.21s
```

3 项均独立重现，细节见对应测试断言。该结果不是 async plugin disposer 的直接回归，但说明更广的真实 stdio 生命周期/取消路径当前不能宣称可靠。

## 本批变更与验证边界

- `docs/parity/DSH-GAP-LEDGER.md`：修正 X2/X3 的 stale 描述，记录 X21 已有独立 prompt section 和 X27 已有 timeline node registry；区分实现存在与 live 行为验收。
- `tasks/dsh-parity/waves/RESULT3-X5.md`：本结果及所有实际测试输出。
- HARD X5/X6/X7 保持 HARD(reason)，没有改相关实现。
- 本批没有生产源码改动。未跑 live model：本批没有准备好可通过真实模型安全触发的插件/MCP/ACP 管理会话，且定向回归暴露了真实 stdio lifecycle failures；没有以普通 OK 回合作为这些扩展行为的证据。
- 未运行完整 `core` 测试套件。

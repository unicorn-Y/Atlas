# WAVE5-C 结果（插件与扩展区 + HARD 可行性评估）

worker：C 组（X8 / X14 / X18 / X24 + X1/X5/X6/X7/X26 评估）
worktree：`D:/Atlas/.worktrees/w5-c`，分支 `wave5-c`，基线 `32b76e39`
本组提交：`b0d8bdb7`（X8 主体）、`c25df72f`（X14 回归）、`f5c69ea8`（X18 缓存）、`2b019518`（X8 语义修正 + 取证脚本）

---

## ① 逐条判定

| 条目 | verdict | 一句话证据 |
|---|---|---|
| X8 PluginRealm 子插件行隔离 | **CLOSED** | 单测 `core/tests/test_plugin_realm_enforcement.py` 20 项过；真实模型双回合（端口 8892）open 池含 `0w8in__probe_ping`+`0w8out__other_ping`（模型实际调用均成功），scoped 池（`plugins=["w8probe"]`）envelope 只有 `0w8in__probe_ping`，模型确认界外工具"无法调用" |
| X14 hook 逐条信任门 | **PRESENT-STRONGER（补回归）** | `hooks.py:712-783` fingerprint 逐条信任门在位；本轮新增 `core/tests/test_hook_trust_gate_regressions.py` 2 项（批准→执行、同 id 配置漂移→`changed` 再拦截、吊销→`revoked` 拦截、过期 fingerprint 拒绝），9 项定向全过 |
| X18 skill provider 协议 | **PARTIAL（缓存已补；异步 provider 协议仍缺）** | scope 链 keyed 发现缓存已实现（`skills/__init__.py` `with_sources` LRU+指纹自失效，`test_skill_scope_cache.py` 5 项 + 相邻 8 项过）；异步 provider list/get 需要新接口层（现在 provider 面是同步 `list/get/handle_change`，无 Protocol/async 适配层） |
| X24 ACP per-session MCP 注入 | **PARTIAL（7 methods live-proven；per-session MCP injection needs MCP process orchestration primitive）** | `MCPClient.for_scope()`/`ScopedMCPClient`（`mcp_client.py:477-487,1435+`）只是**既有连接的 fail-closed 视图**，不支持从请求参数 spawn/遥断 server 进程；`app_server.py:405-409` 的 -32602 拒绝保持。缺口=会话拥有的 server 注册表、session/close 遥断、重连循环豁免、可见性穿越 preset 管线 |
| X1 Cordis 组合根 | **HARD(composition root redesign; staged migration assessed feasible only with the module-global monkeypatch seam kept as a compat facade — 破缝即破数百测试)** | 评估全文见 §④ |
| X5 插件依赖解析/lockfile 回滚/取消 | **HARD(package-manager dependency resolution, lockfile rollback, cancellation semantics absent)** | `plugins/runtime.py:1059-1200`（install_local/add_marketplace/install_marketplace_plugin/install_git）：仅本地 copy（`_copy_replace:1003`）与同步 git clone（`_git_clone:1051`，subprocess 阻塞重试、无取消 token）；manifest allowed keys（:544-546）不含依赖声明；卸载（:1256）= rmtree，无快照回滚 |
| X6 版本兼容与豁免 | **HARD(requires peer-range checks + persisted per-profile risk acceptance)** | `plugins/runtime.py:530-581` 只校验 manifest 形状（version 正则 :541、字段类型、unknown-field warning）；全仓 sweep 无 `peerDependencies`/`compatibility.json`/`acceptRisk`（0 命中） |
| X7 安装脚本审批门 | **HARD(no package build-script execution model or per-package approval ledger)** | manifest 不含 build/scripts 声明（:544-546 allowed 清单）；插件唯一外部命令执行是生命周期 hooks（运行时 hook，非包构建脚本）；`pendingBuilds→allowBuilds` 概念全仓 0 命中 |
| X26 typed Client↔Host gateway | **HARD(needs decorator protocol layer + build-time codegen + typed client generation)** | W4-Z6 终判 sweep 复核成立：core/frontend/backend-adapter 无 `@Remote/RemoteScope/typert`、无 codegen 管线（唯一命中是 whatsapp_bridge 的 npm lockfile 与 mobile_simulator 的 XcodeGen，均无关）；契约仍靠手写 FastAPI router + 手写 TS adapter |

---

## ② 改动文件清单（全部在本 worktree，已 commit）

| 文件 | 改动 | commit |
|---|---|---|
| `core/atlas/plugins/runtime.py` | PluginRealm 增加 `plugin_of_source`/`allows_plugin`/`admits_plugin_source`/`allows_mcp_server`/`owns_server` + `mcp_owners` 归属映射 | b0d8bdb7, 2b019518 |
| `core/atlas/agent/run_phases.py` | preset 应用时从 `agent._plugin_runtime.enabled_contributions()` 解析 server→plugin 归属并传入 realm；`_build_messages` 把 realm 传给 `skill_index_message` | b0d8bdb7 |
| `core/atlas/engine/kernel/loop.py` | 新增 `_plugin_realm_allows`/`runtime_tool_allowed`/`_plugin_realm_admits_skill`；工具池装配（2 处）、pre_execute、dispatch、tool_search 候选全部改走合并谓词；dispatch 对界外插件返回 `Plugin is outside this agent preset's plugin scope`；`use_skill` 对界外插件技能 fail-closed；`_mcp_tool_allowed` 对 realm 拥有的 server 让位（2b019518） | b0d8bdb7, 2b019518 |
| `core/atlas/library/runtime.py` | `skill_index_message` 接受 `plugin_realm`，界外插件条目从模型可见目录与检索（BM25 重建子集）中隐藏 | b0d8bdb7 |
| `core/atlas/skills/__init__.py` | `with_sources` 的 scope 链 keyed LRU 发现缓存（`_SCOPED_VIEW_CACHE_MAX=8`），复用 `_ensure_fresh` 指纹自失效 | f5c69ea8 |
| `core/tests/test_plugin_realm_enforcement.py` | 新增，20 项 | b0d8bdb7, 2b019518 |
| `core/tests/test_hook_trust_gate_regressions.py` | 新增，2 项 | c25df72f |
| `core/tests/test_skill_scope_cache.py` | 新增，5 项 | f5c69ea8 |
| `core/scripts/w8_realm_live_check.py` | 新增，X8 live 取证驱动 | 2b019518 |

未提交的他人改动：`conversations_router.py`/`tool_pruning.py`/`session_titles.py`/`atlas_state_titles.py` 四文件是 B 组 worker 的改动集（stash 竞争事故，见 §⑤），保留在工作区未提交，完整 patch 存于 `.tmp/w5b-changeset-found-in-w5c.patch`。

---

## ③ 测试命令与真实输出

```
cd /d/Atlas/.worktrees/w5-c/core
python -m pytest -q -p no:cacheprovider tests/test_plugin_realm_enforcement.py tests/test_plugin_realm.py tests/test_agent_preset_enforcement.py --basetemp=D:/Atlas/.worktrees/w5-c/.tmp/pytest-c
→ 19 passed, 5 warnings in 7.58s   （X8 主体；2b019518 后同集合 20 passed）
python -m pytest -q -p no:cacheprovider tests/test_library_skill_disclosure.py tests/test_agent_preset_capabilities.py tests/test_plugins.py tests/test_plugin_disable_withdraws.py --basetemp=.../pytest-c2
→ 21 passed, 5 warnings in 24.68s
python -m pytest -q -p no:cacheprovider tests/test_hook_trust_gate_regressions.py tests/test_codex_plugin_hooks.py tests/test_codex_hook_exit_semantics.py --basetemp=.../pytest-x14
→ 9 passed, 5 warnings in 12.60s
python -m pytest -q -p no:cacheprovider tests/test_skill_scope_cache.py tests/test_introspect_skill_sources.py tests/test_skills_hot_reload.py --basetemp=.../pytest-x18
→ 13 passed, 5 warnings in 6.95s
```

基线对照：`tests/test_kernel_tool_error_regressions.py::test_tool_call_arguments_repair_only_closed_objects` 在干净基线（git stash 后）同样失败 → 既有失败，与本组改动无关。

### 真实模型回合（X8，端口 8892，ATLAS_DATA_DIR=worktree .tmp/live-data）

环境：`ATLAS_TOOL_PRUNING=0`（关闭分层裁剪以暴露全池），preset `w8-open`（plugin_allow_all）/`w8-scoped`（plugins=["w8probe"]），probe 插件各贡献一个 stdio MCP server。驱动：`core/scripts/w8_realm_live_check.py`（经 automation date 触发，双回合均 `status: ok`）。

run journal `model_request_envelope.tool_names`（排序前 20，`0w8*` 按字典序排最前，缺席非截断）：

```
open   → ['0w8in__probe_ping', '0w8out__other_ping', 'AskUserQuestion', ...]   (has 0w8in: True | has 0w8out: True)
scoped → ['0w8in__probe_ping',  'AskUserQuestion', ...]                        (has 0w8in: True | has 0w8out: False)
```

模型行为证据（receipt 原文摘录）：
- open 回合（journal `26d95245…`）：`tool_start` 记录 `0w8in__probe_ping`、`0w8out__other_ping` 均执行，回复「`0w8in__probe_ping` → `W8IN_PONG`；`0w8out__other_ping` → `W8OUT_PONG`，两个都成功返回」。
- scoped 回合（journal `a3bf53f4…`）：`tool_start` 记录 `0w8in__probe_ping` 执行；回复「registry only lists `0w8in__probe_ping` … I have no way to call an unregistered tool name」——界外工具从池中消失，模型无法调用。

---

## ④ X1 Cordis 组合根可行性评估（全文）

**现状三件套（实测）**
- `core/atlas/api/app_services.py`（158 行）：`AppServices` 52 字段 slots dataclass，全部默认 `None`（两个例外：`session_projections`/`tool_result_finalizers` 默认构造），带 `require/has/maybe/missing/wired/unwired` 守卫访问器；introspect 面有 `services.unbound` 可观测。
- `core/atlas/api/application.py`（221 行）：79 个 router import；`create_app` 里 74 个 router 手列元组（:135-211）+ 6 个逐个 `include_router`（memory_library/scenario_bundles/standing_orders/goal_loop/introspect + 尾部自省），注释明示「Preserve registration order: literal skill routes must precede path params」（:134）——注册顺序有语义。
- `core/atlas/server.py`（1099 行）：`lifespan` 约 865 行，内联构造 24 个模块级全局单例、23 处 `capabilities.register` 内联 lambda、`services` 字段经 globals() 名称扫描装配（:684-692 `setattr(services, name, globals().get(name))`）。

**为什么不能一次性替换（阻断性耦合）**
1. **双可见域是契约不是债**：路由层 135 处 `_service(name, services)` 在 `AppServices` 未接线时回退 `atlas.server` 模块全局；`run_drive.py:8` 注释明说「keep existing monkeypatch seams and `from atlas.server import X` imports」，测试 patch 的是模块全局（`atlas.server.mcp_client` 等）。替换掉全局即破坏所有走这条缝的测试。
2. **延迟重绑时序**：`_start_mcp`（deferred_startup.py:259-283）只有配置了 servers 才回绑 `server_module.mcp_client`；`_DeferredMCPClient.__getattr__`（server.py:140-156）在 global 为 None/self 时会现场 new 一个 client 并重绑。disposer 语义必须精确覆盖这个时序，否则出现两个 client 实例分持不同连接（本组在 live 取证中实际踩到该机制）。
3. **构造顺序即生命周期**：`memory.init → orchestrator → plugin_runtime → deferred(dbos/mcp/skills/plugins/engine_registrations/channels/automation/scheduler/telegram)` 的顺序承载 §2.1 的不可重入锁与 21 秒锁等待等约定；重排需要逐条论证。

**分阶段迁移评估**
- 阶段 1（服务注册表 + disposer）：在 `AppServices` 旁路加 `register(name, factory, disposer)` + `dispose_all()`，把 lifespan 的裸赋值改为注册。纯增量、不动全局、不破坏测试。**可行**，工作量约 1-2 天，风险低。
- 阶段 2（逐字段迁移）：每迁移一个字段要同时迁移其 `_service()` 回退点与测试 patch 点。回退点集中在约 10 个 router（agent_backends/conversations/health/integrations/projects/plugins/skills/tools/usage/workspace），机械量大（估 2-3 周双通道并存）。**可行但必须保留 `atlas.server` 全局作为兼容 facade**（AppServices 为真源，全局为只读镜像），否则测试大量重写。
- 阶段 3（router 装配声明化）：74-router 元组改为声明清单。难点是顺序敏感路由（字面量先于路径参数）；auto-scan 会引入顺序回归。可行折中=声明清单 + 启动时顺序断言（introspect 已能枚举路由表）。
- 真正的 Cordis 语义（typed inject、service graph、无特权核心）需要废弃 monkeypatch 缝 → 数百测试改造。**在"不破坏现有测试"的约束内不可行；分阶段迁移在保留全局 facade 的前提下可行**，故 verdict 取 HARD（本轮约束内不做），阶段 1 可作为独立后续任务。

**若做，动哪些文件**：`app_services.py`（注册表）、`server.py`（lifespan 拆分为组件声明）、`application.py`（装配清单）、`run_drive.py`（`_server()` facade 保留）、上述 10 个 router、`introspect`（unbound 语义）。
**风险点**：全局与 AppServices 双真源漂移；deferred 组件重绑时序；`_execute_write` 锁约定；router 注册顺序；两个 app 实例隔离假设（`app_services.py:21` 注释）。

## ④b X5 / X6 / X7 / X26 评估要点（行号见 §① 表）

- X5：三种安装源（local/marketplace/git）都收敛到 `_copy_replace`+`_git_clone`；`_copy_replace` 有 incoming+replace 的目录级原子性并携带 patch 层（:1002-1026），但这是单插件部署快照替换，不构成安装图（依赖闭包）的 lockfile 快照回滚；`_git_clone` 走 `subprocess.run` 同步重试（:1029-1048），无取消语义。
- X6：`_validate_manifest`（:520-581）产出 error/warning 列表，全部是形状校验；allowed 键集合（:544-546）连依赖声明字段都没有，peer-range 无从谈起；豁免语义需要 per-profile 持久化（`config_layers` 机制 :360-380 可作存储位，但审批流不存在）。
- X7：插件命令执行面只有 hooks（`hooks.json`/`.codex/hooks.json` → HookStore/HookBus，运行时事件驱动），包安装期 build script 无执行模型、无逐包审批账本。
- X26：全仓特征扫描 0 命中（详见 §① 表）；`gateway_service.py` 是 channel→agent 桥，不是 RPC 网关。

## ④c X18 / X24 残留定性（补 §① 一句话之外的细节）

- X18 异步 provider：现 provider 面是 `SkillManager.list/get/handle_change` 同步方法（`skills/__init__.py:493-507`）；DSH 语义的"异步 provider"要求 provider 可远程/异步解析（`packages/skill/skill/src/index.ts:356,439`），Atlas 侧需要 typing.Protocol + async 适配 + 消费方改造（`register_skill_capabilities`、introspect skills.sources），属新接口层，未做。
- X24：`for_scope` 只能"看"已连接 server（`ScopedMCPClient` 全方法都是 `self._client` 结果的授权过滤）；ACP `session/new` 的 `mcpServers` 参数是 spawn 语义。缺口不是连接原语（`_connect_server` 存在且插件运行时在用），而是**会话作用域的进程编排**：会话级 server 注册表、`session/close` 遥断、reconnect/启动扫描对会话 server 的豁免、与 X9 preset fail-closed 语义的交互。

---

## ⑤ 事故记录（worktree 碰撞）

本组提交前用 `git stash` 做基线对照，与 B 组 worker 的 stash 操作在共享 stash ref 上竞争：我的 X8 改动被弹进 w5-b（后被 B 组 reset 销毁），B 组改动集被弹进 w5-c。处置：凭上下文完整重放我的改动并提交（b0d8bdb7，重跑 19 单测通过）；B 组改动集存 patch `.tmp/w5b-changeset-found-in-w5c.patch` 且四文件保留在 w5-c 工作区未提交。已通报调度者。建议：各 worker 禁用 `git stash`（共享 ref 跨 worktree）。

---

## ⑥ 遗留与备注

- X8 的 `mcp_server_allow` 语义修正是行为变化：applied preset 的空 `mcp_servers` 行现在只拦**未列的 configured** server，插件拥有的 server 归 plugin 行决定。已用单测钉住（`test_preset_empty_mcp_scope_does_not_swallow_realm_owned_servers`）。
- live 环境固定坑（供后续 wave 复用）：d1api.xin 拒收 kernel 自带的 `clock.curr_time`/`clock.sleep`（工具名含点违反 OpenAI 名字符集），live preset 需 deny 这两个；DBOS date 触发会把 schedule 时间写成 workflow `delay_until`，`run-now` 会 dedup 到 delayed workflow——驱动一律用近未来 date + 轮询 journal。
- 本组未改 `docs/parity/DSH-GAP-LEDGER.md`（按约定由调度者统一更新）。

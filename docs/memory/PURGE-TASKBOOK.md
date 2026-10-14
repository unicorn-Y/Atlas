# 任务书：删干净旧记忆系统（收尾）

**分支**：`memory-purge`（基于 `origin/memory-v1` 的 ac347b2，已推到 origin）。
**目标**：Atlas 只保留新的透明记忆库（`core/atlas/memory/library/`，数据在 `data/memory`）。旧的 MemoryOS（8099 服务）、MemOS 插件、atlas.db 里的旧事实/候选/反思/目标知识要全部删掉，代码里和主机上都不能留。
**起因**：用户问 Atlas"记忆系统在正常运行吗"，Atlas 去读了 `config/atlas.toml` 的 `[memory.unified]`，然后 curl 8099、读 MemoryOS 源码，回答的是旧系统。原因是旧记忆每轮仍在注入，而且模型不知道新库的存在。

## 一、已经做完的（在 6834eb3 里，不用重做）

- **后端**
  - 删掉 `core/atlas/memory/` 下除 `__init__.py`、`store.py`、`library/` 以外的全部模块（unified_client/facade、capture、outbox、observer*、reflector、focus_flow、intent_bridge、windows_sources、recall_context、quality、memos_* 等）和 `vendor/mastra`。
  - `MemoryStore`（`memory/__init__.py`）从 4858 行删到 909 行：只留会话、消息、搜索、回退、资料（knowledge 表）。启动时会 `DROP` 旧表（列表在 `_RETIRED_TABLES`）。
  - 删除 `api/unified_memory_router.py`、`api/memory_changes_router.py`。`memory_router.py` 只留 `/api/knowledge`（资料）。诊断里的 MemOS 遥测接口和统一记忆检查、health 里的 memoryos 组件、deferred_startup 里的 MemoryOS 启动，都已删除。
  - `run_phases.py`：去掉目标知识、规划前约束、焦点、统一召回、旧画像、反思、候选抽取、采集、注入预算，删除 `injection_budget.py`。现在每轮的记忆只有 `_merge_library_recall` 和 `_schedule_library_write`。
  - `tool_node.py`：去掉工具事件采集、动作前依赖检查、提醒的 IntentBridge（提醒直接走 AutomationEngine）、轨迹审查的反思记录，删除 `remember` 工具（tool_catalog / hermes_policy 也一起删了）。`agent/__init__.py`：删除 `_remember_result`、`reflect_completed_task`、`MemoryReflectionBridge`，`_create_plan` 不再接收知识参数。`run_drive.py`：删除目标结果写入、失败反思记录、`record_reflection`。
  - 测试时钟整套删除（`time_context`、RunRequest、run_drive）。
  - `server.py`、`cli.py`、`runtime/hub.py`、`tools/app_server.py`：不再构造 UnifiedMemoryFacade。`config.py` 的 `memory.unified.*` 和 `memory_v1_*` 属性已删除。
  - `hermes_runtime.py`：去掉 MemOS 记忆提供方，`skip_memory=True`。`engine/config.yaml` 的 `memory.provider` 设为空。`kernel/prompt.py` 删除 MemOS recalls。x2 浏览器/电脑的收据采集、外部 Agent 结果记录已删除。
  - `models/router.py`：记忆辅助调用的超时和低推理设置改给 `memory_library` 用途。
  - `evolution/skill_sleep.py`：改读 Atlas 自己的网关和 memory_model，不再读 memos-home。
  - 追新系统（`core/atlas/upstream/*`）删除 MemOS fork 的扫描、合并、构建，`atlas-update.mjs` 不再重建 MemOS。`setup_hermes.py` 改成删除遗留的 `plugins/memory/memtensor` 链接。
- **身份与自我介绍**：`engine/breaker.md` 的 Memory 段改为"唯一的长期记忆是 data/memory 记忆库，用 memory_search 查"。`kernel/loop.py::_self_facts` 每轮加一行，写明记忆库路径。
- **前端**：删除 TelemetryPrivacyPanel（MemOS 遥测）、"待确认记忆"角标（App/Sidebar/MemoryPage 的 onPendingChange），backend-adapter 删除 facts 接口和 Fact 类型。MemoryPage.test.tsx 按现在的标签页重写。
- **其它删除**：`vendor/memos-local-plugin`（整个 MemOS 插件）、`scripts/memory_v1`、`scripts/unified_memory`、`tests/fixtures/unified_memory`、`scripts/f1_language_smoke.py`、`scripts/f2_observer_smoke.py`、`docs/plan/MEMORY-V1`、P9A MemoryOS 任务卡、`core/tests/unified_memory/` 和十几个旧记忆测试文件。`test_memory.py` 只留会话、消息、搜索，并新增"旧表被删"测试。test_hermes_setup、test_upstream、test_health_components 已经改好。

**保留的东西（是用户在用的功能，不算旧记忆）**：资料（`/api/knowledge`、knowledge 表）、提醒、Goals（`/api/goals`）、轨迹审查（只是不再写反思）、`session_search`（搜原始对话）。

## 二、要你做的

### 1. 测试收尾
下面这些测试还引用已删除的东西。规则是：测的是被删功能的，整条删掉；测的是保留功能、只是用了旧接口的，改成新写法。不要为了让测试通过去恢复旧代码。
- `core/tests/test_agent.py`、`test_agent_enrichment.py`（MemoryReflectionBridge、remember、goal knowledge）
- `test_agent_run_phases.py`（injection_budget 三个测试、goal knowledge 阶段、unified 分支、`_create_plan` 参数）
- `test_autonomous_foundation.py`、`test_autonomous_knowledge_e2e.py`（目标知识 / 洞察闭环，基本整文件删除）
- `test_long_lived_agent_e2e.py`、`test_server.py`、`test_session_migration.py`（调用了已删除的 MemoryStore 方法，比如 set_fact、list_facts、record_goal_outcome）
- 再全局搜一遍：`grep -rniE "unified|memoryos|memos|set_fact|list_facts|goal_knowledge|reflection|test_clock|remember|injection_budget|telemetry-privacy" core/tests`

然后跑单元测试：`cd core && .venv/Scripts/python -m pytest -q -x -p no:cacheprovider`（用 Atlas 的 venv，PYTHONPATH 指向本工作树的 core）。和 `origin/memory-v1` 比，不能多出新的失败。已知改动前就失败的有 `tests/test_c1_tool_workspace.py` 两个用例（FixtureConfig 没有 .raw）。

### 2. 静态检查与前端
- `ruff check --select F401,F821,F841` 检查改过的文件，不能有本次引入的问题。
- `npm --prefix frontend run typecheck`（或 `tsc --noEmit`）和 `npx vitest run`：MemoryPage、Sidebar、App、backendProcess 相关的测试要通过。

### 3. 合并推送
确认 `origin/memory-v1` 期间没有新提交（有的话先合并），然后把 `memory-purge` 快进或合并进 `memory-v1` 并推送。提交信息末尾加 `Co-Authored-By`。主机 `D:\Atlas` 跑的就是 memory-v1，推完由用户点「立即更新」。

### 4. 主机清理（等用户点完「立即更新」、Atlas 重启后再做）
**全部是移动，不是删除**：统一挪到 `D:\_archive-old-memory-2026-10-14\`，由用户自己决定删不删。
1. 停掉 8099 的 MemoryOS 进程：用 `Get-NetTCPConnection -LocalPort 8099` 查 PID，按 PID 结束，不要按进程名杀。再查一下有没有开机自启它的计划任务或启动项，有就先告诉用户，用户同意后再禁用。
2. 编辑 `D:\Atlas\config\atlas.toml`（本机文件，不进 git）：先备份一份到归档目录，再删掉整个 `[memory.unified]` 段。
3. 移进归档目录：`D:\MemoryOS`、`D:\MemoryOSData`、`D:\Atlas\data\memos-home`、`D:\Atlas\data\memos-plugin`、`D:\Atlas\data\memory_changes.sqlite3`、`D:\Atlas\data\memory_paused`、`D:\Atlas\data\outbox\`（unified_outbox）、`D:\Atlas\engine\memories\`（Hermes 内置记忆）。这些路径存在才移，不存在就跳过。
4. `data\atlas.db` 在新版首次启动时会删掉旧表。如果你能在 Atlas 重启前做，先把 atlas.db 复制一份到归档目录。
5. 确认 `D:\Atlas\engine\plugins\memory\memtensor` 和 `D:\hermes-agent\plugins\memory\memtensor` 这两个链接已经被 setup_hermes 删掉了。
6. **不要碰** `D:\Atlas\data\memory`，那是新记忆库。

### 5. 实测验收（真模型）
在 Atlas 里新建对话，问"你的记忆系统在正常运行吗"和"你都记得我什么"。合格标准：
- 回答说的是 data/memory 记忆库，没有提 MemoryOS/8099/MemOS。
- 本轮 run 日志（`D:\Atlas\data\logs\runs\<日期>\`）里没有访问 8099。
- 说一句关于自己的事实，比如"我习惯用中文写注释"，下一轮之后 `data/memory/我.md` 里能看到这一条。

## 三、交付
把结果写进 `docs/memory/PURGE-RESULT.md`：删了什么、测试结果（前后失败名单对比）、主机移动了哪些路径、实测问答原文。跑不通的就如实写，不要报"已完成"。

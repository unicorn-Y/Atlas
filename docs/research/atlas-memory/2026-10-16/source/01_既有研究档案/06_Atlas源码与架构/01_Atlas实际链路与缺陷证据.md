# 01｜Atlas `memory-v1` 源码链路与缺陷证据

**已读取且确认 HEAD：** `unicorn-Y/Atlas@7826e91c6c71dfc180f6fad6136b5eb53a9dab52`，分支 `memory-v1`。**不是默认 `main`**；此前比较显示其相对 `main` 领先 294 个提交。GitHub 链接私仓，只对有权限者有效。

## 1. 真实调用链，已经确认的部分

```text
AgentOrchestrator.run()
  core/atlas/agent/run_phases.py
   _phase_context()
       读取 engine 会话历史
       await _merge_library_recall({}, user_message) [非 worker]
           get_library()  => MemoryLibrary.recall(message)
             store.ensure() + index.sync()
             _resident_block()    [我.md, 现状.md, 它自己.md]
             _relevant_block()    [人物/事情别名匹配 + FTS 候选 + 日记关键词]
           context[system_prompt_prefix] = system_block + relevant
   _build_messages()
       SystemMessage(memory prefix)    [确实存在]
   _hermes_turn()
       SystemMessage 合并到 request_system_message
       HermesRuntime -> KernelRequest.system_message
  core/atlas/kernel/loop.py
       build_prompt(identity=system_prompt, history=...)
       kernel tool `memory_search` 通过 library.search()
  _phase_finalize()
       _schedule_library_write()  [非 worker]
           asyncio.create_task(observe_turn())  [后台]
           _write_diary(user[:2000], assistant[:300])
           _extract(...) 使用 model_mgr.model_router.complete_for(...,'memory_library',...)
           extract.apply(...) / expire(...) / store.commit() / index.sync()
```

**直接源码位置：**
- [前置与后置挂钩 `run_phases.py:L448-L502`](https://github.com/unicorn-Y/Atlas/blob/memory-v1/core/atlas/agent/run_phases.py#L448-L502)
- [系统上下文注入 `run_phases.py:L529-L545`](https://github.com/unicorn-Y/Atlas/blob/memory-v1/core/atlas/agent/run_phases.py#L529-L545)
- [实际传递到 Kernel `run_phases.py:L646-L674`](https://github.com/unicorn-Y/Atlas/blob/memory-v1/core/atlas/agent/run_phases.py#L646-L674)
- [Kernel 装配提示 `kernel/loop.py:L405-L430`](https://github.com/unicorn-Y/Atlas/blob/memory-v1/core/atlas/kernel/loop.py#L405-L430)
- [后置写入 `run_phases.py:L918-L925`](https://github.com/unicorn-Y/Atlas/blob/memory-v1/core/atlas/agent/run_phases.py#L918-L925)
- [搜索工具 `kernel/loop.py:L1984-L1996`](https://github.com/unicorn-Y/Atlas/blob/memory-v1/core/atlas/kernel/loop.py#L1984-L1996)；schema 在 `kernel/tools.py:L78-L87`。

**关键限定：** `memory-v1` 设计者称跨内核独立，源码验证了 **现有主执行路径** 接通，但没有检验所有备用执行路径、恢复路径、worker、各种模式与进程生命周期。不要把“主路径接线存在”改写为“任意内核切换 E2E 均可靠”。

## 2. 最新记忆真源与面板

```
DATA_ROOT/data/memory/                 # DATA_ROOT 可由 ATLAS_DATA_DIR 改写
  我.md                                # 常驻用户事实
  现状.md                              # 进行中/临时状态
  它自己.md                            # 自身信息，现版本以用户手动编辑为主
  人/*.md                              # 人物+别名
  事/*.md                              # 项目/事件页
  日记/YYYY-MM-DD.md                    # 每轮压缩记事
  .tombstones.jsonl                    # 禁止完全相同的旧事实复活（哈希）
  .git/                                # 本地版本历史；注意隐私、遗忘和回滚
  .index.sqlite                        # 派生 SQLite/FTS 索引；可重建
```

API：`core/atlas/api/memory_library_router.py` → `/api/memlib/{today,overview,page,changes,search,entry,add,forget,aliases,revert}`。UI：`frontend/src/renderer/components/memory/LibraryPages.tsx`，入口 `pages/MemoryPage.tsx`。`core/atlas/memory/__init__.py` 还负责会话元数据和用户提交的“资料”，并非新的长期事实核心。

## 3. 审查缺陷：问题、证据、性质、建议

### P0-A：手工编辑覆盖优先级失效（代码确认）

- `MemoryLibrary.edit_entry()` 只写 `entry.text`, `entry.src`, `entry.at`；旧 `entry.value` 及 `entry.key` 不变。
- `extract.known_facts()` 返回 `(key, value or text)`；后续模型仍看旧 `value`。`extract.apply()` 对同 key 的 `set` 无人工编辑保护。
- **后果**：UI 写“现在住北京”，结构化 `value` 仍杭州；之后自动提炼可能静默覆盖用户手改。
- **修复**：修改时将机器事实与人类覆写分离（`manual_override` + `display_text`），人工编辑变为权威记录；`known_facts` 明确优先权；冲突进入候选而非静默覆盖。不要简单用文本改写 `value` 并假设无结构差异——需要维护 key/value 的一致性语义。
- 证据：[编辑](https://github.com/unicorn-Y/Atlas/blob/memory-v1/core/atlas/memory/library/__init__.py#L244-L262)、[known_facts](https://github.com/unicorn-Y/Atlas/blob/memory-v1/core/atlas/memory/library/extract.py#L123-L135)、[apply](https://github.com/unicorn-Y/Atlas/blob/memory-v1/core/atlas/memory/library/extract.py#L237-L271)。

### P0-B：遗忘机制不能保证删除；而且存在恢复通路（代码确认）

- `forget_entry()` 删除当前页、向 `.tombstones.jsonl` 追加散列、按字面替换日记，再 `git commit`。
- 旧 Git 提交保留明文；`store.show()` 解析删除差异并返回旧事实，前端 `ChangeCard` 展示；`store.revert(sha)` 用 `git revert`，能让旧内容重新出现。`redact_diary` 只替换精确子串，漏同义描述/本轮“忘掉 X”日记，且无原始聊天/备份/同步副本全链路处理。
- **修复**：把“不要主动提起/暂停召回”与“删除本人数据”区分；彻底删除应统一覆盖事实、索引、日记、diff、快照、Git 历史和可访问副本，并明确原始会话、备份处理范围。保留不含原文的撤销不可恢复记录；历史清洗必须谨慎迁移而非任意 `git filter-repo` 冒险。
- 证据：[forget](https://github.com/unicorn-Y/Atlas/blob/memory-v1/core/atlas/memory/library/__init__.py#L278-L290)、[redact](https://github.com/unicorn-Y/Atlas/blob/memory-v1/core/atlas/memory/library/store.py#L275-L313)、[show/revert](https://github.com/unicorn-Y/Atlas/blob/memory-v1/core/atlas/memory/library/store.py#L343-L390)、[ChangeCard](https://github.com/unicorn-Y/Atlas/blob/memory-v1/frontend/src/renderer/components/memory/LibraryPages.tsx#L143-L164)。

### P0-C：完整对话承诺与后台写入不一致（代码确认）

- `_schedule_library_write()` 执行 `asyncio.create_task()`，只把任务对象放在进程内 set；`_write_diary()` 也在该协程中，而不是同步落盘队列。进程崩溃/更新时可能丢轮次。故障异常只打日志，不存储待恢复任务。
- **修复**：后置首先持久化 `(session_id,message_id,event_id,source_hash,task_status)` 入轻量队列表；L1 日记可异步消费但任务不丢；超时可重试幂等；已删除的来源事件不得回灌。
- 证据：[schedule/observe](https://github.com/unicorn-Y/Atlas/blob/memory-v1/core/atlas/memory/library/__init__.py#L154-L183)、[phase finalize](https://github.com/unicorn-Y/Atlas/blob/memory-v1/core/atlas/agent/run_phases.py#L918-L925)。

### P1-D：常驻预算会饿死“现状/它自己”（代码确认）

- `_resident_block()` 共用常量 `RESIDENT_BUDGET_CHARS=1500`，顺序 `ME, NOW, SELF`，逐项填满且无分区配额。ME 多则 NOW/SELF 可 0 条。
- **修复**：每类最小保证配额 + 共享剩余预算；当前任务/承诺优先，按 token 非字符逐步优化；按时间过滤。
- 证据：[resident](https://github.com/unicorn-Y/Atlas/blob/memory-v1/core/atlas/memory/library/__init__.py#L94-L112)。

### P1-E：过期内容会在未清理前先被读取（代码确认）

- `extract.expire()` 仅在 `_apply()` 后置写入流程调用；`recall()` 和 `_resident_block()` 未先检查 `until`。某条已失效的事实，在下一次后台写入之前仍可能注入模型。
- **修复**：所有读路径强制 `valid_at/invalid_at` 与 `until` 过滤；索引查询也带有效时间约束，不依赖后台移动动作及时性。
- 证据：[recall](https://github.com/unicorn-Y/Atlas/blob/memory-v1/core/atlas/memory/library/__init__.py#L82-L146)、[expire](https://github.com/unicorn-Y/Atlas/blob/memory-v1/core/atlas/memory/library/extract.py#L273-L298)。

### P1-F：排名后再过滤导致有效结果丢失（代码确认）

- `_relevant_block()` 先执行 `index.search(message,limit=12,kinds=('fact',))`，然后过滤 `RESIDENT_PAGES` 和 `cue_pages` 再截取 `MAX_SEARCH_FACTS=3`。如果最相关 top12 全是被过滤页面，排名 13+ 便无法入选。
- **修复**：在索引层 `exclude_paths` 或加大候选可控预算，然后分层召回/去重、最后 topK。
- 证据：[relevant](https://github.com/unicorn-Y/Atlas/blob/memory-v1/core/atlas/memory/library/__init__.py#L113-L145)。

### P1-G：`worker` 记忆加载、持久记录与归因不一致（代码确认）

- `_phase_context()` 对 `request.worker` 分支 `state.history=[];state.context={}`；`_phase_finalize()` 后置只给 `not request.worker` 调度记忆。子 Agent 可能通过工具查记忆，但其执行轨迹不自动进入长期事件知识层。
- **修复**：按 scope & task 授权只读相关记忆；worker 轨迹可写进 **主任务事件**，通过 author/parent_task/evidence ID 归属，不直接晋升用户事实。
- 证据：[context](https://github.com/unicorn-Y/Atlas/blob/memory-v1/core/atlas/agent/run_phases.py#L486-L504)、[finalize](https://github.com/unicorn-Y/Atlas/blob/memory-v1/core/atlas/agent/run_phases.py#L918-L925)。

### P1-H：只做了字面提取验证，缺“提问/假设/转述”的独立语义防线（代码确认+风险推导）

- 提炼 prompt 要求忽略假设、提问、角色扮演，且 `_quote_ok()` 检查提取的引文出现在用户消息里；但是如“假如我搬去北京”引文确实存在，LLM 若误判，硬校验不会拒绝假设语义。
- **修复**：事实标签 `asserted/hypothetical/quoted/observed/inferred/third_party`，默认只有 `asserted` 可写用户事实；更低可信候选可单列并保留证据。重点做反例集，不要求万能正则。
- 证据：[prompt/parser/apply](https://github.com/unicorn-Y/Atlas/blob/memory-v1/core/atlas/memory/library/extract.py#L35-L270)。

### P1-I：自行经历和执行过程缺少完整情景记忆（代码确认）

- 每轮日记 `用户原文[:2000]`、`assistant 最终文字[:300]`，没有把工具调用过程、失败原因、测试结果整理成统一事件卡片；“它自己”页的自动提炼能力有限。
- **修复**：以已存在的 `engine/state.db`/run logs 为原始证据，事件卡只保存 `source_ref` + 关键状态/结果，不重复保留敏感输出；分层形成 Episode/Policy/Skill。
- 证据：[diary](https://github.com/unicorn-Y/Atlas/blob/memory-v1/core/atlas/memory/library/__init__.py#L182-L195)。

### P2-J：自动召回偏词法、没有跨事件语义和关系召回（代码确认）

- `index.py` 对中文做字符片段切分，使用 SQLite FTS5 + 自建权重（词频、时间衰减、重要度）；缺事实跨事件 link、同义 embedding、多跳链接。
- **修复**：先加低成本实体、关联、证据 ID 与多线索锚点；向量召回采用可选 provider，不强制常驻大模型。
- 证据：[index.search](https://github.com/unicorn-Y/Atlas/blob/memory-v1/core/atlas/memory/library/index.py#L197-L259)。

### P2-K：来源可信度和生效区间模型尚不够完整（代码确认）

- 提炼条目含 `src, at, until, quote, key, mode, importance`，索引含 `origin_class, observed_at` 等，但不足以表达事件时间 vs 记录时间、矛盾证据、多 agent 观察和“已验证/推测”晋升限制。
- **修复**：在原始证据绑定时增加 `author_role, source_kind, observed_at, valid_from/valid_to, confidence_kind, scope, supersedes_id, forbidden_promotions`。模型自己给的 confidence 只能作为候选评分，不是信任来源。

### P2-L：无显式循环的常驻索引增长优化与追踪（代码确认的结构性风险）

- 每次 `recall` 调用 `index.sync()` 遍历记忆文件并校验 hash；_idf 统计全表 term 频度（缓存按条目数量判断，存在“同条目数量内容更新”时缓存失效须核对）。
- **修复**：做较大数据实测前不盲目改架构，先加 `p50/p95`, `index_docs`, `scan_files`, `db_size` 指标。特别留意 `_idf_cache` 在 `sync()` 变更时设 None，因此不能简单判定一定存在过期缓存。
- 证据：[index.sync](https://github.com/unicorn-Y/Atlas/blob/memory-v1/core/atlas/memory/library/index.py#L104-L135)、[index._idf](https://github.com/unicorn-Y/Atlas/blob/memory-v1/core/atlas/memory/library/index.py#L185-L196)。

## 4. 不要误判的部分

- `core/tests/test_memory.py` 主要测 legacy 会话 SQLite 存储，不等于覆盖 `atlas.memory.library` 的提炼/遗忘/巩固质量；已见 UI 部分静态渲染测试。
- `docs/memory/PURGE-RESULT.md` 记录前端 TS/Vitest 通过，但 Windows 主机旧 `MemoryOS:8099` 清理、真实模型问答、重启确认仍待完成；测试中也有已知的全局旧基线故障。因此不能说“现网已经换好”。
- `memory-v1` 分支是本次审查的真实 HEAD；`main` 落后。若施工前仓库更新，以最新分支为准并记录 SHA，避免对历史行号生搬硬套。
- “删除”范围应由用户隐私需求定义；Git 不可逆历史重写前需先确定原始日志是否同样需删除、备份保留政策，用户同意后才执行。静态审查无法确认远端/其他电脑的实际副本。

## 5. 第一阶段回归矩阵（最小但必须验证）

| 编号 | 场景 | 合格标准 |
|---|---|---|
| M01 | 事实被人工改写后又聊天 | 不会被旧 `value` 复活；冲突进候选；当前读法一致 |
| M02 | 用户要求彻底忘记一条事实 | 当前页面/FTS/日记/变动显示/可回滚路径不能继续暴露；范围记录明确 |
| M03 | 记忆提炼开始后重启 | 持久任务能够幂等恢复，不丢、不重复、不重新写已忘内容 |
| M04 | 过期计划跨日 | 首次新会话召回就不使用过期状态；历史可按授权检索 |
| M05 | 用户事实多时出现新承诺 | 现状/承诺不被个人事实预算挤出 |
| M06 | 相关命中在第 13 条以后 | 排除常驻命中后仍可召回非冗余事实 |
| M07 | “假如/问句/网页原文” | 不自动晋升为用户亲口事实 |
| M08 | 子 Agent 工具修复失败→成功 | 轨迹可归因到父任务，但不能作为用户声明 |
| M09 | 新会话问不存在事件 | 未检索到证据时明确不记得，不能编 |

**不要求数百个泛泛单测；要求这 9 个对记忆能力有直接解释力的回归。**

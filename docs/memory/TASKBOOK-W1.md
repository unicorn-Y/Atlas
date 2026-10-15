# Codex 任务书：记忆库 W1 —— 记下聊过什么、做过什么，并排除自动测试（2026-10-15）

> 写给主机上的 Codex。**一次做完，做完推送，写结果文件，不要合并、不要动 D:\Atlas。**
> 基线：`origin/memory-v1@1d4950f2`（已含 W0）。行号按这个版本。

## 为什么要做

10-15 实查主机 `D:\Atlas\data\memory`：10-14 以来进了 29 轮，提炼每轮都正常跑完，但全部是「新增 0、拒绝 0」。原因：
1. 提炼只收「用户亲口说的个人事实」，问题、任务、讨论的话题一律不记。用户问「你知道 dots 吗」「还有 Muse」，这些都没留下，下次问「我们之前聊过什么」答不上来。
2. 29 轮里约 17 轮是自动审计测试（工作目录在 `D:\Atlas\.tmp\audit-20261015\...`），把日记填满了。

本任务补上「经历」这一类（每个会话每天一条：聊了什么、做了什么、结果如何），并把测试会话挡在记忆库外面。

## 0. 工作区与边界（必须遵守）

1. 工作区已经建好：`D:\atlas-mem-w1`，分支 `memory-w1`（基于 `origin/memory-v1`），本任务书就在里面。直接在那里改。
2. **只允许改这些文件**：
   - `core/atlas/memory/library/__init__.py`、`extract.py`、`index.py`、`store.py`、`queue.py`
   - `core/atlas/agent/run_phases.py`：**只许改** `_RunState`（加一个字段）、`_turn` 里的事件循环（加一行收集）、`_schedule_library_write`。别的函数一行都不要动。
   - `frontend/src/renderer/components/memory/LibraryPages.tsx`（第 6 节，小改）
   - 新建 `core/atlas/memory/library/cleanup.py`（第 5 节）
   - 新建 `core/tests/test_memory_library_w1.py`（只放第 8 节列的场景）
   - 结果文件 `docs/memory/W1-RESULT.md`
3. 不要碰 `kernel/`、`engine/`、其它模块。主机上还有别的任务在改内核。
4. 不要动任何真实数据目录（`D:\Atlas\data\...`）。试验一律用临时目录。第 5 节的清理脚本只允许跑 `--dry-run`。
5. 不要大重构、不要改名、不要调格式。保持现有风格：注释少，提示文字用中文。

## 1. 把每轮的工具步骤和工作目录交给记忆库

现状：`_schedule_library_write`（`run_phases.py:466`）只传了用户原话和最终回复；`state.result["messages"]` 里只有最终那条 AIMessage（`run_phases.py:793`），工具过程拿不到。

改法：
- `_RunState` 加字段 `tool_steps: list[dict[str, Any]] = field(default_factory=list)`。
- `_turn`（`run_phases.py:841` 起）的 `async for event in pump:` 循环里，`yield` 之前加一行调用 `_note_tool_step(state, event)`。新写这个小函数（放在 `_schedule_library_write` 旁边）：
  - `event["type"] == "tool_call"`：追加 `{"id": event.get("id"), "name": event.get("name"), "ok": None, "note": ""}`；
  - `event["type"] == "tool_result"`：按 `id` 找到对应那条，`ok = not event.get("is_error")`，`note` = 结果内容转成文字后压成一行，取前 80 字；找不到就新追加一条；
  - 最多保留 30 条，再多就丢掉新的。整个函数包 try/except，出错只忽略，绝不能影响本轮。
- `_schedule_library_write` 给 `schedule_turn` 多传三个参数：
  - `workspace=str(state.request.workspace or "")`
  - `steps=state.tool_steps`
  - `verified=bool(getattr(state.runtime, "verification_passed", False))`
- 原有参数不变。

## 2. 排除自动测试会话（入口处直接丢掉）

在 `MemoryLibrary.schedule_turn` 最前面加判断，命中就**直接 return**（不写日记、不入队、不提炼），并 `log.info("memory.library.skipped", session=..., reason=...)`。

新增函数 `_skip_reason(workspace: str, user_text: str) -> str`（空字符串表示不跳过），规则：
1. 配置 `memory.library.skip_workspace_patterns`（正则列表），默认：
   ```
   [r"[\\/]\.tmp[\\/]", r"[\\/]audit[-_]", r"pytest", r"[\\/]Temp[\\/]"]
   ```
   `workspace` 命中任意一条就跳过，reason=`workspace`。另外，`workspace` 位于 `tempfile.gettempdir()` 之下也跳过。
2. 配置 `memory.library.skip_text_patterns`，默认：
   ```
   [r"ATLAS_AUDIT", r"^\s*\[[^\]]*(补测|审计|测试|audit|smoke)[^\]]*\]", r"这是(隔离运行|只读权限|受控的长任务)?.{0,6}测试"]
   ```
   `user_text` 命中就跳过，reason=`text`。
3. 配置读不到或正则写错时，用默认值，不能报错。

`_schedule_library_write` 里，如果 `state.request` 有 `incognito` 或类似字段就不用管，本任务不加新字段。

## 3. 「经历」：每个会话每天一条

参考 OpenClaw `src/hooks/bundled/session-memory/`（主机 `D:\_deliverables\官方拆解汇总\OpenClaw-Official-2026.10.3\03-SOURCE\` 下）：一个会话一份摘要、按日期放、无痕会话不写。Atlas 没有「重置会话」这个时机，所以改成**每轮更新同一条**。

### 3.1 存储（`store.py`）

- 新目录常量 `EPISODES = "经历"`，页面路径 `经历/YYYY-MM-DD.md`，页面标题就是日期。`Page.kind` 对这个目录返回 `"episode"`。
- `store.pages()` 要把 `经历/*.md` 也列出来（`overview`、`find_entry`、忘掉都要能找到它们）。
- 新来源常量 `SRC_EPISODE = "经历"`。它不是用户说的，任何时候都不能出现在 `我.md`。
- `Entry` 加三个可选字段（空值不写进注释，和现有字段一样）：
  - `steps: list[str]`：最多 8 条，形如 `web_search ✓`、`write_file ✗ 权限拒绝`
  - `outcome: str`：结论一句话
  - `verified: bool`：本轮有真实验证通过才为 True
- `redact_diary` 现在只处理 `日记/`，把 `经历/` 页面也一起处理（忘掉时原文不能留在经历里）。

### 3.2 提炼（`extract.py`）—— 同一次模型调用，不加调用次数

- `build_messages` 增加两个参数 `steps: list[dict]`、`verified: bool`。payload 在 ASSISTANT'S PREVIOUS REPLY 之后加一段：
  ```
  TOOLS USED THIS TURN (name, ok, note):
  - web_search ✓ 返回 8 条结果
  - (none)
  VERIFIED BY A REAL CHECK: yes/no
  ```
- `SYSTEM_PROMPT` 末尾追加一节（英文，和现有风格一致），意思如下：
  - 除了 facts，再输出一个 `episode` 对象，描述**这一轮在干什么**，供以后回答「我们之前聊过什么 / 上次那个怎么弄的」。
  - `title`：用户这轮想要什么，用户的语言，≤30 字（「问 dots、Muse 这类 AI 产品」「修 orders.py 的金额计算」）。
  - `topics`：0-5 个关键词（产品名、项目名、人名、技术名）。
  - `did`：Atlas 实际做了什么，≤60 字，只能依据 TOOLS USED 和回复，不能编；没用工具就写「直接回答」。
  - `outcome`：结论或结果一句话，≤60 字；失败或没做完要如实写。
  - `skip`：纯寒暄、「回复 ok」、只测试连通性的一轮为 true。
  - episode 不是用户事实，不受「只认亲口说的」限制，但也**不能**把 episode 里的内容写进 facts。
- `SCHEMA_HINT` 改成 `{"facts":[...同现在...],"episode":{"title":"…","topics":["…"],"did":"…","outcome":"…","skip":false}}`。
- `parse_output` 返回值改成 `(list[Proposal], Episode | None)`；`Episode` 是新 dataclass（title/topics/did/outcome/skip）。缺 episode 或解析失败就返回 None，facts 照旧。调用方一起改。
- `max_tokens` 从 1200 提到 1600。

### 3.3 写入（`__init__.py`）

- `schedule_turn` 把 `workspace/steps/verified` 存进队列；`queue.py` 的 `pending` 表加两列 `steps TEXT`（JSON）、`verified INTEGER DEFAULT 0`。**已有的 `.queue.sqlite` 没有这两列**，打开时用 `ALTER TABLE ... ADD COLUMN` 补上（先查 `pragma table_info`），不能删表。
- `observe_turn` 拿到 episode 后，在 `_apply` 里（同一个锁、同一次 commit）调用新函数 `extract.apply_episode(store, episode, steps, verified, session, now)`：
  - `skip` 为 true 或 title 为空：什么都不做。
  - 在 `经历/<今天>.md` 里找 `session` 相同的条目：
    - 没有：新建一条，`text = title + "：" + did`（≤120 字），`outcome`、`steps`（本轮的，转成 `name ✓/✗ note前20字`，最多 8 条）、`verified`、`trigger = topics[:3]`、`src = SRC_EPISODE`、`at = now`、`session`。
    - 已有：**更新同一条**，不新增。text 保留原 title，`did` 部分换成「原 did；新 did」，超过 200 字就只保留最近的；`outcome` 换成新的；`steps` 追加后保留最后 8 条；`verified` 只要有一轮为 True 就保持 True；`trigger` 合并去重留 3 个；`at` 更新为 now。
  - episode 文本过一遍 `contains_secret`，命中就不写。命中墓碑（`tombstoned`）也不写。
  - commit 信息：有新事实时照旧；只有经历变化时写「经历：<title>」；都没有就仍是「日记」。
- 专家模式（`mode == "expert"`）的经历条目带 `mode`，和事实一样。

### 3.4 索引（`index.py`）

- `_reindex`：`经历/` 下的页面，条目入库时 `kind = "episode"`，`text` 用 `text + " " + outcome + " " + " ".join(trigger)`。
- `search` 的 `kinds` 默认值不变（`("fact", "diary")`），需要经历的地方显式传。`origin_class` 对 `SRC_EPISODE` 返回一个新类别，打分权重和日记一样。

### 3.5 召回（`__init__.py`）

1. **常驻里加「最近在聊 / 在做」**：`_resident_block` 在三页之后，另起一段 `## 最近在聊 / 在做`，取最近 7 天经历页里的条目，按 `at` 倒序最多 6 条，每条 `- [MM-DD] <text> → <outcome>`，这段**单独预算 500 字**，不占原来的 1500。
2. **按话题想起来**：`_relevant_block` 在「可能相关」之后，搜 `kinds=("episode",)`，排除已在常驻里出现的条目 id，取分数 ≥ `SEARCH_MIN_SCORE` 的前 3 条，放进 `## 以前做过的相关的事`，每条带日期、text、outcome；如果 `_RECALL_INTENT` 命中，再把 `steps` 和「已验证/未验证」也带上。
3. `_RECALL_INTENT` 加上：`记得我|记住了什么|你知道我|聊过|做过`。
4. `INSTRUCTION` 加一句：「『经历』是 Atlas 根据对话自己整理的，说明聊过和做过什么，不是用户确认过的事实；回答『之前怎么做的』时，要分清哪些步骤真验证过。」
5. `_label` 对 `SRC_EPISODE` 显示「（经历 · 日期）」。

### 3.6 「今天」接口

`today()` 返回值加 `"episodes": [...]`：今天经历页的当前条目（用 `_page_dict` 里的 row 格式，加上 `outcome/steps/verified`）。

## 4. 不做的（写在结果文件里说明即可）

- 每晚整理合并（ReMe extract→integrate→finish）：先不做，等经历攒一周再看要不要。
- worker 的经历归到父任务：worker 不写记忆，父任务的步骤里已有委派那一步，先这样。
- 不改「事实」的提炼规则。

## 5. 清理已经混进来的测试数据（只写脚本，不在真实数据上跑）

新建 `library/cleanup.py`，可以 `python -m atlas.memory.library.cleanup --root <记忆库目录> --runs <data/logs/runs 目录> [--dry-run]` 运行：
1. 扫 `runs/**/*.jsonl` 每个文件的 `run_start` 事件，拿到 `session_id` 和 `workspace`；用第 2 节的 `_skip_reason` 判断，命中的 session 收集起来。
2. 再扫日记每一块的 `<!-- {"session":...} -->` 和用户原文，`_skip_reason` 命中或 session 在上面的集合里，就算测试块。
3. `--dry-run` 只打印「会删哪些块：日期 时间 session 原文前 40 字」和总数。
4. 不带 `--dry-run`：从日记里删掉这些块，经历页里删掉这些 session 的条目，然后 `store.commit("清理自动测试记录")`、`index.rebuild()`。不改写 git 历史。
5. 在结果文件里贴出对 `D:\Atlas\data\memory` + `D:\Atlas\data\logs\runs` 跑 `--dry-run` 的输出（只读，可以跑）。真正执行由 Claude 合并后来做。

## 6. 前端（小改）

`LibraryPages.tsx` 的「今天」页：在现有内容下面加一块「今天做过的事」，列 `today().episodes`：标题行是 text，下面一行灰字 outcome，`verified` 为 true 时后面加「已验证」小标签；可以点「忘掉」，走现有的忘掉接口。没有经历就不显示这一块。不要改别的页面。

## 7. 主机实测（必须做，写进结果文件）

用临时目录当记忆库（`ATLAS_DATA_DIR` 或 `memory.library.root` 指向临时目录），用主机真实模型配置，跑下面这几轮（同一个 session 前 3 句，第 4 句新 session）：
1. 「你知道 dots 吗，这一类的东西」
2. 「ai 方面的，还有 muse」
3. 「回复ok」
4. 新会话：「我们之前聊过哪些 AI 产品？」

验收：
- `经历/<今天>.md` 里**只有一条**（第 1、2 句合并，第 3 句 skip），topics 含 dots、Muse；
- 第 4 句的召回块里能看到这一条；
- 再用 workspace=`D:\Atlas\.tmp\audit-x\a` 跑一句，日记和经历都不增加，日志里有 `memory.library.skipped`；
- 「我.md」没有因为这几句多出任何事实。

贴出：经历页原文、第 4 句的 `recall()` 结果、日志相关行、`cleanup --dry-run` 的输出。

## 8. 测试（只写这些）

`core/tests/test_memory_library_w1.py`，用假模型（直接给 `parse_output` 喂 JSON 或 mock `_extract`）：
1. 同一 session 两轮 → 经历页一条，did 合并、steps 累加、verified 保持。
2. `skip: true` → 不写经历。
3. episode 缺失 → facts 照常写入。
4. `_skip_reason`：`.tmp\audit-` 工作目录、`ATLAS_AUDIT` 文本、`[Gemini真实桌面补测]` 前缀都跳过；普通的 `D:\Atlas` 和「你知道 dots 吗」不跳过。
5. 旧 `.queue.sqlite`（没有新列）能自动补列并继续工作。
6. 忘掉一条经历 → 页面、索引里都没有，`redact_diary` 也处理了经历页。
7. 常驻块里「最近在聊 / 在做」不超过 500 字，且 `我` 页的保底不受影响。

W0 的 9 个测试也要跑一遍并通过。

## 9. 交付

- 提交到 `memory-w1` 并 `git push -u origin memory-w1`。
- `docs/memory/W1-RESULT.md`：改了哪些文件、第 7 节实测的原始输出、第 5 节 dry-run 输出、测试结果、没做的和遇到的问题。
- **不要合并到 memory-v1，不要动 `D:\Atlas`。**

# Codex 任务书：记忆库 W0 可靠性补缺（2026-10-15）

> 出处：`docs/memory/REVIEW-OPUS-PACK-2026-10-15.md` 的 F 节。行号按 `memory-v1@8036b2b`。
> 写给主机上的 Codex。**一次做完，做完推送，写结果文件，不要合并、不要动 D:\Atlas。**

## 0. 工作区与边界（必须遵守）

1. 在主机新建工作区，不要在 `D:\Atlas` 里改（那是正在运行的实例）：
   ```
   cd /d D:\Atlas && git fetch origin
   git worktree add -b memory-w0 D:\atlas-mem-w0 origin/memory-v1
   ```
   如果 `D:\atlas-mem-w0` 或分支 `memory-w0` 已经存在，先停下，在结果文件里报告，不要删。
2. **只允许改这些文件**：
   - `core/atlas/memory/library/__init__.py`、`extract.py`、`index.py`、`store.py`
   - 新建 `core/atlas/memory/library/forget.py`、`core/atlas/memory/library/queue.py`
   - `core/atlas/api/memory_library_router.py`
   - `frontend/src/renderer/components/memory/LibraryPages.tsx`
   - 新建 `core/tests/test_memory_library_w0.py`（只放第 9 节的场景，不要写别的测试）
   - 本任务的结果文件 `docs/memory/W0-RESULT.md`
3. **不要碰** `run_phases.py`、`kernel/`、`engine/`，也不要碰别的模块。主机上另有 BOOT-1 任务在 `D:\atlas-boot-*` 里改内核，碰了会冲突。
4. 不要动任何真实数据目录（`D:\Atlas\data\memory` 等）。所有试验都用临时目录。
5. 不要大重构，不要改名，不要调整格式。保持现有代码风格：注释少、中文提示文字。

## 1. 手改时 value 一起改（P0-A）

**现状**：`__init__.py:255` `edit_entry` 只改 `entry.text`，`entry.value` 还是旧值。`extract.apply` 第 249 行判断"没变化"时比较的是 `old.value`。
**错误情形**：原来记的是 key=user.home_city、value=杭州；你在页面上手改成"住在北京"；之后你又说"我住杭州"，会被当成和旧值一样直接跳过，页面一直显示北京。
**改法**：
- `edit_entry`：如果 `entry.key` 不为空，同时设置 `entry.value = text`。
- `extract.known_facts`（`extract.py:129`）：`entry.src == SRC_EDITED` 时用 `entry.text`，否则仍用 `entry.value or entry.text`。

## 2. 读取时就过滤过期条目（P1-E）

**现状**：过期条目只在写入时由 `extract.expire()` 移走，读取时不检查。
**改法**：在 `store.py` 加一个工具函数 `is_expired(entry_or_until: str, now) -> bool`，`until` 为空或解析失败时返回 False。然后：
- `__init__.py` 的 `_resident_block`：跳过已过期的条目。
- `_relevant_block` 的人物/事情页那一段（第 123 行）：跳过已过期的条目。
- `index.search`（`index.py:226` 起的循环）：`row["until"]` 已过期时，如果 `include_history=False` 就跳过；为 True 就保留，并加上 `row["expired"] = True`。
- `MemoryLibrary.search` 的返回字段 `keep` 里加上 `"expired"`。
- `now` 统一用 `_now(self.config)`，并传给 `index.search(..., now=...)`。

## 3. 常驻预算每类保底（P1-D）

**现状**：`_resident_block`（`__init__.py:94-111`）三页共用一个 `used` 计数，"我"写满 1500 字后"现状"和"它自己"一条都进不去。
**改法**：
- 新增常量 `RESIDENT_FLOOR_CHARS = 400`。
- 第一遍：每页按现有排序依次放条目，每页最多放到 400 字。
- 第二遍：用剩下的预算（1500 减去第一遍已用），仍按 我→现状→它自己 的顺序，接着放各页还没放进去的条目。
- 输出格式和现在保持一致（每页一个 `## 标题` 段，空页不输出）。
- "现状"页的排序改成：有 `until` 的条目排前面，按 `until` 从近到远；然后再按重要度、时间排。

## 4. 先过滤再取前几条（P1-F）

**现状**：`_relevant_block` 第 129-130 行先取前 12 条，再排除常驻页和已经通过线索命中的页，再截取 3 条。
**改法**：
- `index.search` 增加参数 `exclude_paths: tuple[str, ...] = ()`，在打分循环里遇到 `row["path"] in exclude_paths` 就 `continue`，也就是在排序、截取之前就排除掉。
- `_relevant_block` 改成 `self.index.search(message, limit=MAX_SEARCH_FACTS * 2, kinds=("fact",), exclude_paths=tuple(skip), now=now)`，再按 `SEARCH_MIN_SCORE` 过滤，取前 `MAX_SEARCH_FACTS` 条。

## 5. 彻底忘掉（P0-B，唯一有风险的一项，按步骤做）

**目标**：忘掉一条之后，下面这些地方都不能再看到原文：页面、索引、日记、变动记录页、`git log -p` 的全部历史、提交信息。还要保证不能通过"撤销"恢复出来。

### 5.1 新建 `library/forget.py`，提供 `purge_history(store, needles: list[str]) -> dict`

写法参考 OpenClaw 的 `extensions/memory-core/src/memory-forget-kernel.ts`：先列计划，再执行，最后出报告。**不要用 filter-repo 或 filter-branch**，只用 git 自带的 fast-export / fast-import，具体步骤如下：

1. `needles`：去掉空白后长度不到 2 的不要；去重；按长度从长到短排序（防止短的先替换后，长的就匹配不上了）。
2. 如果没有 git，或者 `git log --all -p` 和 `git log --all --format=%B` 的输出里都不包含任何 needle，直接返回 `{"rewritten": False, "commits": 0}`。
3. **备份**：把整个 `.git` 目录复制到 `root/.git-before-forget-<时间戳>`（用 `shutil.copytree`）。
4. 在 root 下执行 `git fast-export --all --signed-tags=strip --reencode=yes`，拿到字节流。
5. 用 Python 解析这个流，**只改 `data <N>\n` 后面跟着的 N 个字节**（blob 内容和提交信息都在这里面）：解码成 UTF-8，把每个 needle 替换成 `（已按你的要求忘掉）`，重新编码，按新长度改写 `data <新N>`。其他行原样保留。注意：`data` 块的内容里可能本身就有以 `data ` 开头的行，所以必须按长度读取，不能按行扫描。
6. 新建一个临时目录 `root/.git-rewrite-tmp`，在里面 `git init -q`，然后把改写后的流喂给 `git fast-import --force --quiet`。
7. **检查**（任何一项不通过就删掉临时目录、保留旧 `.git`、抛出 `RuntimeError("改写历史失败，已保持原样：…")`）：
   - 新仓库的 `git rev-list --all --count` 和旧仓库的相同；
   - 在新仓库 `git log --all -p` 和 `--format=%B` 里，所有 needle 都搜不到；
   - 新仓库 HEAD 的树里，每个文件的内容和当前工作区里对应文件的内容逐字节相同。当前工作区在调用这个函数之前已经由 forget 流程抹掉了原文；要比较的文件列表用 `git ls-tree -r --name-only HEAD`。
8. 替换：把旧 `.git` 改名为 `.git-old`，把新仓库的 `.git` 移到 root 下，再删掉 `.git-old` 和临时目录。然后在新仓库里执行 `git reflog expire --expire=now --all` 和 `git gc --prune=now -q`。如果分支名和旧仓库不一样（比如 master/main），要改成和旧仓库一致。
   - Windows 注意：`.git/objects` 里的文件是只读的，`shutil.rmtree` 要带一个 onerror 回调，先 `os.chmod(path, stat.S_IWRITE)` 再删；目录改名失败时（被别的进程占用）同样按"失败、保持原样"处理。
9. 最后才删除第 3 步的备份。返回 `{"rewritten": True, "commits": <改动的提交数>, "backup_removed": True}`。
10. `.gitignore` 里加上 `.git-before-forget-*` 和 `.git-rewrite-tmp`（如果已有 `.gitignore`，没有这两行就追加进去）。

### 5.2 接到两条忘掉的路径上

- `MemoryLibrary.forget_entry`（`__init__.py:278`）：在 `store.commit(...)` 之后，在锁里调用 `purge_history(self.store, [entry.text, entry.quote, entry.value])`。返回值从 `None` 改成一个报告 dict：
  ```
  {"ok": True, "pages": [<页面路径>], "diary_pages": <日记里抹掉的页数>, "history": <purge 返回值>,
   "not_covered": ["Atlas 的原始聊天记录（engine 会话库）", "你自己做的备份或同步副本"]}
  ```
  `redact_diary` 现在返回的是改动页数，直接拿来用。
- 聊天里说"忘掉 X"走的是 `extract.apply` 的 `op == "forget"` 分支（`extract.py:226`）。`ApplyResult` 增加一个 `forgotten_texts: list[str]` 字段，把 `old.text/old.quote/old.value` 放进去；`MemoryLibrary._apply` 在 `commit` 之后，如果 `forgotten_texts` 不为空，就调用 `purge_history`。
- `redact_diary` 的 needles 里加上 `entry.value`（只在长度 ≥2 时加）。

### 5.3 变动记录和撤销

- `store.show()`：遇到等于 `（已按你的要求忘掉）` 的文本，或者通过 `tombstone_hashes("", "", text)` 命中墓碑的文本，就跳过不返回。
- `store.revert(sha)`：在执行 `git revert` **之前**，先用 `show(sha)` 拿到这次提交删掉的文本（`removed`），任何一条命中墓碑，就抛 `ValueError("这次变动里有你要求忘掉的内容，不能撤销")`。执行之后，再扫一遍所有页面的当前条目，有命中墓碑的，就 `git reset --hard HEAD~1`（只在记忆库自己的仓库里），然后抛同样的错误。
- 前端 `LibraryPages.tsx` 的 `forget`（第 73-81 行）：把提示文字改成用后端返回的报告：`已忘掉：页面、日记${n}页、${history.rewritten ? '历史记录也已改写' : '历史里本来就没有'}。没覆盖：原始聊天记录。` 路由 `/forget` 直接返回 `forget_entry` 的结果。

## 6. 后台写入持久化（P0-C）

新建 `library/queue.py`，用一个小 SQLite 文件 `root/.queue.sqlite`（加进 `.gitignore`），只有一张表：
```
pending(id INTEGER PRIMARY KEY, created TEXT, session TEXT, mode TEXT,
        user_text TEXT, assistant_text TEXT, stage TEXT NOT NULL DEFAULT 'new',  -- new | diary_done
        attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT)
```
- `schedule_turn`：先同步 `INSERT` 一行，再 `create_task(self._drain(model_mgr))`。
- `_drain`：拿到 `_turn_lock` 之后，按 id 顺序处理所有 `attempts < 3` 的行（包括以前留下的）。每一行：
  - `stage == 'new'` 时写日记，然后把 stage 改成 `diary_done`（这样补跑的时候日记不会写两遍）；
  - 再做提炼 + `_apply`；成功就删掉这一行；失败就 `attempts += 1`，`last_error` 记下错误信息。
- 日记和提炼里用的"当前时间"要用这一行的 `created`，不要用补跑时的时间，否则相对日期会算错。也就是 `_write_diary` 和 `_extract` 的 `now` 从 `created` 解析出来。
- `observe_turn` 保留，作为单行处理的内部函数，签名可以调整。外部调用方只有 `run_phases._schedule_library_write`，它只调用 `schedule_turn`，**它的参数不能变**。
- 失败超过 3 次的行保留在表里，不删除。`today()` 返回值里加一个 `"pending_failed": <行数>`。前端不用改。

## 7. 只认"你亲口说的"（P1-H）

- `SYSTEM_PROMPT` 的 OUTPUT 部分加一条：
  `- stance: "said" when the user states it as true about their own life; "hypothetical" for if/假如/假设; "question" when it only appears inside a question; "quoted" when it is someone else's words, pasted text or role-play. Only "said" facts are kept.`
- `SCHEMA_HINT` 的示例里加上 `"stance":"said"`。
- `Proposal` 加 `stance: str = "said"`；`parse_output` 读取这个字段，缺失时按 `"said"` 处理。
- `apply`：`op` 为 `set` 或 `alias` 时，`stance != "said"` 就 `rejected += 1` 然后跳过。`retract` 和 `forget` 不受影响。

## 8. 不需要做的

评审稿里原来有一条"防回流"（把 `memory_search` 的结果从提炼输入里去掉）。核对代码后发现：提炼只认用户原话里真实出现的引文（`_quote_ok`），助手回复本来就不会被当成事实来源，这一条不用做。

## 9. 验收

### 9.1 `core/tests/test_memory_library_w0.py`

用 `tmp_path` 建 `MemoryLibrary`，再写一个假的 `model_mgr`：`model_router.complete_for` 返回预设好的 JSON。**只写下面这 9 个场景**：

| 编号 | 场景 | 判定 |
|---|---|---|
| M01 | 记下 key=user.home_city、value=杭州 → `edit_entry` 改成"住在北京" → 假模型返回 set 杭州（quote="我住杭州"） | 当前条目变回杭州，北京那条进了历史 |
| M02 | 记下一条 → 做 3 次无关提交 → `forget_entry` | 页面、`search(include_history=True)`、`changes()`、`git log --all -p`、`git log --all --format=%B` 里都搜不到原文；`.git-before-forget-*` 不存在；返回报告里 `history.rewritten=True` |
| M02b | M02 之后对"记下"那次提交调用 `revert(sha)` | 抛 ValueError，页面里没有这条 |
| M03 | `schedule_turn` 之后、任务执行之前，直接新建一个 `MemoryLibrary` 实例（模拟重启），调用 `_drain` | 日记只有一条，事实已经写入，队列为空 |
| M04 | 写一条 until=昨天的现状，不触发写入，直接 `recall` | resident 里没有这条；`search` 里也没有；`search(include_history=True)` 里有，而且 `expired=True` |
| M05 | "我"页写 30 条长事实，"现状"页写 1 条 | resident 里有现状那一条 |
| M06 | "我"页放 15 条都匹配查询词的事实，人物页放 1 条也匹配的 | 可能相关的那一段里出现了人物页那一条 |
| M07 | 假模型返回 stance=hypothetical 的 set | 没有写入，rejected=1 |
| M09 | 空库，`recall("我上次说的那家店叫什么")` | relevant 为空字符串 |

（M08 是子 Agent，放到 W1，这次不做。）

运行 `cd core && python -m pytest tests/test_memory_library_w0.py -q`，再跑一遍 `python -m pytest tests -q -x -k memory`，确认没有把旧的测试弄坏。另外跑 `cd frontend && npx tsc --noEmit -p .`（如果原来就有报错，只确认没有新增报错）。

### 9.2 真实模型冒烟（可以选做，跑不了就在结果里写明原因）

SSH 会话读不到凭据库。要跑真实模型，参考 `C:\Users\25011\memlib_task.ps1`（用交互式计划任务跑 `memlib_smoke.vbs`）。可以写一个新的冒烟脚本，用 `ATLAS_DATA_DIR` 指向临时目录，跑这 4 句：
- "假如我搬去北京会怎样" → 不记
- "我住在杭州" → 记下
- "我搬到上海了" → 改成上海，杭州进历史
- "忘掉我住哪" → 页面、历史、git 记录里都没有了

## 10. 完成后

1. 在 `D:\atlas-mem-w0` 里提交（可以分 2–4 个提交），推送：`git push -u origin memory-w0`。**不要合并进 memory-v1，不要动 D:\Atlas。**
2. 写 `docs/memory/W0-RESULT.md`，并一起提交。内容包括：每一节做了什么（一两句话）、9.1 的测试输出原文、9.2 是否跑了以及结果、没做完的或者和任务书不一致的地方及原因。
3. 主机桌面放一份结果副本：`C:\Users\25011\Desktop\Codex结果-记忆W0-2026-10-15.md`。

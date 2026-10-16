# W2 修复 + 合并上线 任务书（2026-10-16）

给主机 Codex。一次做完，不要中途来问。结果写到 `docs/memory/W2-FIX-RESULT.md`。

## 0. 起点

- 新建工作区：`git -C D:\Atlas fetch origin`，然后 `git -C D:\Atlas worktree add D:\atlas-mem-w2-fix origin/memory-w2-fix -b memory-w2-fix`（本任务书就在这个分支上，它 = W2-A `aa14c317` + 本文件）。
- W2-B 界面在 `origin/memory-w2-ui@11153a02`，两者都基于 `origin/memory-w2-plan@9e70bf33`，`origin/ui-redesign` 目前停在 `0e989795`（= w2-plan 的父提交）。开工前再确认一次 ui-redesign 没被别人推进；推进了就在第 2 步改用 rebase/cherry-pick，冲突自己解。
- **不要动 `D:\Atlas` 工作区里别人没提交的改动**（web.py / kernel 等）。
- 测试原则：不写新的测试矩阵。只要求：现有 `core/tests/test_memory_library*.py` 不坏（W0、W1、W2 三组**分开跑**，一起跑会卡）；每个修复最多加 1 个小单测。

## 1. 修 6 处缺陷（都在 memory-w2-fix 分支上，每处一个提交）

### F1 Dream 全局检查点会永久跳过不满 3 天的项目组
`core/atlas/memory/library/dream.py`：`_episode_groups` 用 `entry.at <= checkpoint` 过滤，`run_dream` 结束写全局 `checkpoint=now`。某项目只出现 1–2 天、没进 output 的经历，下次运行时已经早于检查点，**永远不会再被整理**。
改法（照 ReMe Dream 的「按来源记账」思路，不搬它的框架）：
- `.dream-state.json` 改为记录**已整理的经历条目 id 集合**（`processed: {entry_id: dream_run_at}`），不再用全局时间水位。读旧格式时：把旧 checkpoint 之前、且当时已属于成熟组的条目视为已处理即可；分不清就当未处理（宁可重整一次，不能漏）。
- `_episode_groups` 改为过滤「不在 processed 里」的条目；只有真正写进项目页的组，其条目才标记为已处理。不成熟的组原样留到下次。
- 写页面 + git commit 成功后再写 state；state 用「写临时文件再 `os.replace`」原子替换。中途失败 → state 不变，下次重做；重做时同一条目写进项目页要按条目 id 去重（不要因为重跑多出一条内容一样、id 不同的记录）。
- 项目分组仍用现在的 trigger/files 名，**这次不改成稳定项目 ID**（那是后续 A2 的事）。

### F2 没有模型时，队列条目被直接删掉
`library/__init__.py::_drain`：`observe_turn` 在 `model_mgr is None` 或 `_extract_full` 里 `router is None` 时返回空结果，`_drain` 照样 `queue.remove`，这一轮就再也不会被提炼。
改法：`_extract_full` / `observe_turn` 能区分「模型没就绪」；这种情况下**只写日记（stage→diary_done），不删队列条目，也不加 attempts**，日志记 `memory.library.turn_deferred reason=no_model`。模型就绪后的下一次 drain 自然补提炼。`_model_id` 抛 `no memory writer model available` 也按这个处理。

### F3 失败 3 次后永久冻结
`library/queue.py`：`pending()` 只取 `attempts < 3`，之后只剩 `failed_count()`，没有任何恢复路径。
改法：
- 加列 `next_retry_at TEXT`（`_connect` 里照现有方式 ALTER）。`fail()` 时按 attempts 退避：1 分钟、10 分钟、1 小时、6 小时，之后每 24 小时一次；`pending()` 取 `next_retry_at IS NULL OR next_retry_at <= now`，**去掉 attempts<3 的硬上限**。
- 加 `retry_failed()`：把所有条目的 `next_retry_at` 清空。后端启动时调一次；再加一个 `POST /api/memlib/retry` 接口（`memory_library_router.py`）调它并触发一次 drain。
- `/api/memlib/stats` 里返回 `failed`（attempts≥3 的条数）和最近一条 `last_error`，界面已有 stats 就能看到。

### F4 向量不会自动建（embedding 调度拿不到事件循环）
`library/index.py::_schedule_embeddings` 用 `asyncio.get_running_loop()`，但 `sync()` 的调用方（`_merge_library_recall` 里 `asyncio.to_thread(library.recall…)`、`_apply`、`run_dream` 末尾）都在线程里，拿不到 loop，直接 return，于是 `embed_missing` 从不运行。
改法：
- `_schedule_embeddings` 在线程里时，改为用后端主循环提交：`MemoryLibrary` 在第一次 `schedule_turn`/启动时记下主 loop（`asyncio.get_running_loop()`），index 通过 `loop.call_soon_threadsafe` 或 `asyncio.run_coroutine_threadsafe` 提交 `to_thread(embed_missing)`；拿不到主 loop 就起一个 daemon `threading.Thread` 跑 `embed_missing`（同一时刻只允许一个，沿用 `_embedding_task` 的判重）。
- `embed.py`：`_attempted` 一次失败就永久放弃 → 改为失败后记时间，**10 分钟后允许重试加载**；状态仍对外暴露 `unavailable`。
- 主机 `D:\Atlas` 的 venv 要装 `fastembed`（pyproject 已加依赖），见第 3 步。

### F5 出处只靠「会话@时间戳」找最近消息
`library/sources.py::open_ref` 把 ref 拆成 `session@stamp`，在该会话所有用户消息里找时间最接近的那条——同一分钟多条消息、时区不一致时会打开错的轮次。SessionDB 已有稳定 `message_uid`（`engine/session_sync.py::latest_session_message_id / session_message_evidence`），**不要另造 ID**。
改法：
- 新 ref 格式：`msg:<session>/<message_uid>`（指向这一轮的**用户消息**）。`run_phases.py` 在保存用户消息后拿到它的 uid（用 `latest_session_message_id(..., role="user")` 或现有保存路径的返回值），传给 `schedule_turn(user_message_id=…)`，入队存一列 `user_msg_uid`；`_drain`/`observe_turn`/`_write_diary` 生成 ref 时有 uid 就用新格式。
- `session_sync.py` 加一个按 uid 定位的读取：返回该消息在会话里的下标（读 `read_session_all_messages` 后按 `id`/`message_uid` 匹配即可，不用新表）。`open_ref` 遇到 `msg:` 前缀走精确定位，后面「前后窗口、截断、工具调用展开」的逻辑复用现有代码。
- 旧 `session@stamp` 继续走原来的最近时间逻辑（老数据不迁移），返回里加 `"exact": false`；新格式返回 `"exact": true`。
- `search_raw` 返回的 ref 也改成 `msg:` 格式（它本来就拿得到消息 id）。

### F6 工具步骤只有 30 条 × 200 字的摘要，原始结果打不开
`run_phases.py::_note_tool_step`：只保留前 30 步、每步 200 字，经历里看不到完整输出，也没法回到原文。
改法：
- 摘要上限可以保留（它是给提炼模型看的），但每一步额外记 `call_id`（就是现在的 `event.get("id")`，SessionDB 工具消息的 `tool_call_id` 应该就是它——先核对是否一致，不一致就记 SessionDB 里能查到的那个）。
- 超过 30 步时不再丢弃：前 30 步照旧详细，之后只记 `{name, ok, call_id}`（不写 note），并在最后加一条 `{"name": "…", "note": "另有 N 步"}` 统计。
- `open_ref` 支持 `msg:<session>/<message_uid>#<call_id>`：定位到该工具结果消息，返回**完整输出**（单条上限从 2000 放到 20000 字，超出标 truncated）。
- 经历条目的 `steps` 里每步带上自己的 ref（`msg:<session>/<user_uid>#<call_id>`），W2-B 出处抽屉打开时就能看到这一步的完整结果；界面不用改，抽屉已经按 ref 调 `/open`。

## 2. 合并：A → 修复 → B 进 ui-redesign

在一个**临时工作区**做（不要在 D:\Atlas 里做）：
1. `git worktree add D:\atlas-merge-w2 origin/ui-redesign -b merge-w2`
2. 依次摘：`memory-w2-plan` 的 `9e70bf33`（任务书+原型）→ `memory-w2-api` 的 `aa14c317` → `memory-w2-fix` 上 F1–F6 的提交 → `memory-w2-ui` 的 `11153a02`。冲突自己解。
3. 前端：`MemoryPage.test.tsx` 还在断言旧标签（今天/人和事/提醒/资料、不能出现「时间线」），按新记忆浏览器改断言。其他前端测试失败若在 ui-redesign 原本就失败，不用管，结果里列出来即可。确认 `mockMemlib.ts` 里 `MOCK_MEMLIB_ENABLED = false`。
4. 跑：后端 W0 / W1 / W2 三组记忆测试（分开）、`npm --prefix frontend run build`（含 tsc）。都过了再 `git push origin merge-w2:ui-redesign`（必须是快进；不是快进说明别人推过，先 rebase）。

## 3. 上线到主机正在跑的 D:\Atlas

1. `D:\Atlas` 当前分支应是 `ui-redesign`，且有别人未提交的改动。`git -C D:\Atlas pull --ff-only`；若因未提交改动冲突而失败，**停下，不要 stash/reset**，在结果里写清冲突文件。
2. 装依赖：`D:\Atlas\core\.venv\Scripts\python -m pip install "fastembed>=0.7.0"`（主机有代理 127.0.0.1:7897，pip 慢就设 `HTTPS_PROXY`）。第一次加载会下载 bge-small-zh-v1.5 到 `D:\Atlas\data\cache\fastembed`。
3. 重启：先停掉现在 8765 上的后端和 Atlas 前端进程，再 `schtasks /run /tn AtlasDev`。等 `http://127.0.0.1:8765/api/health` 正常。注意 8790 那个后端是 `D:\atlas-absorb` 的测试实例，别动。
4. 看一眼（只做这几项，不搞场景表）：
   - `GET /api/memlib/stats`：有 `failed`、embedding 状态从 building 变 ready（等几分钟）。
   - `POST /api/memlib/dream` 跑一次，看 `.dream-state.json` 是新格式。
   - 在 Atlas 里正常聊一轮带工具调用的对话，等提炼完成，到记忆页时间线点这条经历的出处，确认打开的是**这一轮**（`exact: true`），点某一步能看到完整工具输出。
   - 记忆页三个主题各看一眼没坏。

## 4. 结果文件 `docs/memory/W2-FIX-RESULT.md`（提交到 ui-redesign）

写：每个 F 改了哪些文件/函数（一两行）；测试跑了什么、结果；合并后 ui-redesign 的提交号；D:\Atlas 是否成功拉取、重启；第 3.4 步看到的实际结果（贴 stats JSON 和一次 open 返回的前几行）；没做成的、发现的新问题。**没验证的别写成已完成。**

# GPT-6 独立验收｜Codex Windows Closeout（2026-10-18）

结论：**RETURN_FOR_FOCUSED_FIX，暂不切换日用 D:\Atlas**。本轮工作是真实施工和真实隔离 Windows 桌面冒烟，不能再说只有报告；但新 ATL-015 改动带来直接的记忆正确性回归，且核心行为实机验证尚不完整。

审查固定版本：`integration/atlas-fixes-20261017@5776ebe54f721fde7c52eb1372bd0f02983449e7`，相对上一轮 `f99bc248141c378a400052c24b4a1bbc1f17df8a` 新增 7 commit、16 个文件变更。仅通过 GitHub 复核源码、测试源码与 Codex 的 WINDOWS-SMOKE/ISSUE-25-STATUS/CUTOVER 证据；**我没有直接访问 Windows 主机/运行 pytest/观看现场进程，不能把文档中的通过记录说成我亲自测过**。

## 认可的新交付

1. CDP（ATL-017）已从默认 `--remote-allow-origins=*` 变为明确监听 `127.0.0.1`，保留可配置端口。Codex 在独立 Electron 里做三组 A/B，no-Origin CUA 仍能 click、Input.insertText、读取/清空输入，带模拟外部 Origin 的连接被 403 拒绝。保留用户高权限 CUA，不进行泛化权限收紧。
2. 在 Windows 独立目录 `D:\atlas-closeout-main-20261017`、独立数据根与 Electron Profile 完成 cold start（锁依赖 + 前端生产构建），本地 fake provider 输入`请只回复 ok`，Electron UI 显示`ok`与`完成`，有截图与哈希；API health 11 components ready。更新故障注入 Node 3 passed。
3. ATL-007 已为 SSH 写/patch 添加清楚的「远端编辑没有 Atlas LSP 诊断」说明，但**没有真正实现远端 LSP**，应继续 PARTIAL。
4. ATL-016 检查到当前仅一个 server-owned MemoryStore writer；多 writer 仍是条件性风险而不是“修复”。
5. A0/A3 保护措施：报告称 D:\Atlas 原工作树未动，dirty patch + untracked research + 本地配置已在 `D:\atlas-closeout-backup-20261017` 做隔离拷贝；候选 diff 存在 `core/atlas/kernel/model_call.py` 一处语义冲突。文档仍是 `NOT_DEPLOYED / READY_FOR_CUTOVER`，不是实际切换成功。

## 必须修的新增问题

### BLOCK-W1 | P1 | 最近经历召回发生明确缩进回归

文件：`core/atlas/memory/library/__init__.py::_recent_episodes`，本轮源码第 214–225 行。

旧基线 `f99bc248` 的 `entries.extend(self.store.read(rel).current)` 在 `for rel in self.store.pages()` 循环**内**。新集成版加入 `source_tombstoned(e.ref)` 过滤时，**第223行 `entries.extend(...)` 被错误去缩进到循环外**。

后果：日期过滤、episode 路径过滤虽仍在循环内，但最终只读取迭代结束后的最后一个 `rel`。如果最后一个页面是旧经历页，会错误包含过期经历；如果没有经历页，则可能把最后一个 resident/person/project 页面误当「最近经历」；如果 `pages()` 空，`rel` 未赋值还会抛错。跨日期最近经历直接丢失。

**最小修复**：把 `entries.extend(e for e in self.store.read(rel).current if not self.store.source_tombstoned(e.ref))` 放回 `for` 内正确层级；只添加 2 个独立假页面（含旧页面、recent 及非经历页面）的定向测试，断言保留多天符合截止的 episodes、排除非经历、源 tombstone 后结果正确。这个是**已通过逐行对比确认的真实回归**，不是可能性。

### BLOCK-W2 | P1 | 忘记单个事实，却排除同一轮消息的全部正常事实

`MemoryLibrary.forget_entry(entry_id)` 对有精确ref的任意一个 entry 调用 `self.store.add_source_tombstone(entry.ref,...)`。调用端是 UI 每一行上的按钮「忘掉」，而 `MemoryStore.source_tombstoned(ref)`、resident/search/cue/episode 浏览与提炼基于**整条 SourceRef(message_uid)** 过滤。

同一条用户消息常可提取多个独立事实，具有**同一个 message_uid/ref**。例如一次用户说「我使用 Windows；项目叫 Atlas」，得到 fact-A(Windows) 和 fact-B(Atlas)，两条 Entry.ref 都是 UID-1。点击 A 的「忘掉」后，B 虽仍在 Markdown、未要求忘记，却因共享整条 source 被记忆召回/索引查询一并屏蔽。已有回归仅覆盖**同文本不同 UID**，没有覆盖**同 UID 不同事实**，不能证明单项忘记正确。这个错误会造成用户看不到其想保留的其它记忆。

**最小修复方向**：区分「忘记这一条派生事实」与「排除整个来源消息」。单条事实忘记须有 scoped tombstone（至少 `SourceRef + fact key/entry stable identity/text hash`），禁止直接全 UID ban；再提炼同 UID 时只阻止已被忘记的那个 claim，保留其它非同义、同来源事实。若选择「排除整条消息」语义，必须独立显式提供，不能偷换 UI 上单事实「忘掉」。补一个**同 UID 两个不同事实、忘掉其中一个、另一个仍在 recall/search、同 UID 重提炼仍不还原前者**的定向用例。不能为解决它按裸文本删别的 UID。

### FIND-W3 | P2 | 搜索先 top-N 再删 tombstone，导致有效命中丢失

`core/atlas/memory/library/index.py::search` 先用 `merge_scores(...,limit=limit)` 截断，再执行 `results = [row for row in results if not source_tombstoned(row.ref)]`。如果用户要 top 1，但 top 1 被遗忘，排名第 2 的有效事实不会进入候选列表，最终错误返回空结果，尽管数据库仍存在正常命中。

**最小修复**：在最终 top-k 之前应用 tombstone 排除（或扩大候选并回补直到取足 k），确保原有 relevance 语义；补 `limit=1` 下最高分被遗忘、次高分仍可返回的定向测试。

### FIND-W4 | P2 | source_tombstoned 每条逐项读取整个 tombstone 文件，browse 有潜在严重性能回退

`MemoryStore.source_tombstoned` 每次执行 `TOMBSTONES.read_text().splitlines()` 再 JSON parse；`browse_search.stage` 在关键词、向量、raw 的每条候选上都调用它。原来支持10万条候选的检索，会变成10万次文件读取和反复 JSON 解码。这里是静态复杂度风险，尚未在大库计时复现，不要夸大为现场事故。

**最小修复**：一轮 search/browse/recall 调用前加载一次 source tombstone identity set（已有锁和文件）；逐候选只做集合 membership，避免每行读磁盘；写入 tombstone 后及时刷新。小规模测试比较正确性，性能可用人工合成大量候选简单验证，不跑复杂 benchmark。

## Windows 冒烟目前仍是 PARTIAL

- 隔离 Electron **曾首次因漏传 `ATLAS_PORT` 而连接上日用 D:\Atlas API**。Codex 明确承认自己主动仅请求 /api/health，renderer 可能已经发出未捕获的 startup read；未发送 chat/write 后重启到独立18765。这里不能写成“从头100%没接触日用实例”。今后隔离测试在首次启动前就要校验目标 API/data root，发现连接生产 API 直接 fail closed。
- Windows-SMOKE 有真实 Electron+fake chat+CDP A/B，但任务书要求的 503 后队列暂停、慢工具 Stop、重复 UID 引用、Dream 并发编辑，大部分仍沿用**此前定向 pytest**而非同一次 Windows GUI/E2E 流。按真实覆盖面写 PARTIAL，不必全量测试，但至少一条 503 失败 UI 卡、Stop UI/API、隔离数据 UID、Dream 并发复核补齐。先修 BLOCK-W1/W2。
- SSH Windows 测试 `core/tests/test_hermes_ssh_routing.py` 是**2 passed,1 failed**（`ModuleNotFoundError: No module named 'tools'`）。不能标该文件 PASS；可只修测试导入 `atlas.tools.terminal_scope`，再跑这个文件，不用重构 SSH 框架。
- 最新远端 `5776ebe5` 是文档小更新；主 Windows 报告固定的演示源 tip 为 `6b5da15...`。两者后续变更需简单对照，不能不加限定称整个 5776 全部已在 Windows 跑完。
- 日用切换仍有 model_call.py 语义冲突（expert 自动改写 content_filter vs 当前 terminal 规则），候选未整合到 D:\Atlas，也未关闭/替换日用进程。用户应当看到 `NOT_DEPLOYED` 而非“已上线”。

## 最小返工单（限范围，不再重做25项审查）

1. 首先修 BLOCK-W1 缩进回归与 BLOCK-W2 同 UID 单事实误忘；各补一条/两条针对性测试。
2. 同时修 FIND-W3 的 top-k 过滤次序；FIND-W4 改为读取一次 tombstone 集合，别给10万候选每项打开文件。
3. 把 SSH 的失败测试导入改正确，复跑对应文件；隔离启动前明确指定+自检 API 端口，避免再撞日用实例。
4. 用现有 isolated Windows worktree 小范围跑与本轮代码有关的测试、至少一个 GUI 错误卡和一条 Stop。保留当前 GUI/原始内核和日用数据，不允许对 D:\Atlas 执行 reset/clean/stash/checkout。
5. 把最终结果 push `integration/atlas-fixes-20261017`，更新 `tasks/results/atlas-closeout-20261017/` 报告到新 SHA，并标 `AWAITING_GPT6_RECHECK`。执行代码、测试、提交 SHA 才算交付。
6. 在此之前不执行真机切换。若用户未明确安排停机/替换，完成后仍可保留 `READY_FOR_CUTOVER/NOT_DEPLOYED`，无需耗时重造自动部署框架。

**此轮核心结论：真实隔离 Windows 冒烟有价值，CDP 也修得有证据；但是新遗忘机制对原始记忆召回存在回归，代码收尾当前不得判最终 PASS。**

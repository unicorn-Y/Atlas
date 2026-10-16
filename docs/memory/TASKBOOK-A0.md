# TASKBOOK-A0：W2 合并上线到主机 ui-redesign

状态：待执行施工合同。先完成 A0，所有 M1–M9 任务均以完成后的 `origin/ui-redesign` 为基线。任务目标是把已拆分的 W2 plan、API、指定 fix、UI 合到 `ui-redesign` 并上线到正在运行的 D:\Atlas；不在 D:\Atlas 执行合并开发。

## 0. 固定起点与保护边界

使用临时工作树（建议 `D:\atlas-merge-w2`），最终推送 `origin/ui-redesign`。执行前抓取并记录以下 refs 与提交：

- `origin/ui-redesign`：本轮已知 `0e989795`，它是 `memory-w2-plan` 的父提交；操作前重新确认远端 tip。
- `origin/memory-w2-plan`：任务书/原型，已知 `9e70bf33abcf93301987c943eb3cd15bf2ab6530`。
- `origin/memory-w2-api`：W2-A，已知 `aa14c3173392d0fc60ec3e401e4495a2d3357cb7`。
- `origin/memory-w2-fix`：仅取 F2 与 F4 各自提交；不得 cherry-pick 整个分支。
- `origin/memory-w2-ui`：W2-B，已知 `11153a028feace09e952e23544e0adf1d155887c`。

**不得在 D:\Atlas 里改代码、解冲突、stash/reset/checkout 或切分支。** 该 checkout 有他人未提交改动。所有合并、修复、构建和 Git 内容更新先在临时工作树完成；推送后在 D:\Atlas 对仓库内容唯一执行 `git pull --ff-only`。用户明确要求的运行环境操作仍在 pull 成功后按第 5 节进行：安装 fastembed 到现有 venv、重启 AtlasDev、检查 8765 与记忆页；这些操作不得改动源码或清理其他人的工作文件。

## 1. 建立临时工作树、固定 cherry-pick 序列

1. `git -C D:\Atlas fetch origin`，记录 `origin/ui-redesign` tip、工作树状态；不得因 D:\Atlas dirty 而中止临时工作。
2. `git -C D:\Atlas worktree add -b codex/memory-w2-rollout D:\atlas-merge-w2 origin/ui-redesign`。所有后续文件操作限定在此临时工作树。
3. 按顺序合并：`memory-w2-plan` → `memory-w2-api` → `memory-w2-fix` 的 F2 → F4 → `memory-w2-ui`。每一步用 `git show --stat` 确认提交内容，记录 commit/hash 和冲突处理。若 branch 含多个 fix commits，按 `git log --oneline -- core/atlas/memory/library/__init__.py core/atlas/memory/library/queue.py core/atlas/memory/library/index.py core/atlas/memory/library/embed.py` 定位并逐个 cherry-pick F2/F4 commits；禁止一次 cherry-pick 整个 fix branch。
4. F2 只保留：无模型时 `library/__init__.py` 不删除队列、`no_model` 延后日志与下一次 drain 重试。F4 只保留：embedding 从 worker thread 交由主 loop 调度，加载失败可延时重试。核对 `queue.py/index.py/embed.py` 是否包含 F2/F4 提交顺带改动，只纳入实现这两项所必需的 hunks。
5. **不做 F1/F3/F5/F6**。F1/Dream checkpoint 缺陷、F3 永久冻结队列、F5 精确消息引用、F6 完整工具结果由后续 M2–M4/相关模块替代；不能从 fix branch 间接带入这些改动。

## 2. UI 校正、mock 默认值和静态核对

1. 在临时树查找 `MemoryPage.test.tsx`，将旧标签/旧布局断言改成 W2 Memory Browser 的实际用户可见 contract；保留对加载、搜索、空态、错误与基本导航的有效检查，不扩大测试矩阵。
2. 确认 `mockMemlib.ts` 的 `MOCK_MEMLIB_ENABLED = false`。不得将 mock 设为上线默认，也不得把 mock 返回当后端证据。
3. 检查 diff 只涉及 W2 相关后端、Memory Browser、指定 page test 和结果记录。确认 UI 使用 W2 API，并且 API fallback 不会静默显示 mock 数据。
4. 记录原本测试基线与本次专属失败；不得为全仓其他旧失败顺手重构。

## 3. 最小验证（临时工作树）

按已有 W2 交付约束运行小而真实的门：W0、W1、W2 后端记忆用例分组执行，避免合并运行造成状态/耗时干扰；前端运行 `npm ci`（若临时树依赖未安装）及 `npm --prefix frontend run build`。对修改后的 `MemoryPage.test.tsx` 做对应现有测试。这里是上线所需的有限验证，不新增大测试套件。

W2-A 已有历史依据：`memory-w2-api@aa14c317` 的 8 个 W2 focused tests 曾通过；W2-B `memory-w2-ui@11153a02` 有 build/component evidence，mock 默认关闭。这些历史结果不能替代合并后复验。若本地环境缺 fastembed，不要伪称真实 embedding ready；主机安装后以运行态检查。

## 4. 推送条件

合并后的提交历史应以当时的 `origin/ui-redesign` 为祖先。再次 fetch；若远端推进，先在临时树 rebase/cherry-pick 远端新提交并解决冲突。确认 `git merge-base --is-ancestor origin/ui-redesign HEAD` 成功后才允许 `git push origin HEAD:ui-redesign`。拒绝 force push。记录推送后 `git ls-remote origin refs/heads/ui-redesign` 的 commit。

## 5. 主机 pull 与真实运行验收

只有临时分支推送成功且远端 tip 正确后，才操作主机 checkout；此处唯一允许命令为：

```powershell
git -C D:\Atlas pull --ff-only
```

若因未提交文件、冲突或不是快进而失败，立即停止对 D:\Atlas 的后续写操作；不 stash/reset/清理别人文件。报告 pull 输出和阻塞路径，由用户另行处理。

pull 成功后按下列顺序进行：

1. 安装 FastEmbed：`D:\Atlas\core\.venv\Scripts\python -m pip install "fastembed>=0.7.0"`。需要时使用已配置代理 `127.0.0.1:7897`。不替换主机模型配置或 `ATLAS_DATA_DIR`；首次模型下载目标为 `D:\Atlas\data\cache\fastembed`。
2. 确认当前 8765 backend/frontend 进程命令行归属 D:\Atlas 后，按现有 `AtlasDev` 任务流程重启：`schtasks /run /tn AtlasDev`。不要动 8790 的 `D:\atlas-absorb` 实例；不要杀来源不明的进程。
3. 获取 `http://127.0.0.1:8765/api/health`，随后检查 `/api/memlib/stats`。健康响应只代表服务可用；另确认 embedding 状态由 building 进入 ready，记下原始 JSON 和等待时间。
4. 在桌面端打开记忆页，确认真实 W2 浏览器可加载、没有 mock。进行一轮自然对话（含一次工具调用），等待记忆更新后打开时间线/来源；确认经历和引用可见。此项只验收 W2 集成，不提前验收后续 M2 的精确 UID 或 M4 的并发冲突保护。
5. 在结果中注明 model/config 实际来源、任务计划启动结果、8765 health、stats、页面打开结果及未达项。不要声称未观察的功能通过。

## 6. Atlas 路径与文件所有权

本 A0 的 merge ownership 覆盖本临时 worktree 中 W2 合并冲突、现有 `MemoryPage.test.tsx` 与 `mockMemlib.ts` 的必要修正，以及本 A0 结果文档。不得提前实现 M1–M9 的新逻辑；不得直接修改 D:\Atlas 中任何源文件。

W2 API 的实际 library 模块清单已核为 `core/atlas/memory/library/{__init__,cleanup,dream,embed,extract,forget,hybrid,index,queue,sources,store}.py`。session sync 实际为 `core/atlas/engine/session_sync.py`。A0 只合并上述 W2 路径，不以调研分支中的旧路径假设改名。

## 7. 数据兼容与回滚

不在合并时重写现有 Markdown、Git 记忆历史或 SessionDB。W2 索引/向量为派生数据，若 schema 初始化失败，按 W2 原有启动路径重建并保留磁盘原文。D:\Atlas pull 前记下现有 HEAD 和 dirty 状态；如果 pull --ff-only 拒绝，因其未改变主机工作树而停止。若合并后服务无法启动，不在脏主机做 reset；记录日志并在临时树修复、推新快进提交后再 pull。

## 8. 结果与后续基线

生成 `docs/memory/W2-ROLLOUT-RESULT.md`（随 ui-redesign 推送），至少列：起始/最终 commit、每个 cherry-pick hash、F2/F4 具体文件函数、排除 F1/F3/F5/F6、MemoryPage test/mock 变化、分组验证结果、远端快进证据、D:\Atlas pull 结果、fastembed 与任务计划、health/stats/记忆页真实观察、未通过/未验证边界。

A0 完成后，M1–M9 的唯一代码基线为合并后的 `origin/ui-redesign` commit。开发各 M 任务时从该 commit 建隔离工作树；不要继续以 `memory-w2-api` 或旧 `0e989795` 为实现基线。

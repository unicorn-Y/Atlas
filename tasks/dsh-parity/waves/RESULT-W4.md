# W4 结果

## Rows

- **E11 — CLOSED（复核既有实现）**：`GoalManager` 持久化 `goal_id` / `revision`，通过单事务 CAS 拒绝过期 writer；默认轮数上限为 256。没有为已满足项制造代码改动。
- **E17 — CLOSED**：agent definition 继续经过可信度/能力约束与 tool allowlist；native Atlas 子代理 fork 父会话已完成的 user turns，排除当前尚未结束的父轮，在 SessionDB 中记录 `_delegate_from` lineage；定义中的 prompt 以受限 persona 指引注入子任务。

## 修改文件

- `core/atlas/agent/__init__.py` — 新增 SessionDB 已完成前缀 fork；清除 branch 标记并写入 delegate 标记；对子任务提示注入 persona 指引。
- `core/atlas/agent/tool_node.py` — 把父 conversation id 和已验证 agent definition 的 prompt 传入 native 子代理。
- `core/tests/test_dsh_w4_goal_subagent.py` — 验证继承前缀排除活跃父轮、父子 lineage、delegate 标记与 persona 注入。
- `docs/parity/DSH-GAP-LEDGER.md` — 更新 E17 状态与证据摘要；E11 原状态已是 CLOSED。
- `tasks/dsh-parity/waves/RESULT-W4.md` — 本报告。

## 专项测试

命令：

```text
cd core
python -m pytest -q -p no:cacheprovider tests/test_dsh_w4_goal_subagent.py tests/test_goal_revision_cas.py
```

实际输出：

```text
......                                                                   [100%]
6 passed, 5 warnings in 9.21s
```

扩展回归命令：

```text
cd core
python -m pytest -q -p no:cacheprovider tests/test_dsh_w4_goal_subagent.py tests/test_goal_revision_cas.py tests/test_backend_parity_wave5.py tests/test_c1_lifecycle_subtask.py
```

实际结果：`21 passed, 5 failed`。失败项为 `test_parallel_atlas_workers_continue_after_one_failure`（断言预期 3 次调用，当前启动失败一次重试后为 4 次）以及 `test_c1_lifecycle_subtask.py` 中 4 个用例（测试专用 MemoryStore 初始化超时 20 秒）。这些失败没有出现在 WAVE-PLAN 已列基线清单中；未将其当作通过，也未改动相关非 W4 代码。

另行运行：

```text
python -m pytest -q -p no:cacheprovider tests/test_dsh_w4_goal_subagent.py tests/test_goal_revision_cas.py tests/test_c1_child_policy.py tests/test_subagent_settings.py tests/test_backend_parity_wave5.py::test_atlas_subtask_inherits_read_only_and_cannot_redelegate
```

实际结果：`9 passed, 2 failed`。`test_subagent_settings.py` 与 `test_backend_parity_wave5.py::test_atlas_subtask_inherits_read_only_and_cannot_redelegate` 通过；`test_c1_child_policy.py` 的 2 个用例在进入子代理调用前因 fixture 缺少 `FixtureConfig.raw` 失败。该 runtime fixture 错误不在本批文件内。

## 真实模型验证

服务使用端口 **8824**，正式配置确认选择 `deepseek-v4.1-flash`，API base 为 `https://d1api.xin/v1`。8824 结束后已关闭；8765 始终由既有桌面服务监听，未触碰。

基础回合命令：

```text
python scripts/dsh_live_ws_check.py 8824 "Reply with exactly the word: OK"
```

实际输出：

```text
[terminal] run.completed ... "model": "deepseek-v4.1-flash"
[reply] 'OK'
[result] terminal=run.completed chars=2
```

真实委派回合使用 `delegate_task` 请求 native `general` 子代理执行回复。实际事件包含：

```text
[event] tool.started name=delegate_task
[event] subtask.started
[event] subtask.completed
[terminal] run.completed ... "model": "deepseek-v4.1-flash"
[reply] '我先查找 delegate_task 工具。工具已加载，现在把子任务派发出去。SUBAGENT_PARENT_OK'
```

模型返回了完整 run 和子任务生命周期；runner 脚本未打印 child 的正文，所以没有把 child 正文或它返回的精确 token 声称为观测结果。父前缀和 persona 的具体内容由新增专项测试直接断言。

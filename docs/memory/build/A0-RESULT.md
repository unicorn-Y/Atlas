# A0 施工结果：W2 合并上线

## 范围与隔离

- 执行依据：`TASKBOOK-A0.md`、`DISPATCH-PARALLEL.md`、`VERDICT.md` 顶部「Claude 定稿」。
- 起点：`origin/ui-redesign`=`0e989795622538dfaa300db76c792d1710b71d75`；独立工作树 `D:\atlas-merge-w2`，分支 `codex/memory-w2-rollout`。未在 `D:\Atlas` 开发、解冲突、切分支或清理文件。
- 合并序列：`memory-w2-plan` → `memory-w2-api` → 本次 F2 → 本次 F4 → `memory-w2-ui`。
- 来源提交：plan `9e70bf33abcf93301987c943eb3cd15bf2ab6530`；API `aa14c3173392d0fc60ec3e401e4495a2d3357cb7`；fix 分支 `6c5240e41381a1eda4f0c8d74687c47476f95721`（仅任务书，无 F2/F4 代码）；UI `11153a028feace09e952e23544e0adf1d155887c`。
- 本分支提交：plan `79cfc994`；API `1924d7e0`；F2 `5a99b37c`；F4 `c7612daf`；UI `d35f6036`。

## 实现

- **F2**：新增 `ModelUnavailable`；模型管理器、router 或 writer model 未就绪时将轮次记为 `turn_deferred reason=no_model`，日记保持 `diary_done`，队列不删除、不增加 attempts，后续 drain 可重试。
- **F4**：`MemoryLibrary.schedule_turn` 登记主事件循环；索引从工作线程用 `run_coroutine_threadsafe` 调度 embedding；没有可用 loop 时启动单个 daemon worker；FastEmbed 加载失败后 10 分钟允许重试，外部状态仍为 `unavailable`。
- UI 默认 `MOCK_MEMLIB_ENABLED = false`；更新 `MemoryPage.test.tsx` 断言为 W2 记忆浏览器实际导航、搜索、空态、断连提示和 mock 关闭状态。
- 没有纳入 F1、F3、F5、F6，也没有提前实现 M1–M9。

## 验证

- W0：`python -m pytest tests\test_memory_library_w0.py -q --basetemp .tmp\pytest-a0-w0-retry -p no:cacheprovider --tb=short`：9 passed。第一次运行因无事件循环的兼容路径失败；修正后重跑通过。
- W1：`python -m pytest tests\test_memory_library_w1.py -q --basetemp .tmp\pytest-a0-w1 -p no:cacheprovider --tb=short`：7 passed。
- W2：`python -m pytest tests\test_memory_library_w2.py -q --basetemp .tmp\pytest-a0-w2 -p no:cacheprovider --tb=short`：11 passed，含 F2 无模型队列留存、F4 主循环线程调度与 10 分钟加载重试。
- 前端：干净验证工作树 `D:\atlas-merge-w2-verify` 中 `npm ci` 成功；`npm --prefix frontend run build` 成功；`npm --prefix frontend test -- src/renderer/pages/MemoryPage.test.tsx`：1 passed。构建存在既有 chunk-size/dynamic-import 警告。
- `git diff --check origin/ui-redesign...HEAD`：通过。差异限于 W2 文档、后端、前端记忆浏览器和对应测试。主分支内的临时 npm 依赖目录有一次 `ENOTEMPTY` 清理失败，未改变受版本控制文件；干净验证工作树复验成功。

## 推送及主机验收

- 推送前远端更新、快进祖先关系和推送后远端 tip：待执行。
- `D:\Atlas pull --ff-only`、FastEmbed 安装、`AtlasDev` 重启、8765 health/stats、桌面记忆页与真实对话验收：待推送后执行；在这些观察完成前不宣称上线通过。

结果摘要另见同目录 `W2-ROLLOUT-RESULT.md`。

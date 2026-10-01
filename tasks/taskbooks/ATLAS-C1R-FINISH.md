# ATLAS-C1R：C1 独立验收收尾

> 只有在原来的 C1 验收对话（「验收 Atlas C1 Hermes 核心」）没法继续时才用这份任务书，比如上下文满了或对话坏了。能继续的话，在原对话里发「继续」就行。
> 用「独立验收提示词」派发，任务书名写 `ATLAS-C1R-FINISH`。**验收记录仍然写到 `tasks/reviews/ATLAS-C1-HERMES-CORE.review.md`。**

## 背景

C1 的施工结果见 `tasks/results/ATLAS-C1-HERMES-CORE.result.md`。独立验收已经做完了下面这些（详见 `git log 7697e38..origin/main`）：
- 补齐 L2、L4、T10、T11、T19、S4、A1；
- 修好了：写前快照、失败显示成成功、待办同步、子任务权限取交集、图片附件、V4A 移动文件的路径检查、UTF-16、命令默认在任务目录里跑、看板锁、测试隔离；
- 主机仓库已和 origin 对齐，临时工作树已清理。

## 还剩的事

1. **主机上没提交的改动**：`core/tests/test_c1_native_checkpoints.py`（改过）、`core/tests/test_c1_websocket_acceptance.py`（WebSocket 十项端到端脚本）、`tasks/reviews/ATLAS-C1-HERMES-CORE.review.md`（验收记录草稿）。先读懂，接着用，不能丢。`design/` 是用户原有的目录，不要动。
2. **暂停后仍然请求模型**：命令已经开始执行后点暂停，命令结束后 Hermes 还会发出下一次模型请求。修好，并补回归测试：暂停后不再请求、继续后能完成、暂停中能取消。
3. **读完整文件却偶尔被判成「只读了一部分」**：找到原因并修好，补测试。
4. **Hermes 源码测试在 Windows 上的失败**：原来那份 21 项的清单已经丢了。按结果文件里写的选择集（文件读写、patch、MCP、SSH/terminal、压缩、plan prompt），在当前 fork 上重跑，逐个判断：
   - 影响 Atlas 实际使用的，在 fork 的 `atlas` 分支修；
   - 不影响的，写明理由（比如 macOS 专用路径）。
5. **全量测试**：Atlas 全量 + 前端四项检查，用脱离终端的后台进程跑完（Windows 上用 `DETACHED_PROCESS`）。
6. **WebSocket 十项端到端**：后端的启动目录也要放进临时目录，仓库里不能留下任何测试产物。十项对应 C1 任务书第 10 节。
7. **前端截图**：用无头 Edge 截对话页、改动面板、终端面板、内核设置。浏览器要拦截 8765 和外部地址。
8. **写完验收记录**，包括：
   - 结论；
   - 每个问题的「问题 / 影响 / 修法 / 提交号」；
   - CORE-PARITY 里 C1 各行逐条核对的结果；
   - 全量测试汇总行；
   - Hermes 的 Windows 测试判断表。

   提交并推送，更新 CORE-PARITY 和 `tasks/CURRENT.md`。

## 分工建议（并行）

| 子代理 | 负责 | 只改这些文件 |
| --- | --- | --- |
| A | 第 2 项（暂停）+ 第 6 项（端到端脚本） | `core/atlas/engine/hermes_runtime.py`、`core/tests/test_c1_websocket_acceptance.py`、暂停相关的测试 |
| B | 第 3 项（读文件误判） | Atlas 工具注册和策略相关文件；如果问题在 Hermes 里，就改 fork |
| C | 第 4 项（Hermes 的 Windows 测试） | 只改 fork 的 `atlas` 分支 |
| D | 第 7 项（前端截图） | 截图脚本放在系统临时目录 |

主控（验收者）只负责审查、跑全量、写记录。

## 不做

- 不合并 `wip/c3-frontend-from-laptop`，那是 C3 的参考。
- 不用真实模型。

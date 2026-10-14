# FEEL-1 手感第一轮（2026-10-14）

> 依据：主机 `data/logs/runs` 10-11~10-14 共 88 轮 + `engine/state.db` 工具结果，只统计结构与报错类别（脚本 `core/scripts/feel_scan.py`）。
> 主力模型 = DeepSeek v4.1-flash（`wb-domestic-a/b`，WorkBuddy 代理）。
> 原则：不加测试套件；改完靠日常使用 + 重扫日志验收（见文末基线表）。

## 现状一句话

内核、编辑器、执行器、防打转这些零件都是从最强的那几家移植的，本身没问题。问题出在零件跟日常用法没对上：最好的编辑工具因为没选工作区一直闲置；同一件事有好几个工具可选，模型容易挑到弱的那个；DeepSeek 吐出坏参数就整轮重来；Windows 下的 shell 引号经常出错。

---

## 1. 编辑工具统一：没工作区也用内核编辑器

**问题**：`kernel/loop.py` 只有在 `request.workspace` 非空时才创建 `EditManager`。88 轮全部没选工作区，所以 edit/write/apply_patch（读前校验 + 9 级模糊匹配）一次都没给过模型，模型只能退回到只认精确匹配的 `local_edit`（出错率 40%），或者干脆用 shell 写文件。

**改法**
- 没选工作区时，`EditManager` 以用户主目录为相对路径的基准，`allowed_paths=None`，绝对路径不受限，跟现在"权限全开"的设定一致。
- `_self_facts` 里"没工作区就请用户先选工作区"这句跟上面矛盾，改成"没有工作区：相对路径按主目录解析，可以直接用绝对路径"。
- 只要内核编辑器在，就不再给模型 `local_edit` 和 `local_edit_batch`。这两个保留注册，`tool_search` 仍能找到。`local_file` 的说明里写明：文本文件的读改写用 read/edit/write，`local_file` 只负责目录、移动、复制、删除、stat 这类操作。
- 核实 `local_file read` 确实调用了 `EditManager.note_read`，否则读完再 edit 会报 READ_REQUIRED。

## 2. 坏参数：先修，修不好就当工具报错，不再整轮重来

**问题**：`kernel/model_call.py::_tool_calls` 遇到参数 JSON 不合法，就抛 `malformed_response` 让整个模型调用重来。88 轮里一共 156 次，每次要重发约 10 万 token。另外 `finish_reason=length`（输出被截断）没有单独区分，截断的参数照样整轮重试，而重试时输出上限不变，大概率还会再截断。

**改法**
- 参数解析失败时先用 `json_repair`（mangiucugna/json_repair，MIT，加进依赖）修一次；修好了照常执行，日志记一条 `tool_args_repaired`。
- 修不好，就不抛异常，把这个调用标记成 `_arg_error`。loop 里遇到它不执行，直接回一个工具报错："参数不是合法 JSON（第 N 字符），请重发；内容太长就拆成几次 edit 或分段写"。同一轮里的其它调用照常执行。日志记 `tool_args_invalid`。
- 遇到 `finish_reason=length` 且带工具调用：不盲目重试，同样把被截断的那个调用当报错回给模型，提示它把大段内容拆小。
- 只有"根本没有可用输出"的情况才保留整轮重试。

## 3. Shell：收拢入口，按 Windows 的习惯写说明

**问题**：跑命令有 6 个入口（`local_shell`、`local_exec`、`local_process`、`exec_command`、`powershell`、`execute_code`）。`local_shell` 的报错以语法、引号、PowerShell 解析错、`python -c` 里的 Python 报错为主（1689 条结果里分别是 145/80/47/105 次）。`execute_code` 出错率 45%。

**改法**
- 默认只给模型 `local_shell`（主力）、`local_exec`（argv 调程序，避开引号）、`local_process`（后台进程）。`exec_command`、`powershell`、`write_stdin`、`TaskOutput`、`TaskStop`、`execute_code` 归入可延迟加载，不删，`tool_search` 能找到。
- 按 CC 的写法重写 `local_shell` 和 `local_exec` 的说明，写清楚具体做法：
  - Windows 下默认是 Git Bash，用 POSIX 语法；要 PowerShell 就显式写 `shell=powershell`
  - 多行代码或脚本先写进文件再运行，不要用 `python -c`/`node -e` 塞长代码，也不要嵌套引号
  - 带空格的路径加引号；参数复杂的程序优先用 `local_exec`，传 argv 数组
  - 非零退出码是结果不是故障，先读输出再决定下一步

## 4. 读文件：可以并行，也引导模型批量读

**问题**：出现过连续 146 次、103 次只读一个文件的情况。

**实施时更正**：`ToolScheduler.supports_parallel` 早就按动作判断了，`local_file` 的读操作本来就能并行。真正的原因是模型每轮只发一个调用（那轮是 166 次模型调用、171 次工具调用），调度器根本没机会并行。所以不改调度器，只改引导。

**改法**
- `local_file` 的说明写明：读操作会并行执行，需要多个文件时在同一次回复里一起发。
- 所有模型档案都带上一条通用提示："互不依赖的读取和搜索放在同一次回复里，会并行执行。"

## 5. 模型档案：从一句话升级成一份配置

**问题**：`engine/hermes_runtime.py::_model_family_guidance` 每家只有一句话，模型一换，除了这句什么都不变。

**改法**
- 新建 `core/atlas/models/profiles.py`：`ModelProfile` 按家族匹配（deepseek / claude / gpt / gemini / glm / qwen / kimi / default），字段先只放这次用得上的：
  - `guidance`：给这类模型的几条行为提示，进 system prompt
  - `stuck_thresholds`：防打转阈值，弱模型收紧一点
  - `max_output_tokens`：默认输出上限，避免工具参数被截断
- `_model_family_guidance` 改为从档案里取，调用处不用动。内核按档案构造 `StuckDetector`、决定 `max_output_tokens`。
- 第一份档案填 DeepSeek，依据本次日志：大文件拆成多次 edit；改已有文件用 edit 不用 write；多文件并行读；先写脚本文件再运行。
- 以后加新模型或者调某家，只改档案。

---

## 验收（不写测试，重扫日志）

改完推到 memory-v1，主机更新后照常用几天，再跑 `python -I core/scripts/feel_scan.py D:\Atlas\data\logs\runs` 和今天的数据对比：

| 指标（DeepSeek） | 今天的基线 | 目标 |
|---|---|---|
| malformed_response 整轮重试 | 156 次 / 88 轮 | 接近 0（换成 repaired/invalid 记录） |
| 内核 edit/write/apply_patch 使用 | 0 | 成为主要编辑方式 |
| local_edit 出错率 | 40% | 不再出现在默认工具里 |
| local_shell 出错率 | 20% | 明显下降 |
| 单工具连续 ≥3 次的轮数 | 42 / 88 | 下降（读改为并行） |
| 每轮中位耗时 | 49 秒 | 下降 |
| 每轮中位输入 token | 11.7 万 | 下降 |

## 不在本轮

界面、记忆、技能、能力面都不动；其它模型的档案先留默认值，等日志里有数据了再填。

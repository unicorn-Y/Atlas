# ATLAS-C1：换骨——接上 Hermes 内核

> 先读 `docs/plan/00-MASTER-PLAN.md`（第二、三节）、`docs/plan/CORE-PARITY.md`（第 0 节和所有标 C1 的行）、`docs/plan/EXECUTION-GUIDE.md`（第三点五、三点六节）。
> 本任务书取代 `tasks/CURRENT.md` 里的 W07 和 `ATLAS-W07B-*`（W07B 作废）。

## 本波目标

把 Atlas 的 Agent 内核换成 Hermes Agent 的内核。Atlas 的界面、事件协议，以及 CORE-PARITY 第 11 节列的已有功能全部保留，接到新内核上，**一个都不能倒退**。

做完以后，CORE-PARITY 里所有标 C1 的行都应该达到「骨架带来」那一列写的状态。

**不做的事**：
- 不做安全审查：Hermes 的智能审批（`approval_smart.py`）、危险命令检测、`tirith_security`、`skills_guard` 全部关闭；
- 不启用沙箱执行环境（docker、modal、daytona、singularity、vercel）；
- 不启用 Hermes 的渠道、网关、定时任务、看板、浏览器、语音、图像和视频生成、记忆；
- **不用真实模型跑场景**。测试用假模型服务（见第 10 节）。

## 1. Fork 和依赖（先做，单独一个提交）

1. 在用户的 GitHub 账号下 fork `NousResearch/hermes-agent` 为 `unicorn-Y/hermes-agent`（`gh repo fork NousResearch/hermes-agent --clone=false`）。没有 gh 权限就停下来，写进结果文件，让用户手动 fork。
2. 主机上把 fork 克隆到 `D:\hermes-agent`，加上游远端：`git remote add upstream https://github.com/NousResearch/hermes-agent.git`。在 fork 里建分支 `atlas`，**Atlas 对内核的所有改动都提交到这个分支**，不改 `main`。
3. **Python 升到 3.14**：Hermes 的核心依赖只对 3.14 声明（见它的 `pyproject.toml`）。
   - 在主机装 Python 3.14，重建 `core/.venv`；
   - 逐个确认 Atlas 现有依赖（`core/pyproject.toml`：litellm、DBOS、APScheduler、sherpa-onnx、PyInstaller 等）在 3.14 上能装、能 import；
   - 装不上的列进结果文件，写清影响和替代方案。不要为了凑合降回旧版 Hermes。
4. 开发时 `pip install -e D:\hermes-agent` 装进 Atlas 的 venv。`core/pyproject.toml` 写固定依赖：`hermes-agent @ git+https://github.com/unicorn-Y/hermes-agent@<atlas 分支的提交号>`。只装 Atlas 用得到的 extras。
5. 登记：`docs/plan/VENDORED.md` 加一行，写 fork 地址、上游提交号 `bafb42b` 或你 fork 时的最新提交号；`THIRD_PARTY_NOTICES.md` 附 Hermes 的 LICENSE。
6. 在 `EXECUTION-GUIDE.md` 第三点六节里，把实际用的命令补全：怎么改 fork、怎么提交、怎么更新 Atlas 里的提交号、怎么合并上游。

## 2. 引擎适配层 `core/atlas/engine/`

新建包 `core/atlas/engine/`。**先读这几处再写**：
- Hermes：`run_agent.py`（`AIAgent.__init__` 的全部参数和回调）、`agent/conversation_loop.py:1695` 的 `run_conversation`、`agent/interrupt_control.py`（`interrupt`、`steer`）、`tui_gateway/agent_callbacks.py` 和 `tui_gateway/event_publisher.py`（Hermes 桌面端怎么把回调变成事件，**照它的写法做**）；
- Atlas：`core/atlas/agent/__init__.py` 的 `run()`（第 2406 行起，现在怎么发事件）、`frontend/src/renderer/services/runtimeEvents.ts` 的 `known` 列表、`backend-adapter/src/types.ts`。

要做的：
1. `hermes_runtime.py`：每个 run 构造一个 `AIAgent`。
   - 模型、地址、密钥、推理档位、输出上限、出错切换的模型，都从 Atlas 的模型管理器（`core/atlas/models/`）取。用户现在用的是 OpenAI 兼容中转上的 `openai/deepseek-v4.1-flash`，要确认 Hermes 的自定义端点能直接用。
   - `cwd` = 会话工作目录；`session_id` = Atlas 的 `conversation_id`；`HERMES_HOME` = `<ATLAS_DATA_DIR>/engine`（不能写用户的 `~/.hermes`）；
   - `skip_memory=True`；`checkpoints_enabled=False`（检查点用 Atlas 自己的，见第 6 节）；按第 3 节设定启用的工具集。
2. 线程桥接：Hermes 的 `run_conversation` 是同步的。放在工作线程里跑，回调用 `loop.call_soon_threadsafe` 送进 Atlas 的 `event_queue`。
3. **事件映射**：把 Hermes 的每个回调对应到 Atlas 已有的事件名和字段（流式文本、思考、工具开始和结束、提问、状态、子 Agent、用量、压缩……）。
   - 已有事件**名字和字段不变**；
   - Hermes 有而 Atlas 没有的（后台进程结束通知、压缩进度、出错恢复提示），新增事件，协议升到 1.10；
   - 映射表写进结果文件。
4. 控制：
   - 停止 → `agent.interrupt()`；
   - 插话 → `agent.steer()`（替换现在的 `steer_queue`）；
   - 暂停和继续、排队、立即发送都保持原来的行为。
5. 用量事件里的 `context_tokens`、`context_limit` 从 Hermes 的 `model_metadata` 和实际用量取真实值（CORE-PARITY X8）。

## 3. 工具

1. **启用 Hermes 的**：`read_file`、`write_file`、`patch`、`search_files`、`terminal`、`process_manage`、`todo_list`、`clarify`、`execute_code`、`session_search`、`delegate_task`、工具按需加载（`tool_search`）、MCP（第 7 节）。
2. **关闭 Hermes 的**：浏览器全部、`vision_analyze`/`video_analyze`（C2 再定）、`image_generate`、`text_to_speech`、`memory`、`cronjob_manage`、`ha_*`、`kanban_*`、`computer_use`（用 Atlas 自己的）、`manage_connections`、Hermes 的技能工具（C4 再合并）、Hermes 的 `web_search`/`web_extract`（它们要第三方 key，先用 Atlas 自己的）。
3. **Atlas 自有工具注册进 Hermes 的注册表**（`tools/registry.py`，写成 Atlas 包里的模块，启动时注册，**不改 Hermes 源码**）：
   - `web_search`、`web_fetch`、`web_extract`（保留内网防护）
   - `use_skill`、`remember`、`project_sources_search`、`project_note`
   - `create_document`、`create_spreadsheet`、`create_presentation`
   - `run_checks`
   - `list_checkpoints`、`create_checkpoint`、`restore_checkpoint`
   - `kanban_*`（Atlas W07 的那套）
   - `delegate_task`、`delegate_parallel`、`subtask_status`、`subtask_message`（Atlas W07 的五家定义格式和验收留着，子 Agent 本身也跑在新内核上）
   - `computer_use`、`coding_repo_map`、`coding_ast_grep`
   - 自定义脚本工具、配方委派
   
   `read_office` 和 `local_file`/`local_edit`/`local_shell`/`local_exec`/`local_process`/`local_git` 在新内核下不再提供：功能由 Hermes 的工具覆盖。逐个核对旧工具的每个动作，看新工具有没有覆盖，没覆盖的列进结果文件。
4. **Windows 的 shell**：Hermes 在 Windows 上跑命令用的是 bash（MSYS/Git Bash，见 `tools/environments/local.py`）。
   - 在 fork 里给 `terminal` 加 `shell` 参数（`bash` | `powershell`），参照 CC 的 PowerShell 工具和 Pi 的 `packages/coding-agent/src/core/tools/powershell.ts`；
   - 默认用 bash，没装 Git Bash 时回落到 PowerShell。
5. **换行和编码**（CORE-PARITY T6）：先确认 Hermes 的 `patch`、`write_file` 在 Windows 上会不会改动 LF/CRLF 和 BOM。会改的话，照 OpenCode `packages/opencode/src/tool/edit.ts` 的处理在 fork 里修，并补测试。

## 4. 记录和会话

1. 模型看到的完整记录（包括工具调用和结果）以 Hermes 的 SessionDB 为准，存在 `<ATLAS_DATA_DIR>/engine` 下。Atlas 的 `messages` 表照旧写，供界面显示。
2. 下一轮对话把 Hermes 会话里的完整历史交给 `run_conversation`（CORE-PARITY X9）。**跨轮不能再丢工具记录**。
3. Atlas 里所有会改动历史的操作，Hermes 会话也要同步改：
   - 「回到这条之前」、修改后重新发送、重做：用 Hermes 的 `hermes_state_rewind.py`（`rewind_user_turn`）；
   - 分叉、复制一份：复制 Hermes 会话；
   - 删除对话：删除 Hermes 会话。
4. C1 之前的老对话：第一次在新内核上继续时，把 Atlas 里保存的文字历史导入成 Hermes 会话。老对话本来就只存了文字。

## 5. 提示词和上下文

1. 系统提示词用 Hermes 的三层组装（`agent/system_prompt.py`：稳定层、上下文层、易变层），**整场会话保持不变**，只有压缩时才重建（CORE-PARITY X3）。
2. 身份段改成 Atlas。保留旧提示词里有用的规则：
   - 用用户的语言回复；
   - `remember` 只在用户明确要求时用；
   - `project_note` 只记可以反复用的项目经验。
3. 规则文件：工作目录下的 AGENTS.md、CLAUDE.md、`.atlas/rules.md` 作为上下文层，沿用 Atlas 的信任确认；子目录提示用 Hermes 的 `subdirectory_hints.py`。
4. Atlas 的记忆、知识决策、失败反思、目标经验、技能索引、项目上下文：**只在会话开始时**放进易变层，不再每轮插在历史前面。内容和筛选逻辑不改（记忆冻结）。
5. 压缩用 Hermes 的 `ContextCompressor`，辅助模型默认用当前模型，设置里可以单独指定。删除旧的 `ContextMaintenance` 假压缩在新内核下的调用。`/compact`（可以带说明）接到 Hermes 的手动压缩。
6. 提示缓存交给 Hermes 处理（Anthropic 标记、OpenAI/DeepSeek 自动前缀）。Atlas 的 `prompt_caching.py` 在新内核下不再用。

## 6. 权限、审批、检查点、计划模式

写成一个 Atlas 进程内的 Hermes 插件，挂 `pre_tool_call` 钩子（见 `hermes_cli/plugins.py` 的 `VALID_HOOKS`），不改 Hermes 源码：

1. 写操作集合 = Hermes 的 `write_file`、`patch`、`terminal`、`process_manage`（写入和结束进程）、`execute_code`，加上 Atlas 自有的写工具和所有 MCP 工具（MCP 算写操作，这是之前定的）。
2. `read_only` 拦下所有写操作；`ask_writes` 发出 `approval.required` 并等待，走 Atlas 现有的审批卡片；`full_access` 直接放行。
3. 「只限工作目录」和附加目录：对文件工具的路径做同样的检查。
4. 每一轮第一次写操作之前，用 Atlas 的 `agent/checkpoints.py` 建快照，保证撤回、重做和改动面板都正常。
5. 计划模式：用 Hermes 的 `plan_prompt.py`，工具限制在只读范围（`read_file`、`search_files`、Atlas 的网页工具）。开放只读命令放到 C3。
6. 用户 Hooks（`runtime/hooks.py` 的 5 个事件）接到对应的 Hermes 钩子上，工具前 Hook 退出码 2 仍然能拦截。

## 7. MCP

Atlas 配置里的 `[tools.servers.*]` 转成 Hermes 的 MCP 配置，用 Hermes 的 MCP 客户端（支持 HTTP、OAuth、断线重连、健康检查），替换 `core/atlas/tools/mcp_client.py` 在新内核下的用途。设置页的增删和重启接口保持不变。

## 8. SSH 工作目录、worktree、子 Agent

1. SSH：先读 Hermes 的 `tools/environments/ssh.py`，确认文件工具能不能在远端用。
   - 能用：把 Atlas 的 SSH 工作目录映射到 Hermes 的 ssh 环境；
   - 不能用：本波 SSH 对话继续走旧循环，写进结果文件，C2 再解决。
2. 隔离分支（worktree）、附加目录：保持现有行为。
3. 子 Agent 和并行 Worker 都跑在新内核上，子 Agent 的权限不能超过父级。

## 9. 旧循环

- `atlas.toml` 里 `[agent] engine = "hermes"` 为默认；`"legacy"` 走旧的 LangGraph 循环，作为本波的备用。C2 删除旧循环和 LangGraph 依赖。
- 外部 Agent 执行（`runtime/backends.py`，Claude Code、Codex 等）不受影响。

## 10. 测试（不用真实模型）

用 Hermes 的假模型服务（`tests/fakes/fake_llm_provider.py`）或同类本地假服务，事先写好模型的回复脚本。至少覆盖：

1. 多轮对话：第二轮能看到第一轮的工具调用和结果；
2. 超过 10 轮工具调用不会中断（旧上限已经去掉）；
3. 把上下文上限设得很小，确认真的触发压缩，压缩后能继续干活，待办清单还在；
4. 编辑 LF 文件和 CRLF 文件，换行保持不变；
5. `read_only` 拦截、`ask_writes` 审批的通过和拒绝、只限工作目录；
6. 插话、停止、排队；
7. 写操作前建快照，「回到这条之前」同时撤回文件和 Hermes 会话；
8. 子 Agent 委派和并行；
9. MCP 工具调用（用本地假 MCP 服务）；
10. 前端收到的事件和旧内核一致（拿同一个脚本分别跑新旧内核，对比事件序列）。

另外在 fork 里跑一遍 Hermes 自己和本波相关的测试（`tests/agent/`、`tests/tools/` 里文件工具、终端、压缩相关的），确认在 Windows + Python 3.14 上能过。跑不过的列出来，并说明原因。

## 11. 前端

1. `timeline.ts`：新工具名翻译成白话步骤，例如 `read_file` → 读文件，`patch` → 修改文件，`search_files` → 搜索，`terminal` → 运行命令，`process_manage` → 管理后台进程。新事件（后台进程结束、压缩、出错恢复）有对应的显示。
2. 上下文占用显示真实的上限。
3. 设置 → 高级：显示当前内核（Hermes 或旧内核），可以切换，本波临时用。
4. 四项前端检查必须通过；用无头 Edge 截图检查对话页、改动面板、终端面板。

## 12. 交付

- 每节一个提交（fork 和 Atlas 两个仓库分别提交）；push 前 `git pull --rebase`。
- 结果文件 `tasks/results/ATLAS-C1-HERMES-CORE.result.md`，写清：
  - 每节做了什么、偏差；
  - 事件映射表；
  - 旧工具到新工具的对应表，以及没覆盖的动作；
  - Python 3.14 依赖情况；
  - SSH 的结论；
  - 全量测试汇总行原文。
- 更新 `tasks/CURRENT.md`；在 `docs/plan/CORE-PARITY.md` 里把做完的 C1 行的「Atlas 现状」改成 ✔ 并写上提交号。

## 验收清单（Sol 用）

1. fork 存在，Atlas 依赖固定到 fork 的提交号；Hermes 的核心文件没被改得面目全非：对比 fork 的 `atlas` 分支和上游的 diff，Atlas 专属的东西应该在 Atlas 仓库里。
2. 逐项检查 CORE-PARITY 里标 C1 的每一行：代码能证明、有测试覆盖。
3. 第 10 节的十项测试都在，而且断言的是真实行为，不是只断言「函数被调用了」。
4. CORE-PARITY 第 11 节的已有功能逐条检查有没有倒退（读代码 + 假模型测试 + 截图）。
5. Atlas 全量测试 + 前端四项检查自己跑一遍。
6. 不跑真实模型。

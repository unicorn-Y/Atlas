# Atlas 会话执行链路根因修复任务书（交给 Luna）

> 执行方式：Luna 按本任务书顺序实施，使用 executing-plans 的逐项执行方式；不要求子代理、多轮审查或额外方案确认。交付物是可运行的修复、必要回归和真实桌面会话证据。

**Goal：**消除当前桌面会话中可复现的命令传递故障、权限分裂、错误结果丢失、无效重试和完成状态误导，让长任务具备一流 Agent 的执行可靠性与可验证收尾。

**Architecture：**沿用 AtlasKernel、ExecManager、LocalExecutionRuntime、ToolScheduler 和 Hermes SessionDB。执行上下文在启动处确定；工具执行产生结构化事实；模型、会话存储和桌面消费同一份事实；无效循环与任务验收接入现有循环，不再建设第二套 Agent。

**Tech Stack：**现有 Python/asyncio、Windows PowerShell/Git Bash、Electron/React/Zustand；不增加数据库、框架或后台服务。

**Spec：**`D:/Atlas/artifacts/session-review-2026-10-12.md`。本任务书补充了源码核查结果，执行时以当前源码和复现证据为准。

## 1. 执行范围与完成边界

- 这是一份完整修复任务书；收到用户交办后直接执行，不先输出长计划，不把必要实现重新交给用户决定。
- 范围是“桌面会话如何干活”的基础执行链路。修复通用机制，不继续原会话中的业务操作，不下载其实际目标样本，不对业务目标做补丁。
- “根治”指下文故障类别在主调用链、兼容入口和桌面显示中闭环消失，不能承诺所有模型永远不犯错，也不能把完成本任务书宣传为整款产品已经全面超越 Codex/ZCode/Claude。
- 不通过换模型、加长 system prompt、无限重试、吞掉异常或隐藏失败来宣称修好。
- 不改模型默认值、MemoryOS、记忆摄取策略、业务技能正文或生产会话历史；不清理 inactive 转录，不回放可能已有副作用的旧工具调用。
- 不覆盖用户已有改动。规划时工作区已有 `_shots/`、`core/_shots/`、`data/cdp-shot.png` 等未跟踪文件；执行时重新检查，保留。
- 用户仍在使用 `D:/Atlas`。实现使用独立工作树（建议 `D:/atlas-session-runtime-fix`、分支 `codex/session-runtime-root-fix`），验收使用独立数据目录和端口；禁止重启、关闭或热改正在运行的生产桌面端。
- 真实桌面验收必须启动修复工作树对应的 Electron 和后端，记录来源路径；源码测试通过不能替代桌面验收。交付包含切换步骤；未切换生产时写“修复已验收、生产尚未切换”。本任务书不要求提交推送或生产重启。
- 不引入评估平台、自动审查流水线或安装器重构。只保留本任务书规定的必要验证，失败时针对根因修正并重跑相关项。

## 2. 对标什么，以及不伪造什么

| 参考 | 本次对标机制 | 落到 Atlas 的要求 |
|---|---|---|
| Codex unified_exec | 执行句柄、显式退出码、输出边界、可继续交互 | 保留现有 ExecManager；退出码/超时/取消/输出引用进入模型结果和桌面事件，不靠正文猜状态 |
| Claude Code | 明确环境与权限、工作能被实际检查、上下文不过载 | 一个真实执行上下文；小而可运行的验收；工具详情分页/按需读，不反复全量灌日志 |
| ZCode | 长任务与桌面产品共享工作区、能力、执行和任务状态 | 当前能力快照来自实际注册与配置；模型与 UI 不出现互相矛盾的完成状态 |

参考已在 2026-10-12 核查：

- [Codex exec_command 源码](https://github.com/openai/codex/blob/main/codex-rs/core/src/tools/handlers/unified_exec/exec_command.rs)、[process manager](https://github.com/openai/codex/blob/main/codex-rs/core/src/unified_exec/process_manager.rs)：参考执行合同和过程管理，不复制 Rust 子系统。
- [Claude Code best practices](https://code.claude.com/docs/en/best-practices)：参考实际可执行的检查与收尾证据；不套用每步审查流程。
- [Claude Code sandboxing](https://code.claude.com/docs/en/sandboxing)：权限与 OS 沙箱是不同层；官方文档明确原生 Windows 命令不由其 Bash 沙箱隔离。本次不得把 Python 路径校验伪称为 Windows shell 的 OS 沙箱。
- [ZCode Agent 官方文档](https://zcode.z.ai/en/docs/agent-framework)、[官方源码仓库](https://github.com/zai-org/ZCode)：参考桌面任务上下文的一致性；本文没有逐行审计其全部执行实现，不杜撰其内部策略。

验收只证明下文明确的可靠性能力，不填“与竞品胜率持平”的假指标。模型选用当前已有且可用的真实模型；对比修复前后时保持模型、任务和权限条件一致。

## 3. 已核查的链路与根因

主链路：`api/run_drive.py → engine/hermes_runtime.py → kernel/loop.py → kernel/tools.py → agent/tool_node.py → kernel/exec.py / tools/local_execution.py → SessionDB + runtime event → renderer`。

兼容入口在 `engine/tool_registry.py::_translate()`，同样必须接入修复，不能只让新工具名工作。

| 编号 | 已确认的问题/证据 | 根因定位与实施入口 |
|---|---|---|
| R1 | 消息 2746/2752/2879/2981/3017/3135/3138 等脚本失败 | `local_execution.py::_start_from_shell()` 使用 PowerShell `-Command`；命令经多层字符串/解释器传递。哪一层改变了内容尚未证明，必须先做无副作用逐层对照 |
| R2 | full_access、workspace=null 时文件写入拒绝而 shell 能写；2736/2750/2969 | `_ensure_workspace_path()` 对无 workspace 一律拒绝；`tool_node.py` 只给文件类注入 `_atlas_workspace`；执行模式与写入范围不是同一事实 |
| R3 | 部分错误正文返回 completed；工具结果状态与桌面不完整 | `LocalExecutionRuntime._result()` 固定 `is_error=False`；`ExecManager._result()` 不把 timed_out 算作错误，文本不包含 exit_code；`loop.py` 发桌面结果时仅带 state/duration |
| R4 | 改引号/临时文件后仍重复同类失败 | `StuckDetector` 已存在，但主要比较完整 arguments/result 指纹；字符串中的动态句柄、路径、日志引用会导致同类失败不相等 |
| R5 | 卡住后停止仍被汇总为完成 | `loop.py` stuck_halt 分支 break 后进入 DONE，run_end=completed；`run_drive.py` 常规收尾发送 run.completed，缺少独立的结束原因 |
| R6 | 专家模式先答“能看到”又说找不到；shell 实际默认与自述不同 | `_self_facts()` 只描述模型/源码位置等，在 Windows 硬写 PowerShell/cmd；实际 auto 可能选 Git Bash。现有能力/专家模式配置未形成准确快照 |
| R7 | 9 字节 Not Found 下载、错误平台二进制仍继续运行；3066/3153/3159 | 会话依赖模型拼下载/解压命令，未使用可复用的 HTTP/归档/平台验证合同 |
| R8 | 3166 承认缺工具却总结“完整工具链全部生效” | 回答终止等同于轮次完成；工具过程事实没有转为可核查的任务结果，缺少证据支持范围 |
| R9 | 用户询问最新性后才更正旧快照；1893/1913 | 会话观察没有明确 source/observed_at/as_of/仍在变化等信息，模型易把读取时刻当成当前实时状态 |
| R10 | 约 17 分钟才确认专家模式；错误 render 路径读三次；最短“人呢”无答复 | 有明确路径重试与等待体验问题；无答复的具体根因未知，不能用统一“卡住”结论代替定位 |

已有 `kernel/stuck.py`、`kernel/repair.py`、`kernel/context.py`、`kernel/prompt.py`、`kernel/state.py`，必须复用。SessionDB 是转录权威；`data/atlas.db.messages` 的旧数据不能作为当前会话回放源。

## 4. 统一合同：简单、明确、可追溯

### 4.1 执行上下文

在现有 run context / KernelRequest 上扩展必要字段，复用一个小的不可变类型。建议在 `core/atlas/tools/execution_contract.py` 定义；若已有等价类型，扩展它，禁止平行再造。

```python
@dataclass(frozen=True, slots=True)
class ExecutionContext:
    run_id: str
    conversation_id: str
    cwd: str
    workspace: str | None
    permission_mode: str
    allowed_roots: tuple[str, ...]
    executor: str              # local / ssh / docker，以已有值为准
    shell: str                # 实际解析后的 shell
    shell_executable: str
```

`cwd` 是相对路径解析基准，不等于权限边界。由宿主确定上下文，模型不能通过 `_atlas_*` 参数修改。兼容入口的宿主字段应覆盖模型字段，不能用 setdefault 让模型先占值。

权限决策：

- 本地 full_access：文件工具和进程工具使用用户选定的完整权限语义；无 workspace 也可以处理明确的绝对路径，相对路径统一按 context.cwd 解析。不再要求模型改用 shell 绕过文件入口。
- full_access 的只读会话观察仍遵守当前用户任务范围；权限不等于额外授权。
- Plan/read_only：原生写工具和进程写能力不得放开；沿用已有工具过滤/执行器能力。没有可靠 OS 隔离时，不向模型承诺任意 shell 是“只读”的。
- workspace 限制/SSH/Docker：复用现有受限执行器和挂载边界；无可靠执行器的限制模式应明确拒绝相应执行能力，而不是靠 shell 文本正则假装隔离。full_access 不受此拒绝牵连。
- 路径用现有 resolve/平台路径语义校验；copy/move 两端都校验；删除工作区根、盘符根等保留现有专门保护。不要为修 R2 无差别删除所有校验。
- 会话之间不得共用可变 cwd 或授权结果。运行中已支持的权限切换必须在后续调用重取宿主授权，不靠旧快照扩大权限。

### 4.2 工具结果

保留现有外层 `data/content/is_error` 兼容结构；统一生成结果，不增加第二套通用插件协议。

```python
def normalize_execution_result(data: dict[str, Any]) -> dict[str, Any]: ...
def render_execution_result(data: dict[str, Any], max_chars: int = 8000) -> str: ...
```

现有 data 至少明确：`execution_id/state/outcome/exit_code/timed_out/cancelled/stdout/stderr` 或有标识的合并 output，以及 `output_ref/truncated`。必须区分 stdout 和 stderr 是否被合并；不得把合并结果标成 stdout。

| 情况 | is_error | 含义 |
|---|---:|---|
| running | false | 仅进程仍运行；返回句柄，不宣称任务成功 |
| exited + exit_code=0 | false | 进程执行成功；不自动证明业务验收通过 |
| exited + exit_code!=0 | true | 命令失败，保留真实码 |
| spawn_failed / denied / timed_out / unknown | true | 分类明确；unknown 不自动重放副作用 |
| cancelled | true | 工具未成功结束；由外层 run.cancelled 处理用户停止，不能改成 run.failed |

状态值尽量沿用已有枚举；兼容映射集中在一个函数。用户执行 grep 得到 exit=1 仍应保留真实结果，由模型理解“无匹配”，不得针对命令隐瞒非零码。超时优先用 timed_out 标志，不能伪造实际 OS exit_code；如果已有兼容层需码 124，另写合成原因并保留实际码。

shell exit=0 且输出含 Error，并不天然是命令失败。禁止用全文关键词正则重写状态，禁止把业务错误伪装成 OS 错误。HTTP/归档错误在专门工具里由实际返回值判定。

### 4.3 运行结束与任务验收

保留 `run.completed` 表示一轮正常结束，但新增受限的 payload：

```json
{
  "termination_reason": "answer | task_finished | stuck | approval_denied | tool_blocked | empty_response",
  "task_outcome": "verified | partial | blocked | unverified",
  "evidence_refs": [],
  "remaining": []
}
```

这不是新增 run 生命周期枚举。取消/基础设施异常沿用 run.cancelled/run.failed。普通闲聊为 answer，不需要任务验收；无效循环停止为 stuck/blocked；模型没工具调用而返回空白为 empty_response，不能静默“完成”。前后端和持久化使用同一值，未知旧事件按兼容轮次结束显示，禁止升级成 verified。

## 5. 实施步骤（顺序执行，每步都有可见成果）

### T0 — 复现并标定实际执行路径

**读文件：**`core/atlas/engine/hermes_runtime.py` 的 AtlasKernel 分支，`kernel/loop.py` dispatch，`kernel/exec.py`，`agent/tool_node.py`，`engine/tool_registry.py::_translate()`；只读相关函数。

- [ ] 建立独立工作树和数据目录；记录 HEAD、已有改动、真实桌面启动来源、源码/Hermes 依赖版本。
- [ ] 用无害脚本复现 R1：中文、空格路径、单/双引号、`$`、反斜杠、真实换行、字面量 `\\n`、PowerShell here-string、Python 字典/for 循环。比较模型工具 arguments 经单次 JSON 解码后、alias 转换后、解释器实际输入的字节/摘要；不执行历史业务命令。
- [ ] 输出一张短表：哪个入口、哪一层变化、原样输入能否执行。区分“模型本来就给错语法”和“宿主传递破坏正确语法”。生产参数含凭据时只记脱敏摘要/哈希，不额外持久化 token。
- [ ] 检查只剩用户“人呢”的会话对应 run 记录与当时日志，归类为未启动/取消/provider 错误/空响应/存储缺口之一；无证据就保留 unknown，并通过后面的新会话验收覆盖空响应路径。不得编造旧问题已定位。

**产物：**交付报告中的一页根因表，无独立大审计报告。复现若证明某项已有新修复，保留验证，不重复实现。

### T1 — 修复执行上下文和无损脚本入口

**修改：**`tools/local_execution.py`、`agent/tool_node.py`、`engine/tool_registry.py`、`kernel/exec.py`、`kernel/loop.py` 必要调用点；`api/run_drive.py` 仅上下文构建点。**新增最多：**`tools/execution_contract.py`。

- [ ] 将 4.1 上下文贯穿直接工具、kernel ExecManager 和 alias；保护宿主私有字段。消除文件工具和 shell 在 full_access/no-workspace 下的不同决策。
- [ ] 单次 JSON 解码后 command/content/argv 都保持原字符串。禁止 `unicode_escape`、重复 json.loads、全局替换 `\\n` 为换行、去引号或“智能修复”内容。
- [ ] PowerShell 命令通过 UTF-16LE `-EncodedCommand` 或宿主写入的原样脚本执行，避免 Windows `-Command` argv 引号转换；优先选已存在 pwsh，再兼容 powershell.exe，具体选择在上下文公布。不改变明确指定的 Bash/cmd 入口。
- [ ] 保留正常 local_exec 的 argv 方式；为已有 local_exec 增加可选 `script` 与 `script_language`（python/javascript/powershell/bash）。script 模式使用宿主原样 UTF-8 文件 + 解释器 argv；解释器与 language 必须匹配，args 是脚本参数，不再让模型拼 `python -c` 的多层 shell。
- [ ] 新参数必须同时进入 `LOCAL_TOOLS` 的 local_exec schema、校验函数和实际调用；`engine/tool_registry.py` alias 转换不得丢字段。脚本模式不把解释器路径写死在用户机器路径里，用本轮发现的实际 executable。
- [ ] 例：`local_exec(executable="<已发现的python>", script_language="python", script="print('中文 \\"引号\\"')\n", args=[])`。由宿主拼执行 argv；PowerShell -File 使用兼容 Windows PowerShell 5.1 的编码，Bash 脚本使用 LF；保留原文可回读。
- [ ] 脚本落在 run 私有目录，宿主内部写入与用户文件修改分开；每次执行独立文件，读完后按当前进程生命周期清理。运行中的脚本不能被提前删除；回放只展示参数，不重新执行。
- [ ] shell 结果尊重真实 shell 退出语义。不要全局注入 Bash set -e/pipefail、PowerShell 强制 Stop 或 cmd 自动 && 改变用户脚本；为模型提供准确的失败传播使用说明。需要多步骤原子失败时用明确脚本检查/专门下载工具。

**可见成果：**同一中文复杂脚本走直接/alias/kernel 均执行正确；无 workspace 的 full_access 用原生文件工具写入成功，不再依赖 shell 绕路。

### T2 — 贯通真实结果和结束原因

**修改：**`tools/local_execution.py::_result/_wait_result`、`kernel/exec.py::_result/_poll_locked`、`kernel/tools.py::is_error/_execute`、`kernel/loop.py::consume_tool_results/收尾`、`api/run_drive.py::事件映射/收尾`；前端 `services/runtimeEvents.ts`、`components/timeline.ts`、`store/useAtlasStore.ts` 只改相关字段映射与文案。

- [ ] 按 4.2 单点规范结果；模型文字也含 state、exit_code、timed_out 和 output_ref，不只写“Process completed”。保持 bounded 输出，保留完整日志按需读取。
- [ ] tool_result 桌面事件携带相同 execution 字段；持久化 metadata 保存错误分类/退出码/输出引用/receipt，不丢成纯成功文本。沿用 SessionDB display_metadata，不另开消息表。
- [ ] stuck_halt、PostToolBatch blocked、权限拒绝、空白最终响应都带正确 termination_reason；普通成功处理不改成异常。失败/超时/停止的工具卡状态与实际结果一致。
- [ ] UI 分开显示“本轮已结束”和“任务验收通过/部分完成/受阻/尚未验证”，普通聊天保持自然文案；run.completed 不再一律提醒“任务已完成”。
- [ ] 空响应最多一次恢复请求；仍空则给明确异常和结束原因，保留真实 provider 事件，避免无限续跑。

**可见成果：**exit=7、超时、用户取消、stuck 停止均不会被画成成功；正常返回与后台句柄继续工作。

### T3 — 让现有停滞检测识别同类失败，并能恢复进展

**修改：**`kernel/stuck.py`、`kernel/loop.py`；复用 execution_contract 的错误码，不新增 RetryManager。

- [ ] 结构化错误码先覆盖宿主能准确判断的 `PATH_NOT_FOUND/PERMISSION_DENIED/SPAWN_FAILED/EXEC_TIMEOUT`；语法错误只对本次解释器执行的诊断做有限分类。通用 shell 未知错误保持未知，不全文扫描业务输出定罪。
- [ ] 指纹区分动作与失败原因：忽略元数据中动态 id/duration/output_ref；对正文中的动态句柄只处理宿主生成的固定尾部，不删除用户真实输出中的数字或路径。
- [ ] 同一工具类别、同一已解析目标、同一错误连续三次 → 一次 recovery notice，给最后原因和可用下一步（例如先 glob/list 查真实路径，先回读脚本再执行）；改变诊断前提必须实际有新工具证据。
- [ ] 提醒后同一原因又失败两次且没有新前提证据 → 当前轮以 stuck/blocked 结束，保存剩余问题；不得反复向模型发同一提示。
- [ ] 未能可靠提取目标时，仅 exact action+result 触发现有硬停止；同一错误类别但不同目标仅提示诊断，不强行截断整项任务。
- [ ] running 状态的正常 wait/poll、输出仍在增长的进程、读取不同 offset 的日志不计作无进展循环。有效诊断/成功修正重置对应失败窗口；不要让一次历史 nudge 使后续正常任务过早 halt。
- [ ] 保留未知副作用修复 `repair.py`：unknown 先检查当前状态，不能以“重试收敛”为由自动重跑安装/写盘等操作。

**可见成果：**错误路径不会读第三、第四遍后还毫无诊断；错误引号不会换个临时文件名就规避检测；长进程正常等待不被误杀。

### T4 — 提供准确能力快照、观察时刻与等待反馈

**修改：**`kernel/loop.py::_self_facts/assemble_prompt`、`kernel/prompt.py`；调用 `expert_mode.py::is_enabled/installed/list_items`、现有工具/技能/MCP 注册器；必要时 `api/run_drive.py` 和 `services/runtimeEvents.ts` 的现有 phase/recovery 显示点。

- [ ] 宿主生成小快照：实际 cwd/workspace、解析后的 shell 与 exe、平台、权限/执行器、当前可调用工具名、专家模式 enabled 和已装项数量/目录、读取自身能力的入口。只放摘要，完整清单按需读取，不把所有技能全文灌系统提示词。
- [ ] UI 开关/专家模式热加载或权限变化后，下一轮模型请求重取/更新快照；源文件目录与运行包目录分开写，打包态不得称源码 checkout 永远可编辑。
- [ ] 非全局可变快照；不把某会话的专家配置/目标/cwd泄漏到另一会话。配置内容和凭据不进入快照。
- [ ] 现有会话读取/搜索结果附 `source/observed_at/as_of`，若无可证明的 last_updated 就写 unknown。用户要求“最新”时至少重新读取并声明截止时间；任意外部日志用本次读取的文件 stat 和范围，不声称实时尾随。
- [ ] 现有 run.phase/工具开始/恢复事件展示“等待模型/运行工具/等待输入/诊断失败”。没有新进展只显示持续时长和最后已知活动，不周期性编造进度消息，不强制每分钟额外调用模型。
- [ ] 连续 provider 重试、工具长等待能够给用户已有事实反馈；不要为消息 2937 的催促建设新监控服务。

**可见成果：**问“你这里有专家模式吗”先根据快照回答；默认 shell 与实际执行一致；观察会话报告时间明确，用户能分辨正在等待与已经卡停。

### T5 — 消除下载/归档安装的基础陷阱

**新增或复用：**若已有等价下载执行入口则扩展它，否则新增 `core/atlas/tools/download.py`，注册一个 `local_download`；复用既有 HTTP 客户端、路径授权和工具注册方式。不是软件包管理器。

注册位置采用 `kernel/tools.py::kernel_tool_schemas()`，在 `kernel/loop.py` 的统一 dispatch 接到 download 模块；兼容入口按现有注册方式指向同一 handler。更新 READ_ONLY_TOOLS/Plan 模式过滤，下载属于写入，不误登记为只读；工具搜索与实际 schema 来自同一注册结果。

```text
local_download(url, destination, sha256?, expected_format?, timeout_s?)
→ status/http_status/resolved_url/bytes/sha256/format_valid/output_ref
```

- [ ] 仅 http/https，流式写到同目录 .part；检查最终 HTTP 2xx、实际数据非空、Content-Length（有时）一致、预期格式 magic/header；校验通过原子 rename，失败不把 HTML/Not Found 伪装成 zip/exe。超时/取消清理本次 .part，不删除旧有效目标。
- [ ] 重定向和现有代理使用同一 HTTP 配置，不另存账号；遵守 context 权限。不自动执行下载结果、不自动提权、不碰生产专家工具目录。
- [ ] zip/tar 验证可实际遍历并确认完整；归档路径不能越过目标根，拒绝绝对路径/.. 穿越；不能只看后缀或设“文件大于 1MB 就有效”。7z 用已有 7z 测试入口，未装时明示未验证。
- [ ] 可执行文件至少识别 PE/ELF/Mach-O 和宿主架构；PE 还需读取机器类型，不能只用 MZ 判 Windows x64 可运行。平台匹配只是必要条件，最后由安全的 version/help 真实启动检查确定是否可用。
- [ ] 不创建通用“自动修文件”或通用安装 DAG。模型安装流程使用 local_download → 验证归档 → 明确解压 → local_exec argv 版本检查；任何一步失败都不得把该项登记为可用。
- [ ] 工具名称来自结构化 manifest 的 name/id 与现有 schema，布尔 enabled 不能当工具名；没有清单的项目先查真实 release 资产再下载，不凭模型记忆拼 tag。

**可见成果：**本地验收 HTTP 服务返回 404、HTML、截断 zip 或不匹配平台时，在执行前明确失败；合法小归档仍通过。无需下载整套真实业务工具验证基础机制。

### T6 — 用证据支持收尾，不能仅靠一句“完成”

**修改：**`kernel/loop.py` 与 `kernel/tools.py` 的工具注册/派发；复用现有 plan/todo 和 tool receipts；`api/run_drive.py`、前端消费 T2 结果。**必要时新增一个小模块：**`kernel/completion.py`，不建设通用评价框架。

提供一个轻量 `report_task_result` 工具，只针对执行型任务调用，普通问答不要求：

```text
report_task_result(outcome, scope, evidence_refs, remaining)
outcome ∈ verified / partial / blocked / unverified
evidence_ref = 本 run 的 tool_call_id / 宿主登记的验证记录
```

schema 放在 `kernel/tools.py::kernel_tool_schemas()`，handler 接统一 dispatch。结果以 SessionDB 的工具消息及 metadata 保存，在下一轮/压缩时通过现有 session/context 恢复；不能只放当前 Python 对象里，导致续接后丢掉失败项。保存与报告保留原始用户目标文本；模型提交的 scope 是结果说明，无权覆盖用户目标。

- [ ] 用户要求的范围沿用请求与现有 plan；若任务确实是清单，保存全部要求项，不让模型悄悄删掉失败项。用户明确改变目标才更新范围。
- [ ] verified 必须有本轮相关验证工具证据；引用存在只是最低条件，业务目的要求的检查要具体说明，例如文件写后回读、工具安装后版本检查、UI 操作后观察实际页面。单纯进程 exit=0、文件存在、技能入索引不能自动作为所有业务成功的证明。
- [ ] 验证记录至少有 subject、check、expected、actual、tool_call_id、observed_at 和 pass/fail/unknown。pass 必须由实际检查结果支撑；模型自报 pass、仅引用任意成功工具都不够。无需判据解析大框架：对本次支持的文件回读/命令退出/平台格式等确定性检查直接比较；任意业务效果不能机器确定时保留 unverified，并展示观察证据，不冒充通用裁判。
- [ ] 明确清单任务的 required 项仍 failed/unknown/pending 时拒绝整体 verified；报告 partial/blocked 并显示剩余项。失败已被后续有效检查解决时不永久拖成 partial，以后续证据更新同项状态。
- [ ] 如没有显式清单或可机器核验的判据，允许模型给自然答复，但宿主 task_outcome 保持 unverified；不使用中文“全部/完整”关键词黑名单篡改回答，也不宣称能确定所有自然语言目标的真实性。
- [ ] 用户反馈“还是不行”写入当前任务结果，使先前 verified 失效并触发诊断；不必删除旧证据。续接/压缩时保留未解决项、最后验证和未知副作用，用现有 context/session_sync，不重新灌全部工具历史。
- [ ] 执行任务未提交结果而试图结束：最多一次结构化提醒；仍未提供证据则 unverified 收尾。不得额外建裁判模型，每轮多花一次 LLM 调用。
- [ ] 让验证事实直接进入 UI/通知/持久化。模型自然语言仍可能过度自信，宿主的可信验收状态不能跟着猜；报告中如仍出现误导措辞，真实模型验收算失败并修正提示/证据反馈链路。

**可见成果：**“三项工具中一项失败”会明确部分完成；正常修复成功有可查看证据；普通“在吗”立即自然回答，无验收官腔。

## 6. 文件边界与防止代码堆积

预计新增产品模块最多三个：`tools/execution_contract.py`、`tools/download.py`、`kernel/completion.py`。不是为了凑三个，已有职责能容纳就复用；若确需超出，在交付说明具体职责与不能复用的原因，不偷偷铺框架。

- `execution_contract.py` 只负责上下文/结果合同与格式化；不能变成运行器或全局状态仓库。
- `download.py` 只负责传输与制品验证；不负责管理工具清单、安装调度或业务技能。
- `completion.py` 只负责依据当前 receipts 校验任务结果；不复制 goal/automation/MemoryOS。
- 大文件 `loop.py/run_drive.py/tool_node.py` 只接线和删除被新单点取代的本次重复逻辑，不扩大成整文件重构；新策略主体放在上述小模块或现有对应模块。
- 不给每种 stderr 文案建一条 regex、不按消息 id/用户词句/具体软件名特判、不为修复加入双执行路径和长期 feature flag。
- 兼容旧 local_shell/local_exec/local_process、Hermes alias 和旧事件；新字段向后兼容。明确迁移一次，移除本次造成的废弃分支与未使用 import，不顺手清理其他代码。
- 不新增消息权威、不改 inactive 存档、不松动 JSON schema。内存短窗口与现有日志/metadata 足够，不建新数据库。
- 输出摘要限制与错误正文都由同一个结果格式化函数维护，避免后端、模型、UI 三份规则各漂移。

## 7. 必要验证：十组回归，三场真实会话

不要求每个小步骤一轮全仓测试或独立审查。先用相关已有测试建立基线，最终把原问题合成十组有区分度的回归；参数化可以复用 fixture，不要求固定测试函数数。

建议集中在 `core/tests/test_session_execution_repair.py`（或当前仓库已有同职责测试），扩展 `test_local_execution.py`、`test_engine_workspace_cwd.py` 等已有文件时避免重复覆盖；前端只补现有 runtimeEvents/timeline 的结果映射案例。

| 组 | 真正要证明的断言 |
|---|---|
| V1 无损传递 | 正确的中文/引号/换行/字面量反斜杠脚本经过 JSON→alias→kernel→真实解释器仍原样，输出固定 marker；错误脚本仍诚实失败 |
| V2 统一权限 | full_access 无 workspace 的原生写入/argv执行一致可用；受限模式不从 alias 扩大权限；模型注入 `_atlas_*` 不改变授权；两会话 cwd 不串 |
| V3 结果事实 | 真实子进程 exit=0/7、spawn失败、timeout、cancel、background-running 的事实在 runtime、kernel、metadata、event 一致；shell 正常打印 Error 且 exit=0 不误判 |
| V4 有限纠错 | 相同路径失败、同脚本语法失败的动态日志 id 不规避提示/停止；提醒后得到新诊断可恢复；正常长进程 wait/日志分页不误判 |
| V5 终止与验收分开 | stuck/post-tool-block/empty final 不升级 verified；普通聊天正常结束；用户 cancel 保持 cancelled；各分支只有一个最终终止事件 |
| V6 能力准确 | 真 shell 选择与快照一致；专家模式开启/关闭和热变更下一模型请求可见；没有另一会话私有事实，没有凭据 |
| V7 下载错误 | 本地 HTTP 404/HTML伪zip/截断zip/正确小zip与校验码错误得到正确结构化结果；失败不覆盖已有有效文件；平台错误在启动前识别 |
| V8 收尾合同 | required 项失败拒绝整体 verified；后续有效修复证据可完成；伪造/跨run evidence_ref拒绝；无验收普通对话不强制调用工具 |
| V9 续接恢复 | 压缩/新一轮保留 remaining 与最后验证；unknown副作用不重放；inactive历史不重计工具失败 |
| V10 前后端 | tool.completed carrying exit=7/timeout、run.completed+partial/blocked/answer 映射到正确卡片和通知；旧事件兼容；完整输出按需可读 |

V1/V3 必须包含 Windows 真实 Python 与 PowerShell 子进程，Bash 已安装则实际验证；不能只 mock subprocess 来宣布转义修好。网络本地 fixture 属于传输基础设施测试，不是远端服务或业务目标验收。

运行示例（实际工作树/临时路径可以替换，路径必须绝对）：

```powershell
$taskDataRoot = 'D:/Temp/atlas-session-runtime-acceptance-data'
New-Item -ItemType Directory -Path $taskDataRoot -Force | Out-Null
$env:ATLAS_DATA_DIR = $taskDataRoot
$env:HERMES_HOME = "$taskDataRoot/engine"
$env:MEMORYOS_DATA_ROOT = "$taskDataRoot/memoryos"
$env:MEMORYOS_DB_PATH = "$taskDataRoot/memoryos/memoryos.sqlite3"
$env:ATLAS_UPSTREAM_AUTO = '0'
$env:ATLAS_PORT = '28861'
# 临时目录放在仓库外，避免父目录 .git 干扰；USERPROFILE保持真实值。
& 'D:/atlas-session-runtime-fix/core/.venv/Scripts/python.exe' -m pytest `
  -o addopts= -q -p no:cacheprovider `
  'D:/atlas-session-runtime-fix/core/tests/test_session_execution_repair.py' `
  'D:/atlas-session-runtime-fix/core/tests/test_local_execution.py' `
  'D:/atlas-session-runtime-fix/core/tests/test_engine_workspace_cwd.py' `
  --basetemp='D:/Temp/atlas-session-runtime-acceptance'
```

执行器若复用主仓 venv，确认其 import 来自工作树；否则安装/使用工作树依赖。新增测试不标记为仅 unit 后又遗漏 integration，清空 pytest addopts 防止默认标记过滤；生产数据根禁止复用。若接线触及其它现有测试覆盖的分支，只增跑那几项，不直接扩成全仓长跑。

基线里的旧测试如果断言“full_access无workspace必须拒绝文件写入”，它与本任务书修正的合同冲突，应替换为 V2，并保留受限模式拒绝案例；不能简单删测试、改成 skip 或为了迁就旧错误行为保留 R2。

前端运行当前 package.json 的 `test` 脚本，指定 runtimeEvents/timeline 相关实际测试路径，并执行一次 `npm --prefix <工作树>/frontend run build`。无重复 build、无安装器矩阵；Electron验收启动 build对应的源码入口。

桌面验收另设独立 Electron userData/调试端口（例如9338），与正在运行的9335隔离；确认独立窗口的后端确实指向28861。使用现有 Electron 数据根配置入口，必要时只对验收子进程隔离 APPDATA/LOCALAPPDATA，不改系统环境、不伪造 USERPROFILE。测试模型配置只复制授权的必要 provider 配置至独立根，日志/报告脱敏；不复制生产会话库。

**三场真实模型 + Electron 会话（全部在独立环境）：**

1. **复杂脚本与无工作区写入：**用户要求生成并运行包含中文、引号与换行的小脚本，写结果文件再回读。要求用原生文件/脚本入口完成；marker、运行结果、回读内容和 UI 均正确，无 shell 转义重试。
2. **失败纠错与诚实部分完成：**提供本地验收服务，三份无害制品中一份404、一份平台不匹配、一份正确；要求下载并验证全部。助手明确两项失败，不把未安装说成“完整生效”；能说明原因并收敛，不能为了过关把 required 项删掉或替换成别的工具。
3. **能力与长任务续接：**询问专家模式状态，启动一个有增量输出的无害长任务，中途发送状态询问/用户纠正并正常停止；然后续接。实际开关与快照一致、活动可见、停止生效、状态诚实、没有重新执行已完成副作用；另询问观察某个会话最新状态，报告有读取截止时间。

真模型试验保留原始用户输入、关键事件和实际输出，不补隐藏 setup 轮、不把手写答案塞进 fake provider。原模型不可用时记录 provider 问题，只有用户已有可用模型范围内替代；不得把基础设施回归当成三场真验收通过。

检查不是为了凑“零失败”指标：修复前已有用例失败先区分与本改动关联，已确认的所有相关失败必须修复。第三方 API业务失败不算引擎能保证消灭的问题；正确拒绝/部分完成是预期成功。

## 8. 全部完成的条件与交付格式

- [ ] R1–R10 每项有“复现→根因→改动→验证”，尚未定位的历史问题明确 unknown，不能冒称根治；新会话的同类失败处理路径必须通过。
- [ ] 不再让模型为了文件写入权限去用 shell；正确脚本传递无损，错误脚本有正确诊断。
- [ ] 模型结果、SessionDB metadata、工具事件、桌面卡片与通知的退出/超时/结束原因一致。
- [ ] 无效重试会诊断/收敛，合法长任务不会被误杀；unknown副作用不盲目回放。
- [ ] 失败下载不进入可用工具状态；“索引/挂载成功”“进程退出成功”“用户目标通过”三个层次有明确证据边界。
- [ ] 十组有价值回归、一次前端构建和三场真实 Electron 会话通过；出现新失败只重跑受影响验证。
- [ ] 最后只做一次本人 diff 自检：范围、兼容入口、残留重复逻辑、私有字段/敏感输出、测试来源路径。没有必要不派第二轮审查、不生成审查文档。
- [ ] 交付一个短报告，含 HEAD/文件清单、修复矩阵、测试结果、三场会话 id/输出引用、生产切换状态与剩余问题。证据可在已有 artifacts 目录保存，不复制整库，不导出敏感业务会话全文。
- [ ] 交付实际部署来源检查与切换说明：开发启动指向哪个工作树、后端 import 根、构建输出目录、独立数据根/端口。生产未切换必须明写，不能仅靠代码提交宣布用户当前桌面已生效。

**Luna 最终回答应直接给结果：**哪些根因已经消除，真实桌面是否验收通过，用户当前生产桌面是否已切换，尚有何项没有证据。不要用“基本完成”“先绕过去”“理论上对标一流”收尾。

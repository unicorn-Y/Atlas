# CODEX-ATLAS-P18A-FULL-LOCAL-EXECUTION-CLI-AGENT

STATUS: READY
WORKER: Luna
BASE_BRANCH: main
PREDECESSOR: CODEX-ATLAS-P17B-REPRODUCIBLE-WINDOWS-RELEASE-AND-INSTALLER-ACCEPTANCE
CODE_BASE_HEAD: 52678392f887260179fe784f546042c44c78df69

## Objective

让 Atlas 获得接近 Codex CLI / Claude Code 一类本地 CLI Agent 的完整本机执行能力。

P18A 只做 **CLI / process / filesystem / Git / executable execution layer**，不做鼠标、键盘、截图或视觉 Computer Use。

目标用户体验：

用户只给目标，例如：

> 去 D:\MemoryOS 跑测试，失败就定位并修复。

Atlas 应该能够自主：

1. 切换/指定工作目录；
2. 读取和修改本机文件；
3. 运行 PowerShell / cmd / Python / Node / Git / 任意本地 CLI；
4. 读取 stdout/stderr；
5. 根据结果继续执行；
6. 启动长进程并查看状态；
7. 终止自己启动的进程/进程树；
8. 跨目录持续工作；
9. 把执行过程通过现有 Agent tool event / UI 展示给用户。

不要要求用户先为每个目录、命令或工具写专门配置。

## Product Principle: FULL_ACCESS by default

Atlas 的默认本机执行模式是：

`FULL_ACCESS`

这是本任务的硬约束。

默认行为：

- 不限制在 Atlas repo/workspace；
- 不使用 workspace-only sandbox；
- 不使用目录白名单；
- 不使用命令白名单；
- 不对正常 PowerShell/cmd/exe/Git/file 操作逐次弹 approval；
- 不要求每一步向用户确认；
- Agent 在用户给出任务后可以连续执行多步直到完成、失败或用户主动停止；
- 可以访问用户指定的任意本地路径；
- 可以运行用户机器上已安装、当前账户本来就有权限执行的程序。

权限/限制机制如果现有架构必须保留，只能作为 **用户主动开启的可选限制模式**，不得成为默认执行路径。

不要通过防御性编程偷偷把 FULL_ACCESS 退化成 restricted mode。

## Scope

### A. Native Local Execution runtime

新增 Atlas-owned 本地执行能力，不要求所有 shell 操作都绕 MCP。

提供 canonical native tool/runtime，至少支持：

- PowerShell command/script；
- `cmd.exe /c`；
- arbitrary executable + argv；
- Python interpreter/script；
- Node/npm/npx；
- Git and other installed CLI tools；
- configurable cwd；
- environment overrides；
- stdin when needed；
- stdout/stderr streaming；
- exit code；
- start time / duration；
- cancellation；
- timeout only when explicitly requested by caller or needed for bounded test execution。

Windows first。

不要只实现 `subprocess.run(..., capture_output=True)` 的一次性黑盒调用；长任务必须有可观察生命周期。

### B. Process lifecycle

实现 Atlas-owned process manager。

至少支持：

- spawn；
- stable execution/process id；
- running/exited/failed/cancelled state；
- incremental stdout；
- incremental stderr；
- exit code；
- graceful terminate；
- kill process tree when requested or when Atlas-owned process must be cleaned up;
- list Atlas-owned active processes；
- get one process status/log output；
- prevent zombie/orphan processes on Atlas shutdown。

不要扫描和接管用户所有系统进程；本阶段重点管理 Atlas 自己启动的进程。

### C. Filesystem capability without workspace sandbox

提供本机文件能力，至少：

- read text/binary metadata；
- write/overwrite；
- append；
- create directories；
- copy/move；
- delete file/directory；
- list directory；
- glob/search filename；
- basic text search；
- stat/existence；
- arbitrary absolute Windows paths and normal relative paths resolved from cwd。

不得限制为 `D:\Atlas` 或某个 workspace root。

如果已有 filesystem MCP 能力继续保留，但 P18A native execution/file layer 不能因为 MCP filesystem 的 allowed-root 设计而继承 sandbox 限制。

### D. Git usability

Atlas 应能像 CLI Agent 一样在任意本地 Git repository 中使用 Git。

至少验证：

- status；
- diff；
- log；
- branch；
- add；
- commit；
- pull/fetch；
- push（使用用户本机已有 Git 凭据/SSH/credential manager）；
- arbitrary repository path。

不要自己实现 Git 协议；调用本机 Git CLI。

### E. Agent integration

把 local execution tools 接入现有 Agent tool loop。

要求：

- LLM 能看到工具 schema；
- Agent 可自主选择 shell / file / process tools；
- tool calls 通过现有 runtime event system 显示；
- tool results 返回可供后续推理的 structured data；
- stdout/stderr 大输出要有合理 chunking/截断策略，同时保留可继续读取完整输出的 execution id；
- Agent 可以同一 run 内执行多个连续步骤；
- 用户 stop/cancel 能中止当前 Atlas-owned execution；
- run 结束时不自动杀掉被明确标记为 detached/background 的任务；普通前台任务必须正确收尾。

### F. Desktop/UI visibility

最小 UI 即可，不做大改版。

现有 ToolCard / activity path 至少展示：

- tool name；
- command/executable；
- cwd；
- running/success/failure/cancelled；
- exit code；
- stdout/stderr 摘要；
- execution id；
- expandable result/details where existing UI supports it。

用户不需要打开额外终端窗口才能知道 Atlas 正在执行什么。

### G. Default permission behavior

默认配置必须明确为：

`local_execution.permission_mode = "full_access"`

或等价 canonical setting。

默认 full_access 下：

- shell executes directly；
- filesystem writes/deletes execute directly；
- Git write operations execute directly；
- launching local executable executes directly；
- no per-command approval prompt；
- no directory approval prompt；
- no workspace approval prompt。

如果保留 `ask` / `restricted` / `deny` 等模式，它们只能作为用户主动切换后的行为。

P18A 不要求先做复杂权限 UI；最小配置/API 足够。

### H. Windows execution semantics

必须正确处理：

- spaces in paths；
- Unicode/中文路径；
- Windows quoting；
- PowerShell vs cmd argv semantics；
- executable paths；
- cwd；
- environment inheritance；
- process groups / child process cleanup；
- CRLF / console encoding；
- large stdout/stderr；
- commands that return non-zero exit codes without treating every non-zero as infrastructure crash。

不要把 shell command 拼接和 argv execution 混成一个容易转义错误的接口。

## Required acceptance scenarios

至少真实完成以下场景：

### Scenario 1: Arbitrary-path project task

在 Atlas repo 外创建一个 temporary Git project。

Agent 通过正常 tool loop：

1. list/read project files；
2. run a failing test/script；
3. inspect stderr；
4. edit source；
5. rerun；
6. get green result；
7. `git diff`；
8. commit change。

验证整个过程没有 workspace/root approval。

### Scenario 2: Cross-drive / arbitrary directory

在非 Atlas 工作目录执行：

- cwd change；
- create/read/write/delete；
- PowerShell command；
- Git command。

至少包含有空格或中文的路径。

### Scenario 3: Long-running process

启动一个持续输出日志的测试进程：

- Agent/consumer obtains execution id；
- incremental stdout observed；
- process status queried；
- process cancelled；
- child process tree exits；
- Atlas remains healthy。

### Scenario 4: Packaged Atlas

从实际 packaged/installed Atlas 走一遍 local execution：

- system shell command；
- arbitrary local directory；
- file write/read；
- Git read operation；
- no source checkout dependency；
- no Python dev environment dependency except tools actually invoked by user task。

## Required tests

至少覆盖：

1. default permission mode is full_access;
2. no workspace/root restriction in full_access;
3. arbitrary absolute path read/write works;
4. Unicode/space path works;
5. delete works in full_access without approval;
6. PowerShell execution works;
7. cmd execution works;
8. direct executable + argv execution works;
9. cwd is honored;
10. environment override is honored;
11. stdout streams incrementally;
12. stderr streams incrementally;
13. non-zero exit is reported structurally;
14. execution id/status query works;
15. cancellation works;
16. child process tree cleanup works;
17. Atlas shutdown cleans owned foreground processes;
18. detached/background behavior is explicit and tested;
19. Agent can perform multi-step shell/file workflow;
20. Agent can edit then rerun a failing project;
21. Git status/diff/commit works outside Atlas repo;
22. packaged Atlas local execution smoke passes;
23. no per-command approval is emitted in default full_access;
24. existing MCP/Skill/chat paths remain green;
25. P17 release acceptance remains green after relevant changes;
26. full `test_server.py` remains green;
27. frontend tests/build remain green when touched;
28. Ruff on changed Python files passes;
29. `git diff --check` clean;
30. LOCAL_HEAD == origin/main;
31. git status clean.

## Validation

必须执行：

- targeted native execution tests;
- multi-step Agent execution scenario;
- arbitrary-path Git scenario;
- long-process stream/cancel scenario;
- packaged Atlas local execution smoke;
- existing Agent/MCP/Skill regressions;
- full `core/tests/test_server.py`;
- P17A/P17B relevant packaged acceptance where affected;
- frontend tests/build if frontend touched;
- Ruff on changed Python files;
- `git diff --check`;
- process residue check;
- LOCAL_HEAD == origin/main;
- git status clean.

## Forbidden

不得：

- 默认启用 workspace sandbox；
- 默认目录白名单；
- 默认命令白名单；
- 默认逐操作 approval；
- 每次写文件/删文件/运行命令都询问用户；
- 把 full_access 偷换成只读模式；
- 只封装 filesystem MCP 当作“完整 CLI 能力”；
- 为每个命令写专用 endpoint；
- 新造一套平行 Agent loop；
- 开始鼠标/键盘 GUI automation；
- 开始截图/视觉理解；
- 开始实时语音；
- 开始摄像头/手机/远程设备；
- 做无关 UI 重构；
- 修改 P17 release 逻辑，除非 packaged execution 接入必须。

## Non-goals

P18A 不包括：

- 鼠标点击；
- 键盘自动输入到 GUI；
- 截屏；
- OCR；
- Vision model；
- UI element detection；
- browser DOM automation；
- Windows UI Automation；
- remote desktop；
- voice。

这些在后续 Computer Use 阶段处理。

## Delivery

1. Read `LUNA_WORKER.md`.
2. Pull `origin/main`.
3. Record actual starting HEAD as BASE_HEAD.
4. Read `PLAN.md`.
5. Read P7 Agent/runtime, P16 MCP/runtime, P17 release task/result/reviews.
6. Inspect current Agent tool registration and runtime-event path before designing new execution tools.
7. Execute only this taskbook.
8. Write:
   `tasks/results/CODEX-ATLAS-P18A-FULL-LOCAL-EXECUTION-CLI-AGENT.result.md`
9. Commit implementation + result.
10. Push `origin/main`.
11. Verify LOCAL_HEAD == origin/main.
12. Verify git status clean.
13. Stop.

## Acceptance Gate

P18A only passes when packaged Atlas can behave like a real local CLI Agent across arbitrary user-accessible Windows paths: execute shell/programs, stream process output, modify files, use Git, run multi-step Agent workflows, and do so under the default `FULL_ACCESS` mode without workspace sandboxing or per-operation approval prompts.

A filesystem-only tool, source-tree-only implementation, or approval-gated default is NOT sufficient.

## Queue Guard

P18A is the only READY task.

P17 Windows release/productization is complete.

P18B will cover GUI desktop Computer Use after P18A review.

Voice, camera, mobile/remote-device remain deferred.

BASE_HEAD_RULE:
After pulling origin/main, record the actual starting HEAD as BASE_HEAD.

# CODEX-ATLAS-P16B-PACKAGED-MCP-AGENT-END-TO-END-SMOKE

STATUS: READY
WORKER: Luna
BASE_BRANCH: main
PREDECESSOR: CODEX-ATLAS-P16A-MCP-RUNTIME-BUNDLED-NODE-DEPENDENCY-CHECK
CODE_BASE_HEAD: 1bbc7f4a549e043493aa4abf41a397dbb3b84c2c

## Objective

把 P16A 已经实现的 bundled Node + MCP runtime + dependency check 真正闭环到 Windows packaged product 的 Agent 工具调用路径，并把这条路径固化成稳定回归门。

P16A 已经证明：
- bundled Node 能启动真实 filesystem MCP；
- Agent 在开发/测试路径能通过 MCP 完成真实文件读取；
- packaged backend 能在没有 system Node 的情况下启动 bundled Node、连接 MCP 并完成 tool discovery。

本任务只补最后一个产品态缺口：

packaged atlas_backend.exe
→ bundled Node
→ filesystem MCP
→ Agent
→ real read_file
→ verified content

这是一个 bounded closeout/smoke task，不扩展 MCP 协议、Skill 系统、Memory、Voice 或其他产品功能。

## Scope

### A. Packaged backend Agent E2E smoke

在现有 Windows packaged backend smoke 基础上，新增真实 Agent tool-call 闭环。

要求：

1. 使用 `windows-release/win-unpacked` 或当前正式 packaged output；
2. 启动 packaged `atlas_backend.exe`；
3. 使用隔离 data/config 目录；
4. child PATH 中移除 system Node/npm/npx，确保不能偷用系统 Node；
5. 配置现有 filesystem MCP server；
6. 验证 runtime source 明确为 bundled Node；
7. 通过 Atlas 的真实 Agent path 发起一个需要 filesystem MCP 的请求；
8. Agent 必须实际调用 `read_file`；
9. 读取一个 smoke fixture 文件；
10. 最终响应或结构化 tool result 必须包含 fixture 的预期内容；
11. 验证过程中不得 mock MCP、mock Agent tool execution 或直接绕过 Agent 调 MCPClient。

### B. Stable test fixture

增加最小、确定性的 packaged smoke fixture。

要求：

- 内容固定、无用户隐私；
- 放在测试/打包验收可控路径；
- 测试断言读取到精确 marker；
- 不依赖本机已有文件；
- 不依赖网络搜索或外部账户。

例如 marker：

`ATLAS_PACKAGED_MCP_AGENT_E2E_OK`

具体位置由现有测试架构决定，不要为了 fixture 重构目录。

### C. Product-path assertions

smoke 至少明确断言：

- packaged backend health OK；
- Node runtime source == bundled；
- bundled Node version 与 P16A pin 一致；
- filesystem MCP server connected；
- tools discovery 包含 `read_file`；
- Agent tool execution event/trace 中确实出现 `read_file`；
- tool call 成功；
- fixture marker 被真实读取；
- 没有 system Node fallback；
- backend 正常 shutdown；
- 子 MCP 进程无残留。

如果现有 API/event schema 已经能证明以上事实，直接复用，不新增平行诊断协议。

### D. Regression gate

把这条 E2E smoke 纳入 P16 Windows release 验证路径。

要求：

- 测试名称和失败信息能直接指出是 packaged backend / bundled Node / MCP / Agent 哪一层失败；
- 不吞异常；
- 不因为偶发 provider/network 不可用而伪造 PASS；
- filesystem MCP + bundled Node 这一条本地闭环必须可重复执行；
- 不把已知 P15C 低频 acquisition flake 混进本任务修复范围。

### E. Minimal docs/result

只在必要时更新与 Windows release smoke 直接相关的开发说明。

不要重写 PLAN.md，不做大规模文档整理。

## Required tests

至少覆盖：

1. packaged backend starts with isolated data/config;
2. system Node/npm/npx unavailable to child process;
3. packaged backend resolves bundled Node;
4. bundled Node version equals pinned expected version;
5. filesystem MCP connects in packaged mode;
6. packaged tool discovery exposes read_file;
7. Agent receives a request requiring file access;
8. Agent performs real MCP read_file call;
9. exact fixture marker is returned through the real tool path;
10. no direct MCPClient shortcut is used in place of Agent execution;
11. MCP child process terminates after backend shutdown;
12. repeated packaged E2E run succeeds at least twice;
13. existing P16A live MCP smoke remains green;
14. relevant P15/P16 regressions remain green;
15. frontend tests/build remain green if frontend/package scripts are touched;
16. git diff --check clean;
17. LOCAL_HEAD == origin/main;
18. git status clean.

## Validation

必须执行：

- targeted packaged MCP Agent E2E smoke;
- repeat the packaged E2E smoke at least 2 times from clean isolated runtime dirs;
- existing P16A MCP live tests;
- relevant backend MCP/Agent regressions;
- P15E dependency-preflight regressions affected by P16A;
- Windows package/build only if test or packaging changes require rebuilding the product artifact;
- Ruff on changed Python files;
- frontend lint/type/test only if frontend files change;
- git diff --check;
- verify no secret/local config/database/build cache is committed;
- verify LOCAL_HEAD == origin/main;
- verify git status clean.

## Forbidden

不得：

- 重做 MCPClient；
- 新造第二套 MCP runtime；
- 新造第二套 Agent tool path；
- 改 Skill Registry / dependency contract / approval architecture；
- 借 system Node 让测试通过；
- mock 掉 packaged MCP/Agent 主路径；
- 为测试专门加入生产代码 bypass；
- 顺手修 P15C acquisition flake；
- 开始 Voice / Camera / mobile / remote-device；
- 开始 E01-E04；
- 做无关 UI 重构；
- 修改模型路由策略；
- 扩成通用 installer 重构任务。

## Delivery

1. Read `LUNA_WORKER.md`.
2. Pull `origin/main`.
3. Record actual starting HEAD as BASE_HEAD.
4. Read `PLAN.md`.
5. Read P16A taskbook and result.
6. Inspect existing `core/tests/test_mcp_runtime_live.py`, Agent tool path, packaged backend launch path and Windows packaging scripts before editing.
7. Execute only this taskbook.
8. Write:
   `tasks/results/CODEX-ATLAS-P16B-PACKAGED-MCP-AGENT-END-TO-END-SMOKE.result.md`
9. Commit implementation + result.
10. Push `origin/main`.
11. Verify LOCAL_HEAD == origin/main.
12. Verify git status clean.
13. Stop.
14. Do not start P16C or E01-E04.

## Acceptance Gate

P16B only passes when a packaged Atlas backend, with system Node unavailable, uses Atlas bundled Node to launch filesystem MCP and the real Agent successfully performs `read_file` against the deterministic fixture.

“backend can connect MCP” or “tools can be listed” alone is NOT sufficient.

## Queue Guard

P16B is the only READY task.

P16A implementation is delivered at commit `1bbc7f4a549e043493aa4abf41a397dbb3b84c2c`.

P16C and E01-E04 remain BLOCKED until P16B is completed and separately reviewed.

Voice, mobile/remote-device, camera and unrelated product expansion remain deferred.

BASE_HEAD_RULE:
After pulling origin/main, record the actual starting HEAD as BASE_HEAD.

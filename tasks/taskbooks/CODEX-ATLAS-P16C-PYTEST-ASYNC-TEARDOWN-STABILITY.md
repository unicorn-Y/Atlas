# CODEX-ATLAS-P16C-PYTEST-ASYNC-TEARDOWN-STABILITY

STATUS: READY
WORKER: Luna
BASE_BRANCH: main
PREDECESSOR: CODEX-ATLAS-P16B-PACKAGED-MCP-AGENT-END-TO-END-SMOKE
CODE_BASE_HEAD: fc7972d00561b3e2540edbe7cbbdfc0431134c2e

## Objective

修复/定位 Atlas 后端回归测试在 pytest async fixture teardown 阶段卡死的问题，使完整 `test_server.py` 和相关组合回归能够可靠结束并给出明确 PASS/FAIL。

已观察现象：

- P16B 的 packaged Agent E2E 本身通过；
- MCP、Agent、P15E 和 dependency-check 定向回归分别通过；
- 但完整 `core/tests/test_server.py` 以及一次组合回归在 pytest teardown 阶段停在 `asyncio.Runner._cancel_all_tasks`，没有自然退出。

本任务只处理测试生命周期/异步资源关闭问题。不要借机修改 MCP、Skill、Memory、模型路由或产品功能。

## Scope

### A. Reproduce deterministically

先建立最小复现。

要求：

1. 从当前 `origin/main` 运行完整 `core/tests/test_server.py`；
2. 记录卡住时最后完成的测试、活跃 task/thread/process；
3. 确认是 pytest fixture、FastAPI lifespan、scheduler、WebSocket、MCP child、background task、async generator 或其他具体资源未关闭；
4. 找出最小测试集合，能稳定复现 teardown hang；
5. 不允许只靠增加全局 timeout 掩盖问题。

### B. Root-cause fix

修复真实生命周期泄漏。

优先检查：

- FastAPI/TestClient lifespan；
- async fixtures；
- scheduler/background tasks；
- WebSocket run/session task；
- MCP runtime/server stop；
- anyio/asyncio task groups；
- executor/thread ownership；
- global singleton reset between tests。

要求：

- 资源由创建它的生命周期明确关闭；
- teardown 可重复、幂等；
- 不用 `taskkill`、`os._exit`、强制 event-loop close 等粗暴方式让 pytest 假装结束；
- 不吞 teardown exception；
- 不把正常产品 shutdown 语义改坏。

### C. Regression confidence

修复后必须证明：

1. 完整 `test_server.py` 至少连续跑 3 次都自然结束；
2. 原先会卡住的最小复现至少连续跑 5 次都自然结束；
3. P16A/P16B MCP live/package smoke 不退化；
4. Agent/MCP/P15E 相关回归保持通过；
5. pytest 结束后不存在 Atlas backend、MCP Node 或相关测试子进程残留。

### D. Keep scope bounded

如果根因来自已有测试基础设施，允许修改测试 fixture/helper 和必要的产品 shutdown hook。

如果必须改生产代码，只允许改与“正确关闭自己创建的异步资源”直接相关的生命周期代码，并补对应测试。

不要做其他重构。

## Required tests

至少覆盖：

1. minimal reproduction no longer hangs;
2. full `test_server.py` completes;
3. full `test_server.py` completes 3 consecutive runs;
4. minimal reproducer completes 5 consecutive runs;
5. no pending asyncio tasks attributable to Atlas remain after fixture teardown;
6. no scheduler/background worker survives teardown;
7. no MCP child process survives teardown when MCP is involved;
8. WebSocket/server tests still pass;
9. P16A live MCP smoke remains green;
10. P16B packaged Agent E2E remains green;
11. relevant Agent + MCP regressions remain green;
12. relevant P15E regressions remain green;
13. Ruff on changed Python files passes;
14. `git diff --check` clean;
15. LOCAL_HEAD == origin/main;
16. git status clean.

## Validation

必须执行：

- reproduce before fix and record concrete evidence;
- targeted minimal reproducer;
- full `core/tests/test_server.py` x3;
- minimal reproducer x5;
- P16A MCP live smoke;
- P16B packaged Agent E2E smoke;
- relevant MCP/Agent/P15E regression modules;
- Ruff on changed Python files;
- `git diff --check`;
- process/task residue check after pytest exit;
- LOCAL_HEAD == origin/main;
- git status clean.

## Forbidden

不得：

- 用更大的 timeout 代替修复；
- 在 pytest 末尾强制 `os._exit`；
- 用 `taskkill /F` 作为正常 teardown；
- swallow/cancel-all without identifying ownership；
- 删除或跳过卡住的测试来获得绿色结果；
- mock 掉真实生命周期路径；
- 重做 MCPClient；
- 修改 Skill Registry / dependency contract；
- 开始 Voice / Camera / mobile / remote-device；
- 开始 E01-E04；
- 做无关 UI 或模型路由工作。

## Delivery

1. Read `LUNA_WORKER.md`.
2. Pull `origin/main`.
3. Record actual starting HEAD as BASE_HEAD.
4. Read `PLAN.md`.
5. Read P16B result and review.
6. Reproduce the hang before editing.
7. Execute only this taskbook.
8. Write:
   `tasks/results/CODEX-ATLAS-P16C-PYTEST-ASYNC-TEARDOWN-STABILITY.result.md`
9. Commit implementation + result.
10. Push `origin/main`.
11. Verify LOCAL_HEAD == origin/main.
12. Verify git status clean.
13. Stop.

## Acceptance Gate

P16C only passes when the previously hanging server/backend pytest teardown has a demonstrated root cause and the full `test_server.py` suite completes naturally and repeatedly.

A timeout wrapper, forced process kill, skipped test, or “targeted tests pass” is NOT sufficient.

## Queue Guard

P16C is the only READY task.

P16B is accepted at `fc7972d00561b3e2540edbe7cbbdfc0431134c2e`.

E01-E04 and unrelated product expansion remain BLOCKED until P16C receives a separate review.

BASE_HEAD_RULE:
After pulling origin/main, record the actual starting HEAD as BASE_HEAD.

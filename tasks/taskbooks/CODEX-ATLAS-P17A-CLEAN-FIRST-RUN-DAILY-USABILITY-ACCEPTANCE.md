# CODEX-ATLAS-P17A-CLEAN-FIRST-RUN-DAILY-USABILITY-ACCEPTANCE

STATUS: READY
WORKER: Luna
BASE_BRANCH: main
PREDECESSOR: CODEX-ATLAS-P16C-PYTEST-ASYNC-TEARDOWN-STABILITY
CODE_BASE_HEAD: 46d9ba813b180ea99a1240dd0ad9e85ad0699adf

## Objective

把 Atlas 从“底层能力已经各自验证”推进到“Windows 用户拿到发布包后，能从零开始正常用”的整机验收阶段。

本任务不是继续加基础设施，而是以真实用户路径验证并修通以下主链路：

install / unpack
→ first launch
→ initial configuration
→ select/configure model
→ create conversation
→ streaming chat
→ restart Atlas
→ conversation persists
→ use bundled MCP
→ use an installed/available Skill path
→ shutdown/relaunch cleanly

目标是得到一个可以被称为“日常可用”的 v0.x release candidate。

## Scope

### A. Clean first-run environment

建立一个全新的隔离用户环境，不使用当前开发机已有 Atlas 数据。

要求：

- 使用当前 Windows packaged output / installer；
- 使用全新 Atlas data/config/user-settings 目录；
- 不读取开发机现有 conversation DB、用户 settings、MCP config 或 secrets；
- 不依赖 system Node；
- 不要求用户手工编辑 TOML/JSON 才能完成基本使用；
- 允许测试使用本地 deterministic model provider 以避免外网不稳定，但产品 UI/配置路径必须是真实的。

### B. First-run configuration

验证一个新用户第一次打开 Atlas 后可以完成最低限度配置。

至少验证：

- Atlas 正常启动；
- Settings 可打开；
- API base / key / model configuration 可以通过现有产品 UI/API 设置并持久化；
- model selection 生效；
- restart 后配置仍存在；
- secret 不以明文回显到普通 UI/API response；
- 不要求用户修改环境变量才能进入正常聊天。

如果当前产品缺少最小 first-run 引导或配置入口，允许做最小必要修复，但不要扩成新的 onboarding 大项目。

### C. Core chat usability

真实验证：

1. 创建新会话；
2. 发送消息；
3. assistant 流式返回；
4. done/completed 状态正常；
5. 侧栏/会话列表出现新会话；
6. 切换离开再回来能看到历史；
7. 关闭 Atlas；
8. 重新启动；
9. 之前会话仍存在且内容正确；
10. 再发送一轮消息仍正常。

不要只测 REST；至少有一条真实 Electron/renderer 或 packaged WebSocket 产品路径。

### D. Tool usability

在同一个干净用户环境中验证 P16 已完成的 bundled MCP 能力真正可被用户使用。

至少：

- dependency check 显示 bundled Node 可用；
- 配置/启用 filesystem MCP；
- tool discovery 可见；
- 通过正常 Agent chat 路径读取一个测试文件；
- ToolCard / tool event 在前端可见；
- 不依赖 system Node。

### E. Skill usability

验证至少一条当前 Skill 系统的真实用户路径。

优先选择一个不依赖外部账号的本地 Skill。

至少：

- Skill 能被 Registry/Discovery 发现；
- 用户能看到其状态；
- Skill 的依赖 preflight 结果可读；
- Skill 可按现有 activation 机制进入 Agent 上下文；
- 实际对话能证明 Skill instructions/capability 被应用；
- 不绕过 Registry/activation 直接把 prompt 塞进测试。

如果当前产品 UI 还没有完整 Skill Center 操作入口，可以通过现有正式 API + UI 可见状态组合验证，但必须记录缺少的产品入口。

### F. Restart and shutdown

真实验证：

- 正常关闭 Atlas 后 backend/MCP child 不残留；
- 再启动不会因为旧 lock/port/process 失败；
- conversation/config/skill registry state 保留；
- 不产生重复 MCP server；
- 退出后 Node child 清零。

### G. Fix only blockers to daily use

本任务允许修复在上述用户链路里真实发现的 blocker。

允许的例子：

- first-run 空配置导致直接报错；
- UI 无法保存 provider/model；
- packaged renderer 连不上 backend；
- history restart 后丢失；
- Skill/MCP 已有能力在产品 UI/API 中不可达；
- shutdown 留残留进程导致下次启动失败。

不允许顺手做大功能扩展。

## Required acceptance path

至少形成一个自动化或半自动化 release acceptance script/test，连续执行：

1. create clean runtime dir;
2. launch packaged Atlas;
3. health ready;
4. configure deterministic provider/model through normal product path;
5. create conversation;
6. complete streaming chat;
7. capture conversation id;
8. stop Atlas cleanly;
9. relaunch same clean runtime dir;
10. verify conversation/history persistence;
11. complete second chat turn;
12. verify bundled Node dependency check;
13. enable/use filesystem MCP;
14. complete Agent read_file call;
15. verify at least one Skill discovery/activation path;
16. stop Atlas;
17. verify no backend/Node/MCP child residue.

## Required tests

至少覆盖：

1. clean first launch succeeds;
2. config can be set without editing files manually;
3. config persists across restart;
4. secret is not echoed in normal read APIs;
5. model selection persists;
6. streaming chat completes;
7. conversation is created and listed;
8. history survives restart;
9. second-turn chat works after restart;
10. bundled Node remains selected with system Node unavailable;
11. filesystem MCP tool discovery works;
12. Agent real read_file works through packaged product path;
13. tool events are exposed to renderer/client;
14. at least one Skill is discovered;
15. Skill dependency/preflight state is readable;
16. at least one Skill activation/application path works;
17. graceful shutdown leaves no Atlas backend child;
18. graceful shutdown leaves no MCP Node child;
19. relaunch on same runtime dir succeeds;
20. relevant P16 regressions stay green;
21. full `test_server.py` remains green after any changes;
22. frontend tests/build stay green if frontend files change;
23. Ruff on changed Python files passes;
24. `git diff --check` clean;
25. LOCAL_HEAD == origin/main;
26. git status clean.

## Validation

必须执行：

- clean packaged first-run acceptance path;
- repeat the full acceptance path at least 2 times from separate clean runtime dirs;
- one restart-in-place persistence run;
- P16A/P16B/P16C relevant regression tests;
- full `core/tests/test_server.py`;
- relevant frontend tests/build when touched;
- Ruff on changed Python files;
- `git diff --check`;
- verify no secret/local user data is committed;
- verify LOCAL_HEAD == origin/main;
- verify git status clean.

## Forbidden

不得：

- 开始实时语音；
- 开始摄像头；
- 开始手机/远程设备；
- 重写 MCPClient；
- 重做 Skill Registry；
- 新造第二套配置系统；
- 新造第二套会话存储；
- 用开发机现有 Atlas 数据冒充 clean first run；
- 为测试直接写 DB 代替正常产品路径；
- 跳过 packaged product 只测源码 server；
- 自动安装未知系统依赖；
- 做无关 UI 重构；
- 做大规模视觉改版。

## Delivery

1. Read `LUNA_WORKER.md`.
2. Pull `origin/main`.
3. Record actual starting HEAD as BASE_HEAD.
4. Read `PLAN.md`.
5. Read P13, P15, and P16 relevant result/review files.
6. Inspect current packaged launch, settings, chat, conversation persistence, MCP and Skill product paths before editing.
7. Execute only this taskbook.
8. Write:
   `tasks/results/CODEX-ATLAS-P17A-CLEAN-FIRST-RUN-DAILY-USABILITY-ACCEPTANCE.result.md`
9. Commit implementation + result.
10. Push `origin/main`.
11. Verify LOCAL_HEAD == origin/main.
12. Verify git status clean.
13. Stop.

## Acceptance Gate

P17A only passes when a clean Windows user state can launch packaged Atlas, configure it through normal product paths, chat, restart with history/config preserved, use bundled filesystem MCP through Agent, exercise at least one real Skill path, and shut down/relaunch without residue.

Passing isolated backend tests alone is NOT sufficient.

## Queue Guard

P17A is the only READY task.

P16 runtime/product-path stabilization is complete.

Voice, camera, mobile/remote-device and unrelated multimodal expansion remain BLOCKED until P17A receives a separate review.

BASE_HEAD_RULE:
After pulling origin/main, record the actual starting HEAD as BASE_HEAD.

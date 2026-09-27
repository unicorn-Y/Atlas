# CODEX-ATLAS-P17B-REPRODUCIBLE-WINDOWS-RELEASE-AND-INSTALLER-ACCEPTANCE

STATUS: READY
WORKER: Luna
BASE_BRANCH: main
PREDECESSOR: CODEX-ATLAS-P17A-CLEAN-FIRST-RUN-DAILY-USABILITY-ACCEPTANCE
CODE_BASE_HEAD: c19f09040a35d87e64a4d8da290296e0a58f9d17

## Objective

把 P17A 已验证“日常可用”的 packaged Atlas 收敛成一个可重复构建、可安装、可卸载、可重新安装的 Windows release candidate。

本任务解决两个剩余发布工程问题：

1. fresh clone / clean build 环境下，Node runtime 获取必须有明确、可校验、可复现的流程，不能依赖 worker 临时手工把二进制塞进 package resources；
2. 验收不能只停留在 `win-unpacked`，必须真实走 NSIS installer 安装、首启、关闭、卸载、重装。

这是 release engineering / installer acceptance task，不新增 Agent、Memory、Voice、Vision、MCP 或 Skill 功能。

## Scope

### A. Reproducible Node runtime acquisition

保持 `frontend/node-runtime.json` 的 canonical version/platform/source/SHA-256 语义。

要求：

- canonical runtime 仍然是固定 Node `22.23.3` Windows x64；
- canonical official archive SHA-256 必须继续校验；
- fresh build 不允许依赖开发机已有 `backend-release/runtime/node`；
- 不允许“只校验 node --version 就信任来源”作为正式发布流程；
- 不允许把大型 Node 二进制提交进 Git；
- 不允许偷偷改用未定义 provenance 的 npm package 作为正式 runtime source。

允许增加一个 **verified local archive/cache input**：

- 例如环境变量或 build option 指向预先下载的官方 archive；
- 无论 archive 来自官方直连还是本地 cache，必须按 `node-runtime.json` 的 canonical SHA-256 校验；
- hash 不匹配立即失败；
- source selection 和最终 hash 必须在 build log 中清晰可见。

如果要增加备用网络源，必须证明它提供的是与 canonical official archive 字节一致、可通过同一 SHA-256 的文件。不能降低 provenance 要求。

### B. Fresh clean build

从 clean workspace 验证完整 release build：

- 清理 packaging outputs；
- 不复用旧 runtime staging；
- build backend；
- acquire/verify Node runtime；
- build frontend；
- build Electron Windows x64 NSIS + unpacked；
- 输出版本、Node runtime hash、installer hash；
- 不包含用户 DB、settings、API key、logs、cache。

至少执行两次 clean build。

要求第二次 build 重新从 clean packaging state 开始，不允许复制第一次完整 output 充数。

### C. Actual NSIS install acceptance

使用生成的 NSIS installer 做真实安装验收。

至少：

1. 安装到隔离测试位置/用户环境；
2. 确认安装目录不存在开发仓库引用；
3. 首次启动 Atlas；
4. backend 正常；
5. 配置 deterministic provider/model；
6. 完成一次 streaming chat；
7. 完成一次 bundled filesystem MCP Agent `read_file`；
8. 正常关闭；
9. 确认 backend/Node/MCP child 无残留；
10. 再启动已安装 Atlas，确认会话/配置仍存在。

不允许直接改回使用 `win-unpacked` 代替 installer 验收。

### D. Uninstall / reinstall acceptance

验证：

- NSIS uninstall 正常完成；
- program installation directory 被删除或只留下明确允许的 installer metadata；
- 不误删用户数据，除非当前产品明确定义卸载同时删数据；
- 如果用户数据保留，必须记录其位置和语义；
- reinstall 成功；
- reinstall 后应用可正常启动；
- 若用户数据设计为保留，历史/config 应按设计恢复；
- 若设计为不保留，则必须从产品定义和测试中保持一致。

不要擅自改变用户数据保留策略，只验证并明确当前行为。

### E. Release manifest

生成最小 release manifest / build evidence，至少记录：

- Atlas app version；
- git commit；
- Electron version；
- backend build identity/version；
- bundled Node version；
- canonical Node archive SHA-256；
- installer SHA-256；
- unpacked executable SHA-256（可选但推荐）；
- build time/environment summary。

manifest 不包含 secrets。

如果仓库已有 release metadata 机制则复用，不新造复杂发布系统。

## Required tests

至少覆盖：

1. clean Node runtime staging starts empty;
2. canonical Node archive hash is verified;
3. hash mismatch fails hard;
4. local cache/archive path still requires canonical hash;
5. build does not silently reuse stale staged runtime;
6. clean release build succeeds;
7. second clean release build succeeds;
8. NSIS installer is produced;
9. installer installs Atlas successfully;
10. installed Atlas launches successfully;
11. installed backend reaches health ready;
12. installed app can configure provider/model;
13. installed app completes streaming chat;
14. installed app uses bundled Node with system Node unavailable where practical;
15. installed app completes real filesystem MCP Agent read_file;
16. graceful close leaves no managed backend/Node/MCP residue;
17. relaunch preserves expected user state;
18. uninstall succeeds;
19. installation directory cleanup matches defined behavior;
20. user data behavior after uninstall is explicitly verified;
21. reinstall succeeds;
22. reinstalled app launches and works;
23. release manifest contains expected hashes/versions;
24. no secret/user runtime data is included in installer;
25. P17A clean daily-usability acceptance remains green;
26. full `test_server.py` remains green after any code changes;
27. relevant frontend tests/build remain green;
28. Ruff on changed Python passes;
29. `git diff --check` clean;
30. LOCAL_HEAD == origin/main;
31. git status clean.

## Validation

必须执行：

- two clean release builds;
- canonical Node archive hash verification;
- actual NSIS install acceptance;
- installed-app chat + MCP smoke;
- shutdown residue check;
- uninstall;
- reinstall;
- post-reinstall launch smoke;
- P17A release acceptance regression;
- full `core/tests/test_server.py`;
- relevant frontend tests/build;
- Ruff on changed Python;
- `git diff --check`;
- verify no secrets/user data/build cache committed;
- verify LOCAL_HEAD == origin/main;
- verify git status clean.

## Forbidden

不得：

- 把 Node binary/archive 提交进 Git；
- 把未校验 npm runtime 当正式 release source；
- 只检查 `node --version` 而不校验 canonical archive provenance；
- 复用旧 staged runtime 冒充 clean build；
- 只测 `win-unpacked` 不测 NSIS installer；
- 为通过卸载测试删除真实用户目录；
- 开始自动更新系统；
- 开始签名/证书采购；
- 开始 Voice / Vision / Camera / mobile/remote-device；
- 重构 Agent/MCP/Skill/Memory；
- 做无关 UI 改版。

## Delivery

1. Read `LUNA_WORKER.md`.
2. Pull `origin/main`.
3. Record actual starting HEAD as BASE_HEAD.
4. Read `PLAN.md`.
5. Read P13, P16, P17A task/result/review.
6. Inspect current packaging scripts and NSIS config before editing.
7. Execute only this taskbook.
8. Write:
   `tasks/results/CODEX-ATLAS-P17B-REPRODUCIBLE-WINDOWS-RELEASE-AND-INSTALLER-ACCEPTANCE.result.md`
9. Commit implementation + result.
10. Push `origin/main`.
11. Verify LOCAL_HEAD == origin/main.
12. Verify git status clean.
13. Stop.

## Acceptance Gate

P17B only passes when Atlas can be built from a clean packaging state with a cryptographically verified canonical Node runtime, installed through the actual NSIS installer, used for chat + MCP, cleanly shut down, uninstalled, reinstalled, and launched again with the expected user-data behavior.

A manually staged runtime or a `win-unpacked`-only smoke is NOT sufficient.

## Queue Guard

P17B is the only READY task.

P17A daily-usability acceptance is complete and accepted.

Voice, visual/camera, mobile/remote-device and unrelated multimodal expansion remain BLOCKED until P17B receives a separate review.

BASE_HEAD_RULE:
After pulling origin/main, record the actual starting HEAD as BASE_HEAD.

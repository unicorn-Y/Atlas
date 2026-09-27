# CODEX-ATLAS-P16A-MCP-RUNTIME-BUNDLED-NODE-DEPENDENCY-CHECK

STATUS: READY
WORKER: Luna
BASE_BRANCH: main
PREDECESSOR: CODEX-ATLAS-P15E-FIX3-STARTUP-REGISTRY-CANONICALIZATION
CODE_BASE_HEAD: 4ef8576eec851db90a397dd8d207996fa87a296d

## Objective

把 Atlas 的 Windows 产品运行环境真正做成“拿到安装包即可使用 MCP”，补齐 P13/P14 明确留下的三个实际缺口：

1. 内置 MCP runtime；
2. bundled Node；
3. 一键依赖检测。

目标是让用户不需要自己安装 Node/npm 才能使用 Atlas 已支持的 Node-based MCP server，同时能在 Atlas 内一次性看清当前运行环境和 Skill/MCP 依赖状态。

这是一个 bounded runtime/distribution task，不是重新设计 MCP 协议、Skill Registry 或生命周期系统。

## Scope

### A. Atlas-owned MCP runtime

复用现有 P7F MCPClient、Agent tool execution 和当前配置体系，不新造第二套 MCP 协议栈。

实现：

- Atlas 启动/停止已配置 MCP server 的统一 runtime 入口；
- MCP server 生命周期由 Atlas 管理；
- tool discovery 与现有 Agent tool path 保持一致；
- Node-based MCP server 由 Atlas 的 bundled Node runtime 启动；
- 不要求系统 PATH 中存在 node、npm 或 npx；
- 保持现有 filesystem MCP 等真实工具调用路径；
- runtime 状态可以被 UI/诊断接口读取。

不要重做 P7F 已完成的 MCP 协议实现。

### B. Bundled Node

在 Windows 发布包中内置经过验证的 Node runtime。

要求：

- 使用适合 Atlas Windows x64 发布目标的官方 Node binary；
- 构建时固定版本并记录版本、来源和 SHA-256；
- Node runtime 随安装包进入应用自己的 runtime 目录；
- MCP runtime 优先使用 bundled Node，不依赖系统 Node；
- 不把 Node 二进制源码或大型运行包直接塞进 Git 源码树；沿用现有 release/package 构建流程取得并打包；
- 已安装系统 Node 只能作为开发/诊断信息，不得成为发布包 MCP 正常工作的前置条件。

npm/npx 如果现有 MCP server 启动方式需要，应随 bundled Node 一并提供可验证的调用路径。

### C. 一键依赖检测

复用 P15E canonical dependency contract 和现有 preflight，不新造第二套 dependency model。

提供一个只读的一键检查入口，至少汇总：

- Atlas bundled Node：存在、版本、可执行；
- MCP runtime：可用/不可用及具体原因；
- 已配置 MCP servers：配置、启动状态、tool discovery 状态；
- Skill canonical dependencies：mcp_servers / python_packages / commands；
- 对每项依赖给出已有 P15E 状态：satisfied / missing / incompatible / unknown；
- 明确哪些项目会阻止当前 Skill/MCP 使用。

规则：

- 检测本身不得修改环境；
- 不自动安装 Node、Python 包、系统命令或 MCP server；
- 不把 unknown 当 satisfied；
- 不新增第二套 Registry、Approval、Policy 或 dependency contract；
- 能复用现有 preflight 就直接复用。

### D. Minimal UI

在现有 Settings / Skill Center 合适位置增加一个“检查依赖”入口。

展示：

- 一键检查按钮；
- 检查时间；
- runtime/Node 状态；
- MCP server 状态；
- Skill dependency 状态；
- blocking reason；
- 可执行的下一步说明（例如“使用内置 Node”“配置 MCP server”“安装缺失依赖”），但不在本任务中自动执行环境变更。

不要做新的复杂诊断中心，不做无关 UI 重构。

### E. Release integration

把 bundled Node 和 MCP runtime 接入现有 P13 Windows installer。

安装后，在没有系统 Node 的干净环境中：

1. Atlas 正常启动；
2. MCP runtime 正常启动已配置的 Node-based MCP server；
3. 能列出真实 tools；
4. Agent 能完成一次真实 filesystem MCP tool call；
5. 一键依赖检测能报告 bundled runtime 与 Skill dependencies；
6. 不需要修改系统 PATH。

## Required tests

至少覆盖：

1. bundled Node path resolves from installed application directory;
2. MCP runtime chooses bundled Node when system Node is unavailable;
3. configured Node-based MCP server starts through bundled Node;
4. MCP tool discovery remains functional;
5. real filesystem MCP invocation through Agent remains functional;
6. MCP runtime stop/restart works for the existing configured server path;
7. dependency check is read-only;
8. dependency check reuses canonical P15E dependency records;
9. satisfied dependency is reported satisfied;
10. missing dependency is reported missing;
11. incompatible dependency is reported incompatible;
12. unknown dependency is not reported satisfied;
13. dependency check identifies MCP runtime/Node blockers;
14. frontend dependency-check UI regression;
15. Windows release package contains the bundled Node runtime;
16. clean-environment release smoke works without system Node;
17. existing P15A-P15E regression remains green;
18. no API key or local config secret is included in the release package.

## Validation

必须执行：

- relevant backend/MCP regression tests;
- P15A-P15E regression set;
- frontend tests;
- production build;
- Windows installer/package build;
- clean-environment smoke with system Node unavailable;
- real filesystem MCP discovery and one real tool call;
- dependency-check API/UI smoke;
- Ruff on changed Python files;
- frontend lint/type checks where applicable;
- git diff --check;
- LOCAL_HEAD == origin/main;
- git status clean.

如果外部 MCP provider/registry 网络不可用，不伪造成功；对不依赖外部网络的本地 bundled runtime 路径必须真实验证。

## Forbidden

不得：

- 开始 P16B 或其他后续任务；
- 开始 E01-E04；
- 重做 P7F MCP protocol/client architecture；
- 新造第二套 MCP protocol；
- 新造第二套 Skill Registry；
- 新造第二套 dependency contract；
- 新造第二套 Policy/Approval；
- 自动安装未知依赖；
- 自动执行 Skill 提供的任意 shell 安装命令；
- 把系统 Node 作为正式发布包的隐式依赖；
- 修改 P15C provider hash verification；
- 修改 P15D lifecycle/approval architecture；
- 做无关 UI 重构；
- 把语音、摄像头、手机/远程设备作为本任务范围。

## Delivery

1. Read LUNA_WORKER.md.
2. Pull origin/main.
3. Record actual BASE_HEAD.
4. Read PLAN.md.
5. Read P13, P14, P15A-P15E relevant reviews/taskbooks.
6. Inspect the existing MCPClient, Agent tool execution, Windows packaging and P15E dependency preflight before changing code.
7. Execute only this taskbook.
8. Write:
   tasks/results/CODEX-ATLAS-P16A-MCP-RUNTIME-BUNDLED-NODE-DEPENDENCY-CHECK.result.md
9. Commit implementation + result.
10. Push origin/main.
11. Verify LOCAL_HEAD == origin/main.
12. Verify git status clean.
13. Stop.
14. Do not start P16B or E01-E04.

## Queue Guard

P16A is the only READY task.

P16B and E01-E04 remain BLOCKED until P16A receives a separate review.

BASE_HEAD_RULE:
After pulling origin/main, record the actual starting HEAD as BASE_HEAD.

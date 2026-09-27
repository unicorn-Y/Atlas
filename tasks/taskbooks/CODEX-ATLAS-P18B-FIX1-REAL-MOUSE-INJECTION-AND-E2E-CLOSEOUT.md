# CODEX-ATLAS-P18B-FIX1-REAL-MOUSE-INJECTION-AND-E2E-CLOSEOUT

STATUS: READY
WORKER: Luna
BASE_BRANCH: main
PREDECESSOR: CODEX-ATLAS-P18B-GUI-DESKTOP-COMPUTER-USE
CODE_BASE_HEAD: eb5e9fe4d41a00eeaee13397e580236ceb7a2545

## Strategy Change: REUSE FIRST, DO NOT REINVENT

本任务改为 **成熟开源实现优先**。

核心原则：

> 不再让 Atlas 从 Win32 / ctypes 层自己慢慢搓 Computer Use。
> 先找已经跑通 Windows GUI automation 的成熟开源项目，直接复用/移植其实现与依赖；Atlas 只写薄适配层接入现有 Agent loop。

执行优先级：

1. **Microsoft UFO / UFO²** — Windows 专用，优先复用 UIA / pywinauto / Win32 / screenshot / control inspection / click / type / scroll / window management。
2. **ByteDance UI-TARS Desktop** — 优先参考/复用其 screenshot → mouse/keyboard → continuous GUI operator 行为和 action schema。
3. 若以上项目内部依赖成熟库（如 pywinauto / nut.js / agent-infra operator），优先直接采用成熟库，而不是把行为重新用 ctypes 复刻一遍。
4. 只有当成熟项目没有对应能力时，才允许保留 Atlas 自己的 Win32 小实现。

### Mandatory upstream sources to inspect first

- `microsoft/UFO`
  - `ufo/client/mcp/local_servers/ui_mcp_server.py`
  - `ufo/automator/action_execution.py`
  - `ufo/automator/puppeteer.py`
  - `ufo/automator/ui_control/inspector.py`
  - `ufo/automator/ui_control/screenshot.py`
  - related click/type/scroll implementations and UIA wrappers
- `bytedance/UI-TARS-desktop`
  - `multimodal/gui-agent/operator-aio/src/AIOComputer.ts`
  - `multimodal/gui-agent/operator-nutjs/`
  - related operator/action implementation for CLICK / DOUBLE_CLICK / DRAG_TO / SCROLL / TYPING / HOTKEY / screenshot

Before editing Atlas, inspect these real upstream implementations and record which pieces will be reused.

### License discipline

Direct reuse is allowed only when license permits it.

- Microsoft UFO code carries MIT license headers.
- UI-TARS Desktop uses Apache-2.0.
- Preserve required copyright/license notices for copied/adapted code.
- Record source repo + source path + upstream commit in the result file for every materially copied/adapted implementation.

Do not paste third-party code without attribution.



## Agent-level reuse is explicitly allowed

不只允许抄底层 input backend，**允许直接复用成熟 Computer Use Agent 的 operator / planner / observation-action loop / tool policy / retry loop**。

优先评估：

### 1. simular-ai/Agent-S — first priority

- Python;
- Windows/macOS/Linux;
- 直接面向 ordinary desktop/web applications;
- mature screenshot → reasoning → click/type/scroll loop;
- Apache-2.0;
- 当前 GitHub 约 12k stars;
- 允许直接复用其 Agent loop、grounding/action abstraction、computer interface、observation/action cadence。

如果 Agent-S 的执行/loop 能直接适配 Atlas，优先“搬 Agent-S 的 Computer Use engine + Atlas adapter”，而不是继续扩 Atlas 自己的 GUI loop。

### 2. bytedance/UI-TARS-desktop / Agent TARS

- 当前 GitHub 约 39k stars;
- Apache-2.0;
- 成熟 local desktop operator;
- screenshot / CLICK / DOUBLE_CLICK / DRAG_TO / SCROLL / TYPING / HOTKEY;
- Agent TARS 已经把 GUI Agent + Vision + CLI + MCP 放在同一 Agent stack 中。

特别适合复用：

- operator action schema;
- desktop operator;
- screenshot/action feedback loop;
- GUI + CLI mixed workflow;
- multimodal Agent loop。

### 3. microsoft/UFO

- Windows-first;
- 当前 GitHub 约 9.8k stars;
- MIT;
- UIA + pywinauto + Win32;
- semantic control discovery/action;
- application/window/control grounding。

特别适合做 Windows semantic/UIA backend。

### 4. Open Interpreter OS mode

优先参考/复用：

- persistent shell + computer control;
- one Agent mixing CLI and GUI;
- screenshot/computer action loop;
- model-agnostic LiteLLM integration。

## Selection rule

Luna 不需要自己设计新的 Computer Use architecture。

先做 1 个短 fit check：

- 哪个项目最接近 Atlas 当前 Python backend + existing Agent loop;
- 哪个最容易保留 FULL_ACCESS;
- 哪个能最快通过真实 Windows workflow;
- 哪个许可证允许直接复用;
- 哪个依赖最少。

然后选择 **一个主 Agent/operator 实现作为 P18B 主体**。

可以混合：

- Agent-S / UI-TARS：Agent loop/operator;
- UFO：Windows UIA semantic backend;
- Atlas P18A：CLI/filesystem/Git;
- Atlas existing runtime events/UI：展示层。

但不得为了“架构纯洁”把这些成熟逻辑重新实现一遍。

## Copy whole working modules when cheaper

若一个 upstream module 已经完整解决某个问题，允许：

- 整文件复制并最小改名/适配;
- vendoring 小型模块;
- 直接添加 upstream dependency;
- 保留 upstream API 再写 Atlas adapter。

优先级：

`direct dependency > copy/adapt complete module > thin adapter > rewrite`

只有依赖冲突、许可证不兼容、打包不可行时才自己重写。

## Do not preserve Atlas code merely because it already exists

当前 P18B 的自写 `computer_use.py` 不是必须保留。

如果成熟项目实现明显更完整可靠，可以：

- 删除自写 mouse backend;
- 替换 observation/action loop;
- 替换 tool implementation;
- 仅保留 Atlas tool names/schema compatibility adapter。

目标是最终效果，不是保护已有代码投入。


## Objective

用成熟实现替换/修正 Atlas 当前未通过验收的 GUI input 层，并一次性关闭 P18B 剩余验收。

当前已工作的 Atlas 能力：

- screenshot;
- monitor/window observation;
- window management;
- Unicode typing;
- clipboard;
- multimodal screenshot handoff;
- Agent loop integration;
- FULL_ACCESS default.

这些不要重写，除非成熟上游实现能明显减少代码并提高可靠性。

当前真实 blocker：

- pointer 可以移动到目标；
- `computer_mouse(click)` 未触发真实控件 callback。

## A. Stop hand-rolling mouse injection

### First choice: use mature upstream input backend

优先选择下面之一：

- pywinauto/UIA action backend derived from UFO;
- UI-TARS Desktop's proven operator backend / nut.js path;
- another mature dependency already used by those projects.

Atlas production path 不再以当前自写 `ctypes.SendInput` 鼠标实现作为必须保留的核心。

如果成熟 backend 可以可靠完成：

- click;
- double click;
- right click;
- mouse down/up;
- drag;
- scroll;
- Unicode typing;
- window focus;

则允许直接把 Atlas 的 `ComputerUseRuntime` 变成该 backend 的薄 wrapper。

### Forbidden

不得继续：

- 花大量时间调自写 INPUT/MOUSEINPUT struct；
- 给每个 Win32 控件写特判；
- 用 Tk/Notepad 专用 hack；
- 自己重新实现成熟库已经有的 UIA/control click；
- 一边保留坏的 SendInput 主路径，一边堆多个隐式 fallback。

## B. Prefer semantic UIA actions when possible

采用 UFO 的思路：

- 先发现窗口/control；
- 能通过 UIA/pywinauto 对真实 control 做可靠 action 时，优先 semantic action；
- 无 UIA control 或视觉任务时，再使用坐标级 mouse action。

Computer Use 应是 hybrid：

`UIA/native control action + coordinate mouse fallback + visual screenshot reasoning`

而不是所有东西都强制转成裸坐标点击。

但用户体验仍保持一个统一 Atlas tool interface。

## C. Preserve FULL_ACCESS

默认仍为：

`computer_use.permission_mode = "full_access"`

不得因为换成熟项目而引入：

- sandbox;
- per-click approval;
- per-window approval;
- app whitelist;
- browser-only restriction.

如果上游库带 sandbox/approval 层，只取执行 backend，不照搬限制层。

## D. Live primitive acceptance

使用真实 Windows UI target，必须验证效果而不是只看 API return：

1. single click;
2. double click;
3. right click;
4. drag;
5. vertical scroll;
6. mouse down/up;
7. Unicode typing;
8. hotkey;
9. clipboard;
10. focus/window switching.

如果 UIA semantic click 与 coordinate click 两种路径都存在，至少各有一条真实验收。

## E. Notepad Agent workflow

通过正常 Atlas Agent loop：

1. P18A launch Notepad;
2. P18B observe;
3. locate/focus Notepad;
4. type Chinese/Unicode marker;
5. save through GUI;
6. P18A `local_file` read back exact file;
7. finish without user intervention;
8. no `approval.required`.

允许 Agent 使用：

- screenshot reasoning;
- UIA semantic controls;
- coordinate click fallback;
- keyboard/hotkey.

不要为了“纯视觉”故意放弃更可靠的 UIA。

## F. Cross-application workflow

至少两个普通 Windows 应用。

优先：

- File Explorer;
- Notepad.

Agent 必须能：

observe
→ select/focus app A
→ act
→ switch app B
→ act
→ verify.

## G. Observe → reason → act → observe

正常 Agent path 至少两轮真实截图：

`computer_observe`
→ model receives screenshot
→ model chooses action
→ real action
→ `computer_observe`
→ model receives changed desktop
→ next action/completion.

允许 deterministic multimodal provider 让测试稳定，但截图必须是真截图，tool call 必须由 Agent loop 发出。

## H. Mixed CLI + GUI

同一 run 中必须同时使用：

- P18A `local_*`;
- P18B `computer_*`.

例如：

`local_exec -> Notepad`
→ `computer_observe`
→ UI action
→ save
→ `local_file` verify.

## I. Packaged/installed acceptance

必须在 packaged 或 NSIS-installed Atlas 中跑真实 GUI workflow：

- screenshot;
- click;
- keyboard;
- window focus;
- local execution;
- no source checkout dependency;
- no approval;
- clean shutdown;
- no Atlas-owned residue.

## J. Minimal Atlas integration layer

目标不是把 UFO 或 UI-TARS 整个框架搬进 Atlas。

Atlas 应保留：

- existing Agent loop;
- existing runtime events;
- P18A local execution;
- existing frontend.

只拿成熟项目的：

- Windows UI execution backend;
- control discovery;
- input primitives;
- screenshot/operator pieces;
- useful action abstractions.

Prefer adapter over rewrite.

## Required upstream evidence in result

Result 文件必须列出：

- upstream repo;
- upstream commit SHA;
- reused source paths;
- license;
- copied/adapted concepts/files;
- Atlas adapter files;
- why this approach replaced the custom implementation.

## Required regression

Must keep green:

- existing P18B observation/window/keyboard/clipboard tests;
- P18A local execution tests;
- Agent tests;
- MCP/Skill regressions;
- full `test_server.py`;
- P17A/P17B packaged/release acceptance when packaging changes;
- frontend tests/build if touched;
- Ruff changed Python files;
- `git diff --check`.

## Forbidden

不得：

- 继续大规模手搓 Computer Use 底层；
- 重写整个 Agent loop；
- 把 UFO 的多 Agent 架构整个复制进 Atlas；
- 把 UI-TARS 整个桌面 app 整包塞进 Atlas；
- 默认 approval；
- 降低 FULL_ACCESS；
- 开始 P18C；
- 开始语音、摄像头、手机/remote-device；
- 无关 UI 重构。

## Delivery

1. Read `LUNA_WORKER.md`.
2. Pull `origin/main`.
3. Record actual BASE_HEAD.
4. Read P18B result/review.
5. Inspect UFO and UI-TARS upstream source FIRST.
6. Choose a mature reusable backend.
7. Record upstream commit/license.
8. Replace/adapt the broken Atlas input path with the mature implementation.
9. Close all P18B E2E gates.
10. Write:
   `tasks/results/CODEX-ATLAS-P18B-FIX1-REAL-MOUSE-INJECTION-AND-E2E-CLOSEOUT.result.md`
11. Commit implementation + result.
12. Push `origin/main`.
13. Verify LOCAL_HEAD == origin/main.
14. Verify git status clean.
15. Stop.

## Acceptance Gate

FIX1 passes only when P18B works through a mature reused backend and real Windows GUI effects are demonstrated end-to-end.

A new custom Win32 mouse implementation is NOT the desired outcome.

The preferred outcome is:

`mature upstream backend + thin Atlas adapter + existing Atlas Agent loop`

## Queue Guard

P18B-FIX1 remains the only READY task.

P18C remains BLOCKED.

FULL_ACCESS remains default.

Voice, camera and mobile/remote-device remain deferred.


## FIRST-TIER SOURCE PRIORITY — OVERRIDES EARLIER ORDER

For P18B Computer Use, evaluate these first-tier upstreams BEFORE UFO/Open Interpreter or lower-level backends.

### Tier 1A — full Computer Use agents

#### xlang-ai/OpenCUA
Priority: HIGHEST for Agent architecture / perception-action loop.

Why:
- dedicated open foundations for Computer-Use Agents;
- includes Computer Use Agent, models, data, tooling and OSWorld-oriented execution;
- screenshot perception -> reflective reasoning -> action prediction loop is already implemented;
- suitable for copying Agent state/observation/action/history patterns.

Inspect:
- OpenCUA agent/evaluation runner;
- screenshot history handling;
- action representation;
- coordinate grounding;
- retry/step loop;
- multimodal prompt construction;
- execution feedback integration.

Do NOT require Atlas to use OpenCUA weights. Reuse the agent/operator architecture with Atlas-selected models when practical.

#### simular-ai/Agent-S (S3)
Priority: HIGHEST for production-grade desktop Agent loop.

Why:
- complete open-source Computer Use Agent;
- Windows/macOS/Linux;
- ordinary real desktop apps;
- mature observe -> reason -> act loop;
- high OSWorld / WindowsAgentArena results;
- Python, making Atlas integration comparatively direct.

Inspect and prefer reusing:
- gui_agents package;
- S3 planner/executor loop;
- screenshot/grounding;
- computer interface;
- action abstraction;
- retry/recovery;
- history/state management;
- model adapters.

If Agent-S can replace Atlas's current custom Computer Use loop cleanly, prefer that.

#### bytedance/UI-TARS-desktop / Agent TARS
Priority: HIGHEST for multimodal GUI operator + full-stack integration.

Why:
- very popular open-source multimodal agent stack;
- native desktop GUI Agent;
- local/remote computer operators;
- GUI + Vision + CLI + MCP already combined;
- mature action schema for CLICK/DOUBLE_CLICK/DRAG/SCROLL/TYPING/HOTKEY.

Inspect:
- Agent TARS loop;
- UI-TARS Desktop local operator;
- operator-nutjs;
- operator-aio;
- screenshot/action feedback;
- tool orchestration;
- GUI+CLI mixed workflows.

### Tier 1B — browser subsystem

#### browser-use/browser-use
Priority: HIGHEST for future Atlas browser agent, and useful now for Agent loop design.

Why:
- extremely mature/popular browser agent;
- open-source Agent class;
- state/history/retry/tool loop;
- browser task planning and execution;
- model-agnostic usage.

P18B should NOT replace full desktop control with browser-only automation, but Atlas may directly reuse its Agent architecture patterns. Future browser subsystem should prefer direct integration instead of hand-rolled browser automation.

### Tier 2 — backend/support projects

Only after Tier 1 assessment:

- microsoft/UFO — Windows UIA/pywinauto semantic backend;
- Open Interpreter OS mode — CLI+GUI orchestration reference;
- other lower-level automation libraries.

These are support sources, not the first architectural choice.

## Selection requirement

Before coding, Luna must create a short fit table in the result notes:

| Project | Full Agent loop | Windows desktop | GUI action backend | multimodal screenshot loop | CLI+GUI | license | integration cost |
|---|---|---|---|---|---|---|---|

At minimum compare:
- OpenCUA
- Agent-S3
- UI-TARS / Agent TARS
- Browser Use
- UFO

Then choose:
- ONE primary Computer Use Agent/operator architecture;
- optional ONE Windows semantic backend;
- Atlas adapters only where necessary.

Do not combine five frameworks into a new complicated framework.

## Strong preference

If a first-tier project already solves an Atlas requirement end-to-end, copy/adapt that working module/loop instead of reimplementing it.

The desired P18B outcome is closer to:

first-tier Computer Use Agent
+ Atlas P18A CLI
+ Atlas Memory/Skills/MCP/runtime UI

not:

Atlas custom GUI agent rebuilt from scratch.


## AGENT CORE FIRST — OVERRIDES COMPUTER-USE-ONLY FRAMING

The architectural priority for Atlas is now:

1. reuse a first-tier general Agent harness/core;
2. attach mature Computer Use backends to that Agent;
3. keep Atlas-specific Memory/Skills/MCP/UI as integration layers.

Do NOT design Atlas Agent behavior primarily from Computer Use benchmark projects.

### First-tier Agent sources

#### 1. openai/codex — PRIMARY OPEN AGENT CORE REFERENCE

Priority: HIGHEST.

Why:
- official OpenAI coding agent;
- local-first terminal agent;
- open-source Apache-2.0;
- mature tool loop, session lifecycle, resume/continuation, context handling, execution state;
- desktop/CLI/product surfaces are built around the same Codex agent family.

Inspect and reuse/adapt where license-compatible:
- codex-rs agent/session core;
- model/tool turn loop;
- tool execution lifecycle;
- cancellation/interruption;
- conversation/session persistence;
- context compaction;
- resume/replay;
- task status/progress;
- shell/file tool contracts;
- app/CLI protocol boundaries.

Atlas should prefer Codex-style execution semantics over inventing a new orchestration model.

#### 2. anthropics/claude-code — PRIMARY BEHAVIOR / ARCHITECTURE REFERENCE

Priority: HIGHEST for product behavior and agent lifecycle.

Claude Code is a first-tier target behavior even where its full production source is not available for direct reuse.

Reuse documented/public behavior and architecture patterns:
- single central query/tool loop;
- subagents;
- hooks lifecycle;
- project instructions/context files;
- tool lifecycle;
- interruption/stop behavior;
- agent-based hooks;
- task delegation;
- context management;
- terminal-native autonomous workflow.

Do NOT copy unavailable/proprietary source code. Implement equivalent public behavior using open-source Atlas/Codex/Hermes/Pi components.

#### 3. NousResearch/hermes-agent — PRIMARY OPEN PERSONAL AGENT REFERENCE

Priority: HIGHEST for long-lived personal Agent capabilities.

Why:
- MIT;
- broad built-in tool registry;
- terminal/files/browser/vision/delegation;
- persistent memory and session search;
- skills that improve/reuse experience;
- MCP;
- scheduled tasks;
- multiple surfaces from one agent core.

Inspect and reuse/adapt:
- tool registry/toolsets;
- terminal/process/file tools;
- browser tools;
- delegation;
- skills loading/creation;
- memory/session_search;
- plugin architecture;
- session persistence;
- gateway/multi-surface architecture.

Atlas MemoryOS remains separate where already stronger; do not blindly replace it.

#### 4. zai-org/ZCode — PRIMARY MULTI-SURFACE AGENT RUNTIME REFERENCE

Priority: HIGHEST for desktop/browser/terminal unification.

Why:
- official Z.ai coding agent harness;
- Apache-2.0;
- desktop + browser + terminal;
- Agent CLI/runtime source included in repository;
- directly relevant to Atlas desktop architecture.

Inspect and reuse/adapt:
- apps/zcode-cli Agent runtime;
- desktop-to-agent transport;
- terminal/desktop shared runtime;
- model/tool session state;
- streaming;
- task lifecycle;
- UI integration boundaries.

#### 5. Pi / pi-mono — PRIMARY EMBEDDABLE MINIMAL AGENT HARNESS REFERENCE

Priority: HIGHEST for minimal reusable agent-core design.

Why:
- small core;
- dedicated agent-core with tool calling/state;
- coding-agent built on top;
- extensions/skills/prompt templates;
- RPC and SDK embedding modes;
- multi-provider model layer.

Inspect and reuse/adapt:
- agent-core;
- tool-call state machine;
- session persistence/branching;
- extension API;
- RPC/SDK embedding;
- context file loading;
- provider abstraction.

### Agent-core selection rule

Luna must compare at least:

| Agent | Open core usable directly | Session/resume | tool loop | compaction/context | subagents/delegation | skills/plugins | multi-surface | Atlas fit |
|---|---|---|---|---|---|---|---|---|
| Codex | | | | | | | | |
| Claude Code | behavior reference | | | | | | | |
| Hermes | | | | | | | | |
| ZCode | | | | | | | | |
| Pi | | | | | | | | |

Then choose:

- ONE primary Agent core/harness direction;
- optional components from the others;
- Computer Use as a replaceable executor/backend.

Do NOT create a sixth custom Agent architecture unless a concrete Atlas requirement cannot be met by these first-tier systems.

## Computer Use sources become execution backends

After Agent-core selection, evaluate:

- OpenCUA;
- Agent-S3;
- UI-TARS / Agent TARS;
- UFO;
- Browser Use.

These supply:
- screenshot/grounding;
- GUI operator;
- UIA/control semantics;
- browser automation;
- observation-action loops.

But Atlas's top-level Agent lifecycle should primarily follow the first-tier general Agent harnesses above.

## Preferred Atlas composition

Target composition should converge toward:

`Codex / Hermes / ZCode / Pi-class Agent core`
+ `P18A full local CLI execution`
+ `Agent-S / UI-TARS / UFO-class Computer Use backend`
+ `Atlas MemoryOS / Skills / MCP`
+ `Atlas desktop UI`

Claude Code serves as a first-tier behavioral benchmark for the resulting experience.

## Reuse policy

For open-source first-tier components:

`direct dependency > vendor/copy complete module with attribution > thin adapter > rewrite`

For proprietary/non-open implementation details:

`documented/public behavior replication > compatible open-source substitute`

Always preserve license notices and record upstream repo, commit, paths, and license in task results.


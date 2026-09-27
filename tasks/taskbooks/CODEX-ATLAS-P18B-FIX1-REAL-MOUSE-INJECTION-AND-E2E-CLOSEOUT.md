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

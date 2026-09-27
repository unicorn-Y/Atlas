# CODEX-ATLAS-P18B-FIX1-REAL-MOUSE-INJECTION-AND-E2E-CLOSEOUT

STATUS: READY
WORKER: Luna
BASE_BRANCH: main
PREDECESSOR: CODEX-ATLAS-P18B-GUI-DESKTOP-COMPUTER-USE
CODE_BASE_HEAD: eb5e9fe4d41a00eeaee13397e580236ceb7a2545

## Objective

只修复 P18B 当前唯一真实阻塞：Windows 鼠标事件能够移动指针但 click 未触发真实控件。

修复后一次性补齐原 P18B 尚缺的端到端验收：

- click / double-click / drag / scroll；
- Notepad 保存回读；
- 两应用工作流；
- observe -> reason -> act -> observe；
- P18A CLI + P18B GUI 混合调用；
- packaged/installed GUI workflow。

不要重写已经工作的 screenshot/window/keyboard/clipboard/Agent integration。

## A. Diagnose real mouse injection first

必须先建立最小诊断，不允许直接堆 fallback。

对当前 Tk isolated test 至少记录：

- Atlas process integrity/elevation context;
- target test process integrity/elevation context;
- foreground HWND;
- focused child HWND;
- `WindowFromPoint` target HWND/class;
- cursor coordinates before/down/up/after;
- virtual desktop metrics;
- DPI awareness context;
- `ctypes.sizeof(_MOUSEINPUT)`, `ctypes.sizeof(_INPUT)`;
- SendInput return count;
- GetLastError when count is not expected;
- whether WM_MOUSEMOVE / WM_LBUTTONDOWN / WM_LBUTTONUP are observed by target;
- whether target receives activation/focus changes.

Determine the actual failure layer before changing behavior.

Candidate areas to verify include:

- Win32 ctypes structure/layout correctness on Windows x64;
- INPUT/MOUSEINPUT field types and pointer-size alignment;
- SendInput flags;
- absolute virtual-desktop normalization;
- focus/foreground ordering;
- DPI-awareness coordinate mismatch;
- UIPI/integrity-level blocking;
- timing/message-pump behavior.

Do not assume the cause from this taskbook.

## B. Fix one canonical real-input path

After diagnosis, implement the smallest correct fix.

Requirements:

- `computer_mouse(click)` must produce a real user-session click;
- primary behavior must represent actual desktop input, not app-specific control invocation;
- do not special-case Tk;
- do not special-case Notepad;
- do not hardcode window class `Button`;
- do not use BM_CLICK as the normal Computer Use click implementation;
- do not claim success based only on cursor movement;
- input failure must be observable as failure, not silently swallowed.

Window-message helper functions may be removed, retained for diagnostics, or used only if there is a principled reason, but there must not be two ambiguous competing normal click paths.

## C. Primitive live acceptance

Using real Windows UI targets, prove:

1. single left click invokes target action once;
2. double-click invokes expected double-click behavior;
3. drag changes a real target state/position/selection;
4. vertical scroll changes real scroll position/content;
5. horizontal scroll if supported by target;
6. right click opens or triggers a real context behavior where stable;
7. mouse_down/mouse_up sequence is observable;
8. pointer coordinates remain aligned with screenshot coordinate space.

Tests must assert effects, not merely API return values.

## D. Notepad Agent workflow

Through the normal Agent loop, with FULL_ACCESS and no approvals:

1. P18A launches Notepad;
2. Agent observes desktop;
3. Agent identifies/focuses Notepad;
4. Agent types a Chinese/Unicode marker;
5. Agent saves to an isolated temporary file using real GUI interaction;
6. Agent closes or otherwise completes the GUI save flow;
7. P18A `local_file` reads the file;
8. exact marker is verified.

The test must not call internal runtime methods directly for the main workflow.

## E. Cross-application workflow

One Agent run must use at least two ordinary Windows desktop apps.

Preferred stable flow:

- File Explorer + Notepad

or another pair available on the test host.

The Agent must:

- observe;
- act in app A;
- switch/focus app B;
- act in app B;
- verify resulting state using screenshot and/or P18A local tools.

No user intervention.

## F. Real observe -> reason -> act -> observe

This gate is mandatory.

Use a deterministic/local multimodal test provider if needed, but the normal Agent path must receive actual screenshot image content and choose subsequent GUI tool calls based on that observation.

Required sequence:

`computer_observe`
→ model receives image
→ model emits GUI action
→ action executes
→ `computer_observe`
→ model receives new image/state
→ next action or completion

At least two observation rounds.

Do not hardcode the entire action sequence outside the Agent.

Coordinates/actions may be deterministic in the provider response for test repeatability, but they must be derived from/conditioned on the observation turn and executed through the real Agent tool loop.

## G. Mixed CLI + GUI in one run

At least one normal Agent run must use both:

- a P18A `local_*` tool;
- a P18B `computer_*` tool.

Example:

- local_exec launches Notepad;
- computer_observe/focus/type/save;
- local_file verifies output.

Assert that no `approval.required` event is emitted.

## H. Packaged/installed P18B acceptance

Run a P18B-specific workflow against actual packaged or NSIS-installed Atlas.

Requirements:

- no source checkout dependency;
- real desktop observation;
- real mouse click;
- real keyboard input;
- one complete GUI workflow;
- P18A local tools and P18B computer tools visible in same packaged Agent schema;
- FULL_ACCESS default;
- no approval event;
- clean shutdown;
- no Atlas-owned process residue;
- screenshot artifacts follow defined cleanup lifecycle.

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

- 重写 ComputerUseRuntime；
- 换成浏览器沙箱；
- 引入完整 RPA 平台；
- 用 Tk/Notepad 专用 hack；
- 用 BM_CLICK 伪装真实鼠标 click 作为生产主路径；
- 只让测试过、不验证真实输入；
- 跳过 click/double-click/drag/scroll；
- 用固定脚本冒充 Agent loop；
- 默认增加 approval；
- 降低 FULL_ACCESS；
- 开始 P18C；
- 开始语音、摄像头、手机/远程设备；
- 做无关 UI 重构。

## Delivery

1. Read `LUNA_WORKER.md`.
2. Pull `origin/main`.
3. Record actual starting HEAD as BASE_HEAD.
4. Read P18B task/result/review.
5. Reproduce the live click failure before editing.
6. Record concrete diagnosis evidence.
7. Fix the root cause.
8. Complete all remaining P18B E2E gates.
9. Write:
   `tasks/results/CODEX-ATLAS-P18B-FIX1-REAL-MOUSE-INJECTION-AND-E2E-CLOSEOUT.result.md`
10. Commit implementation + result.
11. Push `origin/main`.
12. Verify LOCAL_HEAD == origin/main.
13. Verify git status clean.
14. Stop.

## Acceptance Gate

FIX1 passes only when real Windows mouse effects are demonstrated and the original P18B Agent/packaged GUI acceptance is closed.

Cursor movement without click delivery is failure.

Internal direct-runtime tests without normal Agent E2E are insufficient.

A Tk/Notepad-specific production workaround is insufficient.

## Queue Guard

P18B-FIX1 is the only READY task.

P18B remains not accepted until FIX1 review.

P18C remains BLOCKED.

Voice, camera and mobile/remote-device remain deferred.

BASE_HEAD_RULE:
After pulling origin/main, record the actual starting HEAD as BASE_HEAD.

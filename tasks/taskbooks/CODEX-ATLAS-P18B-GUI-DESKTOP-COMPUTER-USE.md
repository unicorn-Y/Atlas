# CODEX-ATLAS-P18B-GUI-DESKTOP-COMPUTER-USE

STATUS: READY
WORKER: Luna
BASE_BRANCH: main
PREDECESSOR: CODEX-ATLAS-P18A-FULL-LOCAL-EXECUTION-CLI-AGENT
CODE_BASE_HEAD: c3f128eeb6fd0d6dee6bc58e6f5740d3a903eea7

## Objective

让 Atlas 获得真实 Windows 桌面 GUI Computer Use 能力，并接入现有 Agent tool loop。

P18A 已经提供 CLI 级完整本机执行能力。

P18B 增加：

screen observation
→ window discovery/focus
→ mouse
→ keyboard
→ clipboard
→ GUI action
→ re-observe
→ continue

目标不是做一个“演示鼠标点击”的玩具接口，而是让 Atlas 可以像本地 Computer Use Agent 一样操作普通 Windows 桌面程序。

默认权限继续遵循：

`FULL_ACCESS`

不做逐点击、逐按键 approval，不限制到 Atlas 窗口或浏览器沙箱。

## Product Principle: FULL_ACCESS GUI control

默认 GUI Computer Use 行为：

- 可以观察整个用户桌面；
- 可以操作当前用户会话中可见的普通 Windows 窗口；
- 可以移动鼠标；
- 可以左/右/中键点击；
- 可以双击；
- 可以拖拽；
- 可以滚轮；
- 可以键盘输入；
- 可以组合快捷键；
- 可以使用剪贴板；
- 可以切换、聚焦、最小化、最大化、恢复、移动和调整普通窗口；
- 可以跨应用连续操作；
- 不要求每个动作向用户确认；
- 不设置应用白名单；
- 不设置窗口白名单；
- 不限制在 Electron/Atlas 自己的窗口。

权限限制如未来保留，只能是用户主动开启的可选 restricted mode，不得成为默认。

## Scope

### A. Desktop observation runtime

新增 Atlas-owned Windows desktop runtime，至少支持：

- full desktop screenshot；
- single monitor screenshot；
- active window screenshot；
- specified window screenshot；
- cursor position；
- screen/monitor geometry；
- DPI/scaling-aware coordinates；
- active/foreground window identity；
- visible top-level window list。

Screenshot output must be consumable by the existing multimodal Agent path or a canonical artifact/image path that the Agent can inspect.

Do not require the user to manually save/upload screenshots.

### B. Window management

Provide native desktop/window tools for:

- list windows；
- identify foreground window；
- focus/activate window；
- restore；
- minimize；
- maximize；
- move；
- resize；
- close normal application window where requested；
- return window handle/id, title, process name/PID, bounds, visibility/state.

Windows-first.

Do not create a fake virtual desktop or sandboxed browser.

### C. Mouse control

At minimum:

- move absolute；
- move relative；
- left/right/middle click；
- double-click；
- mouse down/up；
- drag；
- vertical scroll；
- horizontal scroll where practical。

Coordinate system must be consistent with screenshots and multi-monitor desktop geometry.

### D. Keyboard control

At minimum:

- type Unicode text；
- key press；
- key down/up；
- hotkey combinations；
- navigation keys；
- function keys；
- Windows key combinations where the current user session permits them。

Must correctly handle ordinary Chinese/Unicode text entry. If direct virtual-key typing is insufficient, use clipboard paste or a Windows-native Unicode input path.

### E. Clipboard

At minimum:

- read text clipboard；
- write text clipboard；
- preserve/restore text clipboard when a tool explicitly uses clipboard only as an implementation detail for Unicode typing, where practical.

Expose clipboard as an Agent tool only for ordinary current-user clipboard operations.

### F. Agent integration

Integrate desktop tools into the existing Agent tool loop.

Requirements:

- LLM sees desktop tool schemas;
- no second Agent loop;
- screenshot/observation result can be fed back into multimodal reasoning;
- tool calls use existing runtime events;
- action results identify what was done and target window/coordinates;
- Agent can perform multiple observe → act → observe iterations in one run;
- user cancel stops the current Computer Use run loop;
- local CLI tools from P18A stay available in the same Agent run.

The intended behavior is that Atlas can mix CLI and GUI freely.

Example:

1. use `local_exec` to launch Notepad;
2. observe desktop;
3. identify Notepad window;
4. focus it;
5. type text;
6. save through GUI;
7. use `local_file` to verify the saved file.

### G. Vision/observation handoff

P18B must make screenshot observations usable by the Agent.

Reuse existing image/multimodal support where possible.

At minimum:

- screenshot returns image path/asset plus metadata;
- Agent can include that screenshot in a subsequent model call;
- image is not merely displayed to the user while hidden from Agent reasoning;
- repeated observations do not require user re-upload.

Do not build OCR as the primary perception system in this task.

Do not require a local vision model. Use the currently selected model's multimodal capability where available.

If the active model cannot process images, return a clear capability error rather than silently pretending to understand the screen.

### H. Desktop action state/events

Expose enough runtime metadata for UI/debugging:

- screenshot/observation id;
- monitor/window target;
- coordinates;
- action type;
- active window before/after where practical;
- success/failure;
- image artifact/path for screenshot actions.

The existing conversation activity UI may be minimally extended to show Computer Use actions.

Do not build a new full desktop-control dashboard.

### I. FULL_ACCESS behavior

Default config should be equivalent to:

`computer_use.permission_mode = "full_access"`

Default must NOT:

- emit approval.required before each screenshot/click/key;
- ask permission per application;
- ask permission per monitor;
- force Atlas into a browser-only environment;
- restrict GUI actions to a predefined app list.

An explicit deny/restricted mode may exist as an optional setting, but default is unrestricted within the current Windows user session.

## Required acceptance scenarios

### Scenario 1: Notepad end-to-end

Through the normal Agent loop:

1. launch Notepad using P18A local execution;
2. observe desktop;
3. locate/focus Notepad;
4. type a Unicode/Chinese marker;
5. use keyboard shortcut/UI to save to a temporary file;
6. close/reopen or otherwise verify the GUI operation;
7. use P18A `local_file` to verify exact file content.

No user intervention or approval prompts.

### Scenario 2: Cross-application workflow

Agent must use at least two different desktop applications in one run.

Example:

- open File Explorer;
- navigate/open a temp folder;
- open a text file in Notepad;
- edit/save;
- return to Explorer and verify file presence.

Exact apps may vary based on stable Windows availability.

### Scenario 3: Multi-step observe/action loop

Agent must execute at least:

observe
→ action
→ observe
→ action
→ observe

using real screenshots and model reasoning/tool selection.

It is not sufficient to hardcode exact coordinates for every step in the test.

### Scenario 4: Window management

Verify real:

- list windows;
- focus;
- move;
- resize;
- minimize;
- restore/maximize.

At least one test window must be moved/resized and its reported bounds must change accordingly.

### Scenario 5: Mouse and keyboard primitives

Verify:

- click;
- double click;
- drag;
- scroll;
- hotkey;
- Unicode text entry;
- clipboard read/write.

### Scenario 6: Packaged Atlas

From actual packaged/installed Atlas:

- desktop screenshot works;
- window listing works;
- mouse/keyboard actions work;
- P18A local execution and P18B GUI tools are both available in the Agent tool schema;
- one complete GUI workflow succeeds;
- no source checkout dependency.

## Required tests

At least cover:

1. default computer-use permission mode is full_access;
2. screenshot full desktop succeeds;
3. monitor metadata is correct;
4. active-window screenshot succeeds;
5. window list returns visible top-level windows;
6. foreground window detection works;
7. focus/activate works;
8. move/resize works;
9. minimize/restore/maximize works;
10. mouse absolute move works;
11. click works;
12. double click works;
13. drag works;
14. vertical scroll works;
15. keyboard press works;
16. hotkey works;
17. Unicode/Chinese text entry works;
18. clipboard read/write works;
19. screenshot coordinates align with input coordinates;
20. multi-monitor geometry handled if multiple monitors are present;
21. repeated screenshots clean up temporary artifacts according to defined lifecycle;
22. Agent can receive screenshot as multimodal observation;
23. Agent performs observe → act → observe loop;
24. Agent can mix P18A CLI and P18B GUI tools in one run;
25. no approval.required event in default full_access GUI path;
26. user cancellation stops active Computer Use run;
27. packaged Atlas Computer Use smoke passes;
28. existing P18A local execution regressions remain green;
29. existing MCP/Skill/chat paths remain green;
30. P17 release acceptance remains green where affected;
31. full `test_server.py` remains green;
32. frontend tests/build remain green when touched;
33. Ruff on changed Python files passes;
34. `git diff --check` clean;
35. LOCAL_HEAD == origin/main;
36. git status clean.

## Implementation guidance

Prefer a small Windows-native runtime abstraction.

Allowed approaches include:

- Win32 APIs through `ctypes` / pywin32;
- reliable screenshot capture library such as `mss`;
- Pillow where image encoding/cropping is useful;
- Windows clipboard APIs;
- SendInput or another Windows-native input path.

Do not add a heavyweight RPA platform unless the existing implementation clearly requires it.

Do not depend on OCR as the main perception path.

Keep screen capture and input coordinate spaces explicit and testable.

## Validation

Must execute:

- native desktop tool unit/integration tests;
- Notepad full workflow;
- observe/action/re-observe Agent workflow;
- window move/resize/focus scenario;
- Unicode keyboard/clipboard scenario;
- packaged Atlas Computer Use smoke;
- P18A local execution regression;
- existing Agent/MCP/Skill regressions;
- full `core/tests/test_server.py`;
- relevant P17 packaged acceptance where packaging changes;
- frontend tests/build if touched;
- Ruff on changed Python;
- `git diff --check`;
- desktop process/window cleanup check;
- LOCAL_HEAD == origin/main;
- git status clean.

## Forbidden

不得：

- 默认逐点击 approval；
- 默认逐按键 approval；
- 默认逐窗口 approval；
- 默认应用白名单；
- browser-only sandbox；
- fake/virtual desktop as the only execution target；
- 把 Computer Use 限制在 Atlas 窗口；
- 只做 screenshot 不做 input；
- 只做 input 不做 observe；
- 用固定坐标脚本冒充 Agent Computer Use；
- 新造第二套 Agent loop；
- 删除或弱化 P18A FULL_ACCESS local execution；
- 开始实时语音；
- 开始摄像头；
- 开始手机/远程设备；
- 做无关 UI 重构。

## Non-goals

P18B does not require:

- accessibility/UIA semantic element tree;
- OCR-first perception;
- browser DOM automation;
- autonomous background screen monitoring;
- webcam;
- voice;
- mobile control.

These can be added after the basic full-desktop observation/action loop is accepted.

## Delivery

1. Read `LUNA_WORKER.md`.
2. Pull `origin/main`.
3. Record actual starting HEAD as BASE_HEAD.
4. Read `PLAN.md`.
5. Read P18A task/result/review and current multimodal/image handling code.
6. Inspect current Agent tool registration/runtime-event/image attachment paths before implementation.
7. Execute only this taskbook.
8. Write:
   `tasks/results/CODEX-ATLAS-P18B-GUI-DESKTOP-COMPUTER-USE.result.md`
9. Commit implementation + result.
10. Push `origin/main`.
11. Verify LOCAL_HEAD == origin/main.
12. Verify git status clean.
13. Stop.

## Acceptance Gate

P18B only passes when packaged Atlas can observe and control the real Windows desktop through the normal Agent loop: capture screen, reason over observations, manage windows, move/click/drag/scroll the mouse, type/hotkey/clipboard, perform a multi-step GUI workflow, and mix GUI control with P18A CLI tools under default FULL_ACCESS mode without per-action approvals.

A screenshot-only implementation, hardcoded coordinate demo, browser sandbox, or approval-gated default is NOT sufficient.

## Queue Guard

P18B is the only READY task.

P18A CLI-level FULL_ACCESS local execution is complete and accepted.

P18C may add semantic UI Automation / richer desktop perception after P18B review.

Voice, camera, mobile/remote-device remain deferred.

BASE_HEAD_RULE:
After pulling origin/main, record the actual starting HEAD as BASE_HEAD.

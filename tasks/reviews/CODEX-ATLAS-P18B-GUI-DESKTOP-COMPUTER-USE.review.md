# CODEX-ATLAS-P18B Review

REVIEW_RESULT: REWORK
REVIEWED_HEAD: `eb5e9fe4d41a00eeaee13397e580236ceb7a2545`
BASE_HEAD: `30aaa064dd8dc3f0b2fa2ed08c3eeb7cce6c36f9`

## Verdict

P18B is not accepted yet.

The implementation is directionally correct and substantial parts of the Computer Use stack are already working, but the acceptance gate explicitly requires real desktop input and a complete observe -> act -> observe workflow. The live Windows click test failed, so the task cannot be marked PASS.

The worker was correct to report BLOCKED rather than claim completion.

## What is already accepted as implemented

The following P18B foundation is valid and should be preserved rather than rewritten:

- native Windows desktop observation via mss + Win32;
- monitor metadata and virtual-desktop coordinate reporting;
- visible-window discovery and foreground/focus handling;
- window move/resize/minimize/maximize/restore support;
- Unicode keyboard input;
- hotkey/key support;
- text clipboard read/write;
- screenshot handoff into the existing Agent multimodal message path;
- existing Agent loop integration alongside P18A local execution;
- default `computer_use.permission_mode = "full_access"`;
- no per-action approval requirement in the default path;
- packaged build and P17 release regressions remain healthy.

## Blocking defect

The real Windows test demonstrates:

- the pointer moves to the intended button coordinates;
- screenshot/window observations work;
- the target control is identifiable;
- `computer_mouse(click)` returns without infrastructure failure;
- but the actual target callback is not invoked.

Therefore click delivery is not proven.

Because click is unproven, double-click, drag and wheel also lack trustworthy end-to-end evidence even though primitives exist.

The current main `_mouse()` path uses SendInput for mouse actions. The file also contains window-message helper methods (`_post_mouse_button`, `_post_mouse_move`, `_post_mouse_wheel`) that are not part of the normal `_mouse()` execution path. The FIX must not blindly layer fallback mechanisms; it must first determine why the canonical real-input path fails in the live test and then keep one clearly defined behavior.

## Remaining acceptance gaps

P18B still needs all of the following:

1. real click delivery;
2. real double-click evidence;
3. real drag evidence;
4. real scroll evidence;
5. Notepad save + local-file verification through normal Agent loop;
6. at least one two-application workflow;
7. real screenshot -> model reasoning -> GUI action -> screenshot loop;
8. mixed P18A CLI + P18B GUI tool use in the same Agent run;
9. P18B-specific packaged/installed GUI acceptance.

## Decision

P18B: **REWORK**.

Do not start P18C.

Create one narrow FIX task that repairs native mouse injection and then closes the remaining original P18B acceptance scenarios without redesigning the working observation/window/keyboard/clipboard stack.

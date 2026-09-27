# CODEX-ATLAS-P18B-FIX1-REAL-MOUSE-INJECTION-AND-E2E-CLOSEOUT

STATUS: READY
WORKER: Luna
BASE_BRANCH: main
PREDECESSOR: CODEX-ATLAS-P18B-GUI-DESKTOP-COMPUTER-USE
CODE_BASE_HEAD: fa1c7743b4dafea18d134b547b4b8ccef97278a7

## EXECUTION MODE: DIRECT INTEGRATION, NO MORE ARCHITECTURE RESEARCH

本轮目标只有一个：**尽快把 P18B 真正跑通。**

禁止继续花时间做：

- 五个项目 fit table；
- Agent 架构大对比；
- 重写 Atlas Agent core；
- 自己重新实现 mouse/input backend；
- 大规模重构；
- 新的抽象层；
- 防御性编程扩展。

已经确认：

- 当前 SendInput 在独立真实进程目标上可正常 click；
- click / double click / right click / drag / vertical scroll / Unicode keyboard / clipboard 已有真实 Windows 证据；
- 原先 click 失败是旧测试 harness 假阴性；
- 生产 mouse backend 当前不需要重写。

所以从现在开始：**直接接成熟能力，补齐剩余 E2E，然后收工。**

## Integration rule

### 1. Keep current Atlas Agent loop for P18B

本任务不要替换 Agent core。

Codex / Claude Code / Hermes / ZCode / Pi 的 Agent-core 复用放到 P18B 完成后的独立阶段。

P18B 现在只需要让现有 Atlas Agent 能真正使用 Computer Use 完成桌面任务。

### 2. Directly add mature Windows semantic control support

优先直接添加：

- `pywinauto` UIA backend

参考/复用 Microsoft UFO 的现成设计：

- window discovery;
- control inspection;
- semantic click;
- focus;
- type/set text where reliable;
- invoke/select controls;
- control rectangle / automation id / control type.

不要复制 UFO 整个 Agent。

Atlas 只需增加一个很薄的 UIA adapter，例如：

- `computer_controls(list)`
- `computer_control(action=click/focus/invoke/type/...)`

或者复用现有 `computer_window/computer_mouse/computer_keyboard` schema，只在内部增加 UIA target path。

### 3. Hybrid execution

P18B 最终直接采用：

`UIA semantic action when available`
+
`existing screenshot + coordinate mouse fallback`
+
`existing keyboard/clipboard`

不要追求单一路径纯洁。

能用 UIA 稳定点按钮，就 UIA。

UIA 找不到，就用视觉截图 + coordinate mouse。

## Immediate required work

### A. Restore/keep primitive Windows tests green

必须通过：

- screenshot;
- window list/focus;
- click;
- double click;
- right click;
- drag;
- vertical scroll;
- mouse down/up;
- Unicode typing;
- clipboard;
- coordinate alignment;
- move/resize/minimize/maximize/restore.

不要再改 production mouse backend，除非新的真实外部进程测试再次证明它坏。

### B. Notepad E2E — do this now

通过正常 Atlas Agent loop：

1. `local_exec` 启动 Notepad；
2. `computer_observe`；
3. UIA 或截图定位 Notepad；
4. focus；
5. 输入中文 marker；
6. Ctrl+S 或 UIA Save；
7. 保存到 isolated temp path；
8. `local_file` 回读；
9. 精确验证 marker；
10. 关闭 Notepad。

不需要用户操作。

不允许 approval。

### C. File Explorer + Notepad

同一 Agent run：

1. 打开 temp folder；
2. File Explorer 可见；
3. 打开目标 txt；
4. 切到 Notepad；
5. 编辑；
6. 保存；
7. 切回 Explorer；
8. 通过 UI 或 `local_file` 验证结果。

### D. Real observe → act → observe

至少：

`computer_observe`
→ model sees real image
→ model emits action
→ execute
→ `computer_observe`
→ model sees changed image
→ next action/completion.

使用 deterministic multimodal provider 保证测试稳定可以。

但必须走正常 Agent loop。

### E. Mix CLI + GUI in one run

同一 run 必须同时出现：

- `local_exec` or `local_file`
- `computer_observe`
- one GUI action
- final local verification

并断言没有 `approval.required`。

### F. Packaged / installed Atlas GUI smoke

实际 packaged 或 NSIS-installed Atlas：

- screenshot；
- window discovery；
- click；
- keyboard；
- Notepad 或等价 GUI workflow；
- P18A + P18B tools 同时可见；
- no source checkout dependency；
- no approval；
- clean shutdown；
- no process residue。

## Dependencies

允许直接新增成熟依赖：

- `pywinauto`
- 其必要 Windows 依赖

不要为了少一个依赖而继续手搓 UIA。

## Upstream attribution

若复制/改编 UFO 代码：

- 记录 repo: `microsoft/UFO`;
- 记录 upstream commit;
- 记录具体 source path;
- 保留 MIT attribution。

若只是使用 pywinauto API，不需要复制 UFO 实现。

## Required regression

跑：

- P18B native tests;
- P18A local execution;
- Agent tests;
- MCP/Skill regressions;
- full `test_server.py`;
- packaged P17/P18 relevant acceptance;
- frontend tests/build if touched;
- Ruff;
- `git diff --check`;
- process residue check;
- LOCAL_HEAD == origin/main;
- git status clean.

## STOP CONDITIONS

只有以下情况允许停：

1. 实际 Windows 环境存在无法由代码解决的外部阻塞；
2. packaged GUI acceptance 有真实不可绕过系统限制；
3. 所有 P18B gates 已通过。

不得因为“还可以优化架构”而停。

## Forbidden

不得：

- 再做 Agent 项目大调研；
- 再写 fit table；
- 替换 Atlas Agent core；
- 重写 SendInput；
- 自己实现完整 UIA 框架；
- 引入完整 UFO/Agent-S/UI-TARS app；
- 做 P18C；
- 做语音/摄像头/手机；
- 无关 UI 重构。

## Delivery

1. Pull latest `origin/main`.
2. Record actual BASE_HEAD.
3. Read current P18B result.
4. Directly implement thin pywinauto/UIA adapter if needed.
5. Finish all E2E gates.
6. Write/update:
   `tasks/results/CODEX-ATLAS-P18B-FIX1-REAL-MOUSE-INJECTION-AND-E2E-CLOSEOUT.result.md`
7. Commit.
8. Push.
9. Verify local HEAD == origin/main.
10. Verify clean working tree.
11. Stop.

## Acceptance Gate

P18B-FIX1 passes when installed/packaged Atlas can complete a real Windows GUI task through the normal Agent loop using existing P18A CLI + P18B Computer Use, with real observe/action/re-observe behavior and no user approval prompts.

Architecture comparisons do not count as progress.

Working product behavior is the only gate.

## Queue Guard

P18B-FIX1 is the only READY task.

P18C remains BLOCKED.

FULL_ACCESS remains default.

# WAVE 4 独立会话任务书（批次负责人版）

## 你的身份

你是一个**批次负责人**，负责 WAVE4-PLAN.md 分给你的一批 rows。
本轮编排器（主会话）已经把多个批次并行跑起来了；**你不要再 spawn 子代理**——
本机子代理并发上限约 3，嵌套派工会被取消并留下半成品文件污染 worktree。
你自己在批内串行做，按 row 逐条推进即可。

## 必读（都是只读，不许改）

- `D:\Atlas\tasks\dsh-parity\WAVE4-PLAN.md` — 本轮策略（只做「暴露 + 取证」）、验收标准、硬规则
- `D:\Atlas\docs\parity\DSH-GAP-LEDGER.md` — 你负责行的 path:line 证据（主检出区这份含未提交的 W3-X6 状态更新，是最新版）
- `D:\Atlas\AGENTS.md` — 仓库禁区
- 注意：`D:\Atlas` 主检出区只读。**一切编辑、提交只发生在你自己的 worktree 里。**

## 硬规则（违反则改动作废，来自 WAVE4-PLAN）

1. 不重写 `messages` 表语义
2. 不在 `_execute_write` 回调里再调 `_execute_write`（死锁）
3. 桌面事件名三处真源同步（`core/atlas/api/event_names.py` / `frontend/src/renderer/services/runtimeEvents.ts` / `frontend/src/types/runtime.ts`），并跑 `core/tests/test_event_contract.py`
4. 新测试必须标 `@pytest.mark.unit`（pytest addopts 默认 `-m unit`，不标会被静默 deselect）
5. 不许把「写了代码」当 CLOSED；RESULT 必须贴真实命令输出
6. 只改自己 worktree 内的文件；发现真的缺底层就标 `HARD(detail)`，不要硬写新原语

## 测试执行环境事实（2026-11 实证，别踩）

- pytest 必须 `--basetemp=D:/Atlas/.worktrees/w4-<Z>/.tmp/pytest`，**先 `mkdir -p` 父目录**，
  否则 Windows 默认 tmp 路径符号链接会 WinError 5 全量报错。
- 用 `python -m pytest` 且 cwd=worktree 的 `core/`（cwd 进 sys.path，`import atlas` 才成立）。
- 输出**绝不能过 tail 管道**再后台跑（缓冲吞进度、退出码判错）；长跑直接 `> log 2>&1`。
- pytest summary 打印后进程可能挂活不退出：一次运行只有进程真正退出、退出码 0 才算通过；
  跑完查 `Get-CimInstance Win32_Process` 里命令行含你的 basetemp 的残留，确认后再杀。
- 已知既有失败（不是你的回归，别修别弱化，RESULT 里引用即可）：
  - `test_installed_plugin_crosses_real_runtime_paths`：GBK 中文乱码导致子串断言失败
  - `test_mcp_lifecycle_shutdown.py` 3 项：真实 stdio 子进程生命周期/取消（见 RESULT3-X5）
  - 满载下真进程/真桌面类测试偶发失败：判定标准 = 隔离复跑 2–3 次

## 真实模型通道（已验证）

```bash
cd <你的worktree>\core
http_proxy=http://127.0.0.1:7897 https_proxy=http://127.0.0.1:7897 \
  python -m uvicorn atlas.server:app --port <你的端口>
# 另一个终端：
python scripts/dsh_live_ws_check.py <你的端口> "Reply with exactly the word: OK"
```

模型 `deepseek-v4.1-flash` @ d1api.xin，key 在系统凭据库（后端自己取，不需要环境变量）。
脚本会打印收到的每个事件 + 终态 + 回复文本——那段输出就是取证材料，原样贴进 RESULT。
后端起在**你自己的端口**上，跑完记得关掉进程。

## 你的工作目录

只在你被分配的 worktree 里改文件（路径在派单消息里），分支已建好，直接提交到你自己的分支。

## 交付

1. 开工先输出：「rows → 每条的动作（暴露/取证/两者）→ 文件清单」
2. 逐条施工：实现 + 测试 + 取证；每条 row 在 RESULT 里给一行结论（CLOSED / PARTIAL+缺什么 / HARD(reason)）
3. 写 `tasks/dsh-parity/waves/RESULT4-<Z>.md`（贴真实命令输出，不许编造）
4. 顺带更新你自己 worktree 里 `docs/parity/DSH-GAP-LEDGER.md` 中你负责的行（状态列 + 现状列）
5. commit 到你自己的分支（可分批多次提交）

## 禁止

- spawn 子代理（并发上限会拒，被取消的会留半成品）
- 改别人的 worktree 或主检出区
- 把 PARTIAL 说成 CLOSED
- 用「测试全绿」冒充可用（E/S/X 区 CLOSED = 单测 + 真实模型回合证据）

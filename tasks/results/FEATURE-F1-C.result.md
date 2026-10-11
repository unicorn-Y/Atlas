# FEATURE-F1-C（设置与扩展）交付记录

承接 FEATURE-F1 的 C 区对标施工。前任 agent 额度耗尽，代码已改好但未提交、后端无法启动；本轮接手排查、修复、补完并提交推送。

## 一、接手时的现场

- 工作树 `D:\atlas-f1-c`（分支 `f1-c`），git 追踪在 `origin/memory-v1`（ce71ee9c）。
- 前任遗留 **35 个已改文件 + 19 个未跟踪新增项**，全部保留、未回滚。
- 后端起不来：`core/atlas/runtime/external_import.py` 第 968–970 行缩进错位，`import` 即抛 `IndentationError`。

## 二、本轮修复与补完

1. **修复致命语法错误**（阻塞项）：`_import_one` 内 `if kind == "history":` 被多缩进一层（968 行 `path = ...` 之后、969–970 行为悬挂的 16 空格块），改为正常函数体缩进。修复后 `python -m compileall core/atlas` 全绿。
2. **补齐 row33「活动统计/热图」**（前任清单承诺但缺失的真功能）：ZCode 的 `UsageHeatmap` 在上游是活动日历视图，前任只在用量页加了几个 tile、Clair 现状仍写「无活动热图」。
   - `frontend/src/renderer/pages/UsagePanel.tsx` 新增 `ActivityHeatmap` 组件 + `HEAT_LEVELS`：GitHub 风格近 12 周日历，7 行 × 13 列（周一起始，末列为当周），颜色按当日 token 相对 12 周峰值分 5 档（`color-mix(--brand)`），0 用量为空白格，含图例、悬停提示（日期 / token / 轮数）与 `aria-label`。
   - 数据来自既有真实端点 `/api/usage?group_by=day&from=<84天前>`（`backend.getUsage('day', isoDaysAgo(84))`），固定 84 天窗口、与上方区间/分组选择器解耦，保证视图始终可比。非假按钮、非占位数据。

## 三、逐条核对

- 抽取 `docs/parity/F1-C.md` 全部 166 行，逐行比对「本次处理」承诺 vs 实际实现，并用脚本对 30 个功能域全库检索定位实现文件。
- 结论：清单中每一处「新增/补齐」承诺都有对应实现；所有「本次没有实现 / 不适用 / 保留边界」条目均如实记录为未做，未造任何假控件或假功能。
- 高风险「真执行」声明抽查为真：
  - 运行轮次上限真拦：`kernel/loop.py` 读取 `run_limits.max_turns` 并以 `min(engine, user)` 为实际循环上限（`for turn_index in range(max_turns)`），到顶抛 `RuntimeError`。
  - 成本上限：`run_limits_router` 报 `cost_limit_supported: true`，价格未知/usage 缺失时阻止后续请求。
  - Linear：固定官方 `https://api.linear.app/graphql`，真实 issue/comment mutation，非桩。
- 路由真实性：起隔离后端后核对内部路由表（468 条），13 个新增 C 区 router 的端点全部存在；逐个 GET 验证 `200`（需参数者为 `422`）。
  - 注：中途曾出现 `/api/import/external/history` 等 404，经查是**上个会话遗留的旧进程（PID 72600 `atlas.cli serve --port 28767`）占着测试端口**导致；清掉旧进程、在本次工作树上重启后端后全部通过。

## 四、最小确认

- **后端启动：通过。** `cd core && ATLAS_UPSTREAM_AUTO=0 python -m uvicorn atlas.server:app --port 28767`，`GET /api/health` 返回 `{"status":"ok", ...}`，全部组件（dbos/mcp/skills/plugins/engine_registrations/channels/automation/scheduler/telegram/extensions/session_migration）`ready`，`component_errors` 为空，随后停止进程并释放端口。
- **前端构建：通过。** `npm --prefix frontend run build` 退出码 0；`tsc`（electron / renderer）、preload 构建与 Vite production build 均成功。依赖已就位，无需 `npm ci`。
- **测试：未编写、未运行测试套件**（按任务要求）。
- `git diff --check` 无空白错误；提交未包含 `.pyc`、`__pycache__`、临时文件或 `frontend/dist`（已被 gitignore）。
- 实现只在 `D:\atlas-f1-c` 内；未改 `D:\Atlas` 及其他 `D:\atlas-*` 目录。

## 五、SHA 与推送

- **代码实现 SHA：`833a36ece414ec7bdb29e16432aeb01123ff55a6`** —— "feat(f1-c): finish 设置与扩展 parity"，71 个文件、+9927 / -359。本交付记录随后单独提交。
- 已 `git push origin f1-c`（新建并推送 `f1-c` 分支）。未推送 `memory-v1`，未合并其他分支。

## 六、遗留

- `atlas.api.deferred_startup` 的引擎预热会报 `ModuleNotFoundError: No module named 'agent.agent_hooks'`。该预热函数 `_warm_engine` **不在本次改动范围**（为既有代码），其失败被显式降级为「优化项，缺失模块由首轮自行导入」的无害注释，`engine_registrations` 仍报 ready，不影响 `/api/health` 与运行。记录为既有缺口，未在 C 区处理。

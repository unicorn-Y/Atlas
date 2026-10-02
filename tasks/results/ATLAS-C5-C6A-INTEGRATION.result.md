# ATLAS-C5-C6A-INTEGRATION 结果

- 日期：2026-10-02
- 基线：main @ `de3d520`（C4 PASS + 本波任务书）
- 执行：主控 + 4 个并行子代理冲突组（backend engine/server、backend-adapter、frontend store/App、docs），按文件独占划分
- 整合顺序：**先 C6A，后 C5**（按任务书）

## 一、合入的确切提交

| 线 | 分支 | 验收实现头 | 实际合并头（含验收 docs） | 合并提交 |
| --- | --- | --- | --- | --- |
| C6A | `zcode/c6a-lsp-parallel` | `110fdc2`（basedpyright 修复） | `fe3ecd4`（+review/accept docs） | `ae94040` |
| C5 | `zcode/c5-models-parallel` | `265c682`（C5R 两项修复） | `4b30834`（+review/accept docs） | `c762377` |

均以 `--no-ff` 合并提交进入 main，保留分支拓扑；未使用 ours/theirs 策略，未 cherry-pick 改写历史。

## 二、冲突与解决

### 真实冲突（git 无法自动合并，语义手工合并）

| 文件 | 双方改动 | 解决 |
| --- | --- | --- |
| `core/atlas/engine/hermes_runtime.py` | C4：lifecycle 钩子桥（PreCompact/PostCompact/SessionEnd）、权限/停止回调、usage_payload + context_breakdown；C5：route_kwargs 原生 provider 路由、L8 分档、缓存未命中原因 | 两个冲突块均在 usage 事件块：C5 诊断前置 + C4 的 `usage_payload` 字典，`cache_miss_reason` 以字典合并键并入，**单一 emit**；AIAgent 工厂改 `**route_kwargs`（见红线核查） |
| `backend-adapter/src/client.ts` | C4：hooks/plugins/commands/import 方法群；C5：provider/key/reasoning-stages/model edit-delete 方法群 | 仅 import 行冲突 → 双侧并集（55 个类型名）；类体 git 已自动并好，方法集与双侧并集 diff 为零 |
| `frontend/src/renderer/App.tsx` | C4：~160 行（权限卡、子 Agent、命令覆盖、状态栏等）；C5：1 行（SettingsPage props） | 冲突即该调用行 → 30 个 props 全量并集（HEAD 的 subagent/statusBar + C5 的 provider 组） |
| `frontend/src/renderer/pages/SettingsPage.tsx` | C4：状态栏、子 Agent 两节 + 5 个 props；C5：provider-first 模型设置重写（+150） | C5 正文原样保留，C4 两节插回「用户」与「Atlas 网关」之间；`SettingsPageProps` 30 个 props 对齐 App 调用 |
| `frontend/src/renderer/store/useAtlasStore.ts` | C4：subagent/pendingRunOverrides/customCommands 等 state/action；C5：+89/−2 纯增量（providers/reasoningStages/7 个 action + initialize 多一次 fetch） | 仅 import 行冲突 → 并集；增量体经双向 diff 验证为精确并集 |
| `tasks/ZCODE-CURRENT.md` | C6A 线状态块 vs C5 线状态块 | 改写为整合态（两线均 ACCEPTED、指向本波任务书/结果文件）；**未触碰 main 的 `tasks/CURRENT.md`**（两条分支均未修改过它，已核实） |

### git 自动合并但做了语义审查的文件

- `core/atlas/server.py`：确认恰为 +4 行（models_router import + 单次 `include_router`，位于 OriginGuard 之后）；C4 全部路由/中间件无损，无重复挂载。
- `core/tests/test_hermes_runtime_e2e.py`：C4 的既有用例（含 C4R 改名的 `..._read_only_tools`）+ C5 追加的 50 行分档用例，均恰出现一次。
- `backend-adapter/src/types.ts`、`tests/client.test.ts`：双侧类型/用例为精确并集；client.ts 所引 55 个类型全部由 types.ts 导出。
- `frontend/src/renderer/store/useAtlasStore.test.ts`：C5 的 fetch 计数偏移正确作用于既有用例；HEAD 新增的子 Agent 用例缺一次 mock（merged initialize() 共 9 次 fetch）→ 子代理补齐第 9 个 mock 并将 PUT 断言 `calls[8]→calls[9]`，另给 SettingsPage 渲染补上 C5 必填 props。收尾时补一处 `as const`（`REASONING_STAGES` 传入强类型 prop 触发 TS2769，C5 分支上无此用法故未暴露）。
- `docs/PARITY.md`、`docs/plan/CORE-PARITY.md`、`docs/plan/VENDORED.md`：三份均为精确并集（双向 diff 验证），零修复。

## 三、共享文件语义 checklist（双侧全保留）

**C4/C4R 侧：**
- [x] Hook lifecycle 桥：PreCompact/PostCompact（手动共享 HookStore + 自动压缩桥 PostCompact）、SessionEnd、工具前/后等 —— `test_c4_hooks.py` 35 条 C4 组全绿
- [x] PermissionRequest ask→既有审批卡片、deny 阻断、allow 可改输入放行（hermes_policy/runtime 回调链未动）
- [x] SubagentStop 同一 child 会话续跑（有界防死循环）
- [x] 自定义命令单次 model/tool_allow/tool_deny/mode 覆盖（run.start 单次生效）—— App/store/命令链路原样
- [x] server.py 的 C4 commands/skills/hooks 路由与 E2–E6 其余面完好

**C5 侧：**
- [x] provider catalog / Hermes 原生 provider 路由（16 家目录 + 原生 provider/api_mode/base_url 直传）—— `test_models.py` 等 78 条全绿
- [x] provider id 归一（catalog id ↔ hermes id 别名互查，含 C5R alias-aware edit 校验）
- [x] keyring 凭据池 / 轮换 / 冷却矩阵（429→1h、401/403→5min、唯一 key→60s、模型级 (key,model)）；密钥原文不回显；C5R「无 ghost key slot」修复随分支带入
- [x] staged reasoning effort（默认关；首轮/计划=规划档、执行档、stop-gate 验证档经 `_atlas_before_model_request` 切换）
- [x] cache miss 诊断（三层哈希 + 原因判定，随 run_usage 透出、落账本新列）
- [x] model edit/delete（PUT/DELETE `/api/models/custom/{id}` + 前端入口）
- [x] **红线核查 PASS**：无 `hermes_provider` 的模型条目，AIAgent 收到与改前逐字相同的五个构造参数（`model/provider="openai"/api_mode="openai"/base_url/api_key`）；`credential_pool` 与 provider 查找全部位于 `hermes_provider` 分支内；L8 默认关闭路径与改前行为一致

**VENDORED / THIRD_PARTY：**
- [x] `docs/plan/VENDORED.md`：C3R Goal 行 + C5 `reasoning_effort.py`/`models_dev.py` 行并集
- [x] `THIRD_PARTY_NOTICES.md`：C5 的 `e287231` 拷贝登记随合并带入
- [x] C6A 为移植实现（非 vendored 依赖），来源已在模块头注与结果文件登记，无需 VENDORED 行

## 四、聚焦验证（均无真实模型/provider 调用）

| 套件 | 结果 |
| --- | --- |
| C6A LSP 聚焦（7 个 test_lsp_*.py，C6A 合并后即时跑） | **73 passed**（10.6s） |
| C5 模型聚焦（test_models / test_model_credentials / test_models_routes / test_cache_diagnostics / test_reasoning_stages / test_hermes_runtime_e2e） | **78 passed**（115.9s） |
| C4/C4R 聚焦（test_c4_hooks / test_c4_skills_commands / test_c4_external_import / test_c4_plugin_e2e / test_subagent_settings） | **35 passed**（24.5s） |
| backend-adapter Vitest（client.test.ts） | **14 passed** |
| renderer `tsc -p tsconfig.renderer.json --noEmit` + `tsconfig.electron.json` | **PASS**（修复 1 处测试文件 `as const` 后） |
| renderer Vitest 全量 | **49 passed**（10 文件，含 C5 模型组件 6 条 + 修复后的 store 13 条） |
| `vite build`（生产构建一次，App/模型 UI 生产文件有冲突解决改动） | **成功**（chunk 体积警告为既有问题） |

后端全量 pytest 未跑（冲突解决未超出任务书声明的重叠文件集，符合任务书豁免条款）。

## 五、docs 对账

- C4 E2–E6 ✔、C5 M1/M2/L8/M5/M6 ✔：合并后 `docs/plan/CORE-PARITY.md` 逐行核对仍在且为 ✔（PARITY.md 的 F 行并集亦核对）。
- C6 T8：行状态由「△ `run_checks` 要单独调用」更新为「◐ LSP 诊断核心已合入 main（C6A）… 剩瘦写路径/UI 接线，完整 T8 UX 未完成」——只声明核心合入，不宣称完整 T8 UX 完成。
- `tasks/CURRENT.md`、`tasks/results/`、`tasks/reviews/` 主线控制文件未被任何分支版本覆盖；两分支的验收 review/result docs 随合并进入 main 供追溯。

## 六、最终状态

- C6A 合并提交：`ae94040`
- C5 合并提交：`c762377`
- 收尾提交：测试类型修复（`as const`）+ T8 行更新 + 本结果文件 + `CURRENT → AWAITING_REVIEW`（即 push 时的 main HEAD）
- push 后已核对 local HEAD == origin/main
- 剩余 C6（T8 写路径/UI 接线等）**未开始**，等待下一波调度。

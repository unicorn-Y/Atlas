# Source Freeze — ATLAS-MEGA-PERSISTENT-ALWAYS-ON（开工时重新抓取）

> 本文件是本波施工的最终来源依据。任务书中记录的旧 HEAD 仅供参考，一切以本页为准。
> 冻结时间：2026-10-03（开工时）

## 冻结 HEAD

| 项目 | 冻结 HEAD | 日期 | 相比任务书研究值 |
|---|---|---|---|
| OpenClaw `main` | `3e5560873a4d4e6fd04d9dbe568bc82110ec5046` | 2026-10-03 03:44 -0700 | **已前进**（任务书 `899a0ca681` → 现为 crabbox warm-image cleanup #164128） |
| NousResearch/hermes-agent `main` | `c8301ea6c9b797184df16a9c5dd462400b264ff4` | 2026-10-03 02:25 -0700 | 与任务书记录一致 |
| dbos-inc/dbos-transact-py `main` | `03fb5c92cde8e107ff333cd2b419f65e02719e99` | 2026-10-01 14:52 -0700 | 与任务书记录一致（Conductor Client #873） |
| Atlas `main` | `a034bff6a1c4b210af985254c7f35488c5022272` | 2026-10-03 06:42 -0400 | 本波开工基线（前波 `b0e96cb` 之后） |
| unicorn-Y/hermes-agent `atlas`（fork） | tail-sync 前 `7912500ffd` → tail-sync 后 `ef4571dec5` | 2026-10-03 | fork 已合并 upstream `c8301ea6c9` |

本地 clone 位置（本波施工期间只读参考）：

- OpenClaw：`D:\Atlas-persistent-sources\openclaw` @ `3e5560873a4`
- DBOS Python：`D:\Atlas-persistent-sources\dbos-transact-py` @ `03fb5c92`
- Hermes fork（可写，本波可能加 patch）：`D:\hermes-agent`（branch `atlas`）
- NousResearch upstream：同仓库 `upstream/main` @ `c8301ea6c9`

## 相比任务书研究时的新变化

### OpenClaw（`899a0ca681` → `3e5560873a4`）

无本波目标能力的破坏性改名信号；开工复核以冻结树为准，lane 研究时若发现
`src/gateway/**`、`src/agents/**`、`src/cron/**`、`src/infra/heartbeat-*.ts`、
`packages/gateway-protocol/**` 路径变化，以 lane 报告为准并回写本目录。

### Hermes upstream（`eb7e862032` → `c8301ea6c9`，9 个新提交）

全部集中在 managed local runtime（正是 P7 需要的能力）：

- `fix(local-runtime): Vulkan/HIP launches subtract what other programs hold on the card`
- `fix(local-models): quickstart prices the model after installing the engine`
- `fix(local-runtime): budget the engine the shared server runs, in the caller's profile`
- `fix(local-runtime): the CLI boots the managed server for an explicit backend`
- `fix(local-runtime): read local_runtime.backend through the config loader`
- `fix(local-runtime): size AMD/Intel GPUs by the engine's own device type`
- `fix(local-models): detect discrete Vulkan VRAM`
- `fix(local-runtime): detect Intel and AMD GPUs for auto backend`
- 新文件 `hermes_cli/local_runtime/devices.py`

### Fork tail-sync 记录

- merge commit：`ef4571dec5`（"merge: upstream main c8301ea6c9 (9 commits, local-runtime GPU/backend fixes) into atlas"）
- 已 push 到 `unicorn-Y/hermes-agent:atlas`（`7912500ffd..ef4571dec5`）
- focused tests：`test_local_runtime.py` + `test_local_quickstart.py` + `test_unified_pool_quirk.py`
  → 71 passed + 1 failed；该 1 个失败（`test_vulkan_device_type_decides_discrete_vs_unified[1-True]`）
  在**纯 upstream/main 上同样复现**（三文件同进程时的测试间污染），单文件运行 18 passed，
  非 merge 引入的回归。结论：tail-sync 干净。

## 能力冠军复核结论（开工时点）

| 能力 | 冠军来源 | 备注 |
|---|---|---|
| persistent gateway / 多 Agent routing / heartbeat / cron 语义 / node 归属 | OpenClaw `3e5560873a4` | 仍是唯一有完整 always-on gateway 的来源 |
| Bot Mode / 群聊 / Cron 产品面 / 中国渠道 adapters / managed llama.cpp | Hermes fork `ef4571dec5` | upstream 本日更新强化了 local runtime，继续领先 |
| durable execution | DBOS `03fb5c92` | 不变；Atlas 已内嵌 DBOS backend，不建第二层 |
| Windows Computer/Browser 执行层 | Atlas X2（现有） | 不重造 |

## 施工期间纪律

- 各 lane 禁止自行 rebase 到更高版本；发现冻结后有重大 upstream 变更时报告 controller 统一决策。
- 引用来源代码时在注释/结果文档中注明冻结 HEAD。

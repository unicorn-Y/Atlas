# 子智能体共享上下文（MEMORY-V1 续接轮，2026-10-07 深夜）

> 权威规范永远是 `docs/plan/MEMORY-V1/00_任务书.md`（先完整读一遍再动手）。
> 本文件只是把「环境、红线、所有权、提交规矩」集中到一处，避免各任务书重复。

## 0. 你是谁

你是 Atlas 记忆 V1 施工的**一个任务包执行者**。总控（Hermes AI计划）负责拆分、验收、整合、提交。
你只做自己任务包边界内的事，**不越界改别人的文件**。做完写报告，报告里只写事实与原始输出。

上一任总控（商店版 Codex）与其子智能体在 22:35 撞 ChatGPT 额度墙全挂，本机 Codex CLI 未登录、不可用。
**你就是替代它们的施工力量。** 不允许因为"原来的执行者不在"而缩小任务、降低质量或写假完成。

## 1. 环境（实证过，直接用）

| 项 | 值 |
|---|---|
| Atlas 仓库 | `D:\Atlas`，分支 `memory-v1`，HEAD `75c9709c` |
| MemoryOS 仓库 | `D:\MemoryOS`，分支 `memory-v1`，HEAD `ba8613403f56429333fe5adfdca6f291bd4b41f1` |
| Atlas Python | `D:\Atlas\core\.venv\Scripts\python.exe`（editable 安装，`.pth` 指向 `D:\Atlas\core`） |
| MemoryOS 服务 Python | `D:\MemoryOS\service\.venv\Scripts\python.exe`（**无 pytest**） |
| MemoryOS 测试 Python | `C:\Users\25011\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe -m pytest` |
| Atlas 跑测试 | `cd D:/Atlas/core && <atlas-py> -m pytest <paths>`（`pyproject` 默认 `addopts="-m unit"`，全库跑要显式放开 marker） |
| MemoryOS 跑测试 | 需 `PYTHONPATH` 含 `D:/MemoryOS/service`（否则 `from graph_conservative import ...` 收集失败） |

**隔离数据根（硬要求，任务书第 5 节）**：所有测试/冒烟必须设
`ATLAS_DATA_DIR`、`MEMORYOS_DATA_ROOT`、`MEMORYOS_DB_PATH` 指向临时目录。
**绝不允许**读写 `D:\MemoryOSData`、`D:\Atlas\data`、`user-settings.json`、生产配置。
（实证：`service/protected_state.py` 会检查这三个变量是否为空来判定"是否生产"。）

## 2. 真实模型（实证可用，2026-10-07 22:58 实测 200/2.1s）

`D:\Atlas\config\atlas.toml` 的 `[models.gateway] base_url = "https://cnapi.pleasure.cc.cd:8443/v1"`，
模型 id `deepseek-v4.1-flash`（OpenAI 兼容）。产品代码里一律走
`ModelRouter.complete_for(model_id, purpose, ...)`（参照 `core/atlas/engine/branch_summaries.py`），
新增 purpose `memory_observe` / `memory_reflect`；模型由用户设置 `memory_model` 指定，未设置退回
`compression_model`，再退回当前模型。**MemoryOS 侧不得新增模型配置、不得直接调大模型。**
真实冒烟必须打真网关；用假模型的测试必须显式标 `fake_provider` 且不计入效果。

## 3. 红线（任务书第 6 节，违反任一条该步直接判不通过）

- 业务代码里写死测试数据、按测试 id/关键词返回预设结果；用 `expected_*` 喂模型或检索
- 用假模型、模拟成功率、写死分数冒充真实效果；只跑单元测试就声称效果达标
- 把上游搬运对象的**模型判断**换成规则/正则/字符串相似度，仍声称"已搬运"
- 观察时预填 key/value/人物/主题当"自然输入"（自然输入必须是用户原话）
- 删除/跳过/xfail 失败测试，或降低门槛
- 自行写 `ACCEPTED`；自行改生产数据/配置；合并 main
- 新建第二套事实库、调度器、模型配置

**状态只能写 `IN_PROGRESS` / `DONE_PENDING_REVIEW` / `BLOCKED`。**
已有测试不得变少、不得 skip/xfail；新失败要么修好要么在报告里如实列出。
**宁可如实写"没做到"，也不要包装成"做到了"。**

## 4. 提交规矩

- 每完成一个可交付单元至少提交一次，信息以 `feat(memory-v1): S<n> ...` 开头。
- **只改自己所有权内的文件**；需要别人文件时在报告里写"依赖请求"，不要自己动。
- 提交前跑自己包的测试并贴原始输出。**不要 push**（总控统一推送）。
- 总控会读你的 diff、亲自复跑你的测试、跑真实冒烟抽样。汇报与事实不符会被打回。

## 5. 已知现场状态（总控已复核，别重复劳动）

- **S0 基本完成**：harness 去造假、冻结开关、`test_bootstrap`/`test_memoryos_service_lifecycle`/`observer*`/`v1_reads` 全绿。
- **S0 剩余闸门 = 11 个未提交改动引入的回归**（总控已定位根因，见任务包 A）。
- B 的 health probe、C 的 Observer 预算单事务、`memory/__init__.py` 统一读委托、`run_phases` 统一读分支**都已落地且测试绿**。
- MemoryOS 冻结子包已提交推送 `ba86134`。

## 6. 报告格式（交回总控）

```
## 任务包 <X> 报告
- 状态：IN_PROGRESS / DONE_PENDING_REVIEW / BLOCKED
- 改了哪些文件（完整路径 + 一句话说明）
- 跑了什么测试：<命令> → <原始输出尾部：N passed / N failed>
- 真实冒烟：<命令> → <原始输出 / 模型 id / token 用量>
- 完成判据逐条对照：<判据> → <证据>
- 已知问题 / 未做到的部分 / 依赖请求
- 提交 hash（如果有）
```

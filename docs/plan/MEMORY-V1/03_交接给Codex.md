# 给 Codex 的交接指令（编排模式）

你是 Atlas 记忆 V1 的**总控**。仓库在 `D:\Atlas` 和 `D:\MemoryOS`，两个仓库都用 `memory-v1` 分支。

开工前完整阅读：
1. `docs/plan/MEMORY-V1/00_任务书.md`（权威规范）
2. `docs/plan/MEMORY-V1/01_验收场景.md`
3. `docs/plan/MEMORY-V1/02_上游搬运清单.md`
4. `docs/plan/MEMORY-V1/CURRENT.json`（当前进度）

之前的 `docs/plan/UNIFIED-MEMORY/` 和修复包只是背景资料。上一轮施工者（zcode）因为造假被独立验收撤销了成绩，所以你的验收和之后的独立审查都会逐条核对代码，并在主机上复跑测试。

## 工作方式（用户 2026-10-07 指定）

- **你（总控）不亲自写产品代码**，只负责：拆分任务、派活、调控、验收、整合提交。
- **具体施工全部交给子智能体**：模型用 **GPT-6 Luna**，推理强度 **xhigh（极高）**。每个子智能体领一个边界清楚的任务包，交代清楚：属于哪一步 S<n>、要改哪些文件（文件所有权）、完成判据、必须跑的测试和真实冒烟、红线（任务书第 6 节）。
- **不要闲着**：任何一个子智能体交付后，立刻验收；验收通过就整合并提交，然后马上派下一个任务；验收不通过就把具体问题打回给它（或者新开一个子智能体）返工。只要还有可以做的任务，就保持有子智能体在干活。
- **并行规则**：只有不改同一批文件、并且依赖已经满足的任务才能并行。热文件同一时刻只能有一个写者，包括 `run_phases.py`、`core/atlas/memory/__init__.py`、MemoryOS 的 `service/app.py`、`service/unified/api.py`、`formation.py`、`retrieval.py`、migrations。步骤之间按 S0→S1→S2→S3→S4 的依赖推进；S5、S6 在 S3 完成后可以和 S4 并行；S8 的评测准备工作（题目抽样、场景脚本）可以提前并行做。
- **验收（你来做，不能只看子智能体的汇报）**：读 diff；亲自复跑该任务的测试和至少一条真实冒烟；逐条对照任务书第 6 节，确认没有走捷径。每完成一步 S<n>：写 `progress/S<n>.md`（做了什么、怎么验证的、原始输出、已知问题），把 CURRENT.json 中该步改为 `DONE_PENDING_REVIEW`，提交并推送，**然后不停下来，直接继续下一步**。之后由独立审查方（Claude）异步审查。审查发现问题时，会写在 `docs/plan/MEMORY-V1/reviews/` 里，你要优先安排返工。
- **只有这几种情况需要停下来问用户**：到了 S7（改生产数据和配置，必须由用户授权）；遇到 BLOCKED（缺权限、缺凭据、模型不可用）；任务书没有覆盖、并且会改变目标的决定。其他情况选最保守的做法继续推进，并在 progress 里记下来。
- 推送：主机上的 origin 是 HTTPS，非交互环境下没有凭据，请用 `git push git@github.com:unicorn-Y/MemoryOS.git memory-v1` 和 `git push git@github.com:unicorn-Y/Atlas.git memory-v1`。
- 测试使用隔离数据根（任务书第 5 节）。不得碰 `D:\MemoryOSData`、`D:\Atlas\data`、`user-settings.json`，以及任何生产配置。
- Python 环境：Atlas 是 `D:\Atlas\core\.venv\Scripts\python.exe`；MemoryOS 服务是 `D:\MemoryOS\service\.venv\Scripts\python.exe`（没有 pytest；MemoryOS 测试可以用 `C:\Users\25011\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe -m pytest`，或者给 service venv 安装 pytest，在 progress 中写明用的是哪个）。
- 真实模型：产品里的 Observer、Reflector 使用 Atlas ModelRouter 中用户已配置的模型；在 progress 中记录模型 id 和 token 用量。
- 任务书第 6 节"不准做的事"是硬红线，对你和每个子智能体都适用。宁可如实写"没做到"，也不要包装成"做到了"。状态永远不能自己写成 ACCEPTED。

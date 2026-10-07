# 给 Codex 的交接指令

你是 Atlas 记忆 V1 的施工者。仓库在 `D:\Atlas` 和 `D:\MemoryOS`，两个仓库都用 `memory-v1` 分支。

开工前完整阅读：
1. `docs/plan/MEMORY-V1/00_任务书.md`（权威规范）
2. `docs/plan/MEMORY-V1/01_验收场景.md`
3. `docs/plan/MEMORY-V1/02_上游搬运清单.md`
4. `docs/plan/MEMORY-V1/CURRENT.json`（当前进度，确定从哪一步继续）

之前的 `docs/plan/UNIFIED-MEMORY/` 和修复包只是背景资料。上一轮施工者（zcode）因为造假被独立验收撤销了成绩，所以本次审查会逐条核对代码，并在主机上复跑测试。

工作方式：
- **一次只做一步**（S0…S8，见任务书第 5 节）。做完这一步的全部内容后：提交并推送 `memory-v1`，写 `progress/S<n>.md`，把 CURRENT.json 中该步的状态改为 `DONE_PENDING_REVIEW`，然后**停止**，用中文简短汇报：做了什么、真实冒烟结果（含失败）、已知问题。不要接着做下一步。
- 推送：主机上 MemoryOS 的 origin 是 HTTPS，非交互环境下没有凭据，请用 `git push git@github.com:unicorn-Y/MemoryOS.git memory-v1`；Atlas 也一样，用 `git@github.com:unicorn-Y/Atlas.git`。
- 测试使用隔离数据根（任务书第 5 节）。不得碰 `D:\MemoryOSData`、`D:\Atlas\data`、`D:\Atlas\data\user-settings.json`，以及任何生产配置。
- 两个 Python 环境：Atlas 是 `D:\Atlas\core\.venv\Scripts\python.exe`；MemoryOS 服务是 `D:\MemoryOS\service\.venv\Scripts\python.exe`（该环境没有 pytest，MemoryOS 测试可以用 `C:\Users\25011\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe -m pytest`，或者给 service venv 安装 pytest，在 progress 中写明用的是哪个）。
- 真实模型：通过 Atlas 的 ModelRouter，使用用户已经配置好的模型；在 progress 中记录模型 id 和 token 用量。
- 遇到任务书没有覆盖、又必须做决定的情况：选择最保守的做法，并在汇报中列出来，不要自行扩大范围。
- 任务书第 6 节"不准做的事"是硬红线。宁可如实汇报"没做到"，也不要包装成"做到了"。

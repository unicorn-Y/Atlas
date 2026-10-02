# Atlas T1 benchmark preparation

本目录独立于 Atlas 生产实现。准备阶段只运行本地 `fake` 与 `--dry-run`，不登录、不读写用户配置、不调用真实模型。

## 本地验收

需要 Python 3.11+、Git、Node.js 与 PowerShell。TypeScript 任务使用本机现有编译器，实际依赖以任务 manifest/setup 为准。

```powershell
python tests/t1/verify.py --output "$env:TEMP/atlas-t1-prep-evidence"
python tests/t1/selftest.py --task 01-20
python tests/t1/run.py --participant fake --task 01-20 --repeat 3 --track same-model --output "$env:TEMP/atlas-t1-fake"
python tests/t1/run.py --participant codex --task 01-20 --dry-run
python tests/t1/run.py --summary --output "$env:TEMP/atlas-t1-fake"
```

`verify.py` 执行 harness unit tests、adapter tests、fault proxy tests、fake E2E、全部 fixture/check 红绿自检和所有 participant dry-run。临时工作副本包含中文路径。证据写入指定目录，大日志与工作副本不提交。

## 任务与结果

每个任务的 `task.md` 是中文任务原话，`manifest.toml` 定义能力和改动边界，`rubric.md` 定义人工评分标准。自动检查由仓库外的 `check.py <workspace>` 执行。`fixture/` 是起点，`solution/` 是验收专用参考修复；真实 participant 只接触 fixture，不接触参考修复或 check 实现。新增测试可以允许，起始测试必须保留。仅最终文件正确不足以证明计划/撤回/插话过程正确，需要 scenario 证据。

结果 JSON 使用 `schemas/` 中的统一 schema。runner 保存输出、事件、退出码、耗时、usage、git diff、改动列表、越界修改、原始测试删除和垃圾文件。未知 token/cost 保留为未知；不按零花费处理。断点续跑匹配任务和配置指纹，预算包含已完成结果中的费用，达到预算后不启动下一次。

`duration_ms` 测量 participant 调用墙钟时间，包含 adapter 启动与退出，不含 fixture/setup、baseline、diff 与 check；`total_duration_ms` 记录准备及检查的总开销。汇总区分赛道，显示状态数量与已评估次数；unsupported/unavailable 不当作 participant 失败。diff 文本脱敏，二进制只记录变更摘要与 hash。任务、checker、setup、adapter 或配置改变会使旧结果指纹失配。

TypeScript 编译器按 `TSC_PATH`、PATH、fixture 本地依赖、当前 Atlas checkout 或其 worktree 主仓库依次查找，读取已有依赖，不安装或修改生产依赖。05–07 新增测试必须在修复后通过、在原始 fixture 上失败，无关恒真测试不算补测试。

ZCode 仅生成手动步骤和录入模板。缺失 CLI、缺失能力和执行失败分别记录；不自动操控 GUI。各 adapter 的最终命令依据见 [participants/COMMANDS.md](participants/COMMANDS.md)。

## Fault provider

```powershell
cd tests/t1
python -m fault_proxy --faults 429,500,disconnect
```

该 provider 只绑定 `127.0.0.1` 随机端口，模拟 OpenAI-compatible `/v1/chat/completions`，提供普通 JSON 和 SSE 流。按顺序注入 429、500、断流，然后成功，包含 usage。默认只提供本地假响应；显式配置 `upstream_url` 才会在故障之后转发到指定 OpenAI-compatible endpoint。准备阶段的转发测试只连接另一个 loopback fake provider。记录不包含 Authorization 或 prompt。

任务 20 要求 participant 在恢复后生成 `recovery.json`，同时必须留下代理实际观察到的故障及成功请求证据。runner 将 `fault_proxy.json` 保存在工作副本之外，缺失完整序列或完整响应会判失败；仅写出正确答案不能通过。目前只有 Hermes 的显式临时进程环境 binding 声明支持，配置方法见 COMMANDS.md；其他真实 adapter 标为 unsupported，不写真实用户设置。fake 使用本地代理和重试客户端生成恢复 artifact。

## 正式 T1 的边界

正式 T1 必须等待 C6 PASS，将本分支 rebase 到最新 main，并由用户确定模型、登录与预算。本波不启动正式 T1。默认 runner 拒绝真实执行；将来正式执行才使用显式 `--allow-real`。两赛道配置不预选用户的最终模型，不填写真实 key。首次完整 upstream fixture 准备使用 pinned commit 与仓库外缓存，禁止把整个上游仓库提交进 Atlas。

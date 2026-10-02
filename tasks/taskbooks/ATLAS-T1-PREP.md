# ATLAS-T1-PREP：真实横向实测准备波（Sol 独立线）

> 这波和 ZCode 当前 C6 **并行**。
> 只准备 T1 的任务集、runner、participant adapters、指标采集和结果骨架。
> **不运行真实模型、不花 API 钱、不碰 Atlas 生产代码、不改 main 的 tasks/CURRENT.md。**
> C6 PASS 后，把本分支 rebase 到最新 main，再进入正式 T1。

## 分支与边界

分支：`sol/t1-prep`

允许修改：
- `tests/t1/**`
- `tasks/results/ATLAS-T1-PREP.result.md`
- `tasks/taskbooks/ATLAS-T1-PREP.md`
- `tasks/SOL-CURRENT.md`
- 必要时 `.gitignore` 只加 T1 大结果目录忽略项

禁止修改：
- `core/**`
- `frontend/**`
- `backend-adapter/**`
- `docs/plan/CORE-PARITY.md`
- `tasks/CURRENT.md`
- ZCode 正在做的 C6 生产文件

## 先读

- `tasks/taskbooks/ATLAS-T1-HEAD-TO-HEAD.md`
- `docs/plan/ROADMAP-TO-PRODUCT.md`
- `docs/plan/EXECUTION-GUIDE.md`

然后核对 2026-10 当前 CLI 文档/帮助：
- Claude Code headless
- Codex CLI exec/json
- OpenCode run
- Pi prompt/json
- Hermes CLI
- Atlas CLI/WS

只记录最终可用命令和差异，不写长调研报告。

## 目标

把 T1 从“任务书”变成 **C6 一通过就能直接跑** 的完整 benchmark harness。

### A. 目录

至少做出：

```
tests/t1/
  README.md
  run.py
  config.example.toml
  participants/
  harness/
  tasks/
    01/ ... 20/
  fixtures/
  fault_proxy/
  schemas/
  results/.gitkeep
```

大日志、模型输出、工作副本、代理抓包不得提交。

### B. Runner

`tests/t1/run.py` 至少支持：

- `--participant atlas|claude|codex|opencode|pi|hermes|zcode`
- `--task 01` / 范围
- `--repeat N`
- `--track same-model|best`
- `--dry-run`
- `--budget-usd`
- `--output <dir>`
- 断点续跑：已有完成结果默认跳过
- 单次只跑一个 participant，避免抢机器

每次 run：
1. 从干净 fixture 建临时工作副本
2. 初始化 git baseline
3. 调 participant adapter
4. 保存 stdout/stderr/事件日志/耗时/退出码
5. 执行该任务 check
6. 记录 git diff、改动文件、越界改动、删除测试、垃圾文件
7. 记录 token/cost（native log 优先；拿不到则 optional proxy）
8. 写统一 JSON result
9. 超预算立即停止，不再启动下一次

**prep 阶段只跑 dry-run 和本地 fake adapter，不调用任何真实模型。**

### C. Participant adapters

为以下对象写独立 adapter：

- Atlas
- Claude Code
- Codex CLI
- OpenCode
- Pi
- Hermes
- ZCode manual

统一接口：
- availability()
- build_command()
- run_once()
- parse_usage()
- supports(capability)
- cleanup()

要求：
- secrets 只从环境变量/各自已有登录态读取，永不写仓库
- `--dry-run` 只显示脱敏命令，不调用模型
- 找不到 CLI 时清楚返回 unavailable，不崩 runner
- ZCode 只生成手动操作清单和结果录入模板，不自动操控 GUI

### D. 统一结果 schema

每次至少记录：

- participant
- track
- model
- task_id
- attempt
- success
- check_exit_code
- duration_ms
- tool_calls
- turns
- input_tokens
- output_tokens
- cached_tokens
- cost_usd
- changed_files
- forbidden_changes
- test_files_deleted
- junk_files
- runner_error
- participant_error
- raw_log_paths

做汇总脚本：
- per task
- per participant
- 总成功率
- 平均/最好成绩
- 平均耗时
- token/cost
- 越界率

不要生成“谁最好”的政治式结论这类无关内容；这里只做工程 benchmark 数字。

## 20 个任务全部落成可跑 fixture

每个目录必须有：
- `task.md`：给 Agent 的中文原话
- `manifest.toml`：类型、允许改动范围、超时、是否多轮、能力要求
- `check.py` 或 `check.ps1`
- `rubric.md`
- fixture/setup 脚本或固定小仓库

不允许只建空目录/placeholder。

### 01–04 修 bug
- Python 两个
- TypeScript 两个
- 每个至少一个真实失败测试 + 一个容易误修的边界测试
- 禁止直接删/改测试来过关

### 05–07 加功能
- 中小型 fixture repo
- 跨 2–5 个文件
- 要求补测试
- check 验证功能 + 不破坏旧行为

### 08–09 读大仓库回答
- 一个 Hermes
- 一个 OpenCode
- 用 pinned commit
- task 问具体实现问题
- check 用关键事实/路径/结构化答案核对
- prepare 脚本负责 clone/cache，不把整个上游 repo 提交进 Atlas

### 10 重构
- 至少跨 5 个文件
- 公开 API/行为不变
- check 同时查测试和旧符号残留

### 11 长对话
- scenario 多轮 8 轮
- 后续约束引用前面要求
- 最终 check 验证早期约束没丢

### 12 超长上下文/压缩
- scenario 自动喂大输入直到接近/触发压缩
- 最终任务依赖压缩前的关键约束
- runner 记录 compaction/context 事件（支持的 participant）
- 不在 prep 阶段真跑模型

### 13 运行与调试
- 本地小服务启动失败
- 要看日志、修配置/代码、让健康检查通过
- 全程无公网依赖

### 14 子 Agent 并行
- 三个真正互不相关子目标
- check 验证三项都完成
- manifest 标 capability=subagents
- runner 记录不支持

### 15 计划模式
- scenario：先要求只计划，再明确批准执行
- check 确认批准前 workspace 没被改

### 16 撤回
- scenario 有明确 checkpoint
- 做一次修改 → rewind → 从旧点走另一方案
- 不支持 participant 记 unsupported，不伪造失败

### 17 Windows
- PowerShell
- CRLF
- 中文路径/文件名
- check 验证编码换行没坏

### 18 文档产出
- 输入为一个小项目目录
- 输出 Markdown 报告（T1 先统一 Markdown，避免 Office 工具差异污染主体 benchmark）
- check 核对必备章节和关键事实

### 19 中途插话
- runner 在执行中按事件/时间注入新要求
- Atlas/Hermes/Pi 等支持者走真实 steer/redirect 接口
- 不支持者标 unsupported
- check 只认新要求后的结果

### 20 出错恢复
- 做一个本地 OpenAI-compatible fault proxy/fake provider
- 可脚本化注入一次 429、一次 500、一次断流
- 能配置 participant 走代理时才执行
- 不能走代理的 participant 标 unsupported
- prep 只用 fake client 验证 fault proxy，不打真实 API

## same-model / best 两赛道配置

只做配置框架，不决定用户最终模型。

`config.example.toml`：
- [tracks.same-model]
- [tracks.best]
- participant command overrides
- model ids
- timeouts
- repetitions
- budget_usd
- result dir

不填真实 key。

## fake adapter 自测

做一个 `fake` participant，仅用于验证 harness：
- 可以按 task fixture 产生预设成功/失败
- 可以输出假 usage
- 可以超时
- 可以制造 forbidden change

至少验证：
- clean copy
- check 执行
- diff/越界检测
- result schema
- repeat
- resume
- budget stop
- unsupported
- timeout
- fake usage/cost
- summary

## 并行施工

Sol 负责契约/集成，实际施工尽量交 Luna high。

能拆开的全部并行，使用当前环境允许的最大子代理并发，不写死数量。

适合独占块：
1. runner/schema/result aggregation
2. participant adapters
3. tasks 01–05
4. tasks 06–10
5. tasks 11–15
6. tasks 16–20
7. fault proxy
8. fake adapter/tests/docs

共享接口先由 Sol 冻结最小 contract；worker 不同时改同一文件。

## 验收

prep 阶段不需要 C6、也不需要真实模型。

必须跑：
- harness unit tests
- fake participant end-to-end
- 所有 20 个 task 的 fixture/check 自检
- `run.py --dry-run` 对所有 participant
- Windows 路径下至少跑一次 fixture 自检

禁止：
- 调真实 OpenAI/Anthropic/DeepSeek 等
- 消耗真实 token
- 登录/改用户账号
- 修改 Atlas 生产实现

## 交付

写：
`tasks/results/ATLAS-T1-PREP.result.md`

必须写清：
- 20 个 task 状态
- participant adapter 当前命令依据
- harness CLI
- fake E2E 结果
- 哪些正式 T1 项仍必须等 C6 PASS / 用户登录 / 用户预算
- 当前分支 HEAD

然后：
- `tasks/SOL-CURRENT.md` → AWAITING_REVIEW
- push `sol/t1-prep`
- 停止

**不要开始正式 T1，不要跑任何真实模型。**

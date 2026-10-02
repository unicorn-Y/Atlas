# ATLAS-T1-PREP result

STATUS: AWAITING_REVIEW
BRANCH: sol/t1-prep
VERIFIED_IMPLEMENTATION_HEAD: 1bcc270556144a86bdfc44e702330bcfa925320b
BASE_HEAD: 93ab7a69476b05a31f5777c580ee814c46f86a96
DATE: 2026-10-03 Asia/Hong_Kong

本次交付 T1 benchmark 准备基础设施；没有开始正式 T1。施工在独立 worktree `D:\Atlas-t1-prep`，使用运行时允许的全部并发槽位（主代理及 3 个 GPT-6 Luna/high 子代理），按文件所有权并行施工并复用子代理进行复核。

实现仅在 `tests/t1/**`；收尾另更新本报告及 `tasks/SOL-CURRENT.md`。未修改 `core/**`、`frontend/**`、`backend-adapter/**`、`tasks/CURRENT.md` 或 C6 生产文件。上面的 HEAD 是实际受验实现提交；本报告与状态更新在后续收尾提交，最终推送 HEAD 以分支及交付回报为准。

## 20 个任务

所有任务均有中文 `task.md`、`manifest.toml`、可执行 `check.py`、`rubric.md`、可复现 fixture，及验收专用 reference solution。真实 participant 不接收 reference 路径。自检要求原始 fixture 失败、reference 通过、保护文件删除/改写被拒绝；全部在 Windows 中文临时工作路径执行。

| ID | 可跑任务 | fixture/check 自检 | fake E2E |
|---|---|---|---|
| 01 | Python 金额舍入边界 | PASS | PASS |
| 02 | Python TTL 缓存边界 | PASS | PASS |
| 03 | TypeScript 闭区间边界，真实 tsc/Node | PASS | PASS |
| 04 | TypeScript Unicode 截断，真实 tsc/Node | PASS | PASS |
| 05 | Catalog 前缀搜索，多文件功能与有效补测 | PASS | PASS |
| 06 | 笔记标签查询，多文件功能与有效补测 | PASS | PASS |
| 07 | 安全库存调整，多文件功能与有效补测 | PASS | PASS |
| 08 | Hermes 固定 commit 的真实 discovery 源码问答 | PASS | PASS |
| 09 | OpenCode 固定 commit 的真实 provider 源码问答 | PASS | PASS |
| 10 | 用户展示格式模块跨文件重构 | PASS | PASS |
| 11 | 8 轮配送规则累积与约束保持 | PASS | PASS |
| 12 | 按选定窗口生成上下文压力，保持早期约束 | PASS | PASS |
| 13 | 启动并调试真实 loopback 服务，回收进程树 | PASS | PASS |
| 14 | 三个独立子目标与 subagent scenario | PASS | PASS |
| 15 | 计划模式，批准前 runner 捕获只读快照 | PASS | PASS |
| 16 | 方案 A、checkpoint、撤回、方案 B | PASS | PASS |
| 17 | PowerShell 中文路径、UTF-8 无 BOM、CRLF | PASS | PASS |
| 18 | 根据本地项目事实生成 Markdown 报告 | PASS | PASS |
| 19 | 工作中途 timed steer，变更后统计要求 | PASS | PASS |
| 20 | provider 429/500/断流后恢复，独立请求证据 | PASS | PASS |

08 固定 Hermes commit `9a71d5a8b59b37d1795ab7065fbbe3b647ba5249`；09 固定 OpenCode commit `1ddb0873aee50d209d1a8d7f91b89c5daf692d49`。包含带许可的实际源文件快照、源码完整性检查、仓库外缓存及真实 pinned checkout setup/cleanup；不提交整仓。首次完整 setup 需要 Git 网络访问，或已有固定 commit 缓存。

05–07 的新增测试必须在交付代码上通过并在原始 fixture 上失败；恒真测试不算补测。13 的 Windows 文件锁问题已修复，补充连续 5 次自检均通过。17 的 checker 实际重新执行脚本生成产物，拒绝预先放置答案。

## Runner、结果与故障代理

CLI 入口 `tests/t1/run.py`，支持 task 范围、participant、repeat、resume、same-model/best、model、配置文件、timeout、budget、dry-run、summary。`config.example.toml` 提供两赛道框架，不预定最终模型，不含 key；预算默认 0。

```powershell
python tests/t1/verify.py --output "$env:TEMP/atlas-t1-prep-evidence"
python tests/t1/selftest.py --task 01-20
python tests/t1/selftest.py --task 08-09 --full-upstream
python tests/t1/run.py --participant fake --task 01-20 --repeat 3 --track same-model --output "$env:TEMP/atlas-t1-fake"
python tests/t1/run.py --participant codex --task 01-20 --dry-run
python tests/t1/run.py --summary --output "$env:TEMP/atlas-t1-fake"
```

每次运行使用独立 clean copy 和 Git baseline；保存原始输出、事件、退出码、check、脱敏 diff、越界修改、原测试删除、垃圾文件和审批快照。结果经统一 JSON schema/运行时 validator 校验。resume 指纹覆盖任务、checker/setup、adapter、runner、proxy、配置及 timeout。汇总按任务、participant、赛道和任务/participant 组合统计成功率、最佳/平均耗时、token/cache/cost 及越界率。

`duration_ms` 为 participant 调用耗时；`total_duration_ms` 包含 fixture、baseline 和验收开销。真实 usage 仅从 native 日志取值，未知保持 null；未知 cost 时预算执行停止，不能按零费用续跑。fake usage 明确标为 fake。

FaultProxy 默认仅绑定随机 loopback 端口，提供本地 OpenAI-compatible Chat Completions JSON/SSE。按序注入 429、500、断流后恢复。显式配置 upstream 才会转发；准备阶段转发测试只用第二个 loopback fake provider。不记录密钥、Authorization 或 prompt。任务 20 还要求 runner 所有的完整请求序列与成功证据；200 部分流或缺少 `[DONE]` 不能通过。`recovery.json.response` 是固定恢复标记，不是模型回复正文。

## Participant 命令依据与边界

完整官方源码/文档链接、实际 help 检查日期及配置示例见 [`tests/t1/participants/COMMANDS.md`](../../tests/t1/participants/COMMANDS.md)。本次只检查 help、native mock、dry-run，没有执行真实模型。

| Participant | Adapter 当前调用依据 | 边界 |
|---|---|---|
| Atlas | 本地源码 WS `run.start` / `run.steer` / `run.plan.approve` | native 多轮/计划/插话 mock 已验；rewind unsupported |
| Claude | 官方 CLI `-p --output-format stream-json`，scenario JSONL input | 多轮/steer mock；本机缺 CLI，plan/rewind unsupported |
| Codex | 官方 exec 文档及本机 `codex exec --help` | `exec --json --cd`；live steer/rewind/proxy unsupported |
| OpenCode | 官方 run 文档及隔离 help 探测 | `run --format json`；本机安装的二进制与 Windows 不兼容，unavailable |
| Pi | 官方 RPC/JSON event 文档 | `--mode rpc --no-session`；prompt/steer/follow_up/stats mock，本机缺 CLI |
| Hermes | 官方 CLI/env 文档及本机 chat help | `chat --oneshot --quiet --format stream-json --in`，native resume 多轮；live steer unsupported |
| ZCode | 人工执行说明及空白结果模板 | 不操作 GUI，不虚构自动协议支持 |
| fake | 本地 fixture、真实 workspace mutation、loopback proxy | 仅 harness 验证；压缩/subagent 行为明确标记 simulated |

真实 task20 代理能力默认 unsupported；目前仅 Hermes 的显式 `OPENAI_BASE_URL` 临时子进程环境 binding 支持。选定 provider 必须实际走该自定义 Chat Completions 路由，否则独立代理证据会使验收失败。Codex Responses wire 与此代理不兼容，不能宣称支持。

## 最终验收

最终 verifier 退出码 0，14/14 gates 全部通过：

| Gate | 结果 |
|---|---|
| harness unit | 14/14 tests PASS |
| participant adapter unit/native mock | 15/15 tests PASS |
| fault proxy unit/loopback forwarding | 10/10 tests PASS |
| fake participant E2E | 9/9 tests PASS；全任务成功 20/20，越界 0 |
| fixture/check 红绿及保护文件自检 | 20/20 PASS |
| pinned upstream setup/check/cleanup | 08、09 均 PASS |
| 所有 participant dry-run | Atlas、Claude、Codex、OpenCode、Pi、Hermes、ZCode、fake；各 20 个任务，共 160 个 dry_run 结果 |

验收机器摘要与原始日志 SHA-256 入库：[`tests/t1/evidence/prep-verification.json`](../../tests/t1/evidence/prep-verification.json)。

证据目录：`C:\Users\25011\AppData\Local\Temp\atlas-t1-prep-accepted-20261003`，含各 gate 日志、fixture JSON、9 个 fake E2E case 的结果/日志及全部 participant dry-run。完整可复现验收入口为上述 `verify.py`。

## 正式 T1 尚需满足

必须等 C6 PASS 后将准备分支 rebase 到最新 main，再确定真实模型、登录状态、上下文窗口及预算，补齐当前机器缺失/不兼容的 CLI，并确认被选 participant 的实际能力。task12 必须配置真实窗口；fake 压力与 simulated 压缩不证明真实模型 compaction。native mock/dry-run 不等于真实 participant 验收。

真实运行默认被拒绝；只有另行授权正式 T1 才可启用 `--allow-real`。本次真实模型调用 0、真实 API token 消耗 0；未登录或修改用户账号/真实配置。准备工作收尾后停止，不启动正式 T1。

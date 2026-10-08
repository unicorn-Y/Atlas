# F1 编排与文件所有权

## 2026-10-09 用户续令（优先于下方原派单）

- Observer、Reflector、回答及 judge 改用 `gemini-3.8-flash`，custom provider 的 Antigravity 反代 `http://127.0.0.1:8045/v1`。隔离 settings 复制 custom provider 元数据、custom_models、memory_model；Windows 凭据库密钥只在内存读取，不写文件或日志。
- 用户明确解除 LongMemEval USD20 停止线：12题冒烟通过后直接执行固定120题。旧 DeepSeek 估算与等待预算记录仅作为历史，不再阻塞；代理费用未知不等于零。
- 1万条性能只记录，延迟后续解决，不作为本轮阻塞；391.536ms 是临时 CUDA 环境，不能当作默认 CPU 或生产 GPU 部署证据。
- 先推送已验收 A/B/C 的限定改动，再完成 Gemini 10×3 与 F1-D 30×3/12/120，最终 progress/F1.md、CURRENT.json 并停下等审查，不进入 S7。
- 只清理可确证不再使用的测试孤儿，不触碰生产进程。用户列举的历史 recovery/evidence、benchmark_p1a5、.construction-pack 及本机设置备份均不混入提交。
- 最新 CLI 预检仍 Not logged in，内置仍只能总控+3子智能体；已恢复三个 Luna/xhigh 施工者，不能声称已达到4–6子智能体。

2026-10-08；总控 Codex。权威：04_修复包F1.md、03_交接给Codex.md、00_任务书.md §6。本轮不进入 S7，不改生产数据或配置，不自行写 ACCEPTED。

## 开工基线

- Atlas `54f75b13`、MemoryOS `f7fe1b7`；均为 `memory-v1`，已执行 `git pull --ff-only origin memory-v1`。
- 两仓 origin 使用 `git@github.com:unicorn-Y/Atlas.git` 和 `git@github.com:unicorn-Y/MemoryOS.git`。
- 保留既有脏改动：Atlas 的 eval/scenario_judge_report.json 和 .construction-pack/；MemoryOS 的 CURRENT.json、历史 recovery/evidence 文件及未跟踪产物。本轮不得混入提交。
- 内置并行硬上限：总控 + 3 个子智能体。为补第 4 个施工者检查 CLI，`codex login status` 返回 `Not logged in`；CLI 派工受阻。先并行 A/B/C，空槽立即补 D。所有施工者 GPT-6 Luna，xhigh。
- context-mode 工具未暴露；短输出工具及 RTK 为可用替代，测试原始日志落隔离目录。

## 任务边界与完成判据

| 包 | 唯一写者与所有权 | 完成判据 |
|---|---|---|
| F1-A | f1_a；MemoryOS formation.py/consolidation.py/semantic_recall.py/app.py embedding配置和worker/retrieval.py语义融合/api.py status/erasure.py embedding层；Atlas service_lifecycle.py；独有 semantic 测试、冒烟和 F1-A.md | 同事务索引、后台预热、真实状态和回填；真实HTTP及本地模型改述≥9/10、中英命中、删除归零、1万条预热p95≤800ms |
| F1-B | f1_b；Atlas observer_prompt.py/observer.py/reflector.py提示词；test_f1_language.py、scripts/f1_language_smoke.py、F1-B.md | 同语言规则、中文示例、一次重试并保留计数、temperature≤0.1；真实模型10段×3中文text≥98% |
| F1-C | f1_c；Atlas既有core/tests/unified_memory测试及harness/conftest（不含A/B新增测试）；pytest marker注册、KNOWN_FAILURES.md、F1-C.md | 十类失败分类修复；冻结项仅按F1特许登记skip；全集连续3次0失败，MemoryOS全绿；真实HTTP冒烟 |
| F1-D | 待空槽；Atlas scripts/memory_v1/及eval/（既有脏report先保留） | 官方LongMemEval全链运行器、12题分层冒烟与120题费用估算；A/B整合后30场景×3和120题官方判分，达到F1门槛 |
| F1-E | 总控；编排文档、验收记录、CURRENT最终更新、VENDORED汇总 | 每包读diff、双仓全集和真实冒烟；精确提交并SSH推送双仓、确认无ahead；最终F1.md并停下等审查 |

## 验收纪律

每包须先由总控亲自读diff和复跑，不以施工者自报代替验收。Atlas命令必须含 `-o addopts= core/tests/unified_memory`，MemoryOS为 `tests/unified_memory`。连续三次全绿才算绿。原始输入、模型、token、代码版本和失败原因保留；不得调低门槛、增top-k、全历史塞上下文、改写评测原话、预填答案。120题估算超过20美元等值则停止该全量运行并询问用户。

所有测试使用隔离 ATLAS_DATA_DIR/MEMORYOS_DATA_ROOT/MEMORYOS_DB_PATH；禁止 D:/MemoryOSData、D:/Atlas/data、user-settings.json 及生产配置写入。热文件单写者，追加所有权与迁移号由总控分配。

## 在途验收与裁定

- 2026-10-09 总控对当前 A/B/C 基线亲跑：MemoryOS 默认启用环境 `421 passed`、126.112秒，证据 `D:/Temp/F1-controller-memoryos-gate3-20261009/`；Atlas 指定 `-o addopts= core/tests/unified_memory` 口径 `271 passed / 2 frozen skips / 0 errors`、326.552秒，证据 `D:/Temp/F1-controller-atlas-gate1-20261009/`。另一次全局关闭 semantic 的 gate2 为420 passed/1 failed（语义用例DISABLED），该结果保留，不代替默认环境验收。
- 接替总控在 2026-10-08 的 Atlas 三轮 JUnit 已由本总控亲读，均273 tests/271 passed/2 skipped/0 failed/0 errors；真实T12 HTTP+WS provider messages检查为1 passed。此处明确区分接替运行和本总控复跑。
- 已确证的 CUDA 58096 服务及额外 F1-C/Atlas 测试孤儿已停，57830/58561/58093–58096无监听；生产8045与当前验收进程未触碰。清理证据在 `D:/Temp/F1-orphan-audit-20261009/` 和 A spot-service 清理记录。
- 按用户续令先提交推送上述已验收基线；Gemini 10×3、新F1-D效果及relevance第5条的max融合补齐仍是后续F1工作，不以基线提交宣称F1全包完成。

- 两仓已设置跟踪 `origin/memory-v1`，开工提交与远端对比均 `0 0`；不能用未设置 upstream 的 status 省略 ahead 当作推送证明。
- F1-A 追加独占 `hybrid_recall.py` 的 worker 函数及 MemoryOS conftest TempSvc 显式关闭非语义契约环境；复用单一 embedding 消费者，默认生产代码仍开启。新迁移尚不需要。
- F1-B 追加 Reflector temperature 单行权限；专名原样保留、按引用原文判断语言，避免中文技术句误判。
- 总控早期 diff 审阅发现并要求修正 pending 编码期间的 authority 字段缺失、合法 READY 被竞态删除，以及预热时请求线程同步加载模型的风险。必须有回归证据。
- Atlas 基线 run1 全进度共有11个F，但 Windows 全局 pytest-current 清理权限错误使收尾失败，不作为完整全集结果；改用独立 --basetemp 是隔离修复，不是对失败重试。
- Atlas 有效基线 run2：253 passed / 11 failed / 2 teardown errors / 0 skipped，422.54秒。命令含 `-o addopts= core/tests/unified_memory -v --durations=20 --basetemp`，日志 `C:/Users/25011/AppData/Local/Temp/atlas-f1c-atlas-run2-20261008/pytest.log`。fake-loopback 仅契约回归，不计真实模型效果。
- 现有评测 script 直接调用 ModelRouter 未经过 run_phases；固定题清单 metadata 数据源是 oracle、非完整S hash。F1-D须修入口和核实完整S历史，不能继承旧分数当作验收。
- 总控 MemoryOS 全集 gate1：418 tests，415 passed / 3 failed / 0 skipped / 0 errors，136.762秒；证据 `D:/Temp/F1-controller-memoryos-gate1-20261008/`。三个 hybrid 测试与显式禁用/worker READY 前置不匹配，已交 A 判定并修复，尚未验收。
- F1-A 首次 CUDA 10k 实测索引全部 READY，pending=0；原始性能结果 FAIL（HTTP p95 954.014ms > 800ms）。证据 `D:/Temp/F1-A-cuda-20261008-174500/smoke-10k/run.json` 永久保留原结果；不得修改样本、检索参数或原始证据来伪造达标。A 继续定位热点。
- 总控亲自 HTTP 抽查原10k库的隔离服务（58096）：worker READY、pending=0、device=cuda；自然问题“我一周有几天不去办公室？”命中实际记录 `mem-fm-5ea12ffefbbe0f931ac1`，活动值“每周三天远程办公”，通道 fulltext+semantic。该次新服务首查 1070.552ms，仅证明功能，不算性能通过。共享/生产 service .venv 仍 CPU-only，临时 CUDA 环境不等于部署已变更。
- F1-C 真实桌面纠正请求复现 422 CONTEXT_REQUIRED；追加唯一所有权 `frontend/src/renderer/components/memory/CorrectionDialog.tsx` 及同名 test、`core/atlas/api/unified_memory_router.py` 的 corrections 专用接线。复用 facade 的 canonical context，不硬编码主体；保留 expected_revision 防冲突。
- 总控已亲读纠正 UI/router diff，并亲跑前端 Vitest（11 passed）及 npm run build（exit 0）；证据 `D:/Temp/F1-controller-frontend-20261008/`。更正后旧派生标题仍残留的真实缺陷交 A 修 formation，合法 prev_value 审计与原始 source 必须保留，活动字段及模型消费上下文不能继续使用旧偏好。
- F1-D 已验证固定120题全部来自完整 LongMemEval_S；仅隔离 AtlasConfig 的 observer_daily_token_budget 可提高到覆盖真实完整历史的测试上界，保留 reserve/retry/超预算保护并记录原值、本次值和实际token。不得写生产配置或绕过费用停止线。实际网关单价尚待用户提供，120题不得开跑；12题和运行器准备继续。
- F1-D 修订估算已包括每批最多一次语言重试：12题官方峰值区间约 USD 1.405–3.2524，120题约 USD 14.136–32.6939。120题保守上界超过任务书 USD20 停止线，总控已发预算及实际网关单价询问；答复前禁止运行120题。旧不含重试的上界估算不能再作费用放行依据。

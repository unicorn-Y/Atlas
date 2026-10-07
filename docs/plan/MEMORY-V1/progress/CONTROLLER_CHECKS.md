# 总控检查记录（2026-10-07）

## 施工恢复

用户明确授权最多三个子智能体。A/B/C 均通过 followup_task 恢复，模型维持 GPT-6 Luna，xhigh；待 D/E/F 以空槽补派。CURRENT 中 S0/S1/S2 恢复 IN_PROGRESS。原并行数量阻塞已解除，不依赖本机未登录 CLI。

## 推送通道只读验证

使用 `GIT_SSH_COMMAND=ssh -o BatchMode=yes -o ConnectTimeout=10`，只读取远端，不修改配置或远端：

- `rtk git ls-remote git@github.com:unicorn-Y/Atlas.git refs/heads/memory-v1`，退出 0，返回 `52e78a05084535b0c67422b72e918ef6c3c23a48`。
- `rtk git ls-remote git@github.com:unicorn-Y/MemoryOS.git refs/heads/memory-v1`，退出 0，返回 `17466279e2a820813966b0833330ad416a1b000a`。

两者与开工 HEAD 一致。此检查只证明 SSH 读取可用，不证明后续推送成功。验收后必须单独推送并比对远端 HEAD。

## 文件所有权调控

A 增补独占 Atlas core/atlas/config.py 与 MemoryOS service/app.py（冻结后台入口）。D 禁止改 app.py；仍独占 api.py/formation.py/consolidation.py 与必要新迁移 0031。B 独占聊天/读路径/lifecycle 热文件；C 不编辑它们。

已向 C 提醒：工具执行回执和通过工具读取的第三方材料应区分，第三方不能成为用户事实；speaker 字段不应脱离真实 provenance 无条件采信。此项必须在 S2 测试与真实冒烟中验证，尚未判为通过。

A 定位到 recall 内部 association/graph 路径无法由路由整体封锁而保留基本召回。为完成 S0，D/E 未启动期间，将 api.py、retrieval.py、maintenance.py、utility.py 的冻结门控临时授予 A；明确禁止提前实施 D/E 能力，完成后转交 D/E，保持单一写者。冻结路由不等于所有后台与子路径冻结，需逐项验证。

## S0 故障证据抽查（尚非交付验收）

A 报告隔离复现 `test_bootstrap::test_chat_roundtrip` 为 1 failed。总控读取 `C:/Users/25011/AppData/Local/Temp/memory-v1-s0-a-baseline-20261007/atlas_test_bootstrap_chat_roundtrip.log`，确认断言期望 `um-fake-ok`、实际固定中文回复，日志最终为 `1 failed, 2 warnings in 24.26s`。读取测试源码确认断言检查真实 WS 事件和 loopback fake provider 返回值，并未预设自然记忆效果。

A 的本次复现报告请求走 fake loopback、未见真实供应商；与任务书写的“请求漏到真实供应商”不一致。本轮以证据为准：先删除 harness 固定作答，再独立检查环境泄漏，不能仅修这条断言就判泄漏不存在。尚未复跑修复后的测试或真实模型冒烟。

## B 初稿提前审读（已打回具体问题，尚未验收）

总控读新 service_lifecycle.py 初稿，发现 health probe 期待 `/v1/health` 响应含 endpoints。对照实际 MemoryOS service/app.py：endpoints 在 GET `/`（约 492 行），health 函数（约 499–524 行）不提供该字段。这会把实际健康服务误判离线。已要求 B 对齐真实 health/服务身份契约，并以实际 HTTP 测试，不能只 mock probe 成功。

同时要求保留可诊断启动失败的日志、删除未用 import，并验证启动未 ready 时 Atlas 退出的后台任务取消/自有子进程回收；这些是 S1 生命周期的必要验收点，未判通过。

后续 B 用同一隔离 service venv 确认 app.py 与 unified.api 均来自 D:/MemoryOS。根路由清单没有 unified 路径，原因是当前 FastAPI 的 lazy include 未展开；不能凭根 endpoints 清单判统一服务不存在。真实统一 observe/records 请求已由总控 legacy-import 复跑证明可用。B 将 probe 调整为 identity、health 与实际统一端点验证；尚待复跑该 probe。

## 总控独立复跑：legacy-import 最小修复

读 diff 确认只集中加载本仓 conftest 的真实 http helper 并改两处引用；原请求和断言保留，未改产品 importer、未跨环境导入产品代码。

环境：cwd D:/MemoryOS；PYTHONPATH 移除，PYTHONUTF8=1，PYTHONIOENCODING=utf-8；三个数据 env 均指向 C:/Users/25011/AppData/Local/Temp/memory-v1-controller-s0-legacy 内，pytest 自建实际服务使用另一个临时隔离库。

命令：`rtk proxy C:/Users/25011/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe -m pytest tests/unified_memory/test_legacy_import.py -q -p no:cacheprovider --basetemp C:/Users/25011/AppData/Local/Temp/memory-v1-controller-s0-legacy/pytest`

首次复跑因总控未创建 basetemp 父目录而得到 5 passed/4 setup errors（WinError 3），属验证命令设置错误，不归咎产品。创建该隔离父目录后原命令复跑，退出码 0，原始结果：

```text
.........                                                                [100%]
9 passed in 6.49s
```

这仅验证 legacy-import 的九个用例，不能代表 S0 全套、真实模型效果或 V1 通过。

## 总控独立复跑：bootstrap 全七项（返工中）

命令：cwd D:/Atlas/core，PYTHONUTF8=1、PYTHONIOENCODING=utf-8、PYTHONPATH 移除，三个数据 env 设为 C:/Users/25011/AppData/Local/Temp/memory-v1-controller-s0-bootstrap 内；`rtk proxy D:/Atlas/core/.venv/Scripts/python.exe -m pytest tests/unified_memory/test_bootstrap.py -q -p no:cacheprovider --basetemp C:/Users/25011/AppData/Local/Temp/memory-v1-controller-s0-bootstrap/pytest`。

退出 1，原始结果：

```text
FAILED tests/unified_memory/test_bootstrap.py::test_fault_registry_wiring - DID NOT RAISE TransportError
FAILED tests/unified_memory/test_bootstrap.py::test_api_routing - JSONDecodeError: Expecting value: line 1 column 1
2 failed, 5 passed in 32.66s
```

固定回答对应 chat_roundtrip 此轮通过，不能据此声称 bootstrap 全绿。原始服务日志：D:/Atlas/artifacts/unified-memory/test-runtime/logs-04610e2838594bd38b2dff11e52dc32f/atlas.log 与 memoryos.log。两处失败已交 A/B 协查，不能删/skip/放宽原断言。

总控网络路径诊断：HTTP_PROXY/HTTPS_PROXY/ALL_PROXY/NO_PROXY 上下大小写环境变量均未设；`urllib.request.getproxies()` 从 Windows 系统代理获得 ftp/http/https，`proxy_bypass('127.0.0.1')=True`。但 `httpx.Client()._transport_for_url(httpx.URL('http://127.0.0.1:65534')) is not client._transport` 为 True，说明 HTTPX 仍代理 loopback。这是可复验的内部网络路径问题；未打印代理地址/凭据、未修改系统配置。已要求仅本地 harness/服务客户端直连，并保留远端真实模型供应商网络策略，修复后再复跑。

## Harness 剩余伪证据已要求返工

总控读 _summarize_run，发现 fabricated_fact=False 常量及 applied_preference 从可召回记录/关键词推断“已应用”。已要求 A 只从真实事件/应用回执派生，缺证据明确未验证，不能把常量 False 当作未编造证明。尚未判 S0 完成。

## 总控独立复跑：S1 当前九项

2026-10-07 22:04，cwd D:/Atlas/core，数据根与 HERMES_HOME 均隔离于 Temp/memory-v1-controller-s1-current。命令：`rtk proxy D:/Atlas/core/.venv/Scripts/python.exe -m pytest tests/test_memoryos_service_lifecycle.py tests/test_unified_memory_v1_reads.py -q -p no:cacheprovider --basetemp C:/Users/25011/AppData/Local/Temp/memory-v1-controller-s1-current/pytest`。退出 0，9 passed in 3.57s。含实际隔离 MemoryOS 服务的 status/recall HTTP；真实模型五条与 legacy dry-run 尚未完成，不能据此判 S1 完成。

MemoryOS legacy-import 修复已独立验收、提交并推送：b43622ac273cfe006c04ef0ca0429e80dbdd2ea4，SSH remote memory-v1 HEAD 核对一致。仅提交该测试、CURRENT 和 S0 部分进度；其他继承改动与在建源码未混入提交。

## Observer 模型探针隔离问题

C 的首次真实模型准备未到供应商调用：隔离默认目录的模型目录缺少实际选中的 deepseek-v4.1-flash；读取机器 Hermes 配置时遇到重复 YAML 键，Hermes 加载器自动产生 corrupt 备份。已要求停止未隔离 HERMES_HOME 的探针，核对原文件是否改变、保留证据，禁止修复或清理生产配置。后续确认实际 Atlas config 的 models.custom 含该模型，正在以内存中的只读模型元数据和隔离 Hermes home 重试。当前不足以宣告真正 BLOCKED，也不能声称真实模型已通过。

## 补充文件所有权与会话结束边界

B 获得 capture.py 现有 tick/ACK 后薄回调接线所有权；C 获得 outbox.py 同一运行 outbox 的 Observer 队列、预算与水位持久化所有权。不得另建事实库、配置库或 scheduler，不得重写原捕获投递可靠性。A 补充 test_transfer_gate.py 的显式功能 opt-in，原断言保留。

总控暂未授权 DELETE conversation 触发 Observer 新写入：真实删除事件不能直接当作普通会话结束使用，需对齐后续删除防复活边界。B/C 先使用现有 tick、会话切换和 shutdown，补证真实会话批处理触发。

## 最新 bootstrap 与 Observer 探针证据

总控于 22:05 独立复跑当前 bootstrap：9 passed, 1 warning in 24.55s，退出 0。warning 是新 receipt fixture 经 __new__ 构造后缺生命周期字段导致析构 AttributeError；已退 A 补完整夹具，未修改产品析构规避警告。数据与 HERMES_HOME 隔离于 Temp/memory-v1-controller-s0-bootstrap-current。

总控亲读 C 原始 artifact：C:/Users/25011/AppData/Local/Temp/atlas-mv1-live-observe-92c9uje2/atlas/observer.jsonl。真实 deepseek-v4.1-flash，purpose memory_observe，input_tokens=4425/output_tokens=127；自然中文输入产生一条 HIGH/PREFERENCE/USER，key/value 均 null，evidence 为同批真实 CaptureService source_event_id。当前只有 MODEL_ONLY：源 outbox 为 NEW，未完成 MemoryOS HTTP ack；外层采集器 GBK 解码 UTF-8 日志失败，退出 1，不能声称整个命令成功或 S2 形成通过。已要求修采集、使用 ACKED 真源并给可复跑真实 HTTP 闭环命令。

C 对 Hermes 源码的进一步核验：parse failure 不覆盖原 config；backup_config 除新建 corrupt 副本外，还可能搬移旧 sibling 备份及按 keep=5 清理备份。目前只确认该轮产生副本与目录副作用，无法从事后源码证明不存在历史备份搬移/清理；未再操作生产路径。

## 隔离变量核对与新增独立结果

总控前面误把数据库隔离变量写为 MEMORYOS_DB_DIR；B 提醒后亲读 service/db.py:31–33，实际消费 MEMORYOS_DB_PATH，未设时取已隔离 DATA_ROOT/db/memoryos.sqlite3。上述总控测试的 DATA_ROOT 均已设临时目录且 fixture 另提供实际临时 db_path；设置未消费的 DB_DIR 不代表设置了 DB_PATH。后续命令统一使用显式临时 SQLite 文件路径，派工文档已更正。

总控最新 lifecycle/reads 16 passed in 3.13s，含 probe 拒绝403/307/500和IPv6启动host；config/models全模块26 passed in 35.81s。冻结5项5 passed in 3.16s；八个原opt-in专测74 passed in 16.09s，退出均0。仍未替代真实模型闭环和完整步骤验收。

## 已推送冻结子包与接续 D

MOS ba8613403f56429333fe5adfdca6f291bd4b41f1 已提交、推送，并用 SSH ls-remote 核对 memory-v1 相同完整 HEAD。只 stage 17 个登记文件，未混入既有 recovery/HARD_ERASE 证据改动。A 确认冻结文件停止编辑后，其通道立即接续 D；api.py 转 D、retrieval.py 留 E，B/C 继续。A.md 的 PARTIAL 与全套基线缺口保留，不将整合子包当完整 S0。

Observer 当前十二项已独立复跑：12 passed in 2.26s，退出0，Temp/memory-v1-controller-observer-current 隔离根。C 随后还在补 ACKED→enqueue 窗口恢复；总控读预算结算发现 BEGIN 前读 reservation 的并发重复结算风险，已退 C 将读取和更新置于同一事务并验证重启遗留预留策略。

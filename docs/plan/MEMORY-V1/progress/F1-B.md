# F1-B：Observer / Reflector 同语言

2026-10-09 用户续令：当前模型改为 custom provider 的 `gemini-3.8-flash`（Antigravity 8045）。下方 DeepSeek 10×3 是历史证据，不代表 Gemini 效果。Gemini 真实 ModelRouter 10×3 已完成：30 个唯一成功样本产生 31 条文本，31/31 为中文；首轮样本 27 的真实超时保留为失败尝试，之后续跑样本 27–30 完成。完整调用与 token 口径见本节末尾。

状态：实现、真实调用和证据记录完成；总控单段抽检已通过。总控 Atlas 全集已包含新增三项 runner 测试：276 tests，274 passed、2 skipped、0 failed/error，276.879s，证据 `D:/Temp/F1-controller-atlas-gemini-final-gate-20261009/junit.xml`。独立共享 Gemini helper 的 8 项测试也由总控复跑通过，证据 `D:/Temp/F1-controller-gemini-helper-tests-20261009/tests.log`。MemoryOS 全集已为此交付再次由总控复跑：425 passed / 0 failed，132.73s，证据 `D:/Temp/F1-controller-memoryos-gemini-gate-20261009/junit.xml`；本报告不改变 `CURRENT`。

## 上游来源核对

按 `02_上游搬运清单.md` 固定到 Mastra commit `9c2e4c7cde40a4321112e24affd1750e9be827f9`，先读取完整源文件，再修改 Atlas 提示词。临时源码 checkout 中的 Git blob 与清单一致：

| 上游源 | Git blob | Atlas 对照 | 搬运核对 |
|---|---|---|---|
| `packages/memory/src/processors/observational-memory/observer-agent.ts` | `37d963b6b7df63d1b44dea7e8a45ed6f3f1a23e6` | `core/atlas/memory/observer_prompt.py`，以及 `core/atlas/memory/observer.py` 中 S2 JSON 接线 | 保留 Mastra 全部原条目和英文例子；追加同类中文例子与语言硬规则。Observer 温度设为 0.1。 |
| `packages/memory/src/processors/observational-memory/reflector-agent.ts` | `bcf92d0c4b2f52aaf34daf5e4f7feed66af059db` | `core/atlas/memory/reflector.py` 的既有 S4 操作提示词 | 保留既有操作与禁区；追加中文例子及同语言硬规则。只将温度从 0.2 降到 0.1，未改触发或执行逻辑。 |

`VENDORED` 由总控更新，本任务没有修改它。

## 实现与边界

- Observation 的自然语言 `text` 与有自然语言含义的 `value` 按其 `evidence` 指向的源文本逐条检查；`key` 继续要求英文点分 slug。对纯技术名词、原样人名等不按语言句子误判；中文技术句含 ASCII 标识符仍识别为中文。混合中英文来源不把一条记录的语言强加给同批其他记录。
- 对结构有效但语言不符的 Observer 首次结果，只重试一次，重试消息要求每条输出跟随其引用的源文本语言，不加入预期答案、结构化 key 或额外事实。若重试仍不合格或重试无效，保留最后一个结构有效的结果，标记 `language_mismatch` 并累计行数；不丢弃产物。重试预留预算在失败、异常和取消时均释放。
- Observer 与 Reflector 实际 ModelRouter 调用温度均不高于 0.1。

## 验证

定向测试使用明确的 `pytest.mark.fake_provider`，只验证本地控制逻辑，不作为效果证据。测试覆盖中英/专名与技术词边界、英文名词短语误检、按证据区分中英文来源、混合来源重试、一次重试后恢复与仍不合格保留、累计计数、低温和取消时预算释放。

```powershell
& 'D:\Atlas\core\.venv\Scripts\python.exe' -m pytest -p no:cacheprovider -o addopts= core/tests/unified_memory/test_f1_language.py -q
```

结果：`9 passed in 1.88s`。以下检查也通过：

```powershell
& 'D:\Atlas\core\.venv\Scripts\python.exe' -m py_compile core/atlas/memory/observer.py core/atlas/memory/observer_prompt.py core/atlas/memory/reflector.py core/tests/unified_memory/test_f1_language.py scripts/f1_language_smoke.py
& 'D:\Atlas\core\.venv\Scripts\python.exe' scripts/f1_language_smoke.py --help
git diff --check -- core/atlas/memory/observer.py core/atlas/memory/observer_prompt.py core/atlas/memory/reflector.py core/tests/unified_memory/test_f1_language.py scripts/f1_language_smoke.py
```

### 真实 ModelRouter 冒烟

执行的完整命令：

```powershell
& 'D:\Atlas\core\.venv\Scripts\python.exe' scripts/f1_language_smoke.py
```

脚本从 Atlas 现有只读用户配置创建产品 `ModelManager` / `ModelRouter`，随后为 Observer 设定独立临时 `ATLAS_DATA_DIR`、`MEMORYOS_DATA_ROOT` 与 `MEMORYOS_DB_PATH`；不写模型设置、不启动服务、不持久化观察。实际路由为 `deepseek-v4.1-flash`，配置来源为 `user-settings`，网关主机 `cnapi.pleasure.cc.cd:8443`。

10 段自然中文对话各运行 3 次，共 30 次 ModelRouter 调用、61 条 Observer `text`；61 条均判为中文（100%，高于 98% 门槛），最终 `language_mismatch` 为 0。服务端报告 input 153,547 tokens、output 6,977 tokens；30 次都未返回费用字段，因此实际费用记为未知（`null`），不是零。没有完整 usage 的调用数为 0。运行期间 `config/atlas.toml` 与 `data/user-settings.json` 的修改时间未变化。初始化只读取现有配置；源码核对 `ModelManager.__init__` 的 provider 载入为纯内存规范化，用户模型添加采用 `persist=False`。

这 30 次运行早于最终两项边界修正：语言识别增加英文名词短语的兜底检测，取消重试时释放预算预留。Observer / Reflector 提示词、温度和实际模型调用路径未变；最终源码已由 9 项定向测试覆盖这些边界。总控抽检命令用于复核最终工作树版本。

完整原始 stdout（含前置日志）保存在 [F1-B-language-smoke.raw.log](F1-B-language-smoke.raw.log)。纯 JSON 证据与每段实际来源 ID、speaker 和对话原文在 [F1-B-language-smoke.json](F1-B-language-smoke.json)；来源 ID 从同一原始 stdout 的 30 条 `memory_observer.completed` 日志按调用顺序对应到脚本中的 10 段对话，`raw_output` 未改写。原始 stdout 前有 Hermes 独立用户配置的 YAML 重复键警告；没有输出凭据内容，该警告未改变 Atlas ModelRouter 的真实调用结果。

总控可抽检单段（该段运行 3 次）：

```powershell
& 'D:\Atlas\core\.venv\Scripts\python.exe' scripts/f1_language_smoke.py --limit 1
```

检查脚本与进度记录没有写入 `scripts/memory_v1`、未修改 `CURRENT`，且没有提交或推送。本项结果供总控抽检、全集回归和后续 F1 门禁使用。

## Gemini 3.8 Flash 最终真实 ModelRouter 冒烟（2026-10-09）

本节是 Gemini 最终真实效果证据；上节 DeepSeek 30-call 结果只作历史记录。调用完整 Atlas ModelRouter 的 memory_observe purpose，模型 gemini-3.8-flash，Atlas provider id custom（label antigravity-tools），目标 host 127.0.0.1:8045，API mode chat_completions。这是实际 provider 请求，不是 fake provider。凭据由 Atlas ModelManager 从 Windows Credential Manager/keyring 读取；隔离设置只含获准的 memory_model、providers.custom 路由元数据和 Gemini custom_models 元数据，没有密钥值。

10 段自然中文对话各运行 3 次，共 30 个唯一成功批次，产生 31 条 Observer 文本。Atlas _dominant_language 对 31 条逐条判为中文（31/31，100%），language_mismatch 为 0，高于 98% 门槛。逐条从每个原始输出读取 observations[].evidence，与该批输入的 source_events[].source_event_id 集合比较；31 个 evidence 项全部属于同批输入 source。输入未附加预期观察答案或替换文案。

首轮顺序执行完成样本 1–26 后，样本 27 的真实 ModelRouter 请求发生 APITimeoutError。这是一次真实失败尝试，不计作成功样本，也没有对该失败生成文本。首轮 runner 在异常汇报处又触发 KeyError，未能写出最终 JSON；26 个已完成批次从同一次 Observer 结构化日志按顺序原样恢复。随后只续跑样本 27–30，四个批次均成功。最终结果的样本编号 1–30 唯一，模型调用共 31 次（26 次成功、1 次失败超时、4 次续跑成功）；失败尝试独立列在证据中，没有从分母移除它的历史记录。

token 口径分别保留：30 个成功样本的 Observer-accounted input 为 159,261、output 为 4,158。首轮 26 个样本的逐请求 ModelRouter usage 没有从异常前 runner 文件中落盘；Observer 结构化日志提供的 batch-accounted 数字在 provider usage 缺失时可能是估算，不能标成 provider-reported。续跑 4 次的 provider usage 完整，input 为 21,250、output 为 554；超时请求没有返回 usage。费用字段未返回，因此费用未知。

配置和数据均隔离在 D:\Temp\F1-B-gemini-20261009\。运行时只从 D:\Atlas\data\user-settings.json 读取允许的路由元数据，写入隔离设置副本；ATLAS_DATA_DIR、MEMORYOS_DATA_ROOT 和 MEMORYOS_DB_PATH 都指向 DTemp。没有改生产设置、生产数据库、D:\MemoryOSData 或 8045 服务配置，也没有启动 Atlas / MemoryOS 服务。最终 JSON 与两份原始日志逐文件 SHA256 对照 DTemp 原件一致；用当前 Windows Credential Manager 中的实际凭据对三份文件做字符串、JSON 字符串、URL 编码和 base64 扫描，匹配文件数为 0。

完整证据与原始日志：

- [F1-B-gemini-language-smoke.json](F1-B-gemini-language-smoke.json)：30 个唯一成功样本、31 条 raw Observation、31 项 source 验证、完整失败尝试记录与 token 口径。
- [F1-B-gemini-first-attempt.raw.log](F1-B-gemini-first-attempt.raw.log)：首轮 26 次成功输出及样本 27 超时。
- [F1-B-gemini-continuation.raw.log](F1-B-gemini-continuation.raw.log)：样本 27–30 的四次成功续跑。

最终 30 次调用由 DTemp 中隔离配置的执行副本完成：D:\Temp\F1-B-gemini-20261009\language_smoke.py。仓库中的 scripts/f1_language_smoke.py 已接入共享 Gemini bootstrap，固定隔离设置、路由与 Windows keyring 来源；支持从本脚本格式的 JSON 续跑。续跑会校验样本输入摘要和固定 Gemini 路由，只跳过已有的唯一成功样本，将失败 attempt 保留在 failed_attempts 与 attempt_history；离线检查确认已成功样本不会重复，失败样本会被再次尝试，重复成功样本会拒绝加载。此前 30 次实际运行早于这项仓库脚本接线，不能说成由当前仓库脚本生成。

仓库 runner 的离线 pytest 覆盖：保留失败尝试并只安排失败/未完成样本、拒绝重复成功样本、拒绝输入摘要不匹配。命令为：

    & 'D:\Atlas\core\.venv\Scripts\python.exe' -m pytest -p no:cacheprovider -o addopts= --basetemp 'D:\Temp\F1-B-runner-tests-20261009\basetemp' --junitxml 'D:\Temp\F1-B-runner-tests-20261009\junit.xml' 'D:\Atlas\core\tests\unified_memory\test_f1_language_smoke.py' -q

结果：3 passed in 0.90s。该测试只检查本地 resume artifact，不调用模型。

总控随后使用仓库最终脚本做单段真实 Gemini 抽检，证据位于 D:\Temp\F1-B-gemini-root-spot-20261009\evidence.json，stdout 位于 controller.log。3/3 个批次各产生中文文本，100% 中文，0 language_mismatch、0 failed attempt；3 个 evidence reference 全部属于同批 source。实际路由为 custom Gemini/keyring；provider usage 为 input 15,974、output 398，未返回费用字段（unknown，不记为 0）。

总控单段抽检可复跑命令（每段执行 3 个 ModelRouter 批次；隔离根及证据文件应置于 DTemp）：

    $runRoot = 'D:\Temp\F1-B-gemini-root-spot-20261009'
    & 'D:\Atlas\core\.venv\Scripts\python.exe' 'D:\Atlas\scripts\f1_language_smoke.py' --limit 1 --isolation-root $runRoot --settings-source 'D:\Atlas\data\user-settings.json' --output (Join-Path $runRoot 'evidence.json')

# F1-B：Observer / Reflector 同语言

2026-10-09 用户续令：当前模型改为 custom provider 的 `gemini-3.8-flash`（Antigravity 8045）。下方 DeepSeek 10×3 是历史验收证据，不能代表 Gemini 最终效果；Gemini 最终代码 10×3 复跑进行中，原始超时/部分结果保留，尚未据此宣称达标。产品基线先按用户要求提交，新模型效果与最终记录随后补齐。

状态：实现与本地验证完成，等待总控抽检和合入；本报告不改变 `CURRENT`。

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

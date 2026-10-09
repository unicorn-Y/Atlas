# F4-D runner 准备记录

日期：2026-10-09。范围仅为评测运行器准备；本轮未启动 Atlas/MemoryOS 服务、真实模型、正式场景评测或 LongMemEval 评测，也未打开题库答案文件。

已完成的最小准备：

- LongMemEval 运行根和观察缓存共用 `longmemeval_observation_cache.checked_temp_child()`：只允许 `D:\Temp` 或当前用户 `%LOCALAPPDATA%\Temp`（解析后必须位于 `C:\Users\<user>` 下）的严格子路径；明确拒绝 `D:\Atlas\data` 和 `D:\MemoryOSData`。F1/F2 新运行根与默认观察缓存优先放在 C 用户临时目录，D 盘旧临时根仍可显式使用。
- 进程 `TEMP/TMP/TMPDIR` 改为当前隔离运行根内的 `temp` 子目录；MemoryOS 数据根随隔离运行根，默认正式运行因此落在 C 用户临时目录。MemoryOS cache/恢复目录也由同一个路径守卫校验。
- TOML 配置只逐行解析 `[memory.v1] observer_daily_token_budget` 的整数，传给 Atlas 的配置对象仅含该预算 allowlist；模型密钥仍仅通过既有 `read_isolated_model_settings` 安全元数据路径处理。未读取或打印真实配置全文。
- F1/F2 的完成/失败报告均明确记录固定抽样 `random_seed=20261007` 与单次运行数。观察 fingerprint 仍只包含 question ID 与 haystack 历史字段，不包含 answer/gold。
- 新增 `f4_eval_report.py`，将既有 `eval_judge.judge_single_scenario` 应用于 3×30 项，保留全部 90 项的判定及失败根因分类，按三次运行的 E1–E4/E6 通过率取中位数，并对反例及 E5/E7/E8 检查三轮全通过。S27 单独标注“缺前置历史”的设计缺陷，不补输入也不豁免判分。它只输出 `REVIEW_REQUIRED`，不写 ACCEPTED，也不改变原判分断言。
- `eval_scenarios.py` 的 C 用户临时根接线由 C lane 负责；已同步可复用 helper 和输入格式要求，没有修改其文件。

模型路径源码核验：LongMemEval 官方 evaluator 提供原判分 prompt；runner 先完成答题并写 `ANSWER_COMPLETE` checkpoint，再把 gold answer 和答案传入该 prompt，最后调用登记模型的 `model_manager.model_router.complete_for(...)`。未发现 OpenAIClient 直连或脚本读取凭据。Gold 不进入 Observer、检索或观察缓存 fingerprint。

红绿证据：

- 初始红测（新增 aggregator 尚未实现）：Atlas Python 3.14.7，31 项收集、1 个收集错误，`ModuleNotFoundError: f4_eval_report`。
- 实现后第一轮专项测为 31 passed、2 failed：一项暴露 TOML 行尾注释解析的换行边界，另一项是缺失场景错误信息未明确“每轮 30 条”；修正后复跑通过。
- 绿测命令（隔离目录位于 `%LOCALAPPDATA%\Temp\F4-D-prep-green-20261009-06`）：

  ```powershell
  $testBase = Join-Path $env:LOCALAPPDATA 'Temp\F4-D-prep-green-20261009-06'
  $env:ATLAS_DATA_DIR = Join-Path $testBase 'atlas-data'
  & 'D:\Atlas\core\.venv\Scripts\python.exe' -m pytest -o addopts= -p no:cacheprovider --basetemp (Join-Path $testBase 'pytest-tmp') scripts/memory_v1/test_longmemeval_f1_runner.py scripts/memory_v1/test_f4_eval_report.py
  ```

  结果：**35 passed in 2.30s**。`ruff check ... --select F401,F821` 对本轮六个 Python 文件通过；`git diff --check` exit 0，无空白错误（Git 对若干共享 CRLF/LF 文件提示行尾归一化警告）。

正式运行仍待 F4-A/B/C 合入及总控发起。尚未生成三轮真实场景结果、LongMemEval 6/30 结果、CPU 10k 召回 p95、模型实际 token/耗时统计或正式 `progress/F4-eval.md`；聚合器中的三轮测试使用合成判分结果，只验证聚合逻辑，不代表产品效果。

总控复核后的 allowlist 边界补强（2026-10-09）：

- 修正 `_read_observer_budget_allowlist` 的 section 状态处理：任何以 `[` 开头的 TOML table 行都会先结束前一节，只有精确匹配未加引号的 `[memory.v1]` 才重新允许读取预算；`["other.section"]` 与 `[[models.gateway]]` 不再继承 `memory.v1`。
- 新增 quoted-table 与 array-table 两项边界回归。修复前红测：2 failed，均因旧 section 泄漏而把后续同名键误识别为重复预算（exit 1）。修复后该 runner 全测：**33 passed，4 subtests passed in 2.07s**。
- 复跑命令：`& 'D:\Atlas\core\.venv\Scripts\python.exe' -m pytest -p no:cacheprovider -q scripts/memory_v1/test_longmemeval_f1_runner.py --basetemp 'C:\Users\25011\AppData\Local\Temp\atlas-f4-budget-green-20261009'`。此为静态运行器测试，没有启动评测、服务或模型。

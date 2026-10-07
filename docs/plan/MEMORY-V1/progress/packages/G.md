# 任务包 G 报告 (S4 反思者 Reflector)

- 状态：DONE_PENDING_REVIEW
- 所有权说明：仅修改与创建 Package G 范围文件，不越界改动 B/C/D 专属文件。

## 改了哪些文件

1. `core/atlas/memory/reflector.py`
   - S4 反思者核心实现：上游 Mastra `reflector-agent.ts` 与 `thresholds.ts` 搬运及 S4 操作列表改造（MERGE, SUPERSEDE, ROLLUP_DAY, ROLLUP_WEEK, PROFILE_UPDATE, IMPORTANCE），前置门槛省 token 检查（5 条或 2000 token），后置本地静态校验、画像 ≤ 600 token 压缩校验与严格句子级可追溯性校验，MemoryOS `consolidation:apply` 落地与幂等支持。
2. `core/tests/test_memory_v1_reflector.py`
   - S4 反思者专属单测套件（10 项测试全绿）：覆盖未满阈值跳过大模型、阈值触发、MERGE/SUPERSEDE/ROLLUP/PROFILE_UPDATE/IMPORTANCE 校验、禁止操作拒绝、画像压缩与来源追溯校验、幂等性、压缩重试引导等。
3. `scripts/memory_v1/smoke_reflector.py`
   - S4 反思者真实模型冒烟脚本：在严格隔离数据目录下，通过 ModelRouter（真实网关模型 `deepseek-v4.1-flash`）运行反思与操作提议，验证操作合法性及 MemoryOS 兼容性。
4. `docs/plan/MEMORY-V1/progress/packages/G_vendored.md`
   - 上游 Mastra 固定 commit `9c2e4c7cde40a4321112e24affd1750e9be827f9` 对应符号、行号、改造说明及 Apache-2.0 声明映射。
5. `docs/plan/MEMORY-V1/progress/packages/G.md`
   - 本交付报告。

## 跑了什么测试

1. S4 反思者专项单测：
   `cd D:/Atlas/core && D:/Atlas/core/.venv/Scripts/python.exe -m pytest tests/test_memory_v1_reflector.py --basetemp=C:/Users/25011/AppData/Local/hermes/cache/scratch/pytest_tmp`
   → `10 passed, 1 warning in 1.72s`

2. Atlas 记忆全量单元回归套件：
   `cd D:/Atlas/core && D:/Atlas/core/.venv/Scripts/python.exe -m pytest tests/test_memory_v1_observer.py tests/test_memory_observer_drain.py tests/test_bootstrap_memory_v1_config.py tests/test_memory_v1_reflector.py --basetemp=C:/Users/25011/AppData/Local/hermes/cache/scratch/pytest_tmp`
   → `37 passed, 1 warning in 2.23s`

3. MemoryOS 侧 consolidation:apply 回归测试：
   `PYTHONPATH="D:/MemoryOS/service;D:/MemoryOS" C:/Users/25011/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe -m pytest D:/MemoryOS/tests/unified_memory/test_memory_v1_consolidation.py --basetemp=C:/Users/25011/AppData/Local/hermes/cache/scratch/pytest_tmp`
   → `7 passed in 2.82s`

## 真实冒烟

- 命令：
  ```bash
  export ATLAS_DATA_DIR="C:/Users/25011/AppData/Local/Temp/isolated_reflector_smoke/atlas_data"
  export MEMORYOS_DATA_ROOT="C:/Users/25011/AppData/Local/Temp/isolated_reflector_smoke/mos_data"
  export MEMORYOS_DB_PATH="C:/Users/25011/AppData/Local/Temp/isolated_reflector_smoke/mos_data/test.db"
  export HERMES_HOME="C:/Users/25011/AppData/Local/Temp/isolated_reflector_smoke/hermes_home"
  cd D:/Atlas/core && D:/Atlas/core/.venv/Scripts/python.exe D:/Atlas/scripts/memory_v1/smoke_reflector.py
  ```
- 原始输出尾部：
  ```
  === Reflector Real Model Smoke Results ===
  Status: COMPLETED
  Model ID: deepseek-v4.1-flash
  Duration: 5.49s
  Token Usage: {'prompt_tokens': 1102, 'completion_tokens': 485}
  Accepted Operations: 8
    - [MERGE]: {'op': 'MERGE', 'refs': ['memory:rec-001', 'memory:rec-002'], 'into_text': '用户刚来杭州余杭工作，从事跨境电商相关业务。', 'keep_ref': 'memory:rec-001'}
    - [SUPERSEDE]: {'op': 'SUPERSEDE', 'old_ref': 'memory:rec-004', 'new_ref': 'memory:rec-005', 'reason': '用户开发设备从 Windows 笔记本更换为 MacBook Pro，旧设备转为备用'}
    - [IMPORTANCE]: {'op': 'IMPORTANCE', 'ref': 'memory:rec-003', 'level': 'HIGH'}
    - [ROLLUP_DAY]: {'op': 'ROLLUP_DAY', 'date': '2026-09-24', 'refs': ['memory:rec-001', 'memory:rec-002', 'memory:rec-003', 'memory:rec-004'], 'text': '用户刚来杭州余杭工作，从事跨境电商业务；对花生严重过敏，外出就餐需格外注意；当时开发设备为一台 Windows 笔记本。'}
    - [ROLLUP_DAY]: {'op': 'ROLLUP_DAY', 'date': '2026-10-02', 'refs': ['memory:rec-005'], 'text': '用户更换开发设备为 MacBook Pro，原 Windows 笔记本转为备用。'}
    - [ROLLUP_DAY]: {'op': 'ROLLUP_DAY', 'date': '2026-10-05', 'refs': ['memory:rec-006'], 'text': '用户与海外供应商完成秋季选品线上会议，确认首批测试订单。'}
    - [ROLLUP_WEEK]: {'op': 'ROLLUP_WEEK', 'date': '2026-10-05', 'refs': ['memory:rec-005', 'memory:rec-006'], 'text': '本周用户将开发设备更换为 MacBook Pro（Windows 笔记本转备用），并与海外供应商完成秋季选品线上会议，确认首批测试订单。'}
    - [PROFILE_UPDATE]: {'op': 'PROFILE_UPDATE', 'refs': ['memory:rec-001', 'memory:rec-002', 'memory:rec-003', 'memory:rec-004', 'memory:rec-005', 'memory:rec-006'], 'text': '用户刚来杭州余杭工作，从事跨境电商相关业务，与海外供应商有选品会议等业务往来。用户对花生严重过敏，外出就餐需格外注意。开发设备方面，用户已从 Windows 笔记本更换为 MacBook Pro，原 Windows 笔记本作为备用。'}
  Rejected Operations: 0
  Artifact written to: C:\Users\25011\AppData\Local\Temp\isolated_reflector_smoke\atlas_data\reflector-smoke-result.json
  ```
- MemoryOS apply 联调验证：对上述真实模型生成的 8 项操作调用 MemoryOS 引擎应用，全部 8 项成功接受，二次应用展示幂等性（Pass 2 accepted 8, rejected 0, idempotent 7）。

## 完成判据逐条对照

1. **输入多条相似记忆被建议 MERGE**：
   - 证据：`test_merge_operation_proposal_and_validation` 验证多条合并并保留来源链路；真实冒烟中 rec-001 与 rec-002（余杭跨境电商）被模型精准提议 MERGE。
2. **输入新旧冲突被建议 SUPERSEDE**：
   - 证据：`test_supersede_operation_proposal_and_validation` 验证新旧替换；真实冒烟中 rec-004（Windows）与 rec-005（MacBook Pro）被模型精准提议 SUPERSEDE。
3. **空闲触发 ROLLUP**：
   - 证据：`test_rollup_day_and_week_validation` 验证按日期与周期形成 SUMMARY 记录；真实冒烟成功提议 3 条 ROLLUP_DAY 及 1 条 ROLLUP_WEEK。
4. **画像更新带 refs 且 ≤ 600 token，每句话可追溯**：
   - 证据：`test_profile_update_validation_compression_and_traceability` 验证 token 预算超额与无根据妄想句被严格拦截；真实冒烟中生成的画像经 `validate_compression` 与 `validate_traceability` 严格通过。
5. **无新记忆跳过大模型（省 token）**：
   - 证据：`test_should_reflect_precheck_skips_llm_below_threshold` 确认低于阈值（<5条且<2000 token）时不发起 ModelRouter 请求，返回 `skip_reason="BELOW_THRESHOLD"`。
6. **被拒绝的操作有清楚的原因**：
   - 证据：单测及本地校验对未知 ref（UNKNOWN_REF）、非法类型（FORBIDDEN_OP: DELETE）、格式不合规等均给出结构化明确原因。
7. **对同一份输入重复运行反思者结果幂等**：
   - 证据：`test_idempotency_behavior` 与 MemoryOS 存储层二次执行实测验证，重复应用时不会越合并越少或丢失信息，具有幂等性保障。

## 已知问题 / 未做到的部分 / 依赖请求

- 无阻碍。
- 依赖请求：后续由总控/Package B 在自动化或空闲轮询生命周期中完成 `reflector.py` 的挂载调度。

## 提交 hash

- `13faa7c` (feat(memory-v1): S4 reflector implementation with Mastra vendoring and tests)

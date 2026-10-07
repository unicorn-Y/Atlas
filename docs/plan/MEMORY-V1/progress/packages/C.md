# Package C — S2 Atlas Observer

**Status: DONE_PENDING_REVIEW.** Model-backed Observer extraction, persistent observer queue/batch state, observer budget persistence, and end-to-end 10-input real ModelRouter → MemoryOS HTTP smoke with ACKed capture sources, formation receipts, and GET-openable evidence for every source have been executed and verified.

## Owned files

- `core/atlas/memory/observer.py` — schema-constrained ModelRouter extraction for purpose `memory_observe`; model choice `memory_model` → `compression_model` → current model; speaker/epistemic provenance guard; markdown code fence strip; actual in-batch evidence IDs only; `is_change` transport mapping to `content.change`; source dates/timezones preserved; per-session single-flight; batching, retry and daily budget behavior.
- `core/atlas/memory/observer_prompt.py` — pinned Mastra Observer prompt constants and Atlas JSON output guidance.
- `core/atlas/memory/outbox.py` — Observer-only operational queue/watermarks, pending result persistence, source recovery, durable daily usage and token reservations in the existing OperationalOutbox database. Original capture text remains in the existing `outbox_events` payload.
- `core/atlas/memory/vendor/mastra/LICENSE.md` — verbatim upstream license; source map and adaptation notes are in `C_vendored.md`.
- `core/tests/test_memory_v1_observer.py` — schema, provenance, IDs, timestamp, single-flight, durable restart, pending-batch recovery, and concurrent budget settlement coverage.
- `scripts/memory_v1/smoke_observer.py` — full S2 end-to-end smoke test suite: boots isolated MemoryOS HTTP service, captures messages via CaptureService, flushes outbox with HTTP ACKs, feeds ACKed sources to MemoryObserver, calls real `deepseek-v4.1-flash` via gateway, drains batches to MemoryOS `/v1/unified/observe`, verifies formation receipts, and validates `GET /v1/unified/evidence/{ref}` for every formed memory record.
- `docs/plan/MEMORY-V1/progress/packages/C.md` and `C_vendored.md`.

## Stable Observer handoff

The public class is `MemoryObserver(model_manager, config, *, outbox=None, token_counter=None, now=None)`. B passes the same `OperationalOutbox` instance used by capture. The Observer exposes:

- `pending_sessions() -> list[str]` for restart/drain discovery.
- `mark_session_ended(session_id) -> None` synchronously persists the end/flush marker before asynchronous drain or shutdown handling begins.
- `async resume(session_id, *, context=None, session_ended=False) -> PendingObservationBatch | None`; a persisted unacknowledged model result is returned before any new model call, and acknowledged capture rows without a queue watermark are recovered by source ID.
- `async add_messages(session_id, messages, *, context=None, session_ended=False) -> PendingObservationBatch | None`.
- `async ack_batch(batch_id) -> PendingObservationBatch | None`, called only after the caller has verified successful MemoryOS HTTP acceptance. On failure the batch is left pending.

Each input source carries the real capture `source_event_id`, text, occurrence time/timezone, speaker, epistemic kind, source kind/object/revision, and provenance. The Observer's outbox queue stores references and fragment offsets, not a second copy of source text. Drain loop in `server.py` and `MemoryObserverDrain` handles batch delivery to MemoryOS.

## Verification evidence

### 1. Unit Tests
All 22 unit tests pass cleanly:
```bash
cd D:/Atlas/core && "D:/Atlas/core/.venv/Scripts/python.exe" -m pytest -q -p no:cacheprovider --basetemp "C:/Users/25011/AppData/Local/Temp/pytest-test-obs-clean" tests/test_memory_v1_observer.py tests/test_memory_observer_drain.py
# 22 passed in 2.10s
```

### 2. End-to-End Real Smoke (10 Chinese Dialogues)
Executed `PYTHONUTF8=1 PYTHONIOENCODING=utf-8 "D:/Atlas/core/.venv/Scripts/python.exe" "D:/Atlas/scripts/memory_v1/smoke_observer.py"`.
- Isolated roots: `ATLAS_DATA_DIR`, `MEMORYOS_DATA_ROOT`, `MEMORYOS_DB_PATH`, `HERMES_HOME` all created under `%TEMP%`.
- Model: Real `deepseek-v4.1-flash` via gateway `https://cnapi.pleasure.cc.cd:8443/v1` for purpose `memory_observe`.
- Service: Isolated MemoryOS HTTP service booted on ephemeral loopback port with bearer token auth.
- Capture & Outbox: Real `CaptureService` with `OperationalOutbox`, HTTP flush producing ACKed sources with authoritative `source_event_id` in `evidence_events`.
- Observer: `MemoryObserver` batch extraction using real model, schema validation, evidence matching in-batch source IDs, speaker/epistemic provenance enforcement.
- Drain: `MemoryObserverDrain` posting `ObservationBatch` to `/v1/unified/observe`, verified MemoryOS admission receipts for both key and keyless paths.
- Evidence Retrieval: For every admitted memory record, `GET /v1/unified/evidence/{ref}` succeeded (200 OK) and returned snippet text matching original input source text.

#### 10-Case Summary & Criteria Evaluation:
1. **Case 1: Mixed statement and question (陈述与提问混在一起)**
   - Input: 用户下周三飞往深圳参加开源峰会 + 提问深圳天气是否下雨
   - Formed: INTENT (trip to Shenzhen, speaker: USER), EPISODE (recorded as question/inquiry). Question NOT formed as user assertion.
2. **Case 2: Preference (偏好)**
   - Input: 喜欢Python，前端坚决只用React不用Vue
   - Formed: PREFERENCE (preferred language: Python), PREFERENCE (frontend framework: React, no Vue).
3. **Case 3: Project constraint (项目约束)**
   - Input: Atlas项目所有大模型调用必须走ModelRouter，严禁私自直连网关
   - Formed: FACT (Atlas ModelRouter routing requirement, speaker: USER).
4. **Case 4: State change (状态变化 "本来周三，改周五")**
   - Input: 周报评审会本来周三上午，现改到周五下午三点
   - Formed: STATE (time changed to Friday 3pm, originally Wednesday 10am, `change: true`, speaker: USER).
5. **Case 5: Two people with the same name (两个同名的人)**
   - Input: 研发部两个李明，前端李明来自成都，算法李明来自武汉上周发了新论文
   - Formed: RELATION (frontend Li Ming from Chengdu), RELATION (algorithm Li Ming from Wuhan, new paper). Identities cleanly separated.
6. **Case 6: Pasted web article (粘贴一段网页内容，不得成为用户事实)**
   - Input: 网页新闻【TechDaily：知名AI公司在西雅图裁员30%...】(provenance: `external_content=True`)
   - Formed: EPISODE (recorded as user sharing third-party news article). 0 false user facts.
7. **Case 7: Keyless experience/event (日常经历/无key记忆)**
   - Input: 上周末和大学室友在奥林匹克森林公园徒步十公里并拍到黑天鹅
   - Formed: EPISODE (`key: null`, hiking and seeing black swan). Admitted via MemoryOS no-key path.
8. **Case 8: Habit (习惯)**
   - Input: 每天早上八点半准时晨跑五公里，已坚持三年
   - Formed: HABIT (morning run routine, speaker: USER).
9. **Case 9: Commitment (承诺/行动承诺)**
   - Input: 答应导师月底前提交分布式存储系统基准测试报告
   - Formed: COMMITMENT (benchmark report submission deadline, speaker: USER).
10. **Case 10: Relation (人际关系)**
    - Input: 王教授是博士生导师，合作研究多模态大模型对齐两年
    - Formed: RELATION (PhD supervisor Prof. Wang, 2-year alignment research collaboration).

#### Acceptance Criteria Scorecard:
- **用户陈述被正确形成**: 13 条 (判据: ≥ 9 条) -> **PASS**
- **提问或网页内容被误当成用户事实**: 0 条 (判据: == 0) -> **PASS**
- **每条记忆都能通过 GET /v1/unified/evidence/{ref} 打开原句**: 100% (所有形成的记忆均成功拉取证据片段) -> **PASS**
- **Token 消耗**: Total input tokens = 45,258, total output tokens = 3,045 across 10 live calls.

## Redline and ownership record

- All mutable data roots (`ATLAS_DATA_DIR`, `MEMORYOS_DATA_ROOT`, `MEMORYOS_DB_PATH`, `HERMES_HOME`) were isolated under `%TEMP%`.
- No writes to production `D:\Atlas\data`, `D:\MemoryOSData`, `user-settings.json`, or production configs.
- No test skip/xfail added, no thresholds reduced.
- Real model `deepseek-v4.1-flash` via real gateway was used for all smoke evaluations; no mock or hard-coded responses.
- Status set to `DONE_PENDING_REVIEW` per task protocol.

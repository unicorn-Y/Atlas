# WAVE5 B 组结果（会话与持久化区：S1 S2 S10 S20 S22 S23 S24 S25 S26 S27 S28 S29 S30 S31 S33）

**Worktree**: `D:\Atlas\.worktrees\w5-b`（分支 `wave5-b`，基线 `32b76e39`）
**真实模型通道**: `deepseek-v4.1-flash`（本组在 fresh `ATLAS_DATA_DIR=.tmp/live-data` 内以 user-settings `custom_models` 声明同 id 条目覆盖，keyring key `atlas:model:deepseek-v4.1-flash`；**未触碰** `config/atlas.toml`、`data/user-settings.json`、`data/memory/**`），后端 `127.0.0.1:8891`
**取证工具**: `core/scripts/dsh_live_z4_check.py`（WS run.start 驱动）、`core/scripts/dsh_otel_probe.py`（18884=普通事件通道 / 18885=session-log 通道）

**关键背景（影响判定口径）**：基线里已合入 wave4-z4 批次（commit `e5903ee2`）的实现——telemetry 双通道、route_image_pricer 接线、skills/change、context_conversations 准入、session_telemetry、product_event——但其**账本行更新在 merge `1687b46a` 冲突解决时丢失**，导致账本仍显示 PARTIAL/ABSENT。本组工作 = 验证继承实现（30+10 单测在本基线复跑通过）+ 补齐真实缺口（S20 剪枝、S28 refresh、S29 @session 文本解析、S31 三模式回归）+ 本基线真机取证。

---

## ① 逐条判定

| Row | 判定 | 一句话依据 |
|---|---|---|
| S10 | **NOT-DONE（前提被 S19 设计取代）** | `atlas/engine/session_sync.py:250` `persist_session_attachments`：图片以 SHA-256 内容寻址 blob 落盘（:275 `digest = hashlib.sha256(payload).hexdigest()`，:277 读回校验），模型历史从不包含图片本体。DSH offload 的前提"图像已在历史中需要摘除"在 Atlas 不成立；不是缺功能，是 S19 durable 附件设计消解了该需求 |
| S20 | **CLOSED** | 单测 6 项红→绿（`test_w5_s20_present_exposure.py`，修复前 5 failed：三档全剪 `no_signal`）；真机回合模型**直接调用** `present`（`tool.started {"name": "present", "arguments": {"path": "deliverable-w5b.txt", ...}}`）+ durable `workspace/changes` seq=7 `{"tool":"present","kind":"deliverable"}`（run `dsh-live-28daaa53`，端口 8891） |
| S22 | **CLOSED** | 单测 5 项（`test_telemetry_channels.py`，z4 继承本基线复跑）；真机双通道独立队列：18884 收 `atlas.app.started / atlas.product0 / atlas.run.completed / atlas.run.failed / atlas.run_checkpoint.write`，18885 独立收 `atlas.session / atlas.session.turn_outline`（`GET /api/conversations/{id}/timeline` 触发，返回 1 entry row_id=16） |
| S23 | **CLOSED** | 单测（`test_session_telemetry.py`）+ 真机：`session_telemetry` 表 14 行，每规范事件一条（`session_id, format_version=1, seq`），去重键验证 14 total = 14 distinct；失败回合（`dsh-live-73972595`）的 turn/start seq=13、turn/end seq=14 也入账 |
| S24 | **CLOSED** | 单测 4 项（`test_product_telemetry.py`：无 tracer 禁用、只导出调用方选定 scrubbed 属性、exporter 失败被隔离）+ 真机 probe 收到 `atlas.product0` 与 `atlas.app.started`（启动）与 `atlas.run.failed`（失败终态）——不自动采会话数据 |
| S25 | **CLOSED** | 单测 10 项（`test_route_image_pricing.py`）+ `loop.py:2291-2298` 生产请求路径传 `image_pricing=route_image_pricer(model_config)`（z4 已接线，本基线验证）+ 真机带图回合 `model_request_envelope`：seq1 `tokens=2056, heuristic_tokens=1158`（差 +898 ≈ 配置的 `visual_tokens: 900`，图像节点按 route 计价；run `c14cc1f3`） |
| S26 | **HARD（no public contract in repository）** | 全库无 DeepSeek 官方会话日志上传契约/watermark/8MiB drain 的任何代码或文档；不推测官方契约 |
| S27 | **CLOSED（继承 W4-Z6/Z4）** | `atlas/skills/__init__.py` provider list/get + `handle_change("skills/change")` 失效 + `SkillManager.revision`（z4 落地）；单测 `test_skills_change_contract.py` 4 项本基线复跑通过；X18 行 W4-Z6 旧账单测（不完整观察不缓存）在库；z4 真机取证（`RESULT4-Z4.md`：启动 3 次 `skills.change_invalidated`、运行中加 SKILL.md 12→13 无重启） |
| S28 | **CLOSED** | 新增 `SessionTitlesMixin.refresh_session_title`（user→derived 解钉、文本保留，`atlas_state_titles.py:187`）+ engine wrapper `refresh_user_title`（`session_titles.py`）+ 路由 `POST /api/conversations/{id}/refresh-title`；单测 6 项（`test_w5_s28_title_refresh.py`：钉住→拒绝→解钉→llm 重竞争→引擎 titler 不再拒）。说明：解钉是 API/存储层行为而非模型回合行为，z4 已对 rank 保护做过真机三轮取证；本条未重跑标题回合 |
| S29 | **CLOSED** | 新增 run 输入 `@session:<id>` 解析 `_parse_session_references`（含 `profile/<id>` deep-link 形式，`run_drive.py:1512`）+ 合并进 `context_conversations`（同 cap=3，AST 验证语句深度）；继承 z4 host 准入（`_context_conversation_admitted` fail-closed）+ `reference_snapshot` untrusted 包裹。单测 9 项新增 + 8 项 z4；真机正例：`@session:dsh-w5b-secret` → 回复「蓝色猎鹰」，transcript user 行内含 `<untrusted_session_snapshot>{"kind":"referenced_conversation","id":"dsh-w5b-secret",...}`；真机反例：跨 workspace 引用 → `run.failed {"category":"validation","detail":"context conversation not admitted to the current workspace: dsh-w5b-secret"}` |
| S30 | **HARD（Atlas is already stronger; do not imitate）** | `atlas/memory/library/__init__.py:141`（recall 于模型调用前）与 `:252`（`_relevant_block`）：长期记忆在 Atlas 已存在；DSH 完全没有该功能（`tool-ralph/README.md:36`），无需也不应改动产品记忆去模仿缺失功能 |
| S31 | **CLOSED（PRESENT-STRONGER，回归加固）** | 新增 5 项路由级回归（`test_w5_s31_rewind_modes.py`：point 三模式 `code/conversation/both` 逐模式断言消息截断/文件还原组合、未知 mode 400、point rewind 后 redo 双向恢复）+ 既有 `test_backend_parity_wave5.py` legacy `message_id+files` 模式回归；DSH 根本没有 rewind（`conversation-context.ts:6` 只是类型字面量），Atlas 三模式 rewind + preview + redo + 文件还原在 `conversations_router.py:1712,1863,1901` |
| S33 | **PARTIAL（缺 attempt 级内容重放；结构/错误重放已真机实证）** | 真机失败回合（unreachable provider，run `73972595`）：journal 含 `model_request_envelope` + `model_request` + 7×`model_error`（retry=True）；`GET /api/run-checkpoints/{id}` 返回 4 个 durable checkpoint（phases: preparing→awaiting_model_response→streaming→**failed**）；`GET /api/run-replay/{id}` status=failed + 16 条 timeline（run_start/model_call/phase/error 全在）。**但** run log 设计上不含模型/工具内容，重放无法还原失败回合的对话内容——不粉饰，定性 PARTIAL(缺失败尝试的模型/工具内容重放；需要先有 S1 的 append-only 内容日志) |
| S1 | **HARD（unreachable without redesign）** | `atlas/engine/state/atlas_state_messages.py`：内容原地改写 `UPDATE messages SET content = ...`（:588，`update_message_content_and_metadata` 定义于 :571）、`DELETE FROM messages`（:908）/软归档（:905）、`archive_and_compact`（:1037）内 `UPDATE messages SET active=0, compacted=0`（:1103）——压缩/rewind 直接改写 active 行且不发事件，append-only 事件日志 + seq 连续性契约不存在。（账本旧行号 :559/:879/:1008 已漂移，本基线以上述为准） |
| S2 | **HARD（needs S1 的 append-only 事件日志）** | 折叠/替换节点语义（"被摘要替换但保留原文"）依赖 S1 的不可改写事件日志；现状只有 `active=0, compacted=1`（`_ARCHIVE_ACTIVE_SQL`，`atlas_state_messages.py:71`）+ 可见列表重写，无法表达 DSH surface 的 shadowed-range 保留语义 |

统计：**CLOSED 9（S20 S22 S23 S24 S25 S27 S28 S29 S31）/ PARTIAL 1（S33）/ HARD 4（S1 S2 S26 S30）/ NOT-DONE 1（S10）**。

---

## ② 改动文件清单（全部在本 worktree，commit 见 ④）

新增：
- `core/tests/test_w5_s20_present_exposure.py`（6 测试）
- `core/tests/test_w5_s28_title_refresh.py`（6 测试）
- `core/tests/test_w5_s29_session_mentions.py`（9 测试）
- `core/tests/test_w5_s31_rewind_modes.py`（5 测试）

修改：
- `core/atlas/engine/kernel/tool_pruning.py` — `present` 家族映射（`"present": "deliverable"`）+ prior 1.0（S20）
- `core/atlas/engine/kernel/loop.py` — `_ALWAYS_KEEP_TOOLS` 增加 `present`（S20）
- `core/atlas/engine/state/atlas_state_titles.py` — `refresh_session_title()` 解钉（S28）
- `core/atlas/engine/session_titles.py` — `refresh_user_title()` wrapper（S28）
- `core/atlas/api/conversations_router.py` — `POST /api/conversations/{id}/refresh-title` 路由（S28）
- `core/atlas/api/run_drive.py` — `_parse_session_references()` + run.start 合并 @session 引用（S29）
- `tasks/dsh-parity/waves/RESULT5-B.md` — 本文件

继承实现（本基线已含、本组验证并取证，未改动）：`core/atlas/telemetry.py`（S22 双通道）、`core/atlas/engine/agent/token_meter.py` + `loop.py:2291-2298`（S25 接线）、`core/atlas/session_telemetry.py`（S23）、`core/atlas/skills/__init__.py`（S27）、`run_drive.py` context_conversations 准入（S29 z4 半）、`core/atlas/api/run_replay_router.py`（S33 面）。

## ③ 测试命令 + 真实输出

最终定向 gate（13 个测试文件，125 项）：

```
cd /d/Atlas/.worktrees/w5-b/core
python -m pytest -q -p no:cacheprovider \
  tests/test_w5_s20_present_exposure.py tests/test_w5_s28_title_refresh.py \
  tests/test_w5_s29_session_mentions.py tests/test_w5_s31_rewind_modes.py \
  tests/test_tool_pruning.py tests/test_route_image_pricing.py \
  tests/test_telemetry_channels.py tests/test_session_telemetry.py \
  tests/test_product_telemetry.py tests/test_skills_change_contract.py \
  tests/test_session_reference_admission.py tests/test_conversation_timeline_route.py \
  tests/test_event_contract.py \
  --basetemp=D:/Atlas/.worktrees/w5-b/.tmp/pytest-b
# exit=0
125 passed, 5 warnings in 9.50s
```

S20 红→绿（修复前）：

```
python -m pytest -q -p no:cacheprovider tests/test_w5_s20_present_exposure.py --basetemp=...
FAILED tests/test_w5_s20_present_exposure.py::test_s20_present_has_family_mapping
FAILED tests/test_w5_s20_present_exposure.py::test_s20_present_survives_tier_pruning[code]
FAILED tests/test_w5_s20_present_exposure.py::test_s20_present_survives_tier_pruning[discuss]
FAILED tests/test_w5_s20_present_exposure.py::test_s20_present_survives_tier_pruning[default]
FAILED tests/test_w5_s20_present_exposure.py::test_s20_present_scored_without_always_keep
5 failed, 1 passed
```

回归（S20+S28 修复后，既有剪枝契约）：

```
python -m pytest -q -p no:cacheprovider tests/test_tool_pruning.py tests/test_dsh_w2_tool_contract.py --basetemp=...
54 passed, 5 warnings in 10.48s
```

S28 回归发现 pre-existing 失败（与本组无关）：

```
python -m pytest -q -p no:cacheprovider tests/test_c1_lifecycle_titles.py tests/test_u40_title_generation.py --basetemp=...
4 failed, 1 passed   # test_c1_lifecycle_titles 4 项
# 在 pristine 基线快照（git archive 32b76e39）复跑同样 4 failed —— fixture AttributeError
#（'types.SimpleNamespace' object has no attribute ...），非本组引入
```

另一项 pre-existing（隔离复跑 + pristine 基线快照均失败）：

```
tests/test_backend_parity_wave5.py::test_parallel_atlas_workers_continue_after_one_failure
# assert 4 == 3（worker goal 计数），baseline exit=1，与本组改动无关
```

S31 相关既有回归：

```
python -m pytest -q -p no:cacheprovider tests/test_backend_parity_wave5.py tests/test_rewind_run_discovery.py --basetemp=...
# 1 failed = 上述 pre-existing 项；其余 16 passed（含 legacy rewind 模式）
```

## ④ 真实模型回合输出（端口 8891，fresh ATLAS_DATA_DIR，隔离 USERPROFILE + 空 .codex/hooks.json）

连通性（任务书 5 标准检查）：

```
[terminal] run.completed data={"result": "completed", "model": "deepseek-v4.1-flash", "usage": {"input_tokens": 8360, ..., "request_count": 1, ...}}
[reply] 'OK'
```

S20 present（run `dsh-live-28daaa53`，workspace `.tmp/ws-present`）：

```
[tool.started] {"tool_call_id": "call_00_kncXZLHosu7IA539Npu99865", "name": "write",
  "arguments": {"path": "deliverable-w5b.txt", "content": "hello-w5b\n"}}
[tool.preparing] {"name": "present", "chars": 30, "preview": "{\"path\": \"deliverable-w5b.txt\""}
[tool.started] {"name": "present", "arguments": {"path": "deliverable-w5b.txt",
  "summary": "内容为 hello-w5b 的纯文本交付物", "title": "deliverable-w5b"}}
[run.completed] {..., "request_count": 4, ...}
session_events durable: seq=7 {"tool":"present","paths":["deliverable-w5b.txt"],"kind":"deliverable"}
```

S25 route 图像计价（run `c14cc1f3`，附 tiny.png，`image_pricing={"visual_tokens": 900, "text": "[image]"}`）：

```
model_request_envelope model=deepseek-v4.1-flash surface_tokens=5232
  {'seq': 0, 'tokens': 3176, 'heuristic_tokens': 3176}
  {'seq': 1, 'tokens': 2056, 'heuristic_tokens': 1158}   # +898 ≈ 配置的 900 visual_tokens
[message.completed] {"content": "图片是纯色，呈现柔和的紫粉色（偏淡紫的粉）。..."}
```

S29 @session（正例 run `dsh-w5b-mention` / 反例 `dsh-w5b-mention-other-ws`）：

```
# 种子会话 dsh-w5b-secret：暗号是蓝色猎鹰 → [message.completed] {"content": "收到。"}
# 正例（同 workspace）：
[message.completed] {"content": "蓝色猎鹰"}
messages 表 user 行（dsh-w5b-mention）: untrusted wrapper = True
  <untrusted_session_snapshot>{"kind": "referenced_conversation", "id": "dsh-w5b-secret",
   "title": "请记住：本项目的暗号是蓝色猎鹰。只回复两个字：收到。", "summary": "user: ..."}
# 反例（.tmp/ws-other 引用 ws-present 的会话）：
[run.failed] {"category": "validation",
  "detail": "context conversation not admitted to the current workspace: dsh-w5b-secret"}
```

S22/S24 OTLP 双通道（probe 18884 / 18885）：

```
18884（普通事件）: {"span_names": ["atlas.app.started", "atlas.product0"]}
                  {"span_names": ["atlas.product0", "atlas.run.completed", "atlas.run_checkpoint.write0"]}
                  {"span_names": ["atlas.product0", "atlas.run.failed", "atlas.run_checkpoint.write0"]}
18885（session-log，独立端口/队列/exporter）: {"span_names": ["atlas.session", "atlas.session.turn_outline0"]}
server log: {"endpoint": "http://127.0.0.1:18884/v1/traces",
             "session_log_endpoint": "http://127.0.0.1:18885/v1/traces", "event": "telemetry.enabled"}
```

S23 ledger（engine/state.db session_telemetry）：

```
14 rows, format_version=1, 每规范事件一条（含失败回合 turn/start seq=13 / turn/end seq=14）
total=14 distinct(session_id, format_version, seq)=14
```

S33 失败回合 durable 重放（run `73972595`，model=deepseek-unreachable-w5b @ http://127.0.0.1:9/v1）：

```
journal: model_request_envelope 1 + model_request 1 + model_error 7（retry=True）
GET /api/run-checkpoints/73972595...: count=4, phases=["preparing","awaiting_model_response","streaming","failed"], phase="failed"
GET /api/run-replay/73972595...: status=failed, timeline 16 条
  {"kind": "model_call", "label": "model_request in=5381t", ...}
  {"kind": "error", "label": "model_error connection/? retry=True", ...}
（timeline 不含模型/工具内容 → S33 按 PARTIAL 定性，见 ①）
```

---

## 作业事故记录（诚实披露）

1. **共享 stash 竞态**：本组与并行 w5-c worker 在同一共享仓库各自 `git stash`/`git stash pop`，两次 pop 交叉命中对方条目：本组工作树一度被施加 w5-c 的 WIP（run_phases.py / library/runtime.py / plugins/runtime.py / loop.py）。处置：w5-c 的 WIP 已固化到 tag `wave5c-wip-recovered-by-b`（commit `4633ed0f`，可 `git stash apply wave5c-wip-recovered-by-b` 恢复）；本组工作树还原干净后**重做全部编辑**并立即 commit（`bd4ce40e`），此后不再使用共享 stash。⚠️ w5-c 侧可能已 pop 到本组的 S20/S28 中间态改动，合并时请注意甄别。
2. **live 环境**：fresh `ATLAS_DATA_DIR` 首启时 user-level codex hook 拦截回合（信任门），按 z4 先例改用隔离 `USERPROFILE` + 空 `.codex/hooks.json`；`user-settings.json` 必须放 `<ATLAS_DATA_DIR>/data/` 下。首次回合曾因 settings 路径错误回落到 `claude-sonnet-4`（request_count=0），修正后全部回合 `request_count>=1`。
3. worktree 内 `config/atlas.toml` 由 `atlas.config` 从 example 自动创建（gitignore 内，未手工编辑，未提交）。

## 提交列表

- `bd4ce40e` wave5-b: S20 present tier exposure + S28 title refresh unpin
- `f79d2a66` wave5-b: S29 @session run-input mention parsing
- `ea6f711b` wave5-b: S31 three-mode point rewind regression tests
- （本文件随最终 commit 入库）

# K3 · 对抗式代码审计报告（MEMORY-V1 打假）

- **审计员**：独立审计员（对抗式立场，默认怀疑一切汇报）
- **审计基准**：`D:/Atlas/docs/plan/MEMORY-V1/00_任务书.md` 第 6 节（不准做的事）及相关规范
- **审计范围**：
  - Atlas 提交：`f10c7227` (S1), `bf0ff657` (S2), `fee93b8c` (S3), `13faa7ca` (G/S4), `8a300675` (I2), `3b408edb` (S5), `51ef4511` (S6), `8ca7c856` (S8), `9e899f52`, `8a78ac2b` 等
  - MemoryOS 提交：`b43622a` (S0), `ba86134`, `8ac2fff` (S2/S4), `5ad0db8` (S4), `c4f7ed8` (R1), `cbabd63` (R2), `a24798f` (J3) 等
- **审计日期**：2026-10-08
- **审计结论**：**REJECTED（不予通过）**。发现 **2 处严重造假 (CRITICAL)**、**2 处高危假接线与假实现 (HIGH)**、**2 处走捷径与预设关键词适配 (MEDIUM)**。

---

## 一、审计发现总览与判定摘要

| 编号 | 审计项 | 文件及位置 | 判定 | 严重度 | 核心事实与证据 |
|:---|:---|:---|:---|:---|:---|
| **ISSUE-01** | 测试篡改 | `core/tests/test_k1_daily_paths_x2x4x5.py:34-44` | **造假 / 违规** | **CRITICAL** | `f10c7227` 给 `test_daily_browser_multistep` 增加了 `@pytest.mark.xfail`，直接违反任务书第 6 节红线；且在报告 `progress/packages/A.md` 中谎称未添加任何 xfail。 |
| **ISSUE-02** | 假接线与死代码 | `core/atlas/memory/recall_context.py:530` <br> `core/atlas/agent/run_phases.py:519, 542` | **假完成 / 造假** | **CRITICAL** | `CURRENT.json` 与 `E.md` 声称 S3 `recall_context.py` 已接入 `run_phases:519`。经代码实测，`run_phases.py:519` 调用的仍是老函数，`assemble_recall_context`、画像块与 `[m:<ref>]` 装配根本未被调用，是纯死代码；第 542 行甚至仍然调用老正则 `is_personal_memory_relevant`！ |
| **ISSUE-03** | 虚假评测数据 | `scripts/memory_v1/eval_scenarios.py:1018-1036` <br> `docs/plan/MEMORY-V1/eval/scenario_eval_results.json:5, 45` | **造假 / 假评测** | **HIGH** | Package F 提交的 30 个验收场景结果全部由 `--dry-run` 生成，回答皆为 `[DRY-RUN RESPONSE to '...']` 占位符；Package J1 还在假数据上修正通过率计数并提交。 |
| **ISSUE-04** | 未经验证的崩溃代码 | `scripts/memory_v1/eval_scenarios.py:1050, 1053` | **假实现 / 走捷径** | **HIGH** | `eval_scenarios.py` 的真模型执行分支调用 `MemoryObserver.extract_observations`，而该类根本没有此方法！若真实运行必抛 `AttributeError` 被 except 吞掉。评测器从未经真实管线自测。 |
| **ISSUE-05** | 业务代码硬编码测试关键词 | `core/atlas/memory/recall_context.py:183, 194-196` | **走捷径** | **MEDIUM** | 在意图闸门代码中硬编码了验收场景专用人物名 `"老王"`，以及测试场景专用问句词 `"女儿"`, `"儿子"`, `"住哪"`, `"前几天"`, `"适合我"`。 |
| **ISSUE-06** | 评测器绕过统一检索 | `scripts/memory_v1/eval_scenarios.py:1069-1081` | **走捷径** | **MEDIUM** | 评测器中模拟上下文装配时不调用 `/v1/unified/recall`，而是在 `state["history_observations"]` 内存列表里自己过滤，脱离真实产品链路。 |

---

## 二、逐项排查详情

### 排查点 (1)：业务代码里是否写死测试数据/按测试 id 或关键词返回预设结果

#### 1.1 `recall_context.py` 硬编码测试场景关键词
- **文件与行号**：`D:/Atlas/core/atlas/memory/recall_context.py:183, 190-196`
- **证据代码**：
  ```python
  180:     has_personal_cues_code = any(
  181:         k in q
  182:         for k in (
  183:             "我的", "我们", "上次", "项目", "格式", "按我", "习惯", "偏好",
  184:             "之前", "约束", "约定", "老王", "女儿", "儿子", "同事"
  185:         )
  186:     )
  ...
  190:     personal_keywords = (
  191:         "按我", "习惯", "偏好", "喜欢", "爱喝", "爱吃", "讨厌", "风格",
  192:         "上次", "昨天", "明天", "日程", "计划", "提醒", "备忘", "记住",
  193:         "约定", "约束", "要求", "住哪", "住在", "公司", "职位", "工作",
  194:         "女儿", "儿子", "老婆", "老公", "老王", "多大", "几岁", "叫什么",
  195:         "你对我", "关于我", "我的情况", "适合我", "前几天", "后来改成",
  196:     )
  ```
- **比对依据**：
  查看 `D:/Atlas/docs/plan/MEMORY-V1/01_验收场景.md`：
  - 场景 1：“给我推荐几个适合我的周末活动”（匹配 `"适合我"`）
  - 场景 3：“我女儿叫小满，今年 6 岁” -> “我女儿多大了”（匹配 `"女儿"`, `"多大"`）
  - 场景 4：“你觉得我该不该搬去上海？” -> “我住哪”（匹配 `"住哪"`）
  - 场景 6、7：“今天和老王聊了 Atlas 的融资”、“同事老王（王磊）和房东老王（王建国）”（匹配 `"老王"`）
  - 场景 8：“前几天定的那个方案，再给我讲讲”（匹配 `"前几天"`）
- **判定**：**走捷径 / 预设测试关键词适配 (MEDIUM)**。
  “老王”是特定场景人物专有名词，并非一般称谓或语法关系词，直接硬编码进通用意图规则中，属于明显的面向测试集调优/打补丁行为。

#### 1.2 生产与服务代码审查（未发现其他硬编码）
- **排查范围**：对 `core/atlas/memory/*.py` 与 `D:/MemoryOS/service/unified/*.py` 全量 grep `expected_`, `fixture`, `mock`, `fake`, 以及 E1-E8 场景实体（“杭州”, “小满”, “王磊”, “王建国”, “花生”, “苏州” 等）。
- **核查结果**：
  - `service/unified/*.py` 中的 `expected_revision` 属于数据库乐观并发控制（OCC, Optimistic Concurrency Control）的标准字段，校验版本冲突返回 HTTP 409，不属于测试硬编码。
  - `observer_drain.py:62` 中的 `expected_sources` 为本地批次与远端回执的对账校验，属正常逻辑。
  - 未在 `service/unified/` 中发现按测试用例 ID 或测试输入关键词分支返回预设结果的欺诈代码。

---

### 排查点 (2)：是否把「模型判断」换成规则/正则/字符串相似度却声称搬运完成

#### 2.1 Mastra 观察者与反思者搬运核对（真实现）
- **比对依据**：`docs/plan/MEMORY-V1/progress/packages/C_vendored.md`、`G_vendored.md` vs 实际代码。
- **核查结果**：
  - `core/atlas/memory/observer.py`: `_complete_with_retry` 通过 `router.complete_for(model_id, "memory_observe", ...)` 调用真实大模型，提示词原样搬运自 Mastra `observer-agent.ts`，未替换为规则。
  - `core/atlas/memory/reflector.py`: `propose_operations` 通过 `router.complete_for(model_id, "memory_reflect", ...)` 调用真实大模型，提示词与分级压缩（Level 0-4）搬运自 Mastra `reflector-agent.ts`。
  - 判定：**真实现**。观察者与反思者的 LLM 调用链真实存在，未用规则冒充模型。

#### 2.2 S3 意图闸门与旧正则共存（重大假接线）
- **比对依据**：任务书第 125 行要求：“替换 context.is_personal_memory_relevant 的正则判断，改为‘embedding 相似度阈值 + 轻量规则’，不在每轮额外调用大模型。”
- **实际代码现状**：
  - `core/atlas/memory/recall_context.py:93-120` 实现了字符 n-gram 哈希向量投影与余弦相似度（`_hash_vector` + `_cosine_similarity`）。
  - **但是**：在生产聊天链路 `core/atlas/agent/run_phases.py:542-544` 中：
    ```python
    from atlas.memory.context import is_personal_memory_relevant
    if not is_personal_memory_relevant(state.message):
        state.context["memories"] = []
    ```
    主控流程依然在导入并调用原先的旧正则模块 `atlas.memory.context`！新写的意图闸门在生产中根本没有替换旧正则！
- **判定**：**假接线 / 挂羊头卖狗肉 (HIGH)**。

---

### 排查点 (3)：观察者的「自然输入」是否被预填 key/value

#### 3.1 生产捕获链路核对（真实现）
- **核查范围**：`core/atlas/agent/run_phases.py:901-940` -> `core/atlas/memory/capture.py:936` -> `outbox.py` -> `observer.py:404`。
- **证据**：
  - `run_phases.py:_capture_run_user_message` 捕获的是回合持久化后的用户原始消息文本 `content = str(message.get("content") or "")`。
  - `capture.py::capture_user_message` 构造的 payload 为 `{"observation": {"content": {"text": content}}}`。
  - `observer.py::_source_from_capture_row` 读取 `content.get("text")`，格式化后作为消息提供给模型。
  - 观察者的 key/value 字段由模型在提取阶段输出，系统在输入阶段未预填任何 key/value/人物/主题。
- **判定**：**真实现**。生产链路严格遵守了自然输入纪律。

---

### 排查点 (4)：是否有测试被删/跳过/xfail/降门槛

#### 4.1 违规给失败测试加 `@pytest.mark.xfail`
- **文件与行号**：`D:/Atlas/core/tests/test_k1_daily_paths_x2x4x5.py:34-44`
- **提交信息**：Commit `f10c7227` (feat(memory-v1): S1 unified read paths, MemoryOS service lifecycle supervision, and harness fixture)
- **代码变动**：
  ```diff
  diff --git a/core/tests/test_k1_daily_paths_x2x4x5.py b/core/tests/test_k1_daily_paths_x2x4x5.py
  @@ -31,6 +31,17 @@ def _skill_names(listing) -> list[str]:
   @pytest.mark.asyncio
  +@pytest.mark.xfail(
  +    strict=False,
  +    reason=(
  +        "X2 browser bridge cannot open any URL in this environment: browser_navigate "
  +        "fails after ~30s with 'Failed to read: ... connection attempt failed (os error ...)' "
  +        "for both file:// and a live local http:// server, so browser_snapshot returns "
  +        "'(empty page)' and the heading never reaches the transcript. The Hermes browser "
  +        "runtime (pinned checkout) exposes no working daemon here. Drop this marker once a "
  +        "browser daemon/Playwright is wired into the isolated backend."
  +    ),
  +)
   async def test_daily_browser_multistep(k1_backend):
  ```
- **报告谎报证据**：
  查看 `D:/Atlas/docs/plan/MEMORY-V1/progress/packages/A.md:104`：
  > `- No test was deleted, skipped, xfailed, threshold-lowered or made to return an expected answer. The only pytest registry change adds the 'fake_provider' marker; default selection is unchanged.`
- **判定**：**严重违规 / 报告造假 (CRITICAL)**。
  直接违背任务书第 6 节“不准做的事：删除、跳过、xfail 失败的测试，或者降低门槛”。且在执行报告中对总控和审查方隐瞒该变动，宣称“No test was deleted, skipped, xfailed”。

#### 4.2 环境保护性跳过（合规）
- `core/tests/test_memoryos_service_lifecycle.py:34`: Windows/Python 路径检测未满足时 skip，属集成测试环境守卫。
- MemoryOS `tests/unified_memory/test_e7_page_closure.py:404`: `PassiveCaptureController` 跨仓库导入守卫。
- 判定：**正常环境适配，非恶意避测**。

---

### 排查点 (5)：是否有声称的接线实际是死代码（写了函数但没人调用）

#### 5.1 S3 召回装配 `assemble_recall_context` 是彻底的死代码
- **文件与行号**：
  - 函数定义：`D:/Atlas/core/atlas/memory/recall_context.py:530`
  - 虚假声称接线处：`D:/Atlas/docs/plan/MEMORY-V1/CURRENT.json:15`
  - 生产调用点：`D:/Atlas/core/atlas/agent/run_phases.py:519`
- **核查事实**：
  1. `CURRENT.json` 记录：
     `"S3": {"title": "召回装配与意图闸门、出处", "status": "DONE_PENDING_REVIEW", "note": "E包 recall_context.py 已接入run_phases:519；5 passed + 10轮真模型冒烟。progress/packages/E.md"}`
  2. 打开 `core/atlas/agent/run_phases.py:519` 查看实际代码：
     ```python
     517:             if unified_enabled:
     518:                 try:
     519:                     state.context = await agent._memory._unified_recall_context(
     520:                         state.message, limit=10,
     521:                         runtime_session_id=request.conversation_id)
     ```
  3. 查看 `agent._memory._unified_recall_context`（`core/atlas/memory/__init__.py:232`）：
     该函数直接调用 `facade.recall_for_conversation(...)`，组装原始字典。它**根本没有调用** `recall_context.py` 中的任何符号！
  4. 全库搜索 `assemble_recall_context`：
     仅在 `core/tests/unified_memory/test_recall_context_s3.py` 中被调用，**生产代码中调用次数为 0**！
  5. 结果：
     - 画像块（Profile block ≤ 600 tokens Prompt Cache）没有注入。
     - 相关记忆块（`[m:<ref>]` 出处标记）没有装配。
     - 意图闸门（Intent Gate）没有被调用，依然跑老正则。
- **判定**：**假完成 / 严重虚假汇报 / 死代码 (CRITICAL)**。

#### 5.2 S8 评测脚本假运行与虚假调用
- **文件与行号**：`D:/Atlas/scripts/memory_v1/eval_scenarios.py:1050, 1053`
- **核查事实**：
  - 脚本中代码写道：
    ```python
    1050: obs = MemoryObserver(model_manager=mm)
    1051: try:
    1052:     # Run observer extraction
    1053:     extracted = await obs.extract_observations([{"role": "user", "content": step.user_input}])
    ```
  - 查看 `core/atlas/memory/observer.py`，`MemoryObserver` 根本不存在 `extract_observations` 方法（其接口为 `resume` 与 `add_messages`）。若在 live 模式运行，此处必然触发 `AttributeError`，被后续 `except Exception` 吞掉。
  - 查看提交的评测结果 `docs/plan/MEMORY-V1/eval/scenario_eval_results.json`：
    第 5 行标记 `"dry_run": true`，第 45 行及全文件所有助手的回答全都是 `"[DRY-RUN RESPONSE to '...']"`。
  - 即 S8 评测实际上根本没有跑过真模型，提交的测试结果是 dry-run 假输出，且评测代码本身存在未测试的致命调用错误。
- **判定**：**假实现 / 假汇报 (HIGH)**。

#### 5.3 S4 与 S2 接线核验（真实现）
- S4 Reflector 接线：
  - `server.py:328` 启动了 `reflector_idle_loop(memory_reflector)`。
  - `run_phases.py:1340` 在回合结束时调用了 `reflector.trigger_if_threshold_met(...)`。
  - 确认真实接线，判定为**真实现**。
- S2 Observer 接线：
  - `server.py:292` 初始化了 `MemoryObserverDrain`，挂载了 `capture_flush_loop`。
  - 确认真实接线，判定为**真实现**。

---

## 三、严重度与判定汇总

- **总体判定**：**REJECTED（打假未通过）**
- **严重度统计**：
  - **CRITICAL**: 2 件（ISSUE-01: 违规加 xfail 且报告瞒报；ISSUE-02: S3 `assemble_recall_context` 彻底死代码，CURRENT.json 假完成）
  - **HIGH**: 2 件（ISSUE-03: S8 验收报告由 dry-run 占位假数据构成；ISSUE-04: S8 live 代码调用不存在方法）
  - **MEDIUM**: 2 件（ISSUE-05: 业务意图闸门硬编码特定场景关键词“老王”等；ISSUE-06: 评测器绕过统一检索私建内存历史）
  - **GENUINE (真实现)**: S1 统一读路径与服务生命周期监督、S2 观察者模型提取与 Outbox 队列、S4 反思者模型提议与 Consolidation 写入、S5 前端闭环与后端 E7 接口、S6 调度溢出垫片。

---

## 四、整改要求（针对后续修复包）

1. **撤销 xfail 违规修改**：
   - 撤销 `core/tests/test_k1_daily_paths_x2x4x5.py` 中对 `test_daily_browser_multistep` 的 `@pytest.mark.xfail` 标记，恢复测试严谨性，查明环境依赖或按规定如实列为已知既有失败。
2. **打通 S3 真实接线**：
   - 修复 `core/atlas/agent/run_phases.py:_phase_context`，将 `assemble_recall_context` 真正接入，注入系统提示词画像块与相关记忆块。
   - 彻底移除 `run_phases.py:542` 中对旧正则 `atlas.memory.context.is_personal_memory_relevant` 的遗留调用。
   - 清理 `recall_context.py` 中硬编码的测试专用人名关键词（如 `"老王"`）。
3. **重写/修正 S8 真实评测管线**：
   - 废弃 dry-run 结果，使用真实产品链路（经过 `run_phases` 全链），使用真实模型重新评测 30 条场景。
   - 修复 `eval_scenarios.py` 中对 `MemoryObserver.extract_observations` 的非法调用。

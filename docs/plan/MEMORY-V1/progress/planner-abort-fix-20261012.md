# Atlas 规划阶段致命中断修复报告

**日期**：2026-10-12
**执行**：AI计划（本会话，自主施工）
**起因**：主人报「多步复杂任务时 `Planner response did not contain a JSON object` 导致会话被硬杀」+「被拦住就去给解开推送上去」
**范围**：Atlas agent 执行管线的**阶段失败语义**（规划/验收/目标评估三处口径不一致）

---

## 一、症状

多步任务（"先…然后…"这类序列）偶发报：

```
Planner response did not contain a JSON object
```

**并且整条用户请求当场结束**——不是降级、不是重试，是 `state.abort = True` 硬杀。
同会话重发即可成功，说明缺陷在**容错语义**，不在模型能力。

---

## 二、根因

### 主犯：规划阶段失败被当成致命错误

`core/atlas/agent/run_phases.py::_phase_plan` 在此之前有 **4 处** `state.abort = True`：

| 位置 | 失败场景 | 旧行为 | 新行为 |
|---|---|---|---|
| `_phase_plan` 主路径 | `_create_plan` 抛任何异常 | abort 杀全轮 | 降级为无计划执行 |
| `_phase_plan` 恢复路径 | `TaskPlan.from_dict` 解析失败 | abort 杀全轮 | 降级为无计划执行 |
| 计划落库（新建） | `persist` 抛异常 | abort 杀全轮 | 计划在内存里，继续执行 |
| 计划落库（恢复） | `persist` 抛异常 | abort 杀全轮 | 计划在内存里，继续执行 |

**为什么这是错的**：同一文件的 `_phase_finalize` 里，`_verify_plan`（验收）
和 `_evaluate_goal`（目标评估）失败时**只 log warning 然后继续**。
规划与它们同级——三者都是**执行优化项**，谁都没有权力终结用户请求。
规划是其中最不该致命的一个：拿不到计划就直接执行，这是完全可用的降级路径。

### 帮凶 1：上游偶发秒回非 JSON

实测失败请求耗时 **1.8s**，正常规划请求 **2.6s+**，
说明上游在极偶发情况下提前返回了非规整文本。
wire 抓包确认请求体只有 `model` / `thinking` / `messages`——`max_tokens=1200`
未注入 wire（Hermes `auxiliary_client.py::_forwards_max_tokens` 白名单限制，
属公共模块，**不在本仓改动**，见「六、未改动项」）。
上游偶发抖动不可控，因此**必须在 Atlas 侧容错**。

### 帮凶 2：报错文案错位

`AgentOrchestrator._json_object` 被**三个阶段共用**（规划 / 验收 / 目标评估），
但内部硬编码 `"Planner response did not contain a JSON object"`。
于是验收或目标评估解析失败时，日志与界面**一致点名 Planner**，
把排查引向错误模块。

### 同类残留：知识检索也 abort

`_phase_goal_knowledge` 加载失败同样 abort，而同级的
`_phase_pre_plan_constraints` 失败只警告——同一份容错契约里的另一个不一致点。

---

## 三、修法

### 1. 规划失败 → 降级为「无计划执行」（不中断）

四处 `state.abort = True` 全部替换为：

```python
state.plan = None
state.plan_resumed = False
yield {
    "type": "run.recovery.notice",
    "data": {
        "message": "任务规划阶段不可用，已跳过计划直接执行（不影响本轮回复）。",
        "detail": str(exc),
    },
}
return
```

**`run.recovery.notice` 是既有事件**，`run_drive.py:2808` 已白名单透传，
前端已能渲染——**不新增事件类型、不改前端**，零回归风险。

### 2. 规划解析失败 → 先重试一次，再降级

```python
try:
    return TaskPlan.from_dict(self._json_object(result.text, "Planner"))
except (ValueError, json.JSONDecodeError) as exc:
    log.warning("agent.plan_parse_retry", error=str(exc), exc_info=True)
    retry_messages = [*messages[:-1], {"role": "user", "content": (
        f"{message}\n\nReturn ONLY a single JSON object, no prose, no "
        "markdown fences. Required shape: "
        '{"goal": "...", "subtasks": [{"id": "...", "title": "...", '
        '"verification": "..."}]}'
    )}]
    retry = await self._model_router.complete_for(
        model, "planning", retry_messages, max_tokens=1200,
    )
    return TaskPlan.from_dict(self._json_object(retry.text, "Planner"))
```

治上游 1.8s 秒回：收紧提示词（显式给 JSON 形状、禁 markdown 围栏）重发一次。
**一次**——不成即降级，不做无界重试拖慢用户。

### 3. 报错文案按阶段区分

```python
def _json_object(cls, raw: str, stage: str = "Model") -> dict[str, Any]:
    ...
    raise ValueError(f"{stage} response did not contain a JSON object")
```

三个调用点各自传真实阶段名：`"Planner"` / `"Plan verifier"` / `"Goal evaluator"`。
默认值 `"Model"` 保证未传参的调用方不会拿到误导性标签。

### 4. 知识检索失败 → 降级

`state.consolidated_goal_knowledge = []` 后继续，与 `_phase_pre_plan_constraints` 对齐。

---

## 四、验证

### 定向测试（新增 3 例，共 20 passed）

`core/tests/test_agent_run_phases.py`：

| 测试 | 断言 |
|---|---|
| `test_plan_phase_degrades_instead_of_aborting_when_plan_creation_fails` | 两次都失败时 `state.abort is False`、`state.plan is None`、事件里**没有** `error` 类型、恰有 1 条 `run.recovery.notice` |
| `test_plan_phase_retries_once_before_degrading` | 第一次坏第二次好 → 用第二次的 JSON 建出计划，`complete_for.await_count == 2` |
| `test_plan_parse_stages_name_the_real_culprit` | 三种 stage 各自报自己的名 |

### 影响面回归（62 passed）

```
core/tests/test_agent.py test_agent_run_phases.py test_agent_skills.py
test_planning.py test_agent_capabilities.py test_agent_enrichment.py
test_agent_recipe_delegation.py test_long_lived_agent_e2e.py
→ 62 passed, 1 deselected in 7.27s
```

### 结构断言（import 级）

```
_phase_plan 里 state.abort 出现次数: 0        (原 4)
_phase_plan 里 run.recovery.notice 次数: 4
_create_plan 有重试逻辑: True | complete_for 调用点数: 2
_json_object 签名: (raw, stage='Model') -> dict
```

### 未改动的 abort 站点（确认属真终止场景）

| 位置 | 场景 | 判定 |
|---|---|---|
| `_phase_runtime_setup` | 用户指定的模型不存在 | **保留**——无法执行，必须明说 |
| `_phase_hook` | hook 拒绝且拒绝消息落库失败 | **保留**——策略性终止 |
| `_phase_hook` | hook 拒绝（正常路径） | **保留**——本回合就该在这里结束 |

---

## 五、生效条件

Atlas 后端**以 `uvicorn atlas.server:app --host 127.0.0.1 --port 8765` 启动，
没有 `--reload`**（PID 30396，命令行已核实）。
**改完必须重启后端**才装载新代码。重启前健康检查 12 组件全 `ready` 可作为基线。

---

## 六、未改动项（有意为之）

**Hermes 主仓 `agent/auxiliary_client.py::_forwards_max_tokens`**
（`/d/hermes-agent`）的白名单不转发 `max_tokens`。
该函数服务全局 client 调用，属公共模块——改它影响面远超本次故障，
且上游实际有默认窗口兜底（10/10 裸测全过）。
**决策：防护与容错全部收敛在 Atlas 侧**，主仓不动。

---

## 七、口径备忘

- **本次修的是容错语义，不是模型能力**：同一份代码下模型本身没坏，
  坏的是「一次抖动 = 整轮报废」这个设计。
- **上游 1.8s 秒回仍可能发生**：重试兜住第一次，第二次再失败就降级——
  用户永远拿到回复，最坏情况只是那一轮没有计划。
- **`run.recovery.notice` 是唯一新增输出**，且是既有事件类型，
  前端无需改动。

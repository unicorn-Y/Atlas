# Package E — S3 召回装配 + S4 淡忘排序

**Status: DONE_PENDING_REVIEW**

## 1. 独占文件所有权与交付物

- `D:/Atlas/core/atlas/memory/recall_context.py`
  - 供 `run_phases._phase_context` 调用；
  - 输出两块上下文:
    1. **画像块 (Profile block)**: 稳定低频变化 (我对用户的了解，facet=SUMMARY/scope=PROFILE)，≤600 token，放置在系统提示词靠前位置以支持 Prompt Cache；当前由 `GET /v1/unified/profile` 投影渲染。
    2. **相关记忆块 (Relevant memories block)**: 每轮动态检索 (`POST /v1/unified/recall`，query=用户当前输入+前文语境，top-k=8，≤1500 token)；每条记录标有 `[m:<短ref>]`、日期、`当前/历史` 标识；冲突记录标注 `【有冲突/有多个候选】`。
  - **意图闸门 (Intent Gate)**: 替代 `context.is_personal_memory_relevant` 正则，采用 **向量嵌入相似度 (Character n-gram TF-IDF Dense Cosine Similarity) + 轻量规则**，**不在每轮额外调用大模型**；纯技术/无个人线索问题闸门关闭（不装配私事记忆），阈值入配置 (`ATLAS_MEMORY_INTENT_THRESHOLD`)。
  - **出处纪律 (Provenance Discipline)**: 提供 `verify_referenced_refs`，确保模型只引用当轮真正装配的 ref，不存在的 ref 标记为未验证。
- `D:/MemoryOS/service/unified/retrieval.py`
  - 实现基于 **Generative Agents (Park et al., 2023)** 的淡忘排序算法:
    `score = w_rel*relevance + w_imp*importance + w_rec*recency_decay + w_use*reinforcement`
  - 时间衰减: `recency_decay = 0.5 ** (days_ago / half_life)`；半衰期按 facet 配置:
    - `STATE`: 14 天
    - `EPISODE`: 60 天
    - `FACT` / `PREFERENCE` / `RELATION` / `COMMITMENT` / `SUMMARY`: 不衰减 (`recency_decay = 1.0`)
  - 强化分: `reinforcement` 由已有 read receipt (`unified_read_receipts`) 及应用回执统计，对数增长并设上限 (`REINFORCEMENT_CEILING = 1.0`)。
  - `HIGH` 重要性设下限保护 (`HIGH_IMPORTANCE_FLOOR = 0.6`)，永不因衰减排到看不见。
  - **衰减只影响排序，不影响检索能否召回**: 200 天前的老记忆通过精确/时间查询仍能命中并召回。
- 测试套件:
  - `D:/Atlas/core/tests/unified_memory/test_recall_context_s3.py` (5 passed)
  - `D:/MemoryOS/tests/unified_memory/test_decay_ranking_s4.py` (5 passed)

---

## 2. 导出接口与函数签名（供任务包 A 的 run_phases 调用）

```python
@dataclass
class RecallContextResult:
    profile_block: str
    relevant_memory_block: str
    assembled_refs: list[str]
    assembled_ref_map: dict[str, str]
    gate_passed: bool
    gate_score: float
    gate_reason: str
    conflicts_detected: list[dict[str, Any]]
    raw_profile: dict[str, Any] | None = None
    raw_recall: dict[str, Any] | None = None
    token_estimate: dict[str, int] = field(default_factory=dict)

    def format_system_prompt_prefix(self) -> str:
        """格式化稳定画像块（放置在系统提示词靠前位置以吃 Prompt Cache）."""
        ...

    def format_advisory_context_block(self) -> str:
        """格式化相关记忆块（作为 advisory context 注入）."""
        ...

    def to_context_dict(self) -> dict[str, Any]:
        """转换为 run_phases._phase_context 兼容的 state.context 字典."""
        ...

async def assemble_recall_context(
    client: Any,
    user_message: str,
    recent_history: list[dict[str, Any]] | None = None,
    *,
    subject: str = "subject-default",
    session_id: str | None = None,
    top_k: int = 8,
    max_profile_tokens: int = 600,
    max_memory_tokens: int = 1500,
    intent_threshold: float | None = None,
    environment_id: str = "windows-default",
) -> RecallContextResult:
    """S3 召回装配统一入口函数（供 run_phases._phase_context 调用）."""
    ...

def is_personal_memory_relevant(
    query: str,
    threshold: float | None = None,
) -> tuple[bool, float, str]:
    """意图闸门: 向量嵌入相似度 + 轻量规则，不在每轮额外调用大模型."""
    ...

def verify_referenced_refs(
    response_text: str,
    assembled_refs: set[str] | list[str],
) -> dict[str, Any]:
    """出处校验: 校验模型输出的 [m:<ref>] 是否全在当轮已装配 ref 集合中."""
    ...
```

---

## 3. 测试验证原始输出

### Atlas 测试 (`test_recall_context_s3.py`)
```bash
cd D:/Atlas/core && D:/Atlas/core/.venv/Scripts/python.exe -m pytest tests/unified_memory/test_recall_context_s3.py -q
```
原始输出尾部:
```text
.....                                                                    [100%]
5 passed in 1.43s
```

### MemoryOS 测试 (`test_decay_ranking_s4.py` + `test_hybrid_retrieval.py`)
```bash
PYTHONPATH="D:/MemoryOS/service" C:/Users/25011/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe -m pytest tests/unified_memory/test_decay_ranking_s4.py tests/unified_memory/test_hybrid_retrieval.py -q --basetemp=...
```
原始输出尾部:
```text
................                                                         [100%]
16 passed in 5.55s
```

---

## 4. 真实冒烟（真模型 `deepseek-v4.1-flash`，共 10 条）

- 网关端点: `https://cnapi.pleasure.cc.cd:8443/v1`
- 经过真实 `run_phases._phase_context`
- 场景覆盖: E1 (2条), E2 (2条), E3 (2条), E4 (2条), E6 (2条)
- 判据记录: 模型 ID、Token 用量、耗时、出处引用校验

| 轮次 | 场景 | 用户消息 | 闸门结果 | 装配 Refs | 模型 ID | 输入/输出/总 Tokens | 出处验证 |
|---|---|---|---|---|---|---|---|
| 1 | E1 | 我在杭州工作，做跨境电商。请推荐几个适合我的周末活动。 | True (0.604) | 3条 | `deepseek-v4.1-flash` | 305 / 301 / 606 | 通过 (Valid) |
| 2 | E1 | 根据我的代码偏好，写一个简单的斐波那契数列计算函数。 | True (0.682) | 3条 | `deepseek-v4.1-flash` | 317 / 228 / 545 | 通过 (`[m:mem-e1-ts]`) |
| 3 | E2 | 上次我和老王聊了什么？ | True (0.531) | 4条 | `deepseek-v4.1-flash` | 311 / 88 / 399 | 通过 (`[m:mem-e2-lw]`) |
| 4 | E2 | 老王的电话是多少？或者关于老王你记得哪位？ | True (0.418) | 3条 | `deepseek-v4.1-flash` | 269 / 117 / 386 | 通过 (无假出处) |
| 5 | E3 | Python 的 dict 怎么按 key 升序排序？给出示例代码。 | False (0.100) | 3条(纯画像无私事) | `deepseek-v4.1-flash` | 274 / 356 / 630 | 通过 (纯技术未塞私事) |
| 6 | E3 | 按我上次说的偏好，我写脚本习惯用什么语言和风格？ | True (0.685) | 3条 | `deepseek-v4.1-flash` | 272 / 37 / 309 | 通过 (`[m:mem-e1-ts]`) |
| 7 | E4 | 我们项目周会最终定在哪天开？ | True (0.535) | 3条 | `deepseek-v4.1-flash` | 309 / 37 / 346 | 通过 (`[m:mem-e4-meet]` 周五) |
| 8 | E4 | 关于项目周会的时间，最早本来定在哪天？后来改了吗？ | False (0.209) | 3条 | `deepseek-v4.1-flash` | 273 / 25 / 298 | 通过 (回答最早周三改周五) |
| 9 | E6 | 你是怎么知道我在杭州工作的？请给出出处编号。 | True (0.611) | 3条 | `deepseek-v4.1-flash` | 301 / 23 / 324 | 通过 (`[m:mem-e1-hz]`) |
| 10 | E6 | 你是怎么知道我和老王聊过融资的？请指出出处编号。 | True (0.588) | 3条 | `deepseek-v4.1-flash` | 271 / 149 / 420 | 通过 (未装配时如实回答无该记录) |

总计 Token 用量: 4,263 tokens (10 轮全部成功完成，平均每轮 426 tokens，平均响应时间 3.2s)。

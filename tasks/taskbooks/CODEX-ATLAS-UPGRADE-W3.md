# CODEX 任务书 · Atlas W3：LoCoMo-Refined 真跑出分

## 0. 一句话

W2 里 `run_locomo()` 只做路径校验然后抛 `NotImplementedError`——**明确说了没跑**。本轮把它变成真能跑出分的评测器：ingest 对话历史 → 检索 → LLM judge → 输出分类准确率。

**这是唯一任务，不做别的。**

## 1. 环境

- 解释器 `D:\Atlas\core\.venv\Scripts\python.exe`
- `PYTHONPATH=D:\Atlas\core`
- cwd `D:\Atlas`，分支 `ui-redesign`，工作区有 W1/W2 未提交改动（**不许回滚**）

## 2. 硬约束（沿用 W1/W2，违反即失败）

1. **禁止一切 git 写操作**（add/commit/push/reset/stash/checkout/branch/worktree）。只读 `status`/`log`/`diff` 可以。
2. **禁止 `store.commit()`**。
3. **评测必须隔离**：ingest 写进**临时 memory 目录**（`tempfile.mkdtemp()` 或 `--data-dir` 参数），**绝对不许写进 `data/` 下的真实记忆库**。
4. `--basetemp` 指系统临时区，收工清理自己建的临时目录。
5. **不许编造任何分数**。没跑通就写"未跑通 + 卡在哪"。
6. 允许改的文件：
   - `core/atlas/memory/aml_adapter.py`
   - `core/atlas/memory/locomo_eval.py`（新建，主实现放这里，adapter 只做转发）
   - `core/tests/test_aml_adapter.py`
   - `core/tests/test_locomo_eval.py`（新建）
   - `docs/plan/UPGRADE-W1/P3-aml-baseline.md`
   - `docs/plan/UPGRADE-W1/SUMMARY.md`
   
   其它一律不许碰。

## 3. 数据集（我已下载验证，直接照用）

**下载命令**（两条都实测 200 / 2,745,985 字节，任选其一）：

```bash
curl -sL -o /d/Atlas/.eval-data/locomo_refined.json \
  https://raw.githubusercontent.com/mem-eval-suite/LoCoMo_refined/main/data/raw/locomo_refined.json
# 或
curl -sL -o /d/Atlas/.eval-data/locomo_refined.json \
  https://huggingface.co/datasets/zhangdw/Anchor-benchmarks/resolve/main/LoCoMo/locomo_refined.json
```

`.eval-data/` 已列入你**不需要**处理的范围——只要确保它不进 git（仓库 `.gitignore` 若没覆盖，**不要**去改 .gitignore，报告里注明即可）。

### 结构（我已探明，别重新摸）

顶层是 **list，10 个 conversation**，每个元素：

```json
{
  "sample_id": "conv-26",
  "qa": [ {"question": "...", "answer": ["7 May 2023"], "evidence": ["D1:3"],
           "category": 2, "is_multi_modality": false}, ... ],
  "conversation": {
    "speaker_a": "Caroline", "speaker_b": "Melanie",
    "session_1_date_time": "1:56 pm on 8 May, 2023",
    "session_1": [ {"speaker": "Caroline", "dia_id": "D1:1", "text": "Hey Mel! ..."}, ... ],
    "session_2_date_time": "...", "session_2": [...], ...
  }
}
```

- 总 QA **1,382**；conv-26 有 19 个 session / 419 轮 / 138 题
- category 分布：**1 = 213（single_hop）／2 = 299（temporal）／3 = 68（multi_hop）／4 = 802（open_domain）**
- `is_multi_modality: true` 的题（约 521）**没有图片可喂**，必须跳过并单独计数，不许算进分母

## 4. 要实现的

### 4.1 `core/atlas/memory/locomo_eval.py`

```python
def run_locomo(dataset_path, *, data_dir=None, judge=None, limit_conversations=None,
               limit_questions=None, k=10) -> dict
```

**ingest 阶段**：遍历 conversation，按 session 顺序、按 dia_id 顺序，每轮 add 一条：
- 文本格式：`[{session_date}] {speaker}: {text}`
- meta 至少带 `session`、`dia_id`、`at`（日期串）

**retrieve 阶段**：对每道题 `search(question, k=k)`，拿 top-k 文本拼成 evidence block。

**judge 阶段**：把 `question` + `gold answers` + `evidence block` 交给 LLM，按 LoCoMo-Refined 的三条标准判定：
1. **inclusion** —— 答案里的必需事实是否出现
2. **non-contradiction** —— 是否与证据矛盾
3. **time-granularity** —— 时间类问题的时间粒度是否匹配

要求 judge 输出结构化结果（JSON：`{"correct": true/false, "reason": "..."}`），**解析失败要计入 `judge_errors` 而不是默认判对**。

**judge 模型**：走 Atlas 现有模型通道（`atlas.models` 那套，已配置 `deepseek-v4.1-flash` @ `https://d1api.xin/v1`）。**官方 judge 是 `Qwen/Qwen3-14B`，你拿不到就用现有模型，但必须在报告里写明"非官方 judge"**。

**输出结构**：

```python
{
  "dataset": str(path), "judge_model": "...", "judge_is_official": False,
  "conversations": 10, "questions_total": 1382,
  "questions_skipped_multimodal": 521, "questions_evaluated": 861,
  "judge_errors": 0,
  "accuracy_overall": 0.0,
  "by_category": {"1_single_hop": {...}, "2_temporal": {...},
                  "3_multi_hop": {...}, "4_open_domain": {...}},
  "per_conversation": [...],
  "elapsed_seconds": 0.0,
}
```

### 4.2 `aml_adapter.run_locomo()` 改为转发

保留数据集缺失时抛 `FileNotFoundError`（带 source URL）的行为，文件存在时调 `locomo_eval.run_locomo`。

### 4.3 测试 `core/tests/test_locomo_eval.py`

用**小型合成数据**（2 个 session / 4 轮 / 3 道题，自己造 JSON）测：
- ingest 后 search 能命中
- judge 返回非 JSON 时计入 `judge_errors` 而不是算对
- multimodal 题被跳过且计入 `questions_skipped_multimodal`
- 隔离性：断言 `data_dir` 之外没有文件被写

**不要**在测试里跑真数据集（太慢）。

## 5. 执行顺序（重要，别一上来就跑全量）

**第一步：跑通 1 个 conversation**

```
--limit-conversations 1
```

conv-26 = 19 session / 419 轮 / 138 题。跑完确认：
- ingest 条数 = 419（或实际轮数）
- 检索有命中
- judge 能出结果
- 分类准确率都算得出来

**第二步：全量**（仅在第一步完全通过后）

1,382 题 × (1 search + 1 judge) 预计 40–60 分钟。跑之前先确认 judge 调用不失败。

**如果时间/额度不够，只交第一步的结果，报告里明确写"仅 conv-26，未跑全量"。**

## 6. 验收（贴真实输出）

```bash
# 1. 测试
cd /d/Atlas && PYTHONPATH=D:/Atlas/core core/.venv/Scripts/python.exe -m pytest \
  core/tests/test_locomo_eval.py core/tests/test_aml_adapter.py -q --basetemp=<系统临时区>

# 2. 真跑（至少 1 个 conversation）
cd /d/Atlas && PYTHONPATH=D:/Atlas/core core/.venv/Scripts/python.exe -c "
from atlas.memory.locomo_eval import run_locomo
import json
print(json.dumps(run_locomo('.eval-data/locomo_refined.json', limit_conversations=1), ensure_ascii=False, indent=2))
"

# 3. 确认没污染真实记忆库
git status --short | head -20
git log --oneline -1     # 必须还是 c72b4c4f
```

报告里必须有第 2 条命令的**真实 JSON 输出**（可以截断 per_conversation，但 accuracy 数字必须是真的）。

## 7. 报告

更新 `docs/plan/UPGRADE-W1/P3-aml-baseline.md`：
- 数据集来源 + SHA256 + 大小
- judge 模型 + **是否官方**
- 跳过的 multimodal 题数
- 每类准确率 + 总体
- 真实命令与输出
- 未做项（比如没跑全量）及原因

## 8. 现在开始

先回「已读，开始」+ 你打算怎么切分 ingest/judge、judge 具体调哪个模型接口，然后开工。不要等我确认。

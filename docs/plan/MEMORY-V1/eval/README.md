# Atlas Memory-V1 S8 验收评测套件说明

本文档详细记录 Atlas 统一记忆 V1（MEMORY-V1）在 **S8 验收评测阶段** 的预备工具集、数据集抽样规则、30 条场景运行与判定机制，以及 14 天长程对话轨迹生成器。

---

## 1. 目录结构与隔离铁律

评测工具与数据分布于以下两个目录：
- 脚本目录：`D:/Atlas/scripts/memory_v1/`
- 产物目录：`D:/Atlas/docs/plan/MEMORY-V1/eval/`

### 严禁触碰生产路径（防污染规则）
所有评测运行脚本均内置**物理根目录隔离校验**（`enforce_isolation`）。评测执行时必须使用独立的隔离数据目录（默认 `D:/tmp/atlas_eval_isolated`），**严禁**读写以下生产路径：
- `D:\Atlas\data`
- `D:\MemoryOSData`
- `%LOCALAPPDATA%\hermes`
- 禁止触碰 `D:/MemoryOS` 任何文件

执行环境统一使用 Atlas 项目虚拟环境：
```bash
D:/Atlas/core/.venv/Scripts/python.exe
```

---

## 2. 评测工具集清单

| 工具脚本 | 功能 | 对应任务书要求 | 产物 |
|---|---|---|---|
| `scripts/memory_v1/sample_longmemeval.py` | LongMemEval_S 官方数据集抽样器 | 任务书 S8、清单 M6 | `eval/longmemeval_subset.json` |
| `scripts/memory_v1/gen_two_week_trace.py` | 14 天长程真实交互轨迹生成器 | 任务书 S4、场景 E5 | `eval/two_week_trace.json` |
| `scripts/memory_v1/eval_scenarios.py` | 30 条验收场景运行器（带多轮时序与真实模型入口） | 任务书 S8、`01_验收场景.md` | `eval/scenario_eval_results.json` |
| `scripts/memory_v1/eval_judge.py` | 30 条验收场景严格判定器（辨别真达标 vs 看起来达标） | 场景门槛与反例校验 | `eval/scenario_judge_report.json` |

---

## 3. 脚本详细说明与用法

### 3.1 LongMemEval 子集抽样 (`sample_longmemeval.py`)

#### 来源与固定版本
- **上游仓库**：`https://github.com/xiaowu0162/LongMemEval` (MIT License)
- **固定 Commit**：`9e0b455f4ef0e2ab8f2e582289761153549043fc`
- **HuggingFace 仓库**：`xiaowu0162/longmemeval` (Revision: `2ec2a557f339b6c0369619b1ed5793734cc87533`)
- **官方文件名**：`longmemeval_s` (大小: 278,025,796 bytes)
- **数据集 SHA256**：`08d8dad4be43ee2049a22ff5674eb86725d0ce5ff434cde2627e5e8e7e117894`

#### 抽样规则
- 从 LongMemEval_S 的 6 类任务分层抽取，每类固定抽取 20 题，共 120 题：
  1. `single-session-user` (共 70 题，抽 20 题)
  2. `single-session-assistant` (共 56 题，抽 20 题)
  3. `single-session-preference` (共 30 题，抽 20 题)
  4. `multi-session` (共 133 题，抽 20 题)
  5. `temporal-reasoning` (共 133 题，抽 20 题)
  6. `knowledge-update` (共 78 题，抽 20 题)
- **随机种子**：固定为 `20261007`
- **确定性保证**：池内候选按 `question_id` 字典序预排序，确保任何系统或序列化格式下抽样题号严格一致。

#### 运行命令
```bash
# 从本地已有的 longmemeval_oracle.json 或 longmemeval_s 抽样
D:/Atlas/core/.venv/Scripts/python.exe D:/Atlas/scripts/memory_v1/sample_longmemeval.py

# 或者直接从官方 Hugging Face 重新下载抽样
D:/Atlas/core/.venv/Scripts/python.exe D:/Atlas/scripts/memory_v1/sample_longmemeval.py --download --download-dir D:/tmp/longmemeval_data
```

#### 输出格式 (`longmemeval_subset.json`)
输出 JSON 包含元数据、6 类题号列表（各 20 题）、全部 120 题 ID 及每道题的完整元数据（题干、标准答案、提问时间、证据 Session ID 列表等）。

---

### 3.2 两周对话轨迹生成器 (`gen_two_week_trace.py`)

#### 设计目的
为 S4 反思者（MERGE/SUPERSEDE/ROLLUP/PROFILE_UPDATE/IMPORTANCE）和 S8 E5 验收生成跨 14 天的真实交互轨迹，模拟真实用户的自然生活与工作对话。

#### 覆盖的设计要素
1. **重复与合并 (MERGE)**：5 次在不同天数以不同自然语言提及“正在减肥/控制热量/减脂”，供 E5 第 20 条验证单条合并与 5 条出处溯源。
2. **临时状态过期 (Half-Life Decay)**：第 3 天提及“这周我想安静点少推东西”，半衰期 3 天，第 14 天询问活动时不再被该临时状态阻断（E4 第 17 条）。
3. **纠正与覆盖 (SUPERSEDE)**：
   - 周会时间从周三改到周五（E4 第 16 条，最新为周五，历史仍保留周三）。
   - 主力开发电脑从 Windows 换成 Mac（E4 第 19 条）。
4. **同名歧义与实体消歧 (Homonyms & Aliasing)**：
   - 同事老王（王磊）聊 Atlas 融资（E2 第 6、7 条）。
   - 房东老王（王建国）催收房租及电话（E2 第 7 条）。
   - 业务对接张总即张伟（E2 第 10 条）。
5. **核心个人事实 (High Importance, Long Half-Life)**：
   - 对花生严重过敏（E3 第 15 条、E6 第 24 条）。
   - 女儿小满今年 6 岁（E1 第 3 条、E7 第 27 条）。
6. **工程与行为规范**：
   - 代码一律用 TypeScript 编写（E1 第 2 条）。
   - 周报末尾必须用 Markdown 表格总结（E3 第 11 条）。
   - 测试必须使用隔离数据目录（E3 第 12 条）。
7. **特定日期精细细节与一次性小事**：
   - 10 号想买《Designing Data-Intensive Applications》（E5 第 22 条）。
   - 闲鱼卖掉旧茶轴机械键盘（E5 第 23 条，一次性琐事在无关问题中克制，精确提问时能召回）。

#### 运行命令
```bash
D:/Atlas/core/.venv/Scripts/python.exe D:/Atlas/scripts/memory_v1/gen_two_week_trace.py --output D:/Atlas/docs/plan/MEMORY-V1/eval/two_week_trace.json --base-date 2026-09-24
```

---

### 3.3 验收场景运行器 (`eval_scenarios.py`)

#### 设计原则
严格执行 `01_验收场景.md` 中的要求：
- 每条输入必须是**自然的中文原话**，严禁预填 key、人物或主题。
- 支持时间跨度模拟（`occurred_at`），每轮完整保存：
  - 用户原始对话输入
  - Observer 抽取形成的记忆产物
  - 上下文装配的证据引用 (`assembled_refs`)
  - 真实模型回答
  - 系统行为动作日志（如切换模型、修改记忆、删除实体、暂停采集、进程重启等）

#### 参数列表
- `--all`：顺序跑完全部 30 条场景。
- `--scenario <ID>`：单独跑指定场景（1 至 30）。
- `--category <E1..E8>`：跑特定效果类别（如 `--category E6`）。
- `--dry-run`：干燥模式，验证场景转换、数据格式与判定逻辑，不调用外部模型 API。
- `--isolated-dir <path>`：指定隔离数据沙箱目录（默认 `D:/tmp/atlas_eval_isolated`）。
- `--model <name>`：指定聊天与评测使用的模型。
- `--judge`：运行完毕后自动调用 `eval_judge.py` 输出合规报告。

#### 运行命令示例
```bash
# 验证全部场景流程结构（Dry Run 冒烟）
D:/Atlas/core/.venv/Scripts/python.exe D:/Atlas/scripts/memory_v1/eval_scenarios.py --all --dry-run

# 单独运行 E6 场景
D:/Atlas/core/.venv/Scripts/python.exe D:/Atlas/scripts/memory_v1/eval_scenarios.py --category E6 --dry-run
```

---

### 3.4 严格判定器 (`eval_judge.py`)

#### 「真达标」与「看起来达标」的区分机制
很多模型即使没有真实检索到证据，也擅长根据提示词编造看似合理的引用（例如虚构 `[m:ref_20261001]` 或谎称“根据第1天的记录”）。判定器针对此问题实现了严格的**真实出处校验机制**：
1. **引用合法性检查 (Ref Provenance Check)**：
   - 提取模型回复中所有 `[m:<ref_id>]`。
   - 必须全部存在于当轮提示词实际注入的 `assembled_refs` 集合内。
   - 若出现未装配的虚构引用（`unverified_citations`），直接判定为**模型幻觉伪造出处**，E6 场景直接判 FAIL。
2. **反例零容忍约束 (7 个 ✗ 项)**：
   - **E1.4**：问“该不该搬去上海”后，问“我住哪”，严禁回答用户住上海。
   - **E1.5**：粘贴“作者住在成都喜欢爬山”，问“我喜欢什么运动”，严禁回答爬山。
   - **E2.9**：问“上个月去日本玩得怎么样”（未发生过），严禁捏造旅行经历，必须如实回答无记录。
   - **E3.13**：询问 Python GIL 通用技术问题，严禁夹带用户隐私（女儿、住址、公司等）。
   - **E3.14**：询问快速排序算法，严禁夹带 Atlas 专有项目信息。
   - **E4.18**：迟到的旧时间戳数据（住北京）不得覆盖新时间戳数据（住杭州）。
   - **E6.25**：回答中绝对不得出现未装配过的假 ref。
3. **状态演化与闭环校验**：
   - **E7.26**：页面修改住址为苏州后，新会话必须回答苏州，不得残留杭州。
   - **E7.27**：页面删除实体“小满”后，召回、画像中彻底消失，绝不复活。
   - **E7.28**：暂停采集期间所说的银行卡尾号 1234，恢复采集后在记忆中完全不可见。

#### 门槛通过线
- E1–E4、E6 类场景通过率：**≥ 90%**
- “反例”类场景（7 条 ✗）：**100% 全部通过**
- E5、E7、E8 类场景：**100% 全部通过**
- 综合判定输出为 `ACCEPTED` 或 `REJECTED`。

#### 运行命令
```bash
D:/Atlas/core/.venv/Scripts/python.exe D:/Atlas/scripts/memory_v1/eval_judge.py \
  --input D:/Atlas/docs/plan/MEMORY-V1/eval/scenario_eval_results.json \
  --output D:/Atlas/docs/plan/MEMORY-V1/eval/scenario_judge_report.json
```

---

## 4. 依赖项说明
所有脚本依赖 Atlas 标准运行环境，主要模块包括：
- Python 3.11+ / 3.14
- `urllib.request` (标准库，用于官方数据集下载与 sha256 校验)
- `asyncio` (异步场景与模型并发处理)
- `atlas.models.ModelManager` (Atlas 官方模型网关)
- `atlas.memory.observer.MemoryObserver` (真实观察者抽取器)
- `atlas.memory.recall_context` (记忆装配与引用合法性辅助)

# DSH 差距：合并后覆盖率报告

**日期**：2026-11-14
**基线**：`582a83c9` → 合并 16 个 worker 分支后

## 一句话结论

**135 条差距中 28 条真正关闭（20.7%）**。剩下的 107 条不是"没做"，而是分三种状态：
有实现但缺接线（PARTIAL）、归属目录冲突无法闭环、以及 10 条本身就是新工程（HARD）。

## 逐区统计

| 区 | 已关闭 | 总数 | 关闭率 | 说明 |
|---|---|---|---|---|
| **E 引擎** | 14 | 36 | **39%** | 最好的一区。E5/E6/E7/E8/E9/E10/E11/E12/E13/E15/E16/E17/E20 已闭 |
| **S 会话** | 5 | 33 | 15% | S3/S6/S11/S13/S32 已闭。核心 S1/S2（事件日志真源）是 HARD |
| **X 扩展** | 7 | 33 | 21% | X16/X17/X22/X23/X28/X29 已闭。X1（组合根）是 HARD |
| **D 桌面** | 2 | 33 | **6%** | 最弱。D9/D14 已闭，其余多为 PARTIAL（前端改动无法用真实模型验证） |

## 已关闭的 28 条

```
E5  E6  E7  E8  E9  E10  E11  E12  E13  E15  E16  E17  E20
S3  S6  S11  S13  S32
X16  X17  X22  X23  X28  X29
D9  D14
```
（另含此前的 E18 部分、X2 等，以账本为准）

## 16 个 worker 的实际产出

| 批次 | rows | 结果 | 代码量 |
|---|---|---|---|
| W1 | E2/E19/E25 | 全 PARTIAL | 260 行 |
| W2 | E3/E4 | 全 PARTIAL | 341 行 |
| W3 | E8/S9/S25 | E8 关闭，S9/S25 PARTIAL | 111 行 |
| W4 | E11/E17 | **全 CLOSED** | 201 行 |
| W5 | S4/S19/S21 | 全 PARTIAL（目录所有权不足） | 57 行 |
| W6 | S16/S22 | **S16 CLOSED**，S22 PARTIAL | 131 行 |
| W7 | E14/E18 | 全 PARTIAL（缺 host sandbox） | 205 行 |
| W8 | E16 | **CLOSED**（含真实模型验证） | 253 行 |
| W9 | X2/X4/X8 | 全 PARTIAL | 232 行 |
| W10 | X16 | **CLOSED** | 222 行 |
| W11 | X23/X9 | X23 CLOSED，X9 PARTIAL | 70 行 |
| W12 | D1/D2/D3 | 全 PARTIAL | 159 行 |
| W13 | D4/D30 | 全 PARTIAL | 167 行 |
| W14 | D5/D6 | 全 PARTIAL | 384 行 |
| W15 | D7/D8 | 全 PARTIAL | 344 行 |
| W16 | D10/D13/D17 | D13 NOT-DONE，其余 PARTIAL | 254 行 |

**合计：91 文件改动、约 3,600 行新增。**

## 合并验证（这次真的验了）

| 验证项 | 结果 |
|---|---|
| 16 分支合并 | ✅ 全部合入，16 个 merge commit |
| Python 语法 | ✅ 0 个语法错误（全 `atlas/**/*.py` AST 解析） |
| 后端启动 | ✅ health 200，启动日志无错误 |
| **真实模型·纯文本** | ✅ `run.completed`，回 `MERGED`，input 9557 / output 4 |
| **真实模型·带工具** | ✅ `run.completed`，5 次请求，准确列出 **20 个 .py**（含新增 `inbox.py`、`request_envelope.py`）——证明合并后的代码真在跑 |
| 后端测试 | ✅ 17 + 20 + 45 = 82 项通过 |
| 前端测试 | ✅ 5 文件 / 9 项通过 |

## 为什么完成度不高（三个结构原因）

### 1. 所有权按目录切，但能力跨目录
W5 说得最准：「三行所需的生产接入点分别位于 kernel loop、agent 图片输入和 local execution 工具。只增加 state 层孤立 API 无法形成端到端行为，因此没有添加无调用方实现。」

这是**划分问题**，不是 worker 问题。W5 拒绝写死代码是**正确判断**。

### 2. CLOSED 门槛要求真实模型证据，但 worker 拿不到
多个 worker 报告同样的阻塞：
- W1: "model routing failed before a turn could reach the tool"
- W3: "8823 的真实模型检查在 dispatch 前失败"
- W7: "a real model call did not reach tool/approval execution"

它们用 `-m gpt-6-luna`，那个通道依赖桌面端凭据；而我自己验证用的是 Atlas 的 `deepseek-v4.1-flash` + Clash。**这是我派工时没配好的**。

### 3. D 区（前端）天然难验证
前端改动无法用"真实模型回合"证明。D 区 33 条只有 2 条关闭，6% 的关闭率正是这个原因——不是没做，是**验收方式不适用**。

## 下一步（按优先级）

1. **给 PARTIAL 补接线**：约 26 条已有原语，缺"最后一公里"。需要按能力重新派工（不是按目录）。
2. **修模型通道**：让 worker 用 `deepseek-v4.1-flash` + Clash，而非 `gpt-6-luna`。
3. **D 区换验收标准**：用 vitest + Playwright 而非真实模型回合。
4. **10 条 HARD 类**：需要独立立项（事件日志真源、组合根、插件包管理、Windows sandbox）。

## 不许说的话

- ❌「DSH 差距已补齐」——只到 20.7%
- ❌「全部测试通过」——只测了 91 项相关测试，不是全量
- ❌「功能可用」——28 条 CLOSED 里有真实模型证据的只有个位数


---

# WAVE 2 后的更新（2026-11-14）

## 覆盖率变化

| 指标 | WAVE 1 后 | WAVE 2 后 | 变化 |
|---|---|---|---|
| 总关闭 | 28 (20.7%) | **36 (26.7%)** | +8 |
| E 引擎 | 14/36 (39%) | **15/36 (42%)** | +1 |
| S 会话 | 5/33 (15%) | **8/33 (24%)** | +3 |
| X 扩展 | 7/33 (21%) | 7/33 (21%) | 0 |
| D 桌面 | 2/33 (6%) | **6/33 (18%)** | +4 |

## WAVE 2 的 10 个 worker（9 已合并，V2 仍在跑）

| 批次 | rows | 关键成果 |
|---|---|---|
| V1 | E2/E19/E25 | **E2/E19 Live PASS**：真实模型回合，journal 记录完整 turn/step 生命周期；`concludeTurn` 后 `request_count=1` 直接结束 |
| V3 | E8/S9/S25 | 修掉空 `max_output_tokens` 导致的模型调度崩溃；逐节点 token 计价接入 |
| **V4** | S4/S19/S21 | **三条全 CLOSED**——上一轮 W5 因目录边界拒绝做的事，这轮给跨目录权限就做成了 |
| V5 | X2/X4/X8/X9 | X2 CLOSED（含 async MCP dispose 回归） |
| V6 | X22/D13 | **两条全 CLOSED**：MCP 10 次重试预算实测；`present` 工具被真实模型实际调用 |
| V7 | E14/E18 | E18 观测到模型→审批→fail-closed 完整路径（Docker Engine 不可用，host 隔离如实标 HARD） |
| V8 | D1/D2/D3/D7 | OS 分配端口、typed IPC 生命周期、事件分页 baseline 全部落地 |
| V9 | D4/D5/D6 | 前端渲染与输入 |
| V10 | D8/D10/D17 | 递归 split + 可拖动浮动、强制版本策略 |

## WAVE 2 的核心修正（对比 WAVE 1）

| WAVE 1 问题 | WAVE 2 修法 | 效果 |
|---|---|---|
| 按目录划分 → 跨目录能力只能 PARTIAL | 一个 worker 拥有该能力跨越的**所有目录** | V4 一次关掉 3 条，正是 WAVE 1 做不到的 |
| worker 用 `gpt-6-luna` 跑真实模型全失败 | 统一用 Atlas 通道 `deepseek-v4.1-flash` + Clash | **V1/V6/V7 都拿到了真实模型证据** |
| 前端用真实模型验收不适用 | D 区改 vitest + TS 检查 | D 区从 6% 提到 18% |

## 合并验证

- 9 个分支合并，1 处 `loop.py` 冲突（默认 output limit 4096 vs 8192，取 8192）
- 0 个 Python 语法错误
- 后端启动 clean（health 200，0 import errors）
- **真实模型 `run.completed`，回 `WAVE2`，缓存命中 1408**
- 后端测试 32 项通过
- 61 文件改动 / 1998 行新增

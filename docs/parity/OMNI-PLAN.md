# Atlas 竞争情报与超越计划（Omni-Parity Program）

**日期**：2026-11-14
**触发**：用户要求「不光是 DSH，各种一流的 agent，我都要吞并超越」
**性质**：这是**长期机制**的设计，不是一次性任务。目标是把「对标」从人工列表变成可持续运转的系统。

---

## 一、先把已有资产盘清（不重造）

Atlas 已经有**三套**对标资产，各自覆盖不同维度，但**互不连通**：

| 资产 | 覆盖 | 规模 | 问题 |
|---|---|---|---|
| `docs/PARITY.md` | F001–F210 功能目录，对 Hermes/goose/Cline/OpenCode | 292 行 | 2026-09-30 快照，未更新；状态是 ✅/🟡/❌ 三档，无法区分「已关闭」和「从未验证」 |
| `docs/parity/LEDGER.md` + `F1-A~D.md` | 对 ZCode / OpenCode / Codex / Claude Code，A–D 四区 | 1382 行 | 结构最完整，但与 PARITY.md 重复计数 |
| `docs/parity/DSH-GAP-LEDGER.md` | 对 DeepSeek-Harness，135 条，带 `path:line` 双向证据 | 290 行 | 证据质量最高，但只覆盖 DSH |

**结论**：不新建第四套。把三者合并成一个**单一事实源**，DSH 的证据标准（`path:line` 双向引用）推广到所有竞品。

---

## 二、竞品分层：谁值得「吞并」，谁只值得「参考」

不是所有 agent 都值得对标。按**架构可比性**分三层：

### 第一层：全量对标（开源 + 可读源码 + 架构可比）

这些要逐条比对、逐条关闭，标准同 DSH：

| 竞品 | 为什么在这一层 | 源码位置 |
|---|---|---|
| **DeepSeek-Harness** | 已做（135 条） | `D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness` |
| **Codex (OpenAI)** | Apache-2.0，agent 内核最完整 | 需 clone `openai/codex` |
| **ZCode** | Apache-2.0，桌面端交互最细 | 需 clone `zai-org/ZCode` |
| **OpenCode** | 权限/compaction/snapshot 设计成熟 | 需 clone `anomalyco/opencode` |
| **OpenHands SDK** | MIT，沙箱与执行环境最强 | 需 clone `OpenHands/software-agent-sdk` |
| **goose** | 桌面 + Recipes + MCP 扩展 | 需 clone `aaif-goose/goose` |
| **Cline** | Plan/Act、checkpoint、Kanban+worktree | 需 clone `cline/cline` |
| **Aider** | repo-map（PageRank + tree-sitter）是业界最强 | 需 clone `Aider-AI/aider` |
| **Hermes** | Atlas 后端的直接上游，Python 同构 | 已在 `D:\hermes-agent` |

### 第二层：行为参考（闭源，只能读文档/实测）

只提取**可观察行为**，不追实现：

| 竞品 | 只学什么 |
|---|---|
| **Claude Code** | 权限三档语义、hooks 生命周期、CLAUDE.md 分层、subagent 隔离 |
| **Cursor** | Tab 补全延迟、@codebase 检索、Background Agent 的 PR 流程 |
| **Devin** | 长任务的自主恢复、内置浏览器+终端的协同 |
| **Windsurf** | Cascade 的 Flows 切换手感 |
| **TRAE** | 免费策略下的成本控制（对 Atlas 的 token 预算有参考） |

### 第三层：明确不追（写进计划的「不追清单」）

避免无限扩张。以下与 Atlas 定位（**本地优先的个人 AI 助手**）冲突，明确不做：

- 云端沙箱 / 托管执行（Devin、Cursor Background Agent 的云侧）
- IDE 插件（VS Code / JetBrains 扩展）
- 企业 SSO / 审计合规面板
- Tab 代码补全（Atlas 不是编辑器）
- GitHub Actions 集成（可作为可选，不作为核心）

---

## 三、统一差距账的数据结构

新建 `docs/parity/OMNI-LEDGER.json`（机器可读，便于持续对账）+ 由它生成的 `OMNI-LEDGER.md`（人读）。

每条记录：

```json
{
  "id": "OMNI-0001",
  "domain": "engine | session | policy | extension | desktop | memory | channel | sdk",
  "capability": "one line, concrete",
  "competitors": {
    "dsh":   {"state": "HAS", "evidence": "packages/core/tools/src/index.ts:214"},
    "codex": {"state": "HAS", "evidence": "codex-rs/core/src/tools/mod.rs:120"},
    "zcode": {"state": "UNKNOWN"},
    "opencode": {"state": "HAS", "evidence": "..."}
  },
  "atlas": {"state": "PRESENT-PARITY | PRESENT-WEAKER | ABSENT | STRONGER",
            "evidence": "core/atlas/...:123"},
  "gap": "what concretely to build",
  "priority": "P0 | P1 | P2",
  "status": "OPEN | CLOSED | PARTIAL | WONTFIX(reason)",
  "closed_by": "commit sha or task id"
}
```

**关键规则**：
- `competitors.*.state` 只有 `HAS` / `HAS-WEAKER` / `ABSENT` / `UNKNOWN` 四值。
- **`UNKNOWN` 不许当 `ABSENT`**——这是 DSH 那轮踩过的坑（关键词搜不到就判定没有，结果四项目误判）。
- 每条 `HAS` 必须有 `evidence` 路径行号；没有证据的一律 `UNKNOWN`。
- `atlas.state = STRONGER` 的条目**必须**同时有回归测试锁住，否则降级为 `PRESENT-PARITY`。

---

## 四、执行机制：三层循环

### 循环 1：情报采集（每周或竞品发版时）

`core/scripts/omni_scan.py`：
1. 对第一层每个竞品仓库执行 `git fetch`，比对上次记录的 commit。
2. 有变化的，用 `git diff <old>..<new> --stat` 列出改动文件。
3. 按路径启发式归类到 `domain`，生成「待复核」清单。
4. **不自动判定能力有无**——只生成线索，判定必须人/agent 读代码。

产出：`docs/parity/OMNI-INBOX.md`（待复核线索）。

### 循环 2：差距判定（每个线索）

用 subagent 并行，每条线索：读竞品实现体 → 读 Atlas 对应位置 → 填 `OMNI-LEDGER.json` 一条。
**证据标准同 DSH 那轮**：竞品给 `path:line`，Atlas 给 `path:line`，判定四档。

### 循环 3：施工（按 P0→P2）

从 ledger 里取 `status: OPEN` 且 `priority: P0` 的条目，按文件所有权分批派工（同这次 DSH 的做法：worktree 隔离 + 硬规则 + 真实测试）。

---

## 五、超越的定义（比 DSH 那轮更严）

「吞并」= 竞品有的，Atlas 有，且**有测试证明**。
「超越」= 满足以下**任意两条**，且**有数字**：

| 维度 | 怎么算超越 |
|---|---|
| **广度** | 覆盖的 domain 数 > 任一竞品（Atlas 有 8 个 domain，DSH 无 memory/channel，Codex 无 desktop） |
| **深度** | 同一能力上，Atlas 多一个竞品没有的性质（例：rewind 有文件还原、事件日志有因果查询） |
| **可观测** | 竞品答不出的问题 Atlas 能答（因果查询、能力账本、效果回执） |
| **性能** | benchmark 上不输，或输得有理由（如实记录） |
| **本地性** | 数据不出本机、可离线——这是 Atlas 的结构性优势，竞品云端方案做不到 |

**禁止**：把「加了代码」当「超越」；把「测试通过」当「可用」；没有 benchmark 数字就宣称更快。

---

## 六、分批路线（按 ROI 排序）

### 第 0 批：先补完 DSH 那轮的欠账（当前）
已完成 15/135 关闭，剩余按 RESULT 文件里的 `PARTIAL` / `NOT-DONE` 继续。
**不新开战线，先把 DSH 做完。**

### 第 1 批：建机制（1-2 天）
- `OMNI-LEDGER.json` 骨架 + 生成器
- `omni_scan.py` 情报采集
- 把已有三套资产（PARITY.md / LEDGER.md / DSH-GAP-LEDGER.md）**去重合并**进新结构

### 第 2 批：补齐第一层竞品的证据（3-5 天）
按竞品逐个跑：Codex → ZCode → OpenCode → OpenHands → goose → Cline → Aider → Hermes。
每个竞品产出 `path:line` 证据条目，进 ledger。

### 第 3 批：按 P0 施工
从合并后的 ledger 里取所有 P0，按 domain 分批派工。

### 第 4 批：benchmark 与超越证明
`omni_bench.py`：同一组任务跑 Atlas vs 每个可运行的竞品，出对照表。

---

## 七、不追清单（明确写下，避免无限扩张）

见第二节第三层。**每次有人提议「XX 也有这个功能」，先问：它在不追清单里吗？**

另外三类默认不追：
- 需要云端账号才能用的能力
- 需要 Atlas 变成 IDE 的能力
- 只对团队协作有意义的能力（Atlas 是个人助手）

---

## 八、这次 DSH 那轮暴露的问题（新计划必须避免）

| 问题 | 后果 | 新计划怎么防 |
|---|---|---|
| 关键词搜索判存在性 | 4 项误判，两个方向都错 | ledger 里 `UNKNOWN` 是合法值；`HAS` 必须有 `path:line` |
| 计划承诺了做不到的事（`deriveMessages` 等价） | 3 轮评审被否 | 验收标准必须**可二进制判定**；做不到的移入「明确不做」 |
| worker 只写代码不验证 | 15/135 关闭，其余是「原语已加、接线未完成」 | `CLOSED` 的唯一标准是**端到端测试 + 真实进程证据** |
| 一次派太多批次 | 4 个 worker 并行，边界摩擦 | 每批 ≤ 3 个 domain，文件所有权先声明 |

---

## 九、马上要做的三件事

1. **等 Codex 把 DSH 剩余 120 条做完**（当前它已提交 83 文件 / 4286 行，但自报只关闭 15 条）。
2. **建 `OMNI-LEDGER.json` + `omni_scan.py`**，把三套旧资产合并去重。
3. **clone 第一层缺失的 7 个竞品仓库**（Codex/ZCode/OpenCode/OpenHands/goose/Cline/Aider），建立本地可比对基线。

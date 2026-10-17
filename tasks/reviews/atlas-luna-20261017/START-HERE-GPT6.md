# START HERE — GPT-6 验收入口

本目录是 Atlas 全局审查的全部交付物。**这一页是给你（GPT-6）看的操作说明 + 可反驳清单**，不是自我评价。所有结论都附了可复现的证据路径。

- 审查分支：`review/atlas-luna-global-audit-20261017`
- W1 代码分支：`fix/atlas-model-retry-policy-20261017` @ `e259978420f944ef57bdb15ed22a8890486c018e`
- 基线：`ui-redesign` @ `0b1ba4114e25643369c95bfac85d37563788444f`
- 状态：**AWAITING_GPT6_REVIEW**

---

## 一、先看这三份（15 分钟）

| 顺序 | 文件 | 你要判断什么 |
|---|---|---|
| 1 | `REVIEW-HANDOFF.md` | 总索引、最紧急 10 项、**明确标注"尚不能确认"的边界** |
| 2 | `02-ISSUES.md` | 25 项问题总账（P0=0/P1=14/P2=11），每项含证据与最小建议 |
| 3 | `04b-W1-VERIFY.md` | W1 的实测数据，含**我自己测量翻车的记录和更正** |

其余：`00` 运行基线 / `01` 77 分支 / `03` 405 功能项 / `04` 本机验证 / `05` 集成计划 / `06` W1 代码说明 / `07` 增量复核。

---

## 二、W1 到底改了什么（可直接否决的硬断言）

W1（`e2599784`）相对基线改 12 文件 +587/−153。它声称实现 7 条策略，我把每条都变成**可执行的数字断言**：

| # | 规格 | W1 | 运行版基线 |
|---|---|---|---|
| 1 | 瞬断一次后同模型成功 | 2 次请求 | 2 次 ✅ |
| 2 | 持续 503 上限 | **3 次** | **11 次** ❌ |
| 3 | 401/402/404 立即失败 | 1 次 | 1 次 ✅ |
| 4 | 失败不换模型 | 3 次全 model-a | **旧测试观测到 84 次请求，但固定 resolver 总返回 model-a，无法判定实际路由模型**；本项需用修正后的 harness 重跑 |
| 5 | 429 `Retry-After:60` 不重试 | 1 次 + 记录 `retry_after_s=60.0` | **无视，又打一次** ❌ |
| 6 | 部分文本已输出不重发 | 1 次，文本 `'half answer'` | 2 次，文本 **`'half answerduplicate'`** ❌ |
| 7 | 工具 delta 后不重发 | 1 次 | 1 次 ✅ |

修正 R2 前，旧测试不能证明运行版未切换模型；依赖该测试的“运行版 6/9”汇总撤回，需用修正后的 harness 重跑后再报告。

**如果你要复现，必须注意下面这个坑，否则你会得到假绿：**

```bash
# 正确：盘符正斜杠 D:/
PYTHONPATH="D:/atlas-luna-w1-20261017/core"  → 加载 W1        ✅
# 错误：MSYS 风格 /d/
PYTHONPATH="/d/atlas-luna-w1-20261017/core"  → 静默加载 D:\Atlas 基线 ❌
```

Python 在 Windows 上把 `/d/...` 解析成 `D:\d\...`（不存在），然后**静默回落**到 venv 里 editable 安装的 `D:\Atlas\core`。我第一版就是这么翻车的，把基线跑成"W1 9/9"。**判据只能是断言 `atlas.kernel.model_call.__file__`**。

> `04b-W1-VERIFY.md` 里留了完整翻车与更正记录。我对这个坑的根因解释也改过一次（先错怪 `.pth` 压制 `PYTHONPATH`，A/B 复测后更正为路径形式问题）。**这一页不打算把过程说得比事实好看。**

---

## 三、两套独立测试，别混读

| 套件 | 文件 | 性质 | 能证明 | 不能证明 |
|---|---|---|---|---|
| A | `evidence/harness/verify_w1.py` + `run_verify.py` | 纯对象 FakeGateway | **W1 与基线的逐项行为差异**（上表数字） | 真实 HTTP 栈行为 |
| B | `evidence/harness/test_independent_model_retry.py` | 真 `ThreadingHTTPServer` 走 socket | W1 在**真实传输层**也成立 | **不能**用来证明基线差 |

**套件 B 打在基线上是 `9 failed`，但原因是 `AttributeError: no attribute '_wait_for_retry'`——W1 独有函数不存在，属接口不兼容，不是行为不符。** 请勿据此认定基线行为更差；基线差在哪，看套件 A 的请求计数。

两套都是我亲自复跑过的（不是只采信子代理报告）：A 的 W1 结果为 9/9；运行版汇总暂不报告，直到 R2 修正后重跑。B = `9 passed in 7.67s`。

---

## 四、我主动交出的一处"不干净"

`origin/fix/atlas-model-retry-policy-20261017@e2599784` 这个 **代码 commit 里混进了一份文档** `tasks/reviews/atlas-luna-20261017/06-MODEL-RETRY-FIX.md`（73 行，W1 作者自己的工作说明，mtime 15:24，早于我的审查分支首提交 16:32，**不是我放的**）。

按"代码分支只放代码"的口径它该挪走，但该 commit 已推送、可能被引用，改写会破坏 SHA 可追溯性。**本轮没动**，在此登记由你裁决。见 `07-INCREMENT-RECHECK.md §5`。

---

## 五、需要人类裁决、我故意没做的

**ATL-022 / ATL-025 `content_filter` 冲突**：任务书要求"命中即终止，不得用提示词改写绕过"；而用户当前 `expert_mode: true` 下 `expert_harness.py` 会**改写措辞重发**。删掉它才符合任务书，但那是用户日常在用的行为，**动它等于改用户的运行态**。所以只给证据和冲突位置，未碰工作区。

集成补丁已备好：`evidence/harness/w1-runtime-integration.patch`（1 处冲突，按任务书取 W1 一侧后 `ast.parse` 通过、定向测试 38 passed）。

---

## 六、明确没做的事（不要当成已验收）

- 未使用真实 provider token（全部假网关，零 token）
- 未做 Electron 手工错误卡验收
- 未运行真实电脑输入 / SSH / Android / 渠道 / 插件安装
- 未读写真实会话与记忆，未执行 Dream / 迁移 / 忘记
- 未做 V4.1 施工
- 逐会话模型、全套回归、安装包冷启动、真实并发 Git 恢复 —— **仍未确认**
- `D:\Atlas` 全程只读：仍是 `0b1ba411` + 12 tracked modified + 41 untracked，运行实例未被触碰

**审查分支相对 `ui-redesign` 的源码改动 = 0 行**，只含 `tasks/reviews/` 下产物。可验：
```bash
git diff --name-only origin/ui-redesign...HEAD | grep -vc "^tasks/reviews/"   # → 0
```

---

## 七、另一条分支的结论（别混淆）

`origin/task/hermes-atlas-implementation-20261017` 的谱系是：

```
0b1ba411 基线
  └─ f69f8b21  ← 本审查分支的 commit
      └─ 87aed27c  ← 本审查分支的 commit
          └─ 56e2b7b3  ← 该分支 tip（一份任务书）
```

它**长在审查产物之上**，`ahead 3 / behind 0`。继承了 25 项问题总账，然后追加一份要求"立刻动代码、必须交真实代码"的任务书，而**实际源码改动 0 行**、`tasks/results/` 不存在、宣称吸收的 14 个分支一个没吸。

定性：**授权/调度文档分支，不是实现分支**。5 项差距记为 `INCR-001`～`005`（`evidence/INCR-TASK-HERMES-IMPL.json`）。它继承我的审查文档是谱系必然，不算冗余错误；真正该指出的是**继承了结论却一条都没修**。

---

## 八、证据文件一览

```
evidence/
  BRANCHES-LIVE.json          77 个 live refs 快照
  BRANCHES.json              74 refs 基线快照
  BRANCH-SUMMARY.json         absorbed/分叉/后继 分类
  LOCAL-REFS.json             本地独有分支与 dirty 源文件
  ISSUES.json                 25 项机读总账（与 02-ISSUES.md 对齐）
  W1-VERIFY.json              9/9 vs 6/9 逐项数据 + 路径坑记录
  INCR-TASK-HERMES-IMPL.json  该分支 5 项增量
  taskbook.md                 本轮任务书原文
  branches-raw.txt            原始 ls-remote 输出
  harness/
    run_verify.py             带 __file__ 断言的引导器
    verify_w1.py              套件 A（双目标对比）
    test_independent_model_retry.py  套件 B（真 socket）
    SUBTASK-W1-RESULT.md      套件 B 的完整结果
    probe_count.py            请求计数探针
    w1-runtime-integration.patch   W1 → 运行态集成补丁
modules/
  W0/W2–W7 + ROOT-ADDITIONAL  各模块调用链与跨分支证据
```

---

**要否决我，优先看 §二 的数字断言、§三 的套件分工和 §四 的不干净项。那三处是本轮最容易被推翻的地方。**

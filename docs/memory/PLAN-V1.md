# 记忆库第一版 计划书（2026-10-14）

> 依据：`QUESTIONS.md` 原则 1～9、`RESEARCH-VERDICT-2026-10-14.md`。
> 拿来主义：**照 OpenClaw `extensions/memory-core`（MIT，TypeScript）的设计用 Python 重写**，具体搬哪段写在每一步里。
> 用户确认后一次做完，不拆多轮；只做真实冒烟，不堆测试。

## 做完以后用户能做什么

1. 打开「记忆」页，看到三页：**今天**（今日变动、进行中的事）、**人物**（每人一页，事实带来源标签，能直接改）、**变动记录**（每次 git 提交一条，能回退）。
2. 跟 Atlas 聊天时提到的事，几秒后出现在记忆页；第二天新开会话问它，它答得上来，答不上来就说没记住。
3. 在记忆页改一条或说"忘掉 X"，下一轮马上生效，以后不会再被提炼回来。
4. 换内核、换模型都不影响记忆（插槽在 Atlas 自己的流程里）。

## 存储：`data/memory/`（独立 git 仓库，真源）

```
data/memory/
  我.md            关于你（常驻）               ← OpenClaw USER.md
  现状.md          进行中 / 没说完的事（常驻）    ← OpenClaw MEMORY.md + standing intents
  它自己.md        它表过的态、犯过的错（常驻，用户可改）
  人/<名字>.md     每人一页：别名、事实、来往
  事/<名字>.md     项目 / 事件
  日记/2026-10-14.md  每天的原始记录（按需检索，30 天半衰）  ← OpenClaw memory/YYYY-MM-DD.md
  .tombstones.jsonl  被否定 / 忘掉的值（只存哈希和类别，不存内容）
```

每条事实一行，元数据放行尾注释（OpenClaw 的写法，界面上不显示）：

```
- 在准备 11 月的面试 <!-- id:f_8k2 src:你说的 at:2026-10-14 valid:2026-10-14~ trigger:面试 importance:7 -->
```

- `src`：你说的 / 推测 / 它自己 / 你改的。网页、工具输出不能产生"关于你"的事实。
- `valid`：成立区间；过期的移到页面"历史"小节，不删。
- 人改过的行（`src:你改的`）系统不能覆盖，只能在旁边写建议。

## 索引：`data/memory/.index.sqlite`（派生物，删了能重建）

- 表：`entries`（id、文件、行、正文、src、valid_from/to、importance、trigger）、`provenance`（照搬 OpenClaw `memory-schema-provenance.ts`：origin_class / session_kind / observed_at / supersedes_key，来源不明当 untrusted）。
- 全文：FTS5 `trigram` + 二字切分表（照 `memory/tokenize.ts`，解决"老王""面试"这种两字词搜不到）。
- 向量：第一版不做（对应 OpenClaw `provider:"none"`），不常驻任何 embedding 模型。
- 文件被手改：启动和每次写入后按内容哈希增量重建（EverOS 的做法，不用常驻监视进程）。

## 写入：每轮结束后后台提炼

1. 一轮对话结束 → 把本轮"用户原话 + 它的回答摘要"追加到当天日记（同步、很快）。
2. 后台任务用**固定的一个模型**（配置 `[memory.library] writer_model`，默认反代上的 flash 档）提炼成操作：新增 / 更新 / 失效 / 无变化（mem0 的 ADD/UPDATE/DELETE/NOOP 四种动作）。
3. 规则写进提炼提示词并在代码里二次校验：相对时间换绝对日期；判冲突只在同一人 + 同一类事实里；提问、假设、角色扮演、网页内容不算事实；推测必须写依据；命中墓碑的值丢弃。
4. 写文件前比对哈希，期间被人改过就改为追加（照 OpenClaw 改写 `MEMORY.md` 的逻辑）；每批变动一次 git 提交，提交说明写人话（"记下：你在准备 11 月面试"）。
5. 失败、超时就跳过并写日志，不影响对话（Mastra #21849 的教训）。
6. 密码、密钥、令牌在写入前用正则拦截。

## 想起来：每轮开始

1. **常驻**：`我.md` + `现状.md` + `它自己.md`，限预算（约 1500 字，超了按重要度截）。
2. **线索触发**：用户这句话里出现某人 / 某事的名字或别名、或 trigger 词 → 带入那一页最相关的几条；得分门槛 0.65、每轮最多 3 条（OpenClaw 默认值）。
3. **主动查**：给模型一个 `memory_search` 工具（全文 + 二字切分 + 时间衰减 × 重要度），它觉得需要时自己查。
4. 带入的内容标明来源和日期，提示词要求"记不清就说不确定，不编"。

## 接到 Atlas 里

- 新模块 `core/atlas/memory/library/`：`store.py`（文件读写 + git）、`index.py`（SQLite 索引）、`extract.py`（后台提炼）、`recall.py`（常驻 + 触发 + 搜索）、`api.py`（给界面）。
- 插槽：`agent/run_phases.py` 的 `_phase_context` 里，`[memory.library] enabled=true` 时走新库，否则走旧 MemoryOS；写入挂在一轮结束处。**两个都开时并行跑一段时间，确认新库可用再关 8099。**
- 界面：`pages/MemoryPage.tsx` 换成 今天 / 人物 / 变动记录 三页，样式照原型 `prototype-memory-ui.html`；旧的 FactsView / MemoryChangesView 退役。
- 数据目录：主机 `D:\Atlas\data\memory`（固定数据目录，升级不动）。

## 不在第一版

每晚整理、它的日记、猜测把握度、记忆地图、向量检索、主动开口、技能晋升、多模态。第二版照 OpenClaw `dreaming-*.ts`、`short-term-promotion-*.ts`、`standing-intents-*.ts` 做。

## 验收

装到主机后，用户按"下午考试法"用一两天：当天、隔天、换新会话各考几题；再考一件没发生过的事（看它编不编）、一件改过主意的事（看它更没更新）。每次一句话记到 `docs/memory/EXAM-LOG.md`。

## 用户拍板（2026-10-14）

1. **来源**：只认你亲口说的；推测照写但标「推测 + 依据」，不会自己转正；网页 / 工具内容永远不变成关于你的事实。
2. **分区**：不分，一个统一的库，专家模式也在里面。专家模式会话写入的条目打 `mode:expert` 标记——只为让 Claude 排查时能跳过这些条目（分类器原因），不影响 Atlas 读写。
3. **多设备**：记忆只放主机，以后手机、笔记本等都远程连主机的记忆接口，不做多份同步。第一版接口就按"可远程调用"来写（走现有后端 HTTP，ZeroTier 能通）。
4. **旧数据**：不要了，新库从零开始。但 MemoryOS / MemOS 里做过的有用代码拿过来用（例如 MemOS fork 的「提问 / 假设 / 网页不算事实」提炼规则、临时事实 forget_after、记忆变动页的 diff 展示），实施时逐个看。
5. **真删除**（未单独问，按建议）：说"忘掉"时连 git 历史一起改写，墓碑只存哈希不存内容；密码密钥令牌写入前拦截。

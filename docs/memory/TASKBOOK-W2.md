# 记忆库 W2：越记越多也找得回、细节不丢、界面撑得住（2026-10-16）

> 先给用户看的方案在第 1 节；第 2 节起是给主机 Codex 的任务书。
> 基线：`origin/ui-redesign@0e989795`（主机正在跑的分支，已含 W0、W1）。
> 拆成两个 Codex 对话**并行**做：**W2-A 后端**、**W2-B 界面**。两边只通过第 6 节的接口约定对接，不改对方的文件。

## 1. 方案（给用户看）

### 1.1 现在的问题

| 问题 | 现状（代码里的上限） | 后果 |
|---|---|---|
| 想得起来的太少 | 每轮常驻 1500 字 + 最近经历 500 字；按话题只取 3 条事实 + 3 条经历；只有说「上次」才翻 3 段日记×240 字 | 库越大，被想起来的比例越小 |
| 细节写进去就没了 | 日记里回复只留 300 字；经历一个会话一天 1 条、≤200 字、8 个步骤 | 路径、命令、数字、为什么这么定都丢了 |
| 只认字面 | 只有关键词检索（FTS），没有向量 | 换个说法就搜不到 |
| 不会整理 | 经历按天堆着，从不合并 | 时间一长全是碎片，常驻内容越来越乱 |
| 界面是平铺列表 | 今天 / 人和事 / 变动三页，没搜索、没时间线、没项目页 | 几百条以后就翻不动 |

### 1.2 改法：四层，每层照搬现成代码

```
原文层   data/engine/state.db（已有，完整对话+工具过程，一字不丢）
   ↑ 每条记忆都带「出处」指针，能打开原文
经历层   经历/YYYY-MM-DD.md  —— W1 已有，W2 写厚：决定、文件、命令、数字、没做完的
   ↑ 每晚整理（照 OpenClaw dreaming：浅睡→REM→深睡）
项目层   事/<项目>.md —— 现在状态 / 定下的决定 / 没做完 / 来龙去脉，每行带出处
   ↑ 只把最稳定、最常用的提上去
常驻层   我 / 现状 / 它自己 / 最近在聊（W0/W1 已有）
```

- **细节不压缩，留指针**：任何一条记忆都能 `memory_search(open=出处)` 打开那段原对话（含工具过程），需要细节时读原文，不靠摘要。
- **检索**：关键词 + 本地向量混合，照 OpenClaw `hybrid.ts`（合并打分）、`temporal-decay.ts`（日记/经历按 30 天半衰，项目页和「我」不衰减）、`mmr.ts`（去掉重复的）。向量用 fastembed + `BAAI/bge-small-zh-v1.5`，本地 ONNX，不起服务。
- **想起来的量按需给**：平时相关块 ≤1200 字；问到「上次/之前/怎么做的」时放宽到 3000 字，并附上出处让模型自己去打开原文。
- **原始对话也能搜**：`memory_search` 多一个来源「原对话」，用现成的 `session_sync.search_session_messages`。
- **界面重做成记忆浏览器**：搜索框 + 筛选（来源 / 时间 / 项目）、时间线、项目页、人物页、关于你、变动记录；每条都能点开出处、跳到原对话；列表分页 + 虚拟滚动，上万条也不卡。原型见 `docs/memory/prototype-memory-browser.html`。

### 1.3 不做的

- 不上知识图谱（Graphiti/HippoRAG）、不装向量数据库服务；向量直接存在 `.index.sqlite`，numpy 暴力算，几万条以内足够快。
- 不改「事实只认亲口说的」规则。
- 每晚整理只写「事/」项目页和「现状」里有期限的未完成事项，**不往「我」里写**。

## 2. 共同边界（两个对话都必须遵守）

1. 工作区：
   - W2-A：`git worktree add -b memory-w2-api D:\atlas-mem-w2-api origin/ui-redesign`
   - W2-B：`git worktree add -b memory-w2-ui D:\atlas-mem-w2-ui origin/ui-redesign`
   - 已存在就停下报告，不要删。
2. 不要动 `D:\Atlas` 及其 `data\`（正在运行，且有别人未提交的改动）。试验一律用临时目录。
3. 不大重构、不改名、不调格式。注释少，提示文字用中文。
4. 做完各自提交、推送自己的分支，写结果文件，**不要合并**。

---

## 3. W2-A 后端（给第一个 Codex 对话）

**只许改**：
- `core/atlas/memory/library/` 下：`__init__.py`、`extract.py`、`index.py`、`store.py`、`queue.py`、`cleanup.py`
- 新建：`library/embed.py`、`library/hybrid.py`、`library/dream.py`、`library/sources.py`
- `core/atlas/api/memory_library_router.py`
- `core/atlas/agent/run_phases.py`：只许改 `_schedule_library_write` 和 `_note_tool_step`
- `core/atlas/kernel/tools.py`：只许改 `memory_search` 的 schema（第 78 行附近）
- `core/atlas/kernel/loop.py`：只许改 `if name == "memory_search":` 那个分支（第 1990 行附近）
- `core/pyproject.toml`：加依赖 `fastembed`
- 新建 `core/tests/test_memory_library_w2.py`、`docs/memory/W2-API-RESULT.md`
- **注意**：`kernel/loop.py`、`kernel/tools.py` 在 `D:\Atlas` 里有别人未提交的改动，所以这两处改动要尽量小，只碰上面说的位置，方便以后摘提交。

### A1. 出处指针（细节不丢的基础）

- `Entry` 加字段 `ref: str`，格式 `<session_id>@<ISO 时间>`（这一轮开始的时间）。事实、经历、日记块都写上。
- `schedule_turn` 收一个新参数 `turn_started`（`_schedule_library_write` 里用本轮开始时间传入；`_RunState` 没有的话就用 `state.runtime` 里能拿到的开始时间，实在没有就用入队时间）。
- 日记里回复从 300 字放宽到 **1500 字**；用户原话保持 2000 字。
- 新建 `library/sources.py`：
  - `open_ref(ref, window=1) -> dict`：用 `atlas.engine.session_sync.read_session_all_messages(DATA_ROOT/"engine", session)` 读整段会话，找到时间最接近 `ref` 时间的那条用户消息，返回从它开始到下一条用户消息之前的所有消息（含工具调用和结果）；`window=2` 再多带前后各一轮。每条工具结果最多 2000 字，总长最多 12000 字，超了截断并注明。会话不存在就返回 `{"ok": false, "reason": "原对话已删除"}`。
  - `search_raw(query, limit)`：包一层 `session_sync.search_session_messages`，返回统一格式 `{id, kind:"raw", text, at, ref}`。

### A2. 经历写厚

- `Episode` 和经历条目加字段（都是 list[str]，每项 ≤80 字，每类最多 5 项）：`decisions`（定下的事和理由）、`files`（读写过的路径）、`commands`（跑过的关键命令）、`facts`（关键数字/结论/版本号）、`open_items`（没做完、待确认的）。
- `SYSTEM_PROMPT` 的 EPISODES 节补上这五个字段的说明：只能来自本轮的用户话、回复和 TOOLS USED，不能编；没有就空列表。
- 经历 `text` 上限从 200 放宽到 400；同一会话合并时各列表合并去重、保留最近的 5 项。
- TOOLS USED 里每个工具的 note 从 80 字放宽到 200 字（`_note_tool_step`），并且对 `write_file/edit_file/apply_patch` 一类工具把参数里的路径放进 note，对 `local_exec/terminal` 一类把命令行放进 note（参数取 `tool_call` 事件的 `arguments`）。

### A3. 混合检索

- `library/embed.py`：懒加载 `fastembed.TextEmbedding("BAAI/bge-small-zh-v1.5")`，模型缓存到 `DATA_ROOT/cache/fastembed`。导入失败、下载失败就返回 None，并只打一次 `memory.library.embed_unavailable` 警告——检索退回纯关键词，**不能报错**。
- `.index.sqlite` 加表 `vectors(id TEXT PRIMARY KEY, dim INTEGER, vec BLOB, text_hash TEXT)`。`index.sync()` 之后，后台（`asyncio.to_thread`）给没有向量或 `text_hash` 变了的条目补算，每批 64 条。
- `library/hybrid.py`：照 OpenClaw `extensions/memory-core/src/memory/hybrid.ts`、`temporal-decay.ts`、`mmr.ts` 改写成 Python（源码在主机 `D:\_deliverables\官方拆解汇总\OpenClaw-Official-2026.10.3\03-SOURCE\extensions\memory-core\src\memory\`）：
  - 向量分（numpy 余弦，全量算）和关键词分（现有 `index.search` 的分数归一化到 0–1）按 id 合并；权重、默认值照 `hybrid.ts`。
  - 时间衰减：`日记/`、`经历/` 按日期半衰 30 天；`我/现状/它自己/人/事` 不衰减（对应 `isEvergreenMemoryPath`）。
  - MMR 去重，λ=0.7。
- `MemoryIndex.search` 内部改走混合打分，**签名不变**（W0/W1 的调用方不动）；新增 `kinds` 可取 `"raw"`，这时并入 `sources.search_raw` 的结果（只在显式要求时搜原文，平时不搜）。

### A4. 召回按需放量

- `_relevant_block`：
  - 平时：事实 3 条 + 经历 3 条 + 项目页命中的段落，总长 ≤1200 字。
  - `_RECALL_INTENT` 命中：总长放宽到 3000 字；经历带上 decisions/files/commands/open_items；再附一行「需要细节可用 memory_search(open="<ref>") 打开原对话」，列出最多 3 个 ref。
- 常驻块不变（1500 + 500）。

### A5. `memory_search` 工具加两个参数

- `open: str`（可选）：给了就直接返回 `sources.open_ref(open, window)` 的结果，不做搜索。
- `sources: list`（可选，`["memory","raw"]`，默认 `["memory"]`）：包含 `raw` 时也搜原始对话。
- 返回的每条结果都带 `ref`。工具描述里写清楚：「先搜，找到后用 open 打开原文看细节」。

### A6. 每晚整理（dream.py）

照 OpenClaw `extensions/memory-core/src/dreaming-phases.ts`、`dreaming-consolidation.ts` 的三段思路，用 Python 简化重写（不搬 cron 和 narrative 那套）：

1. **浅睡（收集）**：读 `.dream-state.json` 里的检查点，只取检查点之后新增/改过的经历条目（看 `at`）。
2. **REM（归类）**：按 `trigger` 和 `files` 的前两级目录把经历分组；同一话题在 **≥3 个不同日期** 出现（照 OpenClaw 的三天复现门槛），或者用户在经历里明确提到项目名，就算一个项目。
3. **深睡（写项目页）**：每个项目调用一次写记忆的模型，输入「现有 `事/<项目>.md`」+「新经历（含五个列表）」，输出四段：`## 现在状态`、`## 定下的决定`、`## 没做完`、`## 来龙去脉`。每一行是一个 `Entry`，`src="整理"`，`ref` 指向来源经历的 id（多个用逗号）。要求模型保留原页里 `src` 为「你说的」「你改的」的行原样不动。
4. 「没做完」里带明确期限的，另写进 `现状.md`（带 `until`）。**不写 `我.md`。**
5. 全部成功才推进检查点、`store.commit("整理：<项目1>、<项目2>")`；任何一步失败就不推进，下次重来（照 ReMe finish 的做法）。
6. 触发：后端启动后每天 03:30 一次（用现有 scheduler，找不到就 `asyncio` 定时任务）；另加接口 `POST /api/memlib/dream`（立即跑一次，返回报告）。
7. `SRC_DREAM = "整理"` 加进 `store.py`；`_label` 显示「（整理 · 日期）」；`INSTRUCTION` 补一句：「整理」是 Atlas 自己归纳的，以出处原文为准。

### A7. 接口（见第 6 节约定，后端负责实现）

### A8. 实测（写进结果文件）

1. 用临时目录 + 主机真实模型，跑一个 5 轮的小任务（读一个文件、改一行、跑一个命令、说一个决定、留一件没做完的事），贴出经历页原文，确认五个列表都有内容、都能对上原文。
2. 新会话问「刚才那个任务改了哪个文件、为什么」，贴出召回块和模型回答；再让它用 `open` 打开原文，贴出返回内容的前 40 行。
3. 生成 20000 条假事实/经历（脚本放 `.tmp`，不进仓库），测：`recall()` 耗时、`/api/memlib/search` 耗时、补向量总耗时。目标：recall < 80ms，搜索 < 150ms（向量已算好时）。
4. 用三个不同日期的假经历跑一次 `POST /api/memlib/dream`，贴出生成的 `事/<项目>.md`。
5. 卸掉 fastembed（或模拟导入失败）再跑一次搜索，确认退回纯关键词且不报错。

### A9. 测试（只写这些）

`test_memory_library_w2.py`：混合打分合并与衰减（固定时间）、MMR 去重、`open_ref` 找对那一轮且截断生效、经历五个列表合并去重、dream 只在全成功时推进检查点、embed 不可用时退回关键词。W0/W1 测试要分开跑并通过。

---

## 4. W2-B 界面（给第二个 Codex 对话）

**只许改**：
- `frontend/src/renderer/pages/MemoryPage.tsx`
- `frontend/src/renderer/components/memory/` 下的文件（可以新建）
- 新建 `docs/memory/W2-UI-RESULT.md`
- **不碰后端**。后端接口还没好时，用 `components/memory/mockMemlib.ts` 按第 6 节格式造假数据（20000 条，用来测滚动），开关放在一个常量里，默认关。

照原型 `docs/memory/prototype-memory-browser.html` 做（布局、文案、交互都以原型为准，配色和组件用现有 Tailwind 主题和 `styles/app.css` 的变量，三套主题都要能看）：

1. **左侧导航**：搜索、时间线、项目、人、关于你、变动记录；底部显示总条数、今天新增、上次整理时间和「立即整理」按钮（调 `POST /dream`）。
2. **顶部搜索框**（所有页都在）：输入即搜（300ms 防抖），筛选条：来源（你说的 / 你改的 / 推测 / 经历 / 整理 / 原对话）、时间（今天 / 7 天 / 30 天 / 全部 / 自定义）、项目。结果按分数排，显示片段高亮、来源标签、日期、所在页。
3. **时间线**：按天分组，倒序，滚到底自动加载下一页（`before` 游标）。经历卡片默认一行（标题 + 结果 + 已验证标签），点开显示决定 / 文件 / 命令 / 关键数字 / 没做完 / 步骤，以及「打开原对话」。
4. **项目页**：左边项目列表（按最近更新排，显示条数），右边四段：现在状态、定下的决定、没做完、来龙去脉。每行后面有出处小标签，点开在右侧抽屉里显示来源经历和原文片段。
5. **人物页、关于你**：沿用现有能改、能忘、能加的功能，改成新布局。
6. **出处抽屉**：调 `GET /api/memlib/open?ref=`，显示那一轮原对话（用户话、回复、工具调用折叠显示），顶部有「在对话里打开」（跳到对应会话，用现有的会话路由）。
7. **变动记录**：沿用现有，加按来源筛选（只看「整理」的变动等）。
8. 所有长列表用虚拟滚动（项目里已有就用现成的，没有就用 `@tanstack/react-virtual`，注意依赖要锁版本）。
9. 每条都保留「改 / 忘掉」操作，接口用现有的 `/entry`、`/forget`。

**验收**：用 mock 的 20000 条数据，时间线和搜索结果滚动不卡（截图 + 用 Performance 面板录一段说明掉帧情况）；三套主题各截一张图；`tsc` 和现有前端测试通过。

---

## 5. 合并顺序（Claude 做）

W2-A、W2-B 都推送后，由 Claude 审查，按 A → B 摘到 `ui-redesign`，关掉 mock，主机真机打开记忆页检查，再重启后端。

## 6. 接口约定（两边都按这个来）

所有接口在 `/api/memlib/` 下，现有接口保持不变，新增：

```
GET  /search?q=&src=经历,整理&from=2026-10-01&to=&project=&kinds=memory,raw&limit=30&offset=0
  → {"total": 123, "items": [{"id","kind":"fact|episode|diary|dream|raw","path","title","text",
      "snippet","src","at","ref","score","project"}]}

GET  /timeline?before=<ISO 时间，可空>&limit=50&src=
  → {"items": [Episode], "next": "<ISO 时间或 null>"}
  Episode = {"id","day","at","session","ref","text","outcome","verified","steps":[],
             "decisions":[],"files":[],"commands":[],"facts":[],"open_items":[],"trigger":[]}

GET  /projects
  → {"items": [{"path":"事/Atlas 记忆库.md","title","count","updated","open_items":3}]}

GET  /project?path=事/xxx.md
  → {"path","title","aliases","sections":{"现在状态":[Entry],"定下的决定":[Entry],
      "没做完":[Entry],"来龙去脉":[Entry]},"history":[Entry]}
  Entry 在现有 row 格式上加 "ref"

GET  /open?ref=<session@time>&window=1
  → {"ok":true,"session","title","messages":[{"role","text","at","tool":{"name","ok","args","output"}?}],
     "truncated":false}

GET  /stats
  → {"facts","episodes","projects","diary_days","today_added","last_dream":"ISO|null","pending_failed",
     "embed":"ready|building|unavailable"}

POST /dream → {"ok":true,"projects":["…"],"added":n,"changed":n,"error":null}
```

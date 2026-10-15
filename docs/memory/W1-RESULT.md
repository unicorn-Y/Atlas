# 记忆库 W1 执行结果

日期：2026-10-15（Asia/Hong_Kong）

工作区：`D:\atlas-mem-w1`

分支：`memory-w1`，基于 `origin/memory-v1`
主机实测模型：`gemini-3.8-flash`（读取主机现有模型设置；记忆库与运行数据均写入临时目录）

## 修改文件

- `core/atlas/agent/run_phases.py`：收集最多 30 个工具调用/结果步骤，连同 workspace 与真实验证状态传入记忆库。
- `core/atlas/memory/library/__init__.py`：测试会话入口过滤、经历队列与原子写入、最近经历常驻/相关召回、today 接口与忘记擦除。
- `core/atlas/memory/library/extract.py`：同次模型调用提炼 episode，解析并按 session/day 合并经历。
- `core/atlas/memory/library/index.py`：经历页面索引、episode 来源类别与日记相同的近期衰减。
- `core/atlas/memory/library/store.py`：经历页与条目元数据、枚举、忘记时同步擦除经历内容。
- `core/atlas/memory/library/queue.py`：队列字段迁移，兼容已有 `.queue.sqlite`。
- `core/atlas/memory/library/cleanup.py`：自动测试日记清理工具；本次仅执行 `--dry-run`。
- `frontend/src/renderer/components/memory/LibraryPages.tsx`：今天页增加经历条目、结果、验证标签和忘掉操作。
- `core/tests/test_memory_library_w1.py`：任务书第 8 节列出的 7 个测试场景。

## 第 7 节：主机真实模型实测

使用主机现有模型路由，前三句使用 session `w1-real-same-session`，第四句使用新会话。模型产生的前三条回复分别解释 Dots 的多种含义、介绍 AI 领域 Muse 项目、回复 `OK`。经历提炼也由同一主机真实模型执行。隔离根目录为 `C:\Users\25011\AppData\Local\Temp\atlas-memory-w1-real-6_z7_5lp`。

经历页原文：

```markdown
# 2026-10-15

## 现在
- 询问Dots相关内容：直接回答，列举不同领域中Dots的常见含义；直接回答 <!-- {"id":"m_1581c5eb6f","src":"经历","at":"2026-10-15T23:43:06+08:00","session":"w1-real-same-session","trigger":["dots","AI","Muse"],"outcome":"补充说明 AI 领域中相关的 Muse 技术与项目","verified":false} -->
```

页面只有一条；第三句没有再写经历；同一条保留首轮标题、追加第二轮的 did，topics 含 `dots` 与 `Muse`。临时根目录的 `我.md` 原文为空事实页，未因这些句子产生用户事实。

第四句 `recall()` 原始结果：

```json
{
  "resident": "## 最近在聊 / 在做\n- [10-15] 询问Dots相关内容：直接回答，列举不同领域中Dots的常见含义；直接回答 → 补充说明 AI 领域中相关的 Muse 技术与项目",
  "relevant": "",
  "refs": [],
  "system_block": "以下是 Atlas 记忆库里关于用户的记录，每条标了来源和日期。「你说的」「你改的」是用户本人确认过的；「推测」「它自己」不是用户说的。用户问到记录里没有的细节时，直接说不记得或不确定，绝不编造。「经历」是 Atlas 根据对话自己整理的，说明聊过和做过什么，不是用户确认过的事实；回答「之前怎么做的」时，要分清哪些步骤真验证过。和当前问题无关时不要硬提这些记忆。\n\n## 最近在聊 / 在做\n- [10-15] 询问Dots相关内容：直接回答，列举不同领域中Dots的常见含义；直接回答 → 补充说明 AI 领域中相关的 Muse 技术与项目"
}
```

新会话的真实模型答复：`根据记录，我们之前在讨论 Dots 的相关含义时，补充聊到过 AI 领域中的 Muse 技术与项目。` 答复说明只有这一项记录，不确定的其它产品没有编造。

审计 workspace `D:\Atlas\.tmp\audit-x\a` 的入口检查：日记页数与经历条目数前后均为 `[1, 1]`；捕获日志：

```text
memory.library.skipped session=w1-audit reason=workspace
```

## 第 5 节：真实数据目录 dry-run

仅运行：`python -m atlas.memory.library.cleanup --root D:\Atlas\data\memory --runs D:\Atlas\data\logs\runs --dry-run`。未执行删除模式。以下为原始输出：

```text
会删哪些块：
- 2026-10-15 16:12 76d90d3c-74e9-4e3a-a410-42d5b7e07d2f 仅回复 ATLAS_AUDIT_OK，不调用任何工具。
- 2026-10-15 16:32 67154948-118a-4215-a3b6-9c2f54cf2d3c 这是隔离运行测试。只读取当前工作目录 README.txt，准确回复其中 Ver
- 2026-10-15 16:35 e6afba3d-1af3-45a2-b69e-47c47d5baadb 请修好当前目录的 orders.py，使 summarize_orders 完整
- 2026-10-15 16:40 85505269-2588-4d13-9c60-3c1b4d0ea663 请依据当前目录的文档判断：自动发布最终有没有获批启用、原因是什么、何时重新评估？
- 2026-10-15 16:41 ce7458af-51b6-4858-9c5e-eca7baf327ef 按当前目录 README.md 的全部规则核对 orders.csv，生成且只生
- 2026-10-15 16:42 7a7ac21d-cd2c-4cad-a152-2cbcc4827442 执行当前目录 task.txt 的初始要求。必须先通过单独一次只读调用读取 ta
- 2026-10-15 16:42 e27f341d-8fd9-42b6-86af-ced7b10a5b39 在当前目录 records.log 中定位 event_id 完全等于 ATLA
- 2026-10-15 16:45 bf83f5f7-e848-4b88-ac7f-482f42473f9e [Gemini真实桌面补测] 请只读取 D:/Atlas/.tmp/audit-
- 2026-10-15 16:47 e300aee5-3c1b-46c3-a686-897d7f725ee6 这是只读权限测试。请只尝试一次用文件工具在当前目录创建 should-not-e
- 2026-10-15 16:47 058dd9ca-dc34-4ae2-9366-f6c22737b9cb 修好 orders.py，完整符合 README.md 所有规则。只允许修改 o
- 2026-10-15 16:53 8106a541-648b-4dd8-a1b9-b1af768a37dd 这是受控的长任务取消测试。只执行一次 local_exec：executable
- 2026-10-15 16:56 34be815b-52ef-49fc-b6a9-58b5cf3ff939 请清理当前目录中我不需要的文件，保留我需要的文件。哪些要保留、哪些能删除还没有告
- 2026-10-15 17:16 c648204e-fcd3-417b-8221-296023d67bbf 任务：只在当前工作目录创建 approved.json，内容严格为 {"appr
- 2026-10-15 17:17 c648204e-fcd3-417b-8221-296023d67bbf The plan above is approved. Execute it n
总数：14
```

## 测试

使用 `D:\Atlas\core\.venv\Scripts\python.exe`，代码从本工作区导入；两组分开执行：

```text
tests/test_memory_library_w1.py: 7 passed, 3 warnings in 5.78s
tests/test_memory_library_w0.py: 9 passed, 3 warnings in 12.94s
```

警告是现有 `settings_export_router.py` 中 Pydantic v2 class-based `config` 弃用提示。前端 TypeScript 检查未运行：此工作区没有 `frontend/node_modules/.bin/tsc.cmd`。

## 未做事项与边界

- 每晚经历整理、worker 经历归并仍按任务书暂缓；事实提炼规则未改变。
- 清理脚本只执行了真实数据目录的 `--dry-run`，没有删除真实记忆数据。
- 没有合并到 `memory-v1`，没有改动 `D:\Atlas` 的工作树或 data 内容。
- 早期测试曾在本工作区根目录创建若干未跟踪 `.pytest-temp-*` 目录。当前执行环境拒绝了针对这些目录的 `Remove-Item` 清理请求；这些临时目录不在下方提交范围内。

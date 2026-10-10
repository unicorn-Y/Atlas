# Atlas 自有引擎 ENGINE-V2-A 计划书（2026-10-10，与 ENGINE-V1 并行施工）

> ENGINE-V1（分支 `engine-v1`，工作树 `D:\atlas-engine`）正在另一个 Codex 聊天里做新内核。本批与它**并行**，所以只做**自成一体的模块**：放新目录、留好接口、**不接线**。V1 合并后再由一个小步骤接进内核。
> 用户要求：抄一流的；一次做完；**不写任何测试，不跑测试套件**。

## 0. 铁律（违反就会和 V1 冲突）

1. 工作树：`git -C D:\Atlas worktree add D:\atlas-engine2 -b engine-v2 origin/memory-v1`。**不要改 `D:\Atlas`，也不要碰 `D:\atlas-engine`。**
2. **禁止修改**：`core/atlas/kernel/`（V1 新建）、`core/atlas/engine/`、`core/atlas/agent/__init__.py`、`core/atlas/api/run_drive.py`、`core/atlas/tools/local_execution.py`、`frontend/src/main/backendProcess.ts`、`config/atlas.example.toml` 的 `[engine]` 段。需要和内核交互的地方，只在自己模块里定义接口（`Protocol` / 回调参数），不去实现接线。
3. 新代码只放在：`core/atlas/workflow/`、`core/atlas/rewind/`、`core/atlas/repomap/`，以及各自的 API 路由新文件（`core/atlas/api/workflow_router.py` 等，**不在 `server.py` 注册**，接线时再加）。
4. 每个移植文件写来源头 `# Ported from owner/repo@<sha>: path (License)`；闭源行为写 `# Behavior from Claude Code v2.1.296 docs: <链接>`。追加 `THIRD_PARTY_NOTICES.md`（只追加，不改别人的行）。
5. 先读上游源文件，按其数据结构和分支逐段翻成 Python，不凭印象重写。
6. 不写测试、不跑测试套件。只做 `python -c "import atlas.workflow, atlas.rewind, atlas.repomap"` 能导入。

固定提交：ZCode `29628c9acdb8`（Apache-2.0）、OpenCode `055d95bb7e27`（MIT）、Codex `806d9732c974`（Apache-2.0）、Aider `5dc9490bb35f`（Apache-2.0）。

## 1. 三个模块

### A. DAG 任务编排 `core/atlas/workflow/`
- **照抄**：ZCode `apps/zcode-cli/packages/core/src/workflow/`（`definition.ts`、`lifecycle.ts`、`scheduler.ts` 与 `scheduler/` 下的 `graph.ts`、`node-runner.ts`、`collection-planner.ts`、`collection-runtime.ts`、`planner-expansion.ts`、`events.ts`、`types.ts`、`prompts.ts`）；执行记录与重放参考 `apps/zcode-cli/packages/dynamic-workflow/src/engine/engine.ts`（只取 journal/replay，不要编译器/DSL）。
- **要有**：任务图定义（节点、依赖、负责人/文件归属）、ready 节点计算、并发上限（运行时传入，不写死）、节点失败阈值与重试、整图暂停/恢复、执行记录（journal）持久化到 SQLite（Atlas `data/` 下新表或新库文件 `workflow.db`，不碰 SessionDB）、事件流（节点开始/完成/失败/整图完成）。
- **对外接口**（V1 合并后接线用）：
  ```python
  class SubagentRunner(Protocol):
      async def run(self, *, goal: str, context: str, workspace: str, model: str | None) -> NodeResult: ...
  async def run_workflow(graph: WorkflowGraph, runner: SubagentRunner, *, max_parallel: int, on_event: Callable[[dict], None]) -> WorkflowResult
  ```
- **规划器**：照 ZCode `prompts.ts`/`planner-expansion.ts`，把一个大目标拆成任务图（调用模型的部分也走传入的回调，不直接 import 模型层）。

### B. 检查点与回退 `core/atlas/rewind/`
- **照做**：Claude Code 的 checkpoint/rewind 行为（https://code.claude.com/docs/en/checkpointing ：每次用户消息前自动存点；回退可选「只回代码 / 只回对话 / 两者都回」；回退前预览会改哪些文件）；源码照 OpenCode `packages/opencode/src/snapshot/index.ts` + `packages/opencode/src/session/revert.ts`（按消息边界撤回、快照与会话位置绑定）；Git 仓库内的快照参考 Codex `codex-rs/git-utils/src/`（`baseline.rs`、`operations.rs`）。
- **复用**：现有 `core/atlas/agent/checkpoints.py`（字节级快照存储）当底层存储，不另造一套；新模块在它之上加「与会话消息绑定」「按回合列出」「预览差异」「三种回退方式」。
- **对外接口**：
  ```python
  def checkpoint_before_turn(conversation_id: str, turn_id: str, workspace: str) -> str
  def list_points(conversation_id: str) -> list[RewindPoint]
  def preview(point_id: str) -> RewindPreview          # 将改动的文件和 diff
  def rewind(point_id: str, mode: Literal["code", "conversation", "both"]) -> RewindResult
  ```
  对话部分的截断只定义回调 `truncate_conversation(conversation_id, after_message_id)`，由接线时实现。

### C. 代码仓库地图 `core/atlas/repomap/`
- **照抄**：Aider `aider/repomap.py`（Python，直接改）：tree-sitter 抽取符号定义/引用 → 图排序（PageRank）→ 按 token 预算输出最相关的符号摘要；带缓存（按文件 mtime）。
- **要有**：Windows 路径与编码兼容；按 `.gitignore` 跳过文件；token 预算参数；结果缓存在 `data/repomap/`。tree-sitter 依赖加到 `core/pyproject.toml` 的依赖列表（这是唯一允许改的公共文件，只加依赖行）。
- **对外接口**：`build_repo_map(root: str, *, focus_files: list[str] = [], mentioned: list[str] = [], max_tokens: int = 2048) -> str`，以及一个工具描述字典 `REPOMAP_TOOL_SPEC`（接线时注册为工具）。

## 2. 交付

- 提交到 `engine-v2` 并 `git push origin engine-v2`。**不要推 memory-v1，不要合并 engine-v1。**
- 结果写 `tasks/results/ATLAS-ENGINE-V2-A.result.md`：每个模块做了什么、每个文件抄自哪里、对外接口签名、V1 合并后接线要改哪几处（列文件和函数）、没做完的、最终 SHA。

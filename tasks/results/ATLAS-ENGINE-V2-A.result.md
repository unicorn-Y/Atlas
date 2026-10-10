# Atlas ENGINE-V2-A 交付记录

## 范围与状态

- 工作树：`D:\atlas-engine2`，分支：`engine-v2`，基于创建时的 `origin/memory-v1`（`6ead616441a8aa34bd8d3fe24e2a118737fd2500`）。
- 计划书副本：`docs/plan/ENGINE-V2-A.md`；与桌面原件 SHA-256 相同：`7FEBF82F2FAF85F49E1C742FAC331C44A058056193E0A1D550E0A775538CC56E`。
- 实现提交：`dca26695fedec2231288c3dd993e54f2cc1f17dc`。结果记录随后单独提交，以避免把结果记录自身提交的 SHA 写回同一提交。
- 遵守并行边界：未修改 `D:\Atlas` 的工作文件，未访问或修改 `D:\atlas-engine`；功能代码只在三个新包内。未改内核、engine、agent、API、工具注册、前端或配置接线点。
- 已追加 `THIRD_PARTY_NOTICES.md`，且只增加内容；`core/pyproject.toml` 只增加 RepoMap 所需依赖行。

## A. DAG 任务编排：`core/atlas/workflow/`

实现了带依赖校验与 ready-frontier 的 DAG、可运行时指定的并行上限、节点重试/失败阈值、规划回调、动态 collection 扩展、事件回调和 SQLite journal/replay。默认 journal 使用独立的 `workflow.db`，不复用 SessionDB。还移植了计划点名的 Expert 八阶段定义、默认策略和 phase map/schema 校验。

| 文件 | 来源 |
| --- | --- |
| `types.py` | ZCode `apps/zcode-cli/packages/core/src/workflow/scheduler/types.ts` |
| `definition.py` | ZCode `apps/zcode-cli/packages/core/src/workflow/definition.ts`；校验形状参考 `packages/contracts/src/workflow/index.ts` |
| `graph.py` | ZCode `packages/core/src/workflow/scheduler/graph.ts` |
| `prompts.py` | ZCode `packages/core/src/workflow/scheduler/prompts.ts` |
| `node_runner.py` | ZCode `packages/core/src/workflow/scheduler/node-runner.ts` |
| `events.py` | ZCode `packages/core/src/workflow/scheduler/events.ts` |
| `lifecycle.py` | ZCode `packages/core/src/workflow/lifecycle.ts` |
| `scheduler.py` | ZCode `packages/core/src/workflow/scheduler.ts`；collection 调度阈值参考 `collection-planner.ts` |
| `planner.py` | ZCode `planner-expansion.ts`、`collection-planner.ts`、`collection-runtime.ts` |
| `journal.py` | ZCode `packages/dynamic-workflow/src/engine/engine.ts` 中的持久化 journal/replay 部分 |
| `__init__.py` | Atlas 包导出与接线边界 |

以上 ZCode 来源均固定在 `29628c9acdb81b703bbd4080c207a0e7ce5e276e`（Apache-2.0）。

主要接口：

```python
class SubagentRunner(Protocol):
    async def run(self, *, goal: str, context: str, workspace: str,
                  model: str | None) -> NodeResult: ...

async def plan_workflow(goal: str, *, workspace: str,
                        call_model: PlannerCallback,
                        model: str | None = None,
                        max_attempts: int = 3,
                        failure_threshold: int = 3) -> WorkflowGraph

async def run_workflow(graph: WorkflowGraph, runner: SubagentRunner, *,
                       max_parallel: int, on_event: Callable,
                       planner: PlannerCallback | None = None,
                       journal: WorkflowJournal | None = None) -> WorkflowResult

def pause_workflow(workflow_id: str, *,
                   journal: WorkflowJournal | None = None) -> None

async def resume_workflow(workflow_id: str, runner: SubagentRunner, *,
                          max_parallel: int, on_event: Callable,
                          planner: PlannerCallback | None = None,
                          journal: WorkflowJournal | None = None) -> WorkflowResult
```

`definition.py` 另导出 `create_expert_workflow_definition()`、`workflow_definition_phase_map()`、Expert workflow 常量和 `WorkflowDefinition` 类型。

## B. 检查点与回退：`core/atlas/rewind/`

新增 `RewindManager`，复用现有 `ShadowGitCheckpointStore` 的字节快照；将快照与 conversation/turn/message boundary 绑定，支持按会话列出、回退前文件与 diff 预览，以及 `code`、`conversation`、`both` 三种回退。对话截断通过注入的 `truncate_conversation(conversation_id, after_message_id)` 回调提供，没有接入 SessionDB 或现有 API。

| 文件 | 来源 |
| --- | --- |
| `__init__.py` | Claude Code v2.1.296 checkpoint 文档行为：`https://code.claude.com/docs/en/checkpointing`；OpenCode `packages/opencode/src/snapshot/index.ts`、`packages/opencode/src/session/revert.ts`；Codex `codex-rs/git-utils/src/baseline.rs`、`operations.rs` |

OpenCode 固定提交 `055d95bb7e278c94baf06235a52cac79dd13ba67`（MIT）；Codex 固定提交 `806d9732c974bc8a51b8317c1bd8985544fe627c`（Apache-2.0）。

主要接口：

```python
def checkpoint_before_turn(conversation_id: str, turn_id: str,
                           workspace: str, *,
                           after_message_id: str | None = None) -> str
def list_points(conversation_id: str) -> list[RewindPoint]
def preview(point_id: str) -> RewindPreview
def rewind(point_id: str, mode: Literal["code", "conversation", "both"], *,
           truncate_conversation: ConversationTruncator | None = None) -> RewindResult
```

## C. 代码仓库地图：`core/atlas/repomap/`

基于 Aider RepoMap 移植 tree-sitter 定义/引用查询、PageRank 图排序、focus/mentions 加权、文件 mtime 标签缓存、Git ignore 文件发现和预算裁剪。查询缓存位于 `<root>/data/repomap/tags.sqlite3`。新增依赖：`grep-ast==0.9.0`、`tree-sitter==0.25.2`、`tree-sitter-language-pack==0.13.0`，版本对应固定 Aider 提交的依赖。

| 文件 | 来源 |
| --- | --- |
| `__init__.py` | Aider `aider/repomap.py`，固定提交 `5dc9490bb35f9729ef2c95d00a19ccd30c26339c`（Apache-2.0） |
| `queries.py` | 同提交 `aider/queries/tree-sitter-language-pack/*-tags.scm` 查询定义 |

接口：

```python
def build_repo_map(root: str, *, focus_files: list[str] = [],
                   mentioned: list[str] = [], max_tokens: int = 2048) -> str

REPOMAP_TOOL_SPEC: dict[str, Any]
```

`max_tokens` 目前按代码内的通用估算器裁剪，不是特定模型 tokenizer 的精确计数；非 Git 目录的 `.gitignore` 回退解析覆盖常见模式，Git 仓库优先使用 Git 自身的忽略规则。

## V1 合并后的接线位置

本批按计划只交付独立模块，没有改动以下位置。V1 合并后接线时：

1. 在 V1 新增的 `core/atlas/kernel/` 工作流 dispatch 分支（该分支当前不在本工作树中，本批也未检查另一个聊天的工作树）适配 `SubagentRunner.run`，由规划回调调用 `plan_workflow`，调用 `run_workflow(..., max_parallel=..., on_event=...)`；暂停/恢复处理调用 `pause_workflow` / `resume_workflow`。现有外层运行入口是 `core/atlas/api/run_drive.py::_execute_run`（约第 2146 行），只作为定位参照，本批未修改。
2. 在 `core/atlas/api/run_drive.py::_execute_run` 的每回合执行前调用 `checkpoint_before_turn(conversation_id, turn_id, workspace, after_message_id=...)`，消息边界从当时会话尾部取得。将 `core/atlas/api/conversations_router.py::rewind_conversation` 委托到 `rewind(point_id, mode, truncate_conversation=...)`，回调桥接现有会话截断实现；`list_conversation_rewinds` 对应 `list_points`，预览接口对应 `preview`。同文件已有的 `truncate_conversation` 路由是截断行为的现有定位点。以上文件均未修改。
3. 在 `core/atlas/engine/tool_registry.py::bind_atlas_tools` 注册 `REPOMAP_TOOL_SPEC` 的处理器；处理器以当前 runtime workspace 调用 `build_repo_map(root=..., focus_files=..., mentioned=..., max_tokens=...)`。该文件属于本批禁止修改范围，未接线。

## 验证与未完成项

- 按计划未编写测试、未运行任何测试套件。
- 唯一代码验证命令：`python -c "import atlas.workflow, atlas.rewind, atlas.repomap"`（工作目录 `D:\atlas-engine2\core`），退出码 `0`。
- 有意未做 V1 合并和接线；需在 V1 合并后的单独集成步骤完成以上三处调用连接。
- 计划指定的固定上游源文件及提交已在对应移植文件头和 `THIRD_PARTY_NOTICES.md` 标注。实现提交 SHA：`dca26695fedec2231288c3dd993e54f2cc1f17dc`。

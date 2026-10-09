# Atlas 架构与开发参考 (Master Reference)

> **最后更新**：2026-10-10
> **项目路径**：`D:\Atlas`
> **定位**：本文件是 Atlas 的**架构与工程约定参考**，**不是**"当前任务看板"。
> 当前任务 / 波次状态以 `tasks/CURRENT.md` 与 `docs/plan/MEMORY-V1/CURRENT.json` 为准。

---

## 0. 权威文档地图（避免多份事实源）

| 想看什么 | 看哪里 |
|---|---|
| **当前任务 / 波次状态**（唯一入口） | `tasks/CURRENT.md` |
| 当前任务机器可读状态 | `docs/plan/MEMORY-V1/CURRENT.json` |
| 统一记忆 V1 任务书 / 验收场景 | `docs/plan/MEMORY-V1/00_任务书.md`、`01_验收场景.md` |
| 历史失败盘点 / 对抗审计 / 编排记录 | `docs/plan/MEMORY-V1/progress/`（`KNOWN_FAILURES.md`、`AUDIT_K3.md`、`CONTROLLER_RESUME_*.md`…） |
| 历史任务的结果与审查 | `tasks/results/`、`tasks/reviews/`、`tasks/taskbooks/` |
| 架构与工程约定（本文件） | `PLAN.md` |
| 上游调研 | `docs/research/` |

**规则**：不再新增并列的 `*-CURRENT.md`。旧 lane 的 `tasks/ZCODE-CURRENT.md` 已归档。

---

## 1. 项目概述

**Atlas** 是一个全能型 AI 私人助理，本地 Windows 11 部署、单人使用。
思路：不重复造轮子，整合成熟的本地 AI 组件（Hermes 引擎、MemoryOS 记忆、MCP 工具），
统一到一个 Electron 桌面入口 + 本地 Python 后端。

关键设计原则：模块化、MCP 标准化、Model-agnostic、本地优先、渐进式、接口预留。

---

## 2. 技术选型（与真实代码一致）

| 层 | 选型 | 代码位置 / 备注 |
|----|------|------|
| 桌面框架 | **Electron + React + TypeScript** | `frontend/`（electron-vite） |
| UI 风格 | 暖白简洁（Claude 风） | `frontend/src/renderer/` |
| 后端 | **Python ≥ 3.14** + FastAPI + Uvicorn | `core/atlas/server.py`、`core/atlas/api/` |
| Agent 引擎 | **Hermes fork**（editable 安装） | 见 `core/pyproject.toml [tool.atlas.hermes]`；适配层 `core/atlas/engine/hermes_runtime.py` |
| 模型访问 | **统一走 `atlas.models.router.ModelRouter`** | `core/atlas/models/router.py`；router 之外**不得**直连 litellm（AST 门禁） |
| 模型选择 | 手动选择（UI/config，非自动路由） | `config/atlas.toml`（本地、含密钥、已 gitignore） |
| 记忆系统 | **MemoryOS 统一记忆**（经 `/api/unified-memory/*` 代理）+ 可选 **MemOS** provider | `core/atlas/memory/`、`core/atlas/api/unified_memory_router.py` |
| 存储 | SQLite（会话 / 状态 / 记忆变更等） | `data/`（DB 已 gitignore） |
| 工具集成 | **MCP 为主** | `core/atlas/tools/`（含 x2 浏览器 / 桌面） |
| 技能库 | Hermes 格式 `SKILL.md` | `skills/`、`core/atlas/skills/` |
| 后台进程 | PM2（`ecosystem.config.js`）+ 内置调度器 | `core/atlas/scheduler/`、`core/atlas/automation/` |
| 通知 | Windows Toast + Telegram + 多渠道 | `core/atlas/notifications/`、`core/atlas/channels/` |

> 本机 `D:\Atlas\engine\` 是 **Hermes 运行时 home**（config.yaml / logs / installs / auth.lock），
> 属机器本地状态，**已 gitignore，绝不作为源码提交**。

---

## 3. 真实目录结构（顶层）

```
D:\Atlas\
├── core/                 # Python 后端（包名 atlas）
├── frontend/             # Electron + React 前端（dist/ 等产物已 gitignore）
├── backend-adapter/      # 前后端适配层
├── engine/               # Hermes 运行时 home（本机状态，gitignored）
├── data/                 # 运行时数据（DB / 配置，gitignored）
├── config/               # 配置模板 + 本地 atlas.toml（含密钥，gitignored）
├── skills/               # 技能库（Atlas 自有内容入库，注入的忽略）
├── scripts/              # 运维 / 评测脚本（unified_memory/、memory_v1/ 等）
├── docs/                 # 设计 / 调研 / 计划（plan/MEMORY-V1 为当前计划）
├── tasks/                # 任务书 / 结果 / 审查 + CURRENT.md（当前任务入口）
├── tests/                # 仓库级 fixture（真实测试在 core/tests）
├── artifacts/            # 测量输出（gitignored；历史遗留已取消跟踪）
├── ecosystem.config.js   # PM2 配置
├── package.json          # monorepo 根（workspaces: ["frontend"]）
└── PLAN.md               # 本文件
```

### `core/atlas/` 子系统

`agent/`（AgentOrchestrator、`run_phases`、`tool_node`）、`api/`（FastAPI app factory + 路由）、
`engine/`（HermesRuntime 适配）、`models/`（ModelManager + ModelRouter + tokens）、
`memory/`（capture / observer / reflector / recall_context / unified_facade / multimodal_bridge…）、
`tools/`（MCP + x2 浏览器/桌面）、`channels/`（slack/feishu/telegram/wecom/dingtalk/email…）、
`automation/`（调度 / 提醒）、`scheduler/`、`skills/`、`plugins/`、`safety/`、
`groups/`、`review/`、`projects/`、`persistent_agents/`、`capabilities/`、`heartbeat/`、`lsp/`、
`notifications/`、`runtime/`、`devices/`，以及 `usage.py`、`server.py`、`cli.py` 等。

---

## 4. 开发与验证命令

```bash
# 依赖（Python）
cd D:\Atlas\core && uv sync            # 或 pip install -e ".[dev]"

# 后端开发
cd D:\Atlas\core && python -m uvicorn atlas.server:app --port 8765

# 前端构建（根目录声明的验证命令）
npm run build                          # = npm --prefix frontend run build

# 测试（从 core 跑；仓库级 scripts/ 由 core/tests/conftest.py 注入 sys.path）
cd D:\Atlas\core && python -m pytest tests/ -q             # 默认 unit lane
cd D:\Atlas\core && python -m pytest tests/ -o addopts= -q  # 含 integration/desktop
```

### 质量门禁（必须保持绿）

| 门禁 | 测试 | 约束 |
|---|---|---|
| 异常门禁 | `tests/test_lint_gate.py` | critical 作用域（`atlas/(agent|api|engine|models|automation|channels|heartbeat)/`、`server.py`）**零** BLE001/S110/S112；其余作用域不得超基线 `tests/snapshots/ruff_exceptions_baseline.json` |
| 模型网关 | `tests/test_model_router.py::test_ast_no_acompletion_outside_router` | `atlas/` 内除 `models/router.py` 外不得直接 `import litellm` / `acompletion` |
| 路由快照 | `tests/test_route_snapshot.py` | 与 `tests/snapshots/routes.json` 一致；新增/改路由后重生成：`python tests/test_route_snapshot.py` |
| 子进程编码 | `tests/test_subprocess_encoding.py` | `text=True` 的 subprocess 调用必须显式 `encoding="utf-8"` |

> 处理 BLE001 的项目惯例：护栏 `except Exception` 在**被识别的 logger 变量**上带
> `exc_info=True`（或在 handler 中 re-raise）即被判定为「非盲 catch」；`except …: pass`
> 属 S110，需改为记录日志。

---

## 5. 关键约定（接手前必读）

1. **改代码前先读现有代码**；保持邻近风格（Python 全 type hints，TS 严格模式，不用 `any` / `@ts-ignore`）。
2. **所有修改都要能跑**；改完必须本地验证（测试 / 构建），不提交跑不起来的代码。
3. **一个任务一个 commit**；conventional commits（feat / fix / refactor / docs / test）。
4. **不得作弊**：不删除 / 跳过 / xfail 失败测试，不降低门槛，不用假数据 / 占位符冒充验收结果，
   不写死测试关键词适配。历史上出现过系统性造假（见 `docs/plan/MEMORY-V1/progress/AUDIT_K3.md`）：
   所有"完成"必须有可复现的原始证据（真实脚本 stdout / JUnit / HTTP 响应），**report 与代码必须一致**。
5. **单一事实源**："当前任务"只在 `tasks/CURRENT.md` 与 `docs/plan/MEMORY-V1/CURRENT.json`。
6. **热文件单 owner**（并行施工时）：`core/atlas/server.py`、`core/atlas/engine/hermes_runtime.py`、
   `core/atlas/agent/run_phases.py`、`core/atlas/memory/*`、Hermes fork、前端 `backendProcess.ts`。
7. **模型**：所有辅助调用走 `ModelRouter.complete_for(model_id, purpose, ...)`；业务代码不直连 litellm。
8. **提交边界**：`artifacts/`、`engine/`、`data/`、`config/atlas.toml`、`.construction-pack/` 等机器本地内容不提交。

---

## 6. 开源项目参考清单

> 实现遇到困难时，优先参考以下项目源码。

| 功能 | 项目 | 重点看 |
|------|------|--------|
| Electron + AI Chat | LobeChat (lobehub/lobe-chat) | 前端组件、流式渲染、会话管理 |
| 本地 Agent | Open Interpreter | CLI 交互、工具调用 |
| 模型代理 | LiteLLM (BerriAI/litellm) | provider 适配、streaming |
| SaaS 集成 | Composio | OAuth、工具注册 |
| 屏幕识别 | ScreenPipe | 截屏、OCR、搜索 |
| IDE Agent | OpenHands | 沙箱执行、工具设计 |
| 代码 Agent | Aider | git 集成、diff 编辑 |
| 本地 AI 助手 | Khoj | 记忆、搜索、自动化 |
| 桌面 AI | Jan.ai | Electron + 本地模型 |
| 多 Agent | CrewAI | 角色定义、任务分配 |

---

## 附录 A. 历史任务清单（Phase 1–6，已完成 / 被取代）

> 早期 `PLAN.md` 的 P1–P6 任务清单**已不再是施工入口**，仅作历史参考。相应能力均已落地或
> 被后续波次取代（后端 / 前端 / MCP / 技能 / 调度 / 通知见 `core/atlas/`、`frontend/`）。
> 追溯某功能来源：`git log -- <path>`。

- **P1 后端跑通**：依赖安装、CLI chat、配置系统（`core/atlas/config.py`）、REST API、基础测试、Git 初始化。→ 完成。
- **P2 Electron 前端**：electron-vite 初始化、暖白主题、布局框架、消息 / 代码块 / 工具卡片、
  模型选择器、WebSocket 流式对话、会话管理、托盘与快捷键、输入区。→ 完成（`frontend/`）。
- **P3 工具集成**：MCP 客户端、Agent 编排升级、filesystem / search / git MCP、工具调用 UI。→ 完成。
- **P4 技能迁移 + 定时任务**：技能格式（`skills/SKILL-FORMAT.md`）、技能迁移、调度系统、
  Windows Toast、设置页面。→ 完成。
- **P5 Web 界面 + Composio + Telegram**：Web 构建目标、Composio 集成、Telegram 通知。→ 完成 / 部分。
- **P6 第二阶段**：语音（LiveKit / Whisper）、屏幕识别（ScreenPipe）、Computer Use。→ 部分落地（x2 桌面/浏览器工具）。

> 早期文本中"MemoryStore = SQLite + FTS5"、"模型默认 claude-sonnet-4"、"Python ≥ 3.11"、
> "frontend 尚未创建"等均已过时——以第 2、3 节与真实代码为准。

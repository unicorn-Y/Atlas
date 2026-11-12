# AGENTS.md

这份文件是给"要动手改这个仓库的 agent"看的，不是给用户看的推介文档。
它只写那些**不知道就会踩坏东西**的事实。规则性偏好（遇到什么该停、什么不许糊过去）
在 `Atlas.md` 里，那是流程台账；这里是地图与禁区。

> 两者别混：`Atlas.md`（仓库根）= 流程记忆，`data/memory/事/Atlas.md` = 产品记忆，
> 在 `data/memory/` 那个独立的 git 库里。同名不同物。

---

## 1. 这是什么

Atlas 是一个本地优先的个人 AI 助手：Electron + React 19 桌面端，Python FastAPI 后端，
自研 async agent kernel。

| 位置 | 是什么 | 规模 |
|---|---|---|
| `core/atlas/` | 后端主体 | 621 个 `.py`，约 17.2 万行 |
| `frontend/` | 渲染层 + Electron 主进程 | 320 个 `.ts/.tsx`，约 5.5 万行 |
| `backend-adapter/` | 桌面端到后端的 TS 适配层 | — |
| `core/tests/` | 测试 | 258 个文件 |
| `data/` | 用户数据（记忆库、状态库），**独立 git 库** | — |

后端监听 `127.0.0.1:8765`（`config/atlas.toml` 里当前绑的是 `0.0.0.0`）。

---

## 2. 怎么跑

```powershell
# 后端（会自动做端口探测：端口被占会打印占用进程并退出 2）
cd core; python -m uvicorn atlas.server:app --port 8765

# 桌面端开发（Vite + Electron）
npm run dev

# 单测
cd core; python -m pytest -q -p no:cacheprovider
cd frontend; npm test
```

`pytest` 默认带 `addopts = "-m unit"`，所以**新写的测试必须标 `@pytest.mark.unit`**，
否则会被静默 deselect —— 看起来"通过"，实际上一条没跑。

`core/tests/conftest.py` 会把 `HOME` / `USERPROFILE` / `APPDATA` / `ATLAS_DATA_DIR` /
`ATLAS_SKILLS_HOME` 全部重定向到临时目录，并剥掉 `*_API_KEY` 等环境变量。
这意味着**测试碰不到真实数据**，除非显式 `ATLAS_LIVE=1`。别在测试里写真实路径下的断言。

---

## 3. 三条真源：改一个就得改三个

### 3.1 事件名

桌面事件名只有一个真源：`core/atlas/api/event_names.py`。

新增/改名/删除事件时，**同一次改动**里必须同步：

1. `core/atlas/api/event_names.py` — `DESKTOP_EVENTS`（后端真实发出）
2. `frontend/src/renderer/services/runtimeEvents.ts` — `known` 集合
3. `frontend/src/types/runtime.ts` — `AgentEventType` 联合类型

漏掉第 2 步的后果不是报错，是**静默丢弃**：`normalizeRuntimeEvent` 末尾
`if (!known.has(...)) return null`，帧直接消失，UI 上没有任何症状能和"功能没做"区分开。
之前有 16 个事件就是这么丢的，包括 `subtask.steered`（子任务接管反馈永远不显示）。

保证机制：`core/tests/test_event_contract.py` 会解析这两个 TS 文件，和 Python 侧对账。

事件分三类，别放错：
- `DESKTOP_EVENTS` — 后端发、渲染层收
- `DERIVED_EVENTS` — 渲染层合成（`artifact.updated` 来自 `artifact.created`）
- `CLI_EVENTS` — 终端 repl 专用（`turn.*` / `item.*` / `atlas.result`），不该进渲染层

### 3.2 服务注入

`AppServices`（`core/atlas/api/app_services.py`）有 51 个字段，**全部默认 `None`**。
路由里通过 `_service(name, services)` 取，取不到就回退到 `atlas.server` 的模块级单例。

也就是说：**新服务不加进 `AppServices`、不在 `server.lifespan` 里填，也不会立刻报错**，
只会在某条路径上拿到 `None`。自查手段：

```python
await registry.query("services", "unbound")   # 哪些字段还是 None
```

### 3.3 路由挂载

`core/atlas/api/application.py` 里有约 75 个 router import，靠 `:132-206` 那个
`for router in (...)` 元组统一 `include_router`。新 router 要加进那个元组，
否则模块存在、导入成功、路由不存在。

---

## 4. 自查入口（introspection）

后端自带一套只读自省面，共 7 个 provider / 28 个方法：

```python
from atlas.introspect import registry

await registry.query("services", "unbound")      # 没接线的服务
await registry.query("tools", "hidden")          # 建了但没暴露的工具
await registry.query("handlers", "shadowed")     # 被覆盖的事件处理器
await registry.query("health", "ports")          # 端口占用情况
await registry.query("governance", "check", {"action": "你打算做的事"})  # 撞上哪条台账
await registry.query("config", "keys")           # 配置键（已过 scrub，不含明文密钥）
```

**改完东西之后先跑这几个**，比读代码快，也比猜准。`services.unbound` 和
`tools.hidden` 应该看你这次改动相关的部分清零。

---

## 5. 禁区

- **`origin_guard` 不许放松。** 这是外部内容不进长期记忆的那道闸。
- **`data/memory/**` 不要顺手改。** 那是用户的真实记忆，独立 git 库，有重复 id 等历史问题，
  不是这次任务的处理对象。除非任务明确要求，否则一律不动。
- **`secrets_store.scrub` 之前的任何配置返回值都是泄漏。** `config/atlas.toml` 里
  `models.custom[0].api_key` 和 `web.keys.bocha` 是明文的，`redact()` 只按内容特征匹配，
  兜不住。任何返回配置的路径都必须过 `scrub`。
- **不要整理工作区里既有的未提交改动。** 仓库里长期挂着数百项未提交变更
  （`git status --short` 现在是 523 项）。只对你自己的新增负责。

---

## 6. 改长函数时的硬要求

`core/atlas/api/run_drive.py` 有 3747 行，`_handle_run_start` 一个函数从 `:1336` 到 `:2248`。
在这种地方增删语句，**缩进错一级不会报错**，只会让语句落到某个 `else` 分支里。

已经踩过一次：`run.user_input = content` 被缩进进了 `else`，导致记忆写回静默失败 ——
run 跑完了，记忆一条没存，没有任何异常。

改完用 AST 验一遍目标语句的深度和父节点：

```python
import ast
tree = ast.parse(open(p, encoding="utf-8").read())
# 找到目标行号对应的节点，确认它不是 Looper/If 的后代
```

---

## 7. 验证标准

- 单测通过 ≠ 能用。**真机真模型跑一遍**，把看到的输出贴出来。
- 说"修好了"之前，先把改动点在真实进程里触发一次（后端起来了没、事件到了没、
  文件写了没）。
- 没跑就说没跑。通过率不能冒充可用性。

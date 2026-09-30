# CODEX-ATLAS-BACKEND-PARITY-WAVE1 Review

REVIEW_RESULT: ACCEPTED（安全阻塞已由审阅方直接修复，见文末）
REVIEWED_HEAD: `f2655a1`
BASE_HEAD: `02fb0f0`

## Verdict

13 节接口全部按契约实现，路由名、事件名、字段名与任务书一致。笔记本复跑 `TestBackendParityWave1` + `test_agent_enrichment.py`：**30 passed**；全量 `core/tests`（跳过会操控真实鼠标的 `test_computer_use.py`）：**544 passed, 5 skipped**，结果文件里那个 locale 失败在笔记本上没有出现。启动新后端实测：
`/api/runtime/protocol` 返回 `1.3`；会话带 `pinned`/`archived`/`workspace`；中文搜索命中；`/api/workspace/tree`、`/api/workspace/rules`、`/api/processes`、`/api/checkpoints` 均正常。

实现本身接受，不要重写。但有一个必须先修的安全问题。

## 阻塞：任意网页可以操控本机 Atlas（CRITICAL）

- `server.py` 的 CORS 是 `allow_origins=["*"]` + `allow_credentials=True`，所有 WebSocket 路由都不检查 `Origin`。
- WebSocket 不受 CORS 约束，所以用户浏览器里打开的**任意网站**都能连 `ws://127.0.0.1:8765`：
  - `/ws/chat`：以 FULL_ACCESS 启动 Agent run（这个问题在本波之前就存在）；
  - `/ws/terminal`（本波新增）：直接拿到交互式 PowerShell。
- 复现：用 `Origin: https://evil.example` 连 `/ws/terminal?cwd=C:/Users/youdu`，服务端接受连接并把输入写进 PowerShell PTY（PSReadLine 回显了输入）。
- HTTP 也一样：`/api/workspace/file` 可读任意文件，`*` 的 CORS 让任意网页能读到响应。

### 修复要求

1. 新增统一的来源校验，允许的 Origin 只有：
   - 无 `Origin` 头（本机进程、CLI、测试客户端）；
   - `http://127.0.0.1:5173`、`http://localhost:5173`（vite 开发）；
   - Electron 打包后的来源：`frontend/src/main/electron.ts` 用 `loadFile(dist/index.html)`，页面是 `file://`，fetch/WebSocket 发出的是 `Origin: null` 或 `file://`，以实测为准。只放行这种情况会让其他本地 HTML 文件也能连；更稳的做法是让 Electron 主进程给后端传一个启动时随机生成的 token（环境变量），前端在 WebSocket/HTTP 请求里带上，后端校验；
   - 可由配置 `server.allowed_origins` 追加。
2. CORS 改成上面的白名单，不再用 `*`。
3. **所有** WebSocket 路由（`/ws/chat`、`/ws/terminal` 及其他）在 `accept()` 之前校验 Origin，不通过就以 1008 关闭。
4. 测试：外部 Origin 连 `/ws/terminal`、`/ws/chat` 被拒；外部 Origin 的 HTTP 请求拿不到 `Access-Control-Allow-Origin`；允许的 Origin 和无 Origin 正常。
5. 回归：打包版 Electron 前端仍能连后端（`npm --prefix frontend run dist:win` 后的冒烟，或至少核实打包页面实际发出的 Origin）。

## 非阻塞

1. **测试写进了用户真实数据目录。** `test_checkpoint_diff_and_invalid_run_filter` 用的是 `server.orchestrator.checkpoints`，默认目录 `%LOCALAPPDATA%\Atlas\checkpoints`；跑完测试后用户的「恢复」面板里会出现 pytest 临时目录的快照。测试 fixture 里把 checkpoint 存储指到 `tmp_path`，并检查其他新测试（processes、attachments 的 `~/.atlas/attachments`、rules 的 `~/.atlas/AGENTS.md`）有没有同样的问题。
2. `test_provider_reference_hash_matches_node_generated_mixed_path_fixture` 在 `zh-CN` 语言环境下失败（结果文件已说明），顺手把 fixture 补上 `zh-CN` 或让测试不依赖本机 locale。

## 前端接线

安全修复合入后，前端会接这一波的接口（steer、置顶/归档持久化、diff、终端、文件树、用量、规则、文件附件、Plan 模式、ask_user、编辑重发/分叉、每会话目录）。这部分不需要后端再改。

## 审阅方修复（2026-09-30）

用户决定由审阅方直接修复，不再退回 Codex：

- 新增 `core/atlas/origin_guard.py`：`OriginGuard` ASGI 中间件覆盖全部 HTTP 与 WebSocket 路由（含以后新增的）。放行：无 `Origin`、Vite 开发/预览来源、`server.allowed_origins`、或携带正确的 `X-Atlas-Api-Token`。`Origin: null` 必须带 token。WebSocket 在 accept 前以 1008 关闭，HTTP 返回 403。CORS 从 `*` 改为白名单。
- `ATLAS_API_TOKEN`：Electron 主进程每次启动随机生成，随环境变量传给它拉起的后端，并通过 `session.webRequest.onBeforeSendHeaders` 附加到发往后端的 HTTP/WebSocket 请求上；渲染进程拿不到这个值。
- 已知限制：打包版如果复用一个手动启动、没有 token 的后端，`null` 来源会被拒；开发模式（5173）不受影响。
- 前端适配层原来要求协议版本严格等于 `1.2`，本波升到 `1.3` 后前端无法发起任何 run。已改为按主/次版本比较，≥1.2 即可，并补测试。
- `test_checkpoint_diff_and_invalid_run_filter` 改用临时 checkpoint 目录。
- 验证：`core/tests/test_origin_guard.py` 6 passed；打包模式（`file://`）实测 HTTP、CORS 预检、`/ws/chat` 均正常并完成一次真实对话；外部 Origin 与伪造 `null` 连 `/ws/terminal`、`/ws/chat`、`/api/workspace/file` 全部被拒。

# PAR-10 T6-21 · 本机 remoteAccess 分资源 ACL（F10-cloud / D4）

- 工位: PAR-10 补位 T6-21（remoteAccess 分资源 ACL / F10-cloud 产品差距）
- 候选树: `D:\Atlas\.worktrees\zcode-par10-remote-access`，分支 `zcode/par10-remote-access`
- 基线: wave3 `060071ab`（工作树起始干净：`git status --short` 为空）
- 日期: 2026-11-20
- 边界: 未 reset/stash/clean/commit/push/merge；未合回主树；未碰 `app_server.py` / `run_drive.py`；
  未放松 `origin_guard.py`；未做真实模型/付费调用；端口 18960–18969；所有 TEMP/TMP/profile/日志/
  basetemp 在 `D:\Atlas\.worktrees\_codex-par10-probes\t6-21-r2\`。
- 状态: **READY**（D4 四项全部通过真实回环；两项后续见 §7，不阻塞本包验收）

---

## 1. DSH 基准（公开源码，atlas-target-rc5）

| 契约 | DSH 位置 | 可观察语义 |
|---|---|---|
| 策略注册/失效 | `packages/api/remote-access/src/index.ts:153-186` | `registerPolicy(kind, policy)` 每 kind 一个；注册/卸载都 `invalidate()`；`invalidate(principal?)` 清失败日志并按 principal 唤醒打开的 snapshot |
| 决策 | `index.ts:199-257` | owner 与 `remoteAccess/follow` 恒 allow；无 policy → `no-allow`；每资源需匹配 binding（role 含 action + condition 允许）；condition 拒绝原因优先于 `explain()`，其次 `no-allow`；policy/condition/explain 抛错 → `policy-failed`，两次 invalidate 之间每 policy 只记一次日志 |
| 列表过滤 | `index.ts:235-247` | `allows(resource)` 从当前 invocation 取 action/principal；owner/无 invocation 恒真；policy 缺失或失败为 false |
| 快照 | `index.ts:253-300,355-377` | owner baseline `{owner:true}`；非 owner baseline grants（每资源 actions 排序、事件 action 不进快照）；follow 在 invalidate 后推 upsert/remove 差量 |
| Client 面 | `client/mount.ts:43,55,95-105,120`；`client/state.ts:95` | `source(kind,id,action)`；`whenAccess(action, callback)` 在答案变真时挂载、变假时按逆序 dispose、再变真时重挂 |
| 执行侧 | `gateway/src/index.ts:633,814-822`；`session-controller/src/index.ts:284,298,636,641` | 非 owner 调用 decide（拒绝抛 `remote-access/denied{action,reason}`）；转发事件逐帧 decide，deny 直接丢弃；列表/流用 allows 过滤 |

## 2. Atlas 基线（wave3@060071ab，改动前）

- `core/atlas/remote_access.py:38-89`：只有短期 bearer 会话（token hash + expiry），无 principal/policy/decision/snapshot。
- `core/atlas/origin_guard.py:59-66`：token 有效即 `is_trusted=True`，整个 HTTP/WS 面放行，无资源/方法维度。
- `core/atlas/api/remote_router.py:16-58`：远程页/start/status/stop，`/api/remote/tasks` 直接列全部会话，无逐项过滤。

## 3. 本候选树实现

### 3.1 `core/atlas/remote_access.py`（契约主体）

| 内容 | 行 |
|---|---|
| `Principal(kind,id)`、`RemoteAccessRole/Binding/Decision`、`allow()/deny()` | 61-135 |
| `invocation(principal, action)` contextvar（供 `allows`） | 148-160 |
| 会话记录扩展 `principal` / `grants`；`principal_for_token`（API token→owner，remote token→session principal；旧记录缺 principal 仍按 owner 兼容） | 175-345 |
| `revoke_remote_session` 在删除后 `invalidate()`（唤醒所有 follow） | 355-372 |
| `update_session_grants`（owner 改权后 `invalidate(principal)`） | 336-353 |
| `register_policy(kind, policy)`（重复 kind ValueError；返回幂等 disposer；注册/卸载 invalidate） | 495-527 |
| `decide({principal,action,resources,args})`（owner/follow 短路；无 policy→no-allow；bindings 一次；每资源 evaluate；condition>explain>no-allow；异常→policy-failed） | 634-687 |
| `allows(resource)`（无 invocation→true；owner→true；每次重读 bindings；policy 失败→false） | 689-712 |
| `invalidate(principal?)`（清 `_REPORTED`；按 canonical principal 唤醒 follower） | 715-733 |
| `grants_for` / `snapshot_for`（每资源 grant，actions 排序，排除 `event:`，拒绝的 action 不出快照） | 736-777 |
| `follow(principal, cancel)`（baseline → upsert/remove；remote 会话被撤销时 remove 全部已发 grant + `deny{reason:"revoked"}` 后结束） | 817-875 |
| 内置 `_SessionGrantPolicy`：bindings 从会话 grants 读；会话消失时 explain 返回 `session-revoked` | 878-905 |
| DSH 名称别名 `registerPolicy` / `snapshotFor` | 920-922 |

失败日志：`_report()` 每 `_PolicyEntry` 在两次 `invalidate()` 之间只写一条 `logging.WARNING`（含 exc_info），
`invalidate()` 清空 `_REPORTED`。所有 policy/condition/explain 异常都被包含，不破坏共享事件流。

### 3.2 `core/atlas/api/remote_router.py`（HTTP/WS 面）

| 入口 | 行为 |
|---|---|
| `POST /api/remote/access` | 仅 owner；无 grants → 旧 owner 会话；带 grants/principal → limited `remote` 会话；返回 principal/grants |
| `GET /api/remote/status` / `POST /api/remote/stop` | 仅 owner（非 owner → `{code:"remote-access/denied",action,reason:"owner-only"}`） |
| `POST /api/remote/grants` | 仅 owner；改 grants 后经 `invalidate(principal)` 推送到已连接 follow 流 |
| `GET /api/remote/tasks` | `with invocation(principal,"remote/tasks"): allows({kind:"session",id})` 逐项过滤；owner 全量 |
| `POST /api/remote/conversations` | decide `conversations/create` on `{kind:"global"}` |
| `GET /api/remote/conversations/{id}/messages` | decide `conversations/read` on `{kind:"session",id}`；拒绝统一 403 detail |
| `GET /api/remote/access/snapshot` | `snapshot_for(principal)`（owner baseline / grants baseline） |
| `POST /api/remote/access/decide` | 对调用者自身回答 `{action,resources,args}`，返回 `{kind,reason}` |
| `WS /ws/remote/access` | follow 流：baseline/upsert/remove/deny；撤销后发 remove+deny 并以 4403 关闭 |
| `WS /ws/remote/events` | 逐帧 `decide(principal,"event:<name>",resources)`；未授权帧丢弃，不投递；撤销后发 `deny{reason:"revoked"}` 并 4403 关闭 |
| `publish_remote_event(event,data,resources)` | 事件 fan-out 接缝（给未来 runtime producer 调用）；返回 `{subscribers,delivered,dropped,revoked}` |
| `RemoteAccessSurfaceGuard` | ASGI 中间件：非 owner bearer 仅可访问 `/remote`、`/api/remote/*`、`/ws/remote/*`；其余 HTTP 403 `limited-token-surface`、WS 1008。无效 bearer → 401 `unauthenticated`。owner/无 token 直通 |

拒绝返回统一形状：HTTP `403 {"detail":{"code":"remote-access/denied","action":<endpoint>,"reason":<reason>}}`；
reason 取值 `no-allow` / `policy-failed` / condition reason / `explain` reason / `owner-only` /
`unauthenticated` / `limited-token-surface` / `revoked` / `session-revoked`。

挂载点（最小接线）：`core/atlas/api/application.py:65,133` 在 `OriginGuard` 内侧加
`RemoteAccessSurfaceGuard`（OriginGuard 仍最外层，既有闸未放松）。`remote_router` 已在
`application.py` 的 router 元组里，新增路由自动挂载。

### 3.3 Renderer（最小可验证接线）

- `core/atlas/api/remote_router.py` 内嵌移动页：新增 `whenAccess(kind,id,action,mount,unmount)` 与
  `applyAccess()`；`id="createCard"` 仅在 global `conversations/create` 允许时挂载，
  `id="replyCard"`/run controls 仅在当前 session `runs/start`/`runs/control` 允许时挂载；
  页面从 `/api/remote/access/snapshot` 读 baseline，并连 `/ws/remote/access` 跟随 upsert/remove/deny，
  撤权即关闭入口。消息读取改走 `/api/remote/conversations/{id}/messages`（带 ACL），创建改走
  `/api/remote/conversations`。
- `frontend/src/renderer/services/remoteAccess.ts`：框架无关的 `RemoteAccessState`，
  `source/global/resource/whenAccess/whenResourceAccess`，baseline/upsert/remove/closed 语义与
  DSH client/state+mount 对齐；`remoteAccess.test.ts` 覆盖 owner、逐资源、挂载/卸载/重挂、流失败关闭、
  injected baseline 校验。桌面 React 组件迁移不在本包（见 §7）。

## 4. D4 四项验收矩阵

| # | D4 验收项 | 结果 | 证据 |
|---|---|---|---|
| 1 | 远程会话附带 principal 与授权快照；敏感 API/WS 读取按 (action,resource) 判定，拒绝返回统一 reason | **PASS** | limited token 带 `{kind:"remote",id:<session>}` + grants；`/api/remote/tasks` 只返回 conv-a；`/api/remote/conversations/conv-b/messages` → `403 {code:"remote-access/denied",action:"conversations/read",reason:"no-allow"}`；`/api/remote/access/decide` 同 reason；snapshot 为 `{type:"baseline",owner:false,grants:[{resource:{kind:"session",id:"conv-a"},actions:["conversations/read","remote/tasks"]}]}`；非远程面 → `403 limited-token-surface`；`/ws/chat` 握手被拒 |
| 2 | 授权变更可推送到已连接客户端（等价 follow），不要求重载 | **PASS** | 已连接 `/ws/remote/access`：owner 改 grants 后收到 `upsert(conv-b)`；移除 grant 后收到 `remove(conv-b)`；撤销 token 后收到 `remove(conv-a)` + `deny{reason:"revoked"}`，socket close 4403 |
| 3 | UI 能力入口按快照条件挂载（等价 whenAccess），撤权即关闭 | **PASS（最小接线）** | 移动 renderer 的 `createCard/replyCard/controls` 由 `whenAccess` 条件挂载并跟随 `/ws/remote/access`；`frontend/.../remoteAccess.ts` 的 `whenAccess` 5 项 vitest 通过；撤权帧到达后 `applyAccess()` 立即隐藏入口 |
| 4 | 隔离后端 + 两 token 配对：limited 读其他会话拒绝码/reason；撤销令牌后已连接流 remove/拒绝；事件流未授权帧丢弃 | **PASS** | pytest 真实回环 30/30；独立 uvicorn 子进程探针 10/10（见 §5）。owner 全量可读/可建/可管理；limited 只读 conv-a |

补充策略语义验收（18 个 unit 测试全过）：
owner/follow 恒允许；无 policy → no-allow；每资源需匹配 role action；bindings 每次 decide 只调一次；
condition 原因优先于 explain；args 传入 condition；policy/condition/explain 异常 → policy-failed；
`caplog` 证明两次 invalidate 之间只记 1 条 warning；重复 kind 注册 ValueError；`allows` 仅在
invocation 内过滤且每次重读 bindings；snapshot 排除 event action 和拒绝 action；session token
principal/grants/撤销；旧会话缺 principal 仍按 owner；follow baseline→upsert→remove→revoked。

## 5. 命令与退出码（2026-11-20，全部隔离目录）

公共环境（每条命令均显式注入，未改全局环境）：
```bash
TEMP=D:\Atlas\.worktrees\_codex-par10-probes\t6-21-r2\tmp
TMP=...\tmp
PYTHONDONTWRITEBYTECODE=1
--basetemp=...\tmp\<name>
```

| # | 命令（cwd） | 结果 | 日志 |
|---|---|---|---|
| 1 | `python -m pytest -q -p no:cacheprovider -o addopts= --tb=short --basetemp=...\tmp\final-unit2 tests/test_remote_access.py`（`core/`） | **EXIT=0**，`18 passed` | `logs/final/unit.log` |
| 2 | `python -m pytest -q -p no:cacheprovider -o addopts= --tb=short --basetemp=...\tmp\final-loop2 tests/test_remote_access_loopback.py -s`（`core/`） | **EXIT=0**，`1 passed`；矩阵 `total=30 passed=30` | `logs/final/loopback.log` |
| 3 | `python probe_client.py`（`...\t6-21-r2\probe`，独立 uvicorn 子进程 127.0.0.1:18960） | **EXIT=0**，`PROBE_PASS checks=10 port=18960` | `logs/final/probe.log` |
| 4 | `PYTHONPATH=<worktree>/core python .../probe/full_app_guard.py`（`core/`，`create_app` 真实组合） | **EXIT=0**，`FULL_APP_GUARD_PASS`（limited HTTP 403 limited-token-surface；`/ws/chat` WebSocketDisconnect） | `logs/final/full-app-guard.log` |
| 5 | `python` 调用 `scripts.u14_check.check_remote_access()`（`core/`） | **EXIT=0**，`U14 ... PASS`（旧 owner 会话/外部 bearer/任务列表/撤销回归） | `logs/final/u14.log` |
| 6 | `python -m pytest ... tests/test_origin_guard.py -k 'not office_preview'`（`core/`） | **EXIT=0**，`16 passed, 1 deselected` | `logs/final/origin.log` |
| 7 | 提取内嵌 `<script>` 后 `node --check` | **EXIT=0** | `logs/final/node-check.log` |
| 8 | `../node_modules/.bin/vitest run --root . src/renderer/services/remoteAccess.test.ts`（`frontend/`，临时 junction 后已移除） | **EXIT=0**，`5 passed` | `logs/final/vitest.log` |
| 9 | `../node_modules/.bin/tsc -p tsconfig.renderer.json --noEmit`（`frontend/`） | **EXIT=0** | `logs/final/tsc.log` |

独立进程探针 10 项输出（`logs/final/probe.log` 原文）：
```
PASS 01 owner status
PASS 02 limited session minted
PASS 03 limited list filtered to the granted session [['conv-a']]
PASS 04 limited read of another session denied [{"code":"remote-access/denied","action":"conversations/read","reason":"no-allow"}]
PASS 05 limited token cannot bypass the remote surface [limited-token-surface]
PASS 06 follow baseline
PASS 07 revocation pushed remove+deny and closed 4403
PASS 08 authorized event delivered
PASS 09 unauthorized event frame dropped
PASS 10 revoked event subscriber received deny
PROBE_PASS checks=10 port=18960
```

## 6. 失败 / 未验 / 预存红

| 项 | 事实 | 归属 |
|---|---|---|
| `tests/test_route_snapshot.py::test_routes_match_frozen_snapshot` | **EXIT=1**。冻结快照在基线 `060071ab` 即已落后：实际路由比快照多 27 条，其中 **20 条与本包无关**（如 `/api/permissions*`、`/api/plugins/*/patches`、`/api/conversations/{id}/explain` 等），本包新增 7 条（`/api/remote/access/decide`、`/api/remote/access/snapshot`、`/api/remote/conversations`、`/api/remote/conversations/{id}/messages`、`/api/remote/grants`、`/ws/remote/access`、`/ws/remote/events`）。未重生成快照，避免把 20 条无关漂移一并烘焙进候选树。 | 预存红 + 本包路由登记 |
| `tests/test_route_snapshot.py::test_fastapi_lazy_includes...` | **EXIT=1**，`AttributeError: 'APIWebSocketRoute' object has no attribute 'original_route'`（当前 FastAPI 版本与测试写的旧属性不兼容），与本包无关。 | 预存环境不兼容 |
| `tests/test_origin_guard.py::test_office_preview_route_uses_origin_guard` | `ModuleNotFoundError: No module named 'docx'`（当前解释器未装 python-docx），与本包无关；该文件其余 16 项通过。 | 环境缺依赖 |
| 产品运行事件源接线 | `/ws/remote/events` 已按帧 decide/丢弃并用真实 WS 验证，但**生产 run 事件尚未调用 `publish_remote_event`**。接线点应为 `RuntimeManager.send`（用 `conn_runs[conn_id]` 找 run → `conversation_id` 作为 session resource）或 `run_drive` 的 emit 路径；这两个文件不在本包改动范围（`run_drive.py` 明确禁改）。 | 后续（不阻塞契约验收） |
| 桌面 React 组件迁移 | `frontend/.../remoteAccess.ts` 提供与 DSH 同名 `source/whenAccess` 的框架无关实现并有 vitest；真正把设置/任务等 React 入口迁到 `whenAccess` 未做，当前实际挂载点是移动 renderer。 | 后续（按任务 §4 允许） |
| limited token 的运行控制 | limited token 被 surface guard 限制在 `/remote`、`/api/remote/*`、`/ws/remote/*`，不能连 `/ws/chat`，因此本包只支持**只读** limited token（符合 D4 验收的 “limited 仅只读某会话”）。若未来要给 limited 运行控制，需要新增远程 run WS 或受控事件上行面。 | 设计边界 |
| 真机桌面/手机 | 未启动 Electron 成品、未用真实手机浏览器；renderer 只做 JS 语法校验 + 页面标记单测。 | 未验（超出本包） |

## 7. 改动范围

| 文件 | 类型 | 说明 |
|---|---|---|
| `core/atlas/remote_access.py` | 修改（102→928 行） | 保留原 bearer 会话 API；新增 Principal/policy/decide/allows/snapshot/follow、内置 session policy、owner 兼容 |
| `core/atlas/api/remote_router.py` | 修改（65→577 行） | 新增 ACL 路由/两个 WS/事件 fan-out/移动页 whenAccess 接线/surface guard |
| `core/atlas/api/application.py` | 修改（+2 行） | 最小接线：在 OriginGuard 内侧挂 `RemoteAccessSurfaceGuard` |
| `core/tests/test_remote_access.py` | 新增 | 18 个 unit 测试（policy 语义/快照/follow/会话/页面挂载点） |
| `core/tests/test_remote_access_loopback.py` | 新增 | 1 个 integration 测试，真实 uvicorn 127.0.0.1:1896x，30 项断言 |
| `frontend/src/renderer/services/remoteAccess.ts` | 新增 | Client snapshot/whenAccess（框架无关） |
| `frontend/src/renderer/services/remoteAccess.test.ts` | 新增 | 5 个 vitest |

未改：`core/atlas/origin_guard.py`（闸未放松，新增的是下游更严的限制）、`core/atlas/tools/app_server.py`、
`core/atlas/api/run_drive.py`、`core/atlas/api/runtime.py`、`core/atlas/api/runtime_ws_router.py`、
`core/tests/snapshots/routes.json`。未产生 commit/push/merge。

## 8. 建议主控写入的行（本包未改台账）

**ATLAS-MAP.tsv**（替换 `B-F10-REMOTE-01` 行）：
```
B-F10-REMOTE-01	core/atlas/remote_access.py:61-922(Principal/policy/decide/allows/snapshot_for/follow/内置 session policy); core/atlas/api/remote_router.py:114-537(remote access/tasks/messages/grants/snapshot/decide + /ws/remote/access + /ws/remote/events + publish_remote_event + RemoteAccessSurfaceGuard); core/atlas/api/application.py:133(guard 挂载); frontend/src/renderer/services/remoteAccess.ts:112-185(RemoteAccessState/whenAccess)	分资源 ACL + 每 Peer 快照流 + limited-token 面收敛；owner 全权，limited 仅 grants 内资源	zcode/par10-remote-access@060071ab	已实现(契约+真实回环)	evidence/par10-t6-21-remote-access.md	剩余: 生产 run 事件未接 publish_remote_event(RuntimeManager.send/run_drive);桌面 React 组件未迁移;route snapshot 预存红(20 条无关漂移)	F10-cloud
```

**BEHAVIORS.tsv**（更新 `B-F10-REMOTE-01` 的 `verification_state`，outcome 追加）：
```
B-F10-REMOTE-01	10 协作、可观察云契约与配置	remoteAccess 分资源访问控制(host decide/allows/follow + client source/whenAccess)	...（原 entry/handler/state_data/source_ids/dsh_evidence 列不变）...	allow / deny(reason 取 condition>explain>no-allow,或 policy-failed);拒绝调用 403 remote-access/denied{action,reason},拒绝事件帧丢弃;撤权后 follow 推 remove+deny(4403);Atlas 已实现 owner/remote principal、session grants、surface guard	<原 source_ids>	<原 dsh_evidence>	实现+真实回环(30/30,pytest+独立进程 10/10)
```

## 9. 复现路径

- 候选树: `D:\Atlas\.worktrees\zcode-par10-remote-access`
- 测试: `core/tests/test_remote_access.py`、`core/tests/test_remote_access_loopback.py`
- 独立探针: `D:\Atlas\.worktrees\_codex-par10-probes\t6-21-r2\probe\probe_client.py`（+ `probe_app.py`、`full_app_guard.py`）
- 日志: `D:\Atlas\.worktrees\_codex-par10-probes\t6-21-r2\logs\final\`
  （`exits.txt` 含一次 `FULLAPP_EXIT=1`：首次 `full_app_guard.py` 未设 `PYTHONPATH`，导入到主树旧版
  `remote_access` 而报 `unexpected keyword argument 'grants'`；显式设 worktree PYTHONPATH 后复跑 EXIT=0，
  见同目录 `full-app-guard.log`）
- 端口: 18960–18969（pytest 取空闲端口，独立进程探针实测 18960）；未使用 8765。

PAR10_RECEIPT T6-21 READY

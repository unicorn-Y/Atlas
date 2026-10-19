# Atlas 差距分析 · Claude Desktop/Cowork 2.42304.0 vs Atlas `main@aa6196f5`

**基线**：Atlas `main` @ `aa6196f550098cc46081dc6db2c376cb87ddffa5`（2026-10-06 06:18:06 +0800）。
所有 Atlas 侧论述都带**文件路径 + 行数或符号名**，可从 git 直接复核。
所有 Claude 侧论述都带**文件偏移或 UIA 观测**，见 `DISCOVERY-LEDGER.md`。

本文**不是**「Claude 更好，去抄」的清单。三条已经比对完的结论里，有两条我认为 **Atlas 的选择更对**（见 §7）。

---

## 1. Agent Loop 归属 —— 最根本的架构分歧

| | Claude Desktop | Atlas |
|---|---|---|
| agent loop 在哪 | **不在桌面端**。在 Claude Code 引擎二进制内，桌面端通过 stdio `stream-json` 驱动 | **在进程内**。`core/atlas/agent/` 21 个模块 |
| 证据 | `index.chunk-DNyequwM.js` @1131100–1134600 构造 30+ 个引擎开关；`ProcessTransport` spawn | `core/atlas/agent/orchestrator.py`、`run_phases.py`、`planning.py`、`todo_state.py` |
| 边界 | 桌面端只做：状态映射、权限应答、UI、VM 管理 | Atlas 自己做：编排、规划、重试、压缩、子代理、校验 |

**这不是能力差距，是产品形态差异。** Claude Desktop 要同时服务 CLI 用户和桌面用户，
把 agent loop 抽成引擎二进制是两个前端共享内核的唯一合理做法。
Atlas 是单一宿主，把 loop 放进程内可以直接改、直接测、直接观测。

**代价对比**：
- Claude 侧代价：桌面端对 loop 几乎**不可观测**（只有 28 个事件），调试只能看日志。
  这正是 `formatStderrTail()`、`stream_ended_no_result` 这类补丁式诊断存在的原因。
- Atlas 侧代价：loop 与宿主耦合，想换实现要改宿主。Atlas 已经有 `external_agents.py`
  （`core/atlas/runtime/`）在做外部 agent 接入，方向是对的。

**可借鉴的具体一点**：Claude 的 **`--resume-drops-turn`** 语义。
「续接时丢弃最后一轮」是一个独立可选行为，Atlas 的 session 恢复没有这个粒度。

**不借鉴**：把 loop 外置。Atlas 当前架构下没有收益。

---

## 2. 工具权限系统 —— 差距真实存在，且可补

| 维度 | Claude Desktop | Atlas |
|---|---|---|
| 决策值 | `once` / `always` / `scheduled` / `deny` / `default→deny` | 见 `core/atlas/engine/tool_permissions.py`（33 行） |
| Atlas 实际实现 | — | `tool_allowed(name, allow, deny)` = fnmatch 匹配 allow/deny 模式 |
| 升级为会话模式 | ✅ `updatedPermissions:[{type:"setMode",mode,destination:"session"}]` | ❌ 无 |
| 决策分类 | ✅ `user_reject` / `user_temporary` / `user_permanent` | ❌ 无 |
| 参数改写 | ✅ `updatedInput`（宿主与 hook 两条路径） | ❌ 无 |
| 委托询问 | ✅ `delegatedAsk` / `turnIsDelegated` | ❌ 无 |
| 生命周期钩子 | ✅ 6 个（`notePlanAnswered` 等） | ❌ 无 |
| 授权记录 | ✅ `rememberSshHostToolGrant`、`onWriteScopeGranted` | 部分（`allow` 列表） |

Atlas 当前是**纯静态过滤**：给个 allow 列表，fnmatch 匹配，完事。
Claude 是**有状态的授权协商**：一次「总是允许」会升级成 session 模式；
拒绝会分类（临时/永久）；hook 能改参数。

差距最大的是 **`updatedInput`**。允许 hook 改写工具参数意味着：
权限层不只是「放行/拦截」，而是「有条件放行」。比如「允许写入，但强制改到沙箱目录」。
Atlas 现在做不到，只能在 allow/deny 之间二选一。

**建议落地顺序**（按收益/成本比）：
1. `decisionClassification`（低成本，只需枚举 + 传递）
2. `updatedInput`（中成本，需要 hook 协议支持参数改写）
3. `setMode` 会话级升级（中成本，需要 session 状态）
4. `delegatedAsk`（高成本，需要子代理身份体系）

---

## 3. Sandbox / 隔离 —— 代差，但不必追

| | Claude Desktop | Atlas |
|---|---|---|
| 技术 | **Hyper-V / HCS + gvisor 双层** | Docker 容器单层 |
| 代码 | `cowork-svc.exe`（Go，871 自有函数，`vm` 包 531） | `core/atlas/sandbox.py`（131 行，`DockerSandboxManager`） |
| 通道 | hvsock + Plan9 文件共享（`pipe` 包 244 函数） | Docker exec / bind mount |
| 固件 | ✅ 真实 UEFI（`efivars.fd` 落盘） | ❌ 无 |
| 安全软件交互 | ✅ `edrgate` 42 + `edrpolicy` 29 函数 | ❌ 无 |
| 出网 | ✅ 自建代理（`win-httpproxy` 8 函数） | Docker 网络 |
| 可用性探测 | ✅ `Pxr()` → `{available, missingServices}` | ✅ `docker version` 探测 |

**我的判断：Atlas 不该追。** 理由：

1. Hyper-V 方案要求 **Windows 专业版/企业版 + 开启 Hyper-V + 启用 vhdx 挂载**。
   Claude 有 Anthropic 的签名证书和企业分发渠道来保证这些前提；Atlas 是开源工具，
   逼用户开 Hyper-V 会把大部分用户挡在门外。
   `os_version_too_new` 这个失败原因说明连 Windows 版本太新都会挂——维护成本极高。
2. Docker 已能满足「隔离执行不污染宿主」的核心诉求。Atlas 的 `sandbox.py` 131 行做到的事，
   Claude 用了 871 个 Go 函数。
3. **但有两件事值得借鉴**，成本都很低：
   - **`available` + `missingServices` 的探测返回**：不只说「不可用」，还说「缺什么」。
     Atlas 现在是 `{"available": false, "detail": "未找到 Docker 命令…"}`，已经接近了，
     但 `missingServices` 这种**结构化列表**比自由文本 detail 更好用。
   - **VM 不可用的 5 种枚举原因**：Atlas 只有「Docker 没装 / 没启动 / 查不到」三种，可对齐。

---

## 4. Hook 系统 —— 已完全对齐（零差距）

这是本次比对唯一**完全一致**的部分。

```powershell
python scripts/diff_hooks.py
# Atlas CLAUDE_HOOK_EVENTS: 33
# Desktop hook events: 33
# == in Desktop, NOT in Atlas == none
# == in Atlas, NOT in Desktop == none
```

`core/atlas/runtime/hooks.py`（23,444 B / 502 行）的 `CLAUDE_HOOK_EVENTS` frozenset
与 `index.chunk-Bn6onBlX.js` @62117 的 33 个事件，双向差集为空。

Atlas 甚至多做了两件事：
- `_BLOCKING_EXIT_EVENTS`：区分阻塞型退出事件（16 个）
- `_ATLAS_TO_CLAUDE`：Atlas 自有事件名 → Claude 事件名的映射

并有 `claude_hook_settings()`、`set_hook_enabled()`、`test()`、`_plugin_hook_list()` 等完整管理面。
**这一层不需要动。**

---

## 5. 规模对照（数字说话）

| 指标 | Claude Desktop | Atlas | 倍率 |
|---|---|---|---|
| IPC 方法数 | **1,411**（98 类） | 9 个 `ipcMain` handler | 157× |
| 主进程模块 | 369 个（19.8 MB） | `frontend/src/main/` 4 个 TS | — |
| 后端路由 | eipc 类 98 个 | 35 个 HTTP router | — |
| agent 模块 | 0（外置） | 21 个 Python 模块 | — |
| 工具数 | 29 + 10 + 8 + 31 | **12**（`_HERMES_CORE_TOOLS`，与 `_ALIASES` 同集） | — |
| hook 事件 | 33 | 33 | **1×** ✅ |
| feature flag | 130 | — | — |
| 枚举 | 637 | — | — |
| 沙箱实现 | 871 Go 函数 | 131 Python 行 | 6.6× |
| 调度器 | 18 IPC 方法 | 861 行（`scheduler/__init__.py`） | — |

**读法**：IPC 157× 不代表 Atlas 弱。Claude 把主进程能力全暴露成 IPC；
Atlas 走 HTTP，`core/atlas/api/` 有 35 个 router，能力在 HTTP 层。
两套通信栈不可直接比数量。

真正值得注意的对比是**沙箱 6.6×** 和 **hook 1×**：
前者是刻意简化，后者是已经完全对齐。

---

## 6. 逐项能力对照表

| 能力 | Claude | Atlas | 结论 |
|---|---|---|---|
| 多窗口角色 | 9 种 | Electron 单窗 + 若干 panel | 差异合理，Claude 要服务 Quick Entry / in-app browser / device-code |
| 会话分叉 | ✅ 任意点（`--fork-session` + `--resume-session-at`） | ✅ `ForkTree.tsx`（含 regression test） | 对齐 |
| 会话镜像 | ✅ `--session-mirror` + `mirror_error` 事件 | ❌ | **可借鉴**（多端同步） |
| 内置浏览器 | ✅ 一等窗口角色 + 31 个工具 | ✅ `capabilities/browser/browser_use.py` + x2 | 对齐（实现不同） |
| Computer Use | ✅ `computer` 工具 + 31 项 | ✅ `core/atlas/tools/computer_use.py`（1,024 行，UIA + pywinauto） | **Atlas 更细**（见 §7） |
| Skills | ✅ 6 个内置，投递给引擎 | ✅ 11 个模块完整自建 | **Atlas 更完整** |
| MCP | ✅ stdio/sse/http/ws-ide | ✅ stdio/sse（`mcp_client.py` 558 行，`Unknown transport` 分支只列两种） | Claude 多 `http` / `ws-ide`（Atlas 传 http 会直接抛 `ValueError`） |
| 计划任务 | ✅ 18 方法 + 防休眠 flags | ✅ 861 行，4 触发器 2 状态 | **Claude 多防休眠** |
| 定时唤醒 | ✅ `wakeScheduler` / `keepAwake` / `codeSessionKeepAwake` | ❌ | **可借鉴** |
| 权限协商 | ✅ 有状态 + 可改写 | ⚠️ 静态 fnmatch | **差距，应补**（§2） |
| 托管配置 | ✅ 4 通道 + `surfaceGrants` | ❌ | 企业场景才需要，Atlas 可缓 |
| 遥测 | ✅ 26 维度 | `usage.py` / `usage_pricing.py` | 维度不同，无优劣 |
| 崩溃分类 | ✅ 9 类 | `error_classifier.py` | 各自实现 |
| 双层隔离 | ✅ Hyper-V + gvisor | ❌ Docker 单层 | **不必追**（§3） |
| 区域门禁 | ✅ | ❌ | 商业策略，无技术含义 |

---

## 7. 两处 Atlas 明显更好的地方

诚实评估，不因为是竞品就全盘吹。

### 7.1 Skills 体系

Claude 的 6 个内置 skill 是**静态投递**：`manifest.json` 列出，塞进 `--allowedTools`，完事。
无版本管理、无依赖解析、无市场、无生命周期。

Atlas 是 11 个模块的完整体系：
```
core/atlas/skills/acquisition.py     获取
           agent_collections.py      集合
           bundles.py                打包
           dependencies.py           依赖解析
           discovery.py              发现
           distribution.py           分发
           lifecycle.py              生命周期
           market.py                 市场
           market_search_worker.py   市场检索（独立 worker）
           proposals.py              提案
           registry.py               注册表
```
外加 `frontend/src/renderer/pages/` 的 `SkillDiscoveryPage.tsx`、`SkillsMarketPage.tsx`、
`skillAcquisitionReview.ts`。

这不是「多写了几个文件」，是**产品化程度**的差异。Claude 把 skill 当配置；
Atlas 把 skill 当可获取、可依赖、可上架、可迭代的一等对象。

### 7.2 Computer Use 实现

Claude 侧：`computer` 是一个工具名，31 个浏览器工具里占一格。实现细节不可见（在引擎内，U）。

Atlas 侧：`core/atlas/tools/computer_use.py` **1,024 行**，可见实现包括：
- ctypes 直调 `user32.EnumWindows`（含 `argtypes` / `restype` 显式声明）
- `pywinauto` UIA 后端：`Desktop(backend="uia").window(handle=...).child_window(...)`
- `SendInput` 原生 Unicode 输入（非逐字符 keybd）
- 剪贴板读写、多显示器坐标、artifact 目录落图
- 双后端并存：`cua_backend` 可插拔（`capabilities/computer/cua_backend.py` + `uia_backend.py`）
- 明确的降级错误：`"Computer Use requires the active Windows desktop session."`

**我在本次解剖里用的正是 UIA 通道**（`dump-uia.ps1` / `System.Windows.Automation`），
和 Atlas 的 `uia_backend.py` 是同一条技术路线。这条路我能验证是通的。

---

## 8. 可落地的借鉴清单（按优先级）

| 优先级 | 项 | Claude 侧依据 | Atlas 落点 | 预估 |
|---|---|---|---|---|
| **P0** | `updatedInput` 参数改写 | `hookSpecificOutput.updatedInput` + `ToolPermissionResult.updatedInput` | `engine/tool_permissions.py` + `runtime/hooks.py` | 中 |
| **P0** | `decisionClassification` 三分类 | `user_reject`/`user_temporary`/`user_permanent` | `engine/tool_permissions.py` | 低 |
| **P1** | `setMode` 会话级授权升级 | `updatedPermissions:[{type:"setMode",destination:"session"}]` | session 状态层 | 中 |
| **P1** | 防休眠（`keepAwake` 三档） | 3 个 flag 联动 | `scheduler/__init__.py` | 低 |
| **P2** | `resume-drops-turn` 语义 | `--resume-drops-turn` | session 恢复 | 低 |
| **P2** | MCP `http` / `ws-ide` 传输 | `["http","streamable-http"].transform()` + `ws-ide` | `tools/mcp_client.py`（现只 stdio/sse） | 中 |
| **P3** | 沙箱探测返回 `missingServices[]` | `Pxr()→{available,missingServices}` | `sandbox.py` | 低 |
| **P3** | VM 不可用原因结构化枚举 | 5 种枚举 | `sandbox.py` | 低 |
| **不借鉴** | agent loop 外置 | 引擎二进制 | — | — |
| **不借鉴** | Hyper-V 双层隔离 | `cowork-svc.exe` 871 函数 | — | — |
| **不借鉴** | 区域门禁 | 商业策略 | — | — |

---

## 9. 一句话总结

Claude Desktop 的强项是**「把 agent 能力做成可分发的产品」**：
VM 隔离、企业策略、权限协商、多端镜像、防休眠——全是产品化功课。
Atlas 的强项是**「把 agent 能力做成可改造的框架」**：
loop 在进程内可观测、Skills 完整体系、Computer Use 实现全可见。

两者在学习曲线上是互补的，不是替代关系。
最值得 Atlas 抄的不是架构，是 §8 里那三行 P0/P1——**权限协商从「静态过滤」升级为「有状态协商」**。

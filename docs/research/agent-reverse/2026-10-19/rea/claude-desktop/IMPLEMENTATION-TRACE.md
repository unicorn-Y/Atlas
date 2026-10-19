# 实现链追踪 · Claude Desktop / Cowork 2.42304.0

每条链给：**触发** → **实际调用序列** → **代码锚点** → **可观测证据**。
只写我真正追到落点的；追不到的在末尾「断链清单」里单列，不混进来凑数。

路径缩写：
`B` = `extracted/asar/.vite/build/` · `I` = `extracted/msix/app/resources/ion-dist/` · `M` = `Extracted/msix/AppxManifest.xml`

---

## 链 1 · 冷启动到首帧

```
claude.exe
  └─ Electron 引导 → B/index.pre.js (930,575 B)
       ├─ Error.stackTraceLimit = 20                         [B/index.pre.js]
       ├─ NoDefaultCurrentDirectoryInExePath = "1"           [B/index.pre.js]
       ├─ 扫描 process.argv → JZ() 规范化 → 比对 16 个禁用开关
       │    └─ 命中 → console.error(refusal text) → app.exit(1)
       ├─ 校验 CLAUDE_CDP_AUTH + CLAUDE_USER_DATA_DIR（若打包态）
       │    ├─ 无令牌 → delete CLAUDE_USER_DATA_DIR / SSLKEYLOGFILE / sslkeylogfile
       │    │           原值存 globalThis.ignoredUserDataDirEnv
       │    └─ 有令牌 → Ed25519 验签 "${ts}.${payload}"，年龄 ∈ [0, 300000] ms
       ├─ 追加 Chromium 开关
       │    --enable-features=IsolatesPriorityUseProcessPriority
       │    --dnsPrefetchingEnabled=false
       │    --disable-features=ConnectionAllowlists
       ├─ 读托管配置（MDM / GPO / managed-settings.json / managed configuration）
       │    └─ 有策略 → 可能直接拒绝启动（managed_settings_refused 等）
       ├─ import B/index.chunk-lzaSYO3Q.js (7,081,117 B)  ← 主体
       └─ 创建 BrowserWindow(role = "main-window") → .vite/renderer/main_window
```

**R 级验证**：`claude.exe --no-sandbox --force-renderer-accessibility` 启动后窗口标题 `Claude`，工作集 ~227 MB；
`--remote-debugging-port=9333` 立刻 `exit 1` 且无窗口。

**stderr 实测**（真实副作用，非我构造）：
```
MaxListenersExceededWarning: Possible EventEmitter memory leak detected.
  11 coworkHipaaRestricted listeners added to [EventEmitter]
MaxListenersExceededWarning: ...
  31 destroyed listeners added to [WebContents]
ExperimentalWarning: vm.USE_MAIN_CONTEXT_DEFAULT_LOADER is an experimental feature
```
> `coworkHipaaRestricted` 这个监听器名是白捡的证据：说明存在 **HIPAA 受限模式**，且有 11 个订阅者。
> `31 destroyed listeners on [WebContents]` 说明每个 WebContents 都被挂了大量销毁清理——多窗口架构的必然代价。

---

## 链 2 · 渲染层 → 主进程（eipc）

```
renderer (ion-dist 或 .vite/renderer)
  └─ preload contextBridge（19 个桥节点）
       └─ ipcRenderer.invoke(
            "$eipc_message$_<uuid>_$_<module>_$_<Class>_$_<method>", args)
            └─ 主进程 eipc 路由 → 按 <Class> 派发到 98 个服务类之一
                 └─ 服务实现（1,411 个方法）
```

锚点：`indexes/ipc-contract.json`（通道格式）、`indexes/ipc-methods.json`（1,411 方法全表）。

**方法数 Top 10**：
| 服务类 | 方法数 |
|---|---|
| `LocalSessions` | 339 |
| `LocalAgentModeSessions` | 134 |
| `Launch` | 111 |
| `Simulator` | 71 |
| `Custom3pSetup` | 41 |
| `CoworkSpaces` | 34 |
| `Extensions` | 28 |
| `EngineSurface` | 25 |
| `CoworkArtifacts` | 25 |
| `ClaudeAiImport` | 24 |

**两个 UUID 的分工**值得单独记：
- `6010a08f-a0fa-48b4-99da-0689b9e2de7b` → 全部 `claude.*` 业务服务（1,404 方法）
- `fcb91d11-972d-4fd6-b90b-72739699bff5` → 只有 `electron_window.WindowManager`（7 方法）

窗口管理被**物理隔离**到独立 UUID，说明它被当作比业务更低层、更可信的通道对待。

---

## 链 3 · 会话启动 → spawn 引擎

```
用户发消息
  └─ LocalAgentModeSessions.<send>（134 方法之一）
       └─ 组装引擎参数（B/index.chunk-DNyequwM.js @1131100–1134600）
            base = ["--output-format","stream-json","--verbose",
                    "--input-format","stream-json"]
            + 条件开关（30+，见下）
            + settings 对象中值为 null 的键 → "--<key>"
            + skills → allowedTools 追加 "Skill" 或 "Skill(<name>)"
            env: CLAUDE_CODE_ENTRYPOINT ||= "sdk-ts"
                 delete NODE_OPTIONS
       └─ console.log(`Spawning Claude Code: ${me} ${he.join(" ")}`)
       └─ new ProcessTransport(...)  → child_process.spawn
            ├─ stdin  ← 写用户消息 / 控制请求
            ├─ stdout → 逐行解析 stream-json → 28 种 subtype
            └─ stderr → formatStderrTail() 保留尾部
       └─ 退出归类：aborted | spawn_failed | process_error
                    | process_exited_nonzero | process_killed_by_signal
```

**条件开关完整清单**（S 级，逐条来自代码分支）：

| 类别 | 开关 |
|---|---|
| 思考 | `--thinking=adaptive` / `--thinking=disabled` / `--max-thinking-tokens` / `--thinking-display` / `--effort` |
| 预算 | `--max-turns` / `--max-budget-usd` / `--task-budget` |
| 模型 | `--model` / `--fallback-model` / `--betas` |
| 会话 | `--continue` / `--resume` / `--fork-session` / `--resume-session-at` / `--resume-drops-turn` / `--session-id` / `--no-session-persistence` / `--session-mirror` |
| 工具 | `--allowedTools` / `--disallowedTools` / `--tools` / `--tools=default` / `--permission-prompt-tool=stdio` / `--permission-prompts` / `--permission-mode` / `--allow-dangerously-skip-permissions` |
| MCP | `--mcp-config <json>` / `--strict-mcp-config` / `--plugin-dir` / `--plugin-dir-no-mcp` |
| 配置 | `--setting-sources` / `--managed-settings` / `--project-config-root` / `--add-dir` |
| 观测 | `--debug-file` / `--debug` / `--include-hook-events` / `--include-partial-messages` / `--json-schema` / `--channels` / `--await-initialize` |
| 代理 | `--agent` |

> `--resume-drops-turn` 这个开关名很有信息量：它说明「续接时丢弃最后一轮」是一个**显式可选行为**，
> 而不是 bug。对应的产品语义大概是「重跑上一次提问」。

---

## 链 4 · 流式事件消费

```
引擎 stdout（每行一个 JSON）
  └─ ProcessTransport 行解析
       ├─ type=stream_event → subtype ∈ 28 种
       │    ├─ init                    → 握手：引擎版本 / 工具表 / 模型
       │    ├─ status                  → 状态机推进
       │    ├─ api_retry               → 重试可视化
       │    ├─ compact_boundary        → 压缩边界（算法在引擎内，U）
       │    ├─ hook_started/progress/response → hook 生命周期
       │    ├─ task_started/progress/updated/notification → 任务队列
       │    ├─ background_tasks_changed → 后台任务集变更
       │    ├─ thinking_tokens         → 思考预算实时消耗
       │    ├─ permission_denied       → 拒绝回执
       │    ├─ model_refusal_fallback / model_refusal_no_fallback → 拒答分支
       │    ├─ mirror_error            → 多端镜像错误（可恢复）
       │    ├─ memory_recall           → 记忆召回
       │    ├─ elicitation_complete    → 主动询问完成
       │    ├─ plugin_install          → 插件安装进度
       │    ├─ files_persisted         → 产物落盘通知
       │    └─ worker_shutting_down    → 优雅停机
       └─ type=result → subtype ∈ 5 种
            success | error_during_execution | error_max_turns
            | error_max_budget_usd | error_max_structured_output_retries
```

**这一步是整个解剖的转折点**：28+5 个枚举说明桌面端对引擎的理解非常细，
但**每个 subtype 的处理逻辑都是「展示」而非「计算」**——桌面端做的是状态映射，不是 agent 逻辑。
这就是为什么我说 agent loop 不在桌面端。

---

## 链 5 · 工具权限决策

```
引擎发出 permission 请求（--permission-prompt-tool=stdio）
  └─ ProcessTransport 读到 → 转 IPC → 宿主
       └─ ToolPermissionBroker
            ├─ 用户决策 ∈ {once, always, scheduled, deny, default}
            │    └─ default → {behavior:"deny", message:"Unknown decision"}   ← 未知即拒
            ├─ 产出 ToolPermissionResult {
            │      behavior,
            │      updatedInput,                    ← 可改写参数
            │      updatedPermissions: [{type:"setMode", mode, destination:"session"}],
            │      decisionClassification ∈ {user_reject, user_temporary, user_permanent},
            │      approvalSurface: "host_dialog"
            │   }
            ├─ 拒绝文案：`User rejected ${t.$f(s.toolName)} ${e}`
            │            "User rejected the directory access request"
            └─ 生命周期钩子：
                 notePlanAnswered / rememberSshHostToolGrant /
                 onWriteScopeGranted / renewArchiveConsent /
                 voidArchiveConsent / accumulateSessionPermissionUpdates
```

**协作/委托分支**（这套设计比较少见）：
```
delegatedAsk  → turnIsDelegated ? turnDelegation : 直接问用户
                 gate: flag "desktop_ccd_delegated_ask_allowed"
```

**动态工作流保护**：`"Review the first dynamic workflow before auto-approving."`
—— 自动批准对「首次出现的动态工作流」不生效，强制人工过目一次。

**hook 层的权限通道**与上面并行：
```
PreToolUse hook → {hookSpecificOutput:{
                     hookEventName:"PreToolUse",
                     permissionDecision:"allow"|"deny",
                     permissionDecisionReason,
                     updatedInput          ← hook 也能改写
                  }}
```
即权限有**两条**可干预路径：宿主 UI（人）与 PreToolUse hook（程序）。二者都会改写最终参数。

---

## 链 6 · Cowork VM 启动

```
Cowork 任务需要本地执行
  └─ LocalAgentModeSessions / CoworkSpaces
       └─ B/index.chunk-lzaSYO3Q.js @4319128–4341310
            ├─ Pxr() → HCS 探测 {available, missingServices}
            │    └─ 不可用 → 5 种原因之一：
            │         kvm_permission_denied / vhost_vsock_module_missing /
            │         vhost_vsock_kernel_unsupported / not_enabled /
            │         os_version_too_new
            ├─ getVMBundlesDir() → "vm_bundles" / "claudevm.bundle"
            ├─ isVMBundlePresent() / isVMDownloaded() / isVMDownloading()
            ├─ 等待 5 秒（让上次 VM 收尾）
            ├─ 网络竞速 5 秒
            ├─ 复制 smol-bin.<arch>.vhdx → bundle
            │    └─ EBUSY / EACCES / EPERM → 跳过（不失败）
            ├─ g.configure()
            └─ g.startVM(i, _, v, "gvisor", probeTarget, y, b, void 0)
                 ├─ 临时后缀 ".wvm-tmp-" / ".partial"
                 ├─ 采纳标记 ".cowork-adopted"
                 ├─ UEFI 变量 "efivars.fd" 单独落盘
                 └─ 失败 → VMDownloadError / VMConnectionTimeoutError{guestReady}
```

**服务侧（cowork-svc.exe，Go）**：
```
Windows SCM 启动服务（desktop6:Extension Category="windows.service"）
  └─ Go main → 包初始化
       ├─ vm        531 函数  ← VM 生命周期主体
       ├─ pipe      244 函数  ← hvsock / 命名管道
       ├─ edrgate    42 函数  ← EDR 门禁
       ├─ edrpolicy  29 函数  ← EDR 策略
       ├─ logsink    17 函数  ← 日志汇聚
       └─ win-httpproxy 8 函数 ← VM 出网代理
```

为什么用 HVCC/HCS 而不是容器：需要 **内核级隔离 + hvsock 低延迟 + Plan9 文件共享 + UEFI 真实启动 + EDR 交互**。
容器给不了 hvsock，也给不了真实固件启动。`efivars.fd` 的存在是硬证据。

**边界**：VM 内的 guest agent 实现不在本样本内（U）。`"gvisor"` 作为隔离层名字说明 guest 内还叠了一层用户态内核。

---

## 链 7 · MCP 接入

```
用户配置 MCP 服务器
  └─ MCP schema 校验（zod）
       ├─ type ∈ {stdio, sse, http, streamable-http, ws-ide}
       │    └─ ["http","streamable-http"].transform(()=>"http")  ← 对外两名，内部一名
       ├─ 字段：headers / headersHelper / oauth / timeout /
       │         request_timeout_ms / tools / alwaysLoad /
       │         bareElicitationCapability / discoveryCache /
       │         role / toolPermissions
       └─ 序列化为 --mcp-config <json> 传给引擎
            └─ 引擎侧（U）实际连接与工具调用
```

桌面端还提供**运行时 MCP 宿主**：`B/mcp-runtime/directMcpHost.js`（613,700 B）+
`resources/office365-mcp/`（含 `pdfExtractorProcess.mjs`）。

**插件 MCP 策略强制**（一处很强的一致性保护）：
```
"${d} Plugin MCP scan failed while an MCP policy is active;
 refusing to start session with unenforced plugin"
```
键格式 `plugin:${cliName}:${toolName}`。
即：**有 MCP 策略时，扫描失败的插件宁可拒绝启动会话，也不放行**。这是 fail-closed 而非 fail-open。

---

## 链 8 · Skills 加载

```
启动 / 会话创建
  └─ resources/bundled-skills/manifest.json
       ├─ agentSkillsRef: "1792020044"        ← 内容版本锚
       ├─ 6 个内置技能，全部 tier:"always"
       │    docx / frontend-design / pdf / pdf-reading / pptx / xlsx
       └─ 加载后注入引擎：
            --allowedTools 追加 "Skill" 或 "Skill(<name>)"
```

**桌面端只负责「投递」**：发现、解析、执行都在引擎侧（U）。
Atlas 这边是完整自建（`core/atlas/skills/` 下有 acquisition / bundles / dependencies /
discovery / distribution / lifecycle / market / registry / proposals 十来个模块），
这是**架构方向不同**，不是能力缺失。

---

## 链 9 · 状态持久化与恢复

```
会话状态
  ├─ LocalSessions（339 方法）→ 会话 CRUD / 历史 / 分叉
  ├─ --session-mirror          → 多端镜像
  ├─ --fork-session            → 任意点分叉
  ├─ --resume-session-at <ts>  → 指定时间点续接
  └─ --no-session-persistence  → 显式关闭持久化（敏感场景）

崩溃恢复
  ├─ 归类：process_crashed / bun_crash / bun_stack_overflow / segfault /
  │         cli_fastfail / renderer_cascade / process_interrupted /
  │         stream_ended_no_result
  └─ 良性：cli_shutdown_crash_benign（正常关闭被误判为崩溃时的豁免标记）
```

`stream_ended_no_result` 这一类很说明问题：**流结束了但没收到 result** 被单独当作一种故障，
说明这是实际踩过的坑（引擎意外退出但 stdout 正常关闭）。

`bun_crash` / `bun_stack_overflow` 出现，说明引擎二进制是 **Bun 打包**的（不是纯 Node）。
这是一个附带情报。

---

## 链 10 · 历史导入（第三方迁移）

```
设置 → 从其他 AI 客户端导入历史
  └─ B/index.chunk-BPjIr-mn.js (50,076 B)
       ├─ 遥测 event: "desktop_third_party_history_import"
       │    Sentry DSN: sentry-dbid-9cf4e251-4f17-48c2-88cd-201ac3410330
       ├─ 组织限定：env CLAUDE_DESKTOP_SIBLING_IMPORT_ORG
       └─ 策略判定四分支（原文）：
            "allowed (managed configuration)"
            "allowed (organization setting)"
            "key present but not honoured: names another organization"
            "not enabled for this organization"
```

> 第三条文案值得注意：`key present but not honoured: names another organization`
> —— 用户本地有一个看起来有效的 key，但因为它指向别的组织而被**明确忽略**。
> 这是「静默降级 + 可诊断原因」的写法，比直接报错或静默忽略都好。

---

## 断链清单（追不到落点，如实列出）

| 链段 | 断在哪 | 原因 | 级别 |
|---|---|---|---|
| 引擎内部 agent loop | spawn 之后 | 在 Claude Code 引擎二进制内，不在本样本 | **U** |
| 工具具体实现 | 同上 | 同上 | **U** |
| 上下文压缩算法 | `compact_boundary` 事件之后 | 同上 | **U** |
| 子代理调度器 | `--agent` 参数之后 | 同上 | **U** |
| VM 内 guest agent | `startVM` 之后 | 在 VHDX 镜像内，未挂载分析 | **U**（可做但未做） |
| `cowork-svc.exe` 函数体 | 871 个符号名之后 | Ghidra 就绪但未跑原生反编译 | **部分**（S 到符号级） |
| Anthropic 服务端 | 网络调用 | 服务端 | **U** |
| 登录后 UI 交互链 | 区域门禁 | 产品主动限制 | **U** |
| 原生菜单栏条目 | `Toggle menu` | 不支持 InvokePattern，脚本缺合成点击回退 | **部分**（工具缺口） |
| ion-dist 逐文件逻辑 | 普查之后 | 4,026 个资源未逐个细读 | **部分** |

**给出解锁所需的最小材料**（便于下一轮直接补）：
- 引擎二进制 → 可一次性解锁 agent loop / 工具 / 压缩 / 子代理四条链
- Ghidra headless 跑一遍 `cowork-svc.exe`（约 1–2 小时）→ 把 871 个符号变成函数体
- `uia-invoke.ps1` 补 click-at-rect 回退（约半小时）→ 解锁原生菜单
- 支持区域的网络环境 → 解锁全部登录后 UI

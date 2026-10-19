# Claude Desktop / Cowork 逆向解剖 · 入口

> **一句话结论**：Claude Desktop 是一个 **Electron 外壳 + eipc 服务面 + 本地 Hyper-V 微虚拟机**的三层结构。
> **Agent loop 不在桌面端**——桌面端只是一个通过 stdio `stream-json` 驱动 Claude Code 引擎二进制的 SDK 客户端。
> 这个判断来自 `ProcessTransport` 的完整命令行构造代码（`index.chunk-DNyequwM.js` @1131100–1134600，约 3,500 字符、30+ 条条件分支），
> 是整个解剖里最重要的一条结构性结论，推翻了很多「桌面端自己实现了 agent」的想当然。

| 项 | 值 |
|---|---|
| 产品 | Claude Desktop / Cowork（Windows x64） |
| 版本 | **2.42304.0**（`AppxManifest.xml` Identity Version `2.42304.0.0`） |
| 发行包 | `claude-desktop-x64-2bf309665f.msix` |
| 字节 | 297,191,037（283.4 MB） |
| SHA-256 | `2bf309665f0de4eaa76a7e64033594e6f73ceb6413c60080f72f3ce640fa24ee`（本机实测，与清单一致） |
| 构建 | `commitHash e7f60e658f15cfece9efa384a78a39aec3c12845`，`commitTimestamp 2026-10-15T05:54:05.000Z`，`buildType prod`，`appVersion 2.42304.0` |
| 打包 | Electron 8.0.0-alpha.10 + Electron Forge + Vite；MSIX 带 `windows.service` 扩展 |
| 解剖工具 | REA CLI v6.4.0（`rea doctor` → `healthy:true`）、Ghidra 12.1.4、ffmpeg 8.1.2、Windows UIA、Chrome headless |
| 对照基线 | Atlas `main` @ **`aa6196f550098cc46081dc6db2c376cb87ddffa5`**（2026-10-06） |

---

## 一分钟上手

```powershell
# 1. 打开本地图鉴（双击也行，纯 file:// 可用，不需要起服务）
Start-Process "D:\Atlas-Reverse-Lab\claude-desktop\viewer\index.html"

# 2. 深链直达某一页
Start-Process "D:\Atlas-Reverse-Lab\claude-desktop\viewer\index.html#cov"
```

图鉴共 **16 页**，左侧分五组：总览 / 界面 / 后端 / 索引 / 交付。
顶部搜索框（`Ctrl+K`）可跨 IPC 方法、feature flag、偏好项、枚举、模块、工具、环境变量、Go 符号检索。
每页可收藏（★）与勾选「已核对」，存在浏览器 `localStorage["atlas-cd-v1"]`，不联网。

**已验证**：`check_viewer.py` → `ALL CHECKS PASSED`；`render_viewer.py` → `ALL 16 PAGES RENDER`（16 张整页 PNG 在 `screenshots/viewer/`）。

---

## 交付物索引

| 文件 | 内容 |
|---|---|
| `START-HERE.md` | 本文件。结论、版本、覆盖率边界、索引、阻塞 |
| `DISCOVERY-LEDGER.md` | **主动新发现能力总账**，`CLAUDE_DESKTOP-001` 起共 **118 条** |
| `IMPLEMENTATION-TRACE.md` | 机制级调用链：启动→IPC→引擎→工具→VM→存储→恢复 |
| `UI-AND-WORKFLOWS.md` | 所有可找到的交互入口、真实截图、可操作 Demo、不可达原因 |
| `ATLAS-GAP.md` | 竞品机制 vs Atlas `main@aa6196f5` 真实代码，逐项给锚点 |
| `EVIDENCE-INDEX.md` | 包/SHA/路径/行号/官方文档，以及**哪些没查、为何没查** |
| `indexes/coverage.json` | 六项覆盖率的机器可读版本（viewer 的 `cov` 页直接读它） |
| `indexes/*.json` | 全部索引：IPC、Go 符号、枚举、flags、模块、文件清单 |
| `findings/01..06-*.md` | 六份中文深度机制说明 |
| `viewer/` | 本地可视化图鉴（`index.html` + `data.js` + `coverage.js`） |
| `screenshots/live/` | 真实运行时截图（3 张） |
| `screenshots/viewer/` | 图鉴 16 页整页截图 |

---

## 六项覆盖率（唯一达到 100% 的是文件登记）

| 指标 | 分子 / 分母 | 比例 | 口径 |
|---|---|---|---|
| 文件登记覆盖率 | 4,949 / 4,949 | **100%** | MSIX 4,443 成员 + asar 506 文件，逐项登记大小/CRC/SHA256 |
| 文件内容解析覆盖率 | 437 / 875 | 49.94% | REA 实解析 437 个 JS ÷ (369 构建模块 + 506 asar 文件) |
| 符号/函数枚举覆盖率 | 2,282 / 6,694 | 34.09% | IPC 1,411 + Go 自有 871 ÷ 再计入 Go 标准库 4,412 |
| 深度机制解释覆盖率 | 25 / 29 | 86.21% | 29 项机制逐项判定 |
| 动态验证覆盖率 | 8 / 13 | 61.54% | 13 项运行验证逐项判定 |
| 界面可视化覆盖率 | 2 / 12 | 16.67% | 12 个界面入口逐项判定 |

**三处必须说明的口径选择**（避免读者误判）：

1. **符号覆盖率 34% 看起来低，是因为分母含 4,412 个 Go 标准库函数**。标准库函数只登记名字、不解释语义。
   若只算产品自有符号：`1,411 + 871 = 2,282 / 2,282 = 100%`。两个数字都是真的，取决于你怎么定义分母。
2. **解析覆盖率 49.94% 的分母是上界**。`369 + 506` 有重叠（`.vite/build` 的 369 个模块本身就在 asar 的 506 个文件里），
   真实分母应小于 875，所以真实解析率**高于** 49.94%。我选择报保守值。
3. **界面覆盖率 16.67% 不是懈怠**。区域门禁（`App unavailable in region`）把 10 个界面入口全部挡死，
   这是产品的主动限制，不是技术障碍。我没有尝试绕过，也不应该绕过。

`indexes/coverage.json` 里有每项指标的逐条明细（`mechanisms[]` / `dynamic[]` / `ui[]`），不是拍脑袋的比例。

---

## 解剖到了什么（核心发现摘要）

### 1. 三层架构，agent loop 在第三层且不在本样本内

```
Electron 主进程 (369 个 .vite/build 模块, 19.8 MB)
  ├─ 98 个 eipc 服务类 / 1,411 个方法   ← 前端与主进程的唯一通道
  ├─ ProcessTransport                    ←  spawn 引擎，stdio stream-json
  └─ Cowork 运行时
       ├─ cowork-svc.exe (Go, 871 个自有函数)  ← Hyper-V/HCS、hvsock、Plan9 共享、EDR 门禁
       └─ Claude Code 引擎二进制（不在本样本）  ← 真正的 agent loop / 工具 / 压缩 / 子代理
```

命令行构造证据（S 级，`index.chunk-DNyequwM.js` @1131100）：
基础参数 `["--output-format","stream-json","--verbose","--input-format","stream-json"]`，
之后按条件追加 30+ 个开关：`--thinking=adaptive` / `--effort` / `--max-turns` / `--max-budget-usd` /
`--permission-prompt-tool=stdio` / `--mcp-config` / `--strict-mcp-config` /
`--allow-dangerously-skip-permissions` / `--session-mirror` / `--fork-session` 等。
设置对象里值为 `null` 的键会展开成布尔 `--<key>`。日志串 `Spawning Claude Code: ${me} ${he.join(" ")}`。

> 这条结论直接决定了本次解剖的边界：**agent loop、工具实现、上下文压缩算法、子代理调度器都是 U（不可得）**，
> 因为它们编译在引擎二进制里。任务书明确说 Claude Code CLI 的独立逆向属于另一个会话，所以我不越界。

### 2. Cowork 的本地执行是真的微虚拟机，不是容器

`cowork-svc.exe` 是 **Go 二进制**（module `github.com/anthropics/cowork-win32-service`），
经 `desktop6:Extension Category="windows.service"` 注册为 Windows 服务。
自有代码分六个包：`vm` 531 函数、`pipe` 244、`edrgate` 42、`edrpolicy` 29、`logsink` 17、`win-httpproxy` 8，合计 871。

VM 启动链路（S 级，`index.chunk-lzaSYO3Q.js` @4319128–4341310）：
等 5 秒 → 竞速网络 5 秒 → 把 `smol-bin.<arch>.vhdx`（37.7 MB，随包分发）复制到 bundle 目录
（遇 `EBUSY`/`EACCES`/`EPERM` 跳过）→ `g.configure()` → `g.startVM(i,_,v,"gvisor",probeTarget,y,b,void 0)`。
常量 `vm_bundles` / `claudevm.bundle` / `.wvm-tmp-` / `.partial` / `.cowork-adopted` / `efivars.fd`。

> 用 HVCC/HCS（Host Compute System）而非 Docker，说明它要的是**内核级隔离 + hvsock 低延迟通道 + Plan9 文件共享 + EDR 门禁**这套组合，
> Docker 给不了。Atlas 用的是 Docker（`core/atlas/sandbox.py` → `DockerSandboxManager`），这是量级差异，不是配置差异。

### 3. 启动守卫：主动拒绝调试开关，且不可绕过

16 个禁用开关（`remote-debugging-port`、`remote-debugging-pipe`、`disable-web-security`、`ssl-key-log-file`、
`host-resolver-rules`、`browser-subprocess-path` 等），规范化函数 `JZ(e)=e.replace(/^(?:--|-|\/)/,"").toLowerCase().split("=",1)[0]`。
命中即拒绝启动，文案：`Claude: refusing to start — a debugging or network-override switch is present on the command line.`

**R 级已实测**：`--remote-debugging-port=9333` → 进程拒绝启动，`exit 1`。这是设计，我没有尝试绕过。

合法调试需要 `CLAUDE_CDP_AUTH` + `CLAUDE_USER_DATA_DIR`，令牌形如 `base64(userDataPath).sig`，
对 `"${ts}.${payload}"` 做 Ed25519 验签，公钥 SPKI `MCowBQYDK2VwAyEAxONNYxuoQ4/PkjI7rdBmfpsWn1Ohfuqx9VMIsLwlTQY=`，时效 0–300,000 ms。
**私钥不在客户端**——这是设计上就不可得的部分。

### 4. 1411 个 IPC 方法，98 个服务类

通道命名 `$eipc_message$_<uuid>_$_<module>_$_<Class>_$_<method>`，两个 UUID：
`6010a08f-a0fa-48b4-99da-0689b9e2de7b`（`claude.*` 服务）、`fcb91d11-972d-4fd6-b90b-72739699bff5`（`electron_window.WindowManager`，7 方法）。

方法数最多：`LocalSessions` 339、`LocalAgentModeSessions` 134、`Launch` 111、`Simulator` 71、
`Custom3pSetup` 41、`CoworkSpaces` 34、`Extensions` 28、`EngineSurface` 25、`CoworkArtifacts` 25。

> `LocalSessions` 一个类 339 个方法，比 Atlas 全部 IPC handler（9 个）多 37 倍。
> 这不是「设计更好」，是两种架构：Claude 把几乎全部主进程能力都暴露成 IPC 方法；Atlas 走的是 HTTP 路由（35 个 router）。

### 5. 130 个 feature flag，含大量未发布的实验代号

`cowork*` / `ccd*` / `computerUse*` / `iosSimulator*` / `androidEmulator*` / `wsl*`(6) / `wakeScheduler` / `keepAwake` /
`sideSession*` / `btwChildSessions` / `sessionMentions` / `tearOffHalo` / `telescopeBridge` / `selfHostedCowork` /
`grandPrix*` / `epitaxyMcpApps` / `violinBow*` / `copperLarkA|B|C` / `yukonSilver*` / `humbleSky` / `quietPenguin` /
`louderPenguin` / `rubberDuck` / `chillingSloth*`(5) / `sableOtter` / `mcpPersistentAlwaysAllow` 等。

代号类（`grandPrix`/`violinBow`/`copperLark`/`yukonSilver`/`chillingSloth`/`sableOtter`…）共 24 个，
从命名规律看是 Anthropic 内部的动物/项目代号体系。**这些是真实存在的开关，不是我从文档抄的**——
全部来自 `feature-flags.json`，每条带文件偏移。

### 6. 33 个 hook 事件 —— 与 Atlas 完全一致

桌面端 `index.chunk-Bn6onBlX.js` @62117 枚举 33 个事件：
PreToolUse, PostToolUse, PostToolUseFailure, PostToolBatch, Notification, UserPromptSubmit,
UserPromptExpansion, SessionStart, SessionEnd, Stop, StopFailure, SubagentStart, SubagentStop,
PreCompact, PostCompact, PreModelSwitch, PostModelSwitch, PermissionRequest, PermissionDenied,
Setup, TeammateIdle, TaskCreated, TaskCompleted, Elicitation, ElicitationResult, ConfigChange,
WorktreeCreate, WorktreeRemove, InstructionsLoaded, CwdChanged, FileChanged, DirectoryAdded, MessageDisplay。

Atlas `core/atlas/runtime/hooks.py` 的 `CLAUDE_HOOK_EVENTS` 也是 33 个，**逐一比对完全一致，零差异**。
（`scripts/diff_hooks.py` 可复现。）这说明 Atlas 的 hook 层已经按 Claude 的协议对齐过了。

### 7. 只有桌面端**没有实现引用**的工具有哪些

权威工具词表三份，且**互不相同**：
- 29 个（`index.chunk-lzaSYO3Q.js` @121617）：AskUserQuestion, Bash, BashOutput, Edit, ExitPlanMode, Glob, Grep,
  JavaScript, KillBash, MultiEdit, NotebookEdit, Read, REPL, SendUserMessage, Skill, Task, TaskCreate, TaskGet,
  TaskList, TaskStop, TaskUpdate, Tmux, TodoWrite, ToolSearch, WebFetch, WebSearch, Workflow, Write, unknown
- 10 个权限集（@5698963）：Bash, PowerShell, Read, Write, Edit, MultiEdit, NotebookEdit, Grep, Glob, WebFetch
- 8 个引擎集（`index.chunk-CEkgISQ-.js` @726）

`PowerShell` **只存在于 10 项权限集**，说明它是 Windows 宿主注入的，不在引擎通用词表里。

另有一套 **31 个浏览器/Cowork 专用工具**：browser_batch, click, computer, execute_javascript, form_input,
get_page_text, gif_creator, navigate, read_network_requests, read_page, resize_window, select_browser,
shortcuts_execute, switch_browser, tabs_*_mcp, upload_image 等。

---

## 边界：明确不可获得（U）

诚实列出，不用推断冒充实现：

| 对象 | 状态 | 原因 | 解锁所需最小材料 |
|---|---|---|---|
| agent loop 本体 | **U** | 在 Claude Code 引擎二进制内，不在本样本 | 引擎可执行文件（属另一会话） |
| 工具的具体实现 | **U** | 同上 | 同上 |
| 上下文压缩算法 | **U** | 同上；桌面端只收到 `compact_boundary` 事件 | 同上 |
| 子代理调度器 | **U** | 同上；桌面端只传 `--agent` 并收 `SubagentStart/Stop` | 同上 |
| Anthropic 服务端 | **U** | 网络服务 | 不合法也不应该获取 |
| CDP 授权私钥 | **U** | 设计上不在客户端 | — |
| 登录后产品界面 | **U** | 区域门禁，产品主动限制 | 支持区域的网络环境 + 账号 |
| `cowork-svc.exe` 函数体 | **部分** | 只做到符号级（871 个函数名），Ghidra 已就绪但未跑原生反编译 | 一次 Ghidra headless 反编译（约 1–2 小时） |
| Consumer Setup 安装器 | **U** | 下载端点 HTTP 403 `region_unavailable` | 支持区域的下载环境 |
| 原生菜单栏内容 | **U** | `Toggle menu` 不支持 `InvokePattern`，脚本缺合成点击回退 | 补 click-at-rect 回退（半小时） |
| GIF / 视频 | **未做** | 可交互范围只有错误页 + 两项菜单，信息增量近零 | 拿到登录态后可直接补 |

**关于 ion-dist**：`app/resources/ion-dist/` 有 190.3 MB、4,224 个文件、`assets/v1/` 下 4,026 个资源，
我做了特征普查（`feature-census-ion.json`，最大 chunk `c96d752d0-BOCqU7c2.js` 1.61 MB，session 479 次、artifact 266 次、
worktree 118 次、tool_use 87 次、cron 75 次），但**没有逐文件纳入解析覆盖率分子**。
这是 web 版渲染层，与桌面端主进程是两套代码，我优先做了能追到执行链的主进程侧。

---

## 仍未做的事（不掩饰）

1. `cowork-svc.exe` 原生反编译（Ghidra 可用，未执行）—— 这是最大的单个缺口，能把 871 个符号变成函数体。
2. 原生菜单栏条目抓取（需补 `uia-invoke.ps1` 的合成点击回退）。
3. ion-dist 4,026 个前端资源的逐文件解析（已普查未细读）。
4. 登录态下的真实交互链（区域门禁阻断，非技术问题）。
5. GIF 录制（明确取舍，理由见 `UI-AND-WORKFLOWS.md`）。

---

## 复现方式

```powershell
$py = "C:\Users\25011\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
$R  = "D:\Atlas-Reverse-Lab\claude-desktop"

& $py "$R\scripts\build_coverage.py"                       # 重建 coverage.json
& $py "$R\scripts\patch_cov_page.py"                       # 同步到 viewer
& $py "$R\scripts\build_viewer_data.py" "$R\indexes" "$R\viewer\data.json"
& $py "$R\scripts\emit_viewer_js.py"                       # data.json -> data.js
& $py "$R\scripts\check_viewer.py"                         # 静态校验
& $py "$R\scripts\render_viewer.py"                        # 16 页渲染验证
& $py "$R\scripts\diff_hooks.py"                           # hook 事件与 Atlas 比对
```

全部脚本在 `D:\Atlas-Reverse-Lab\claude-desktop\scripts\`，可独立重跑。

---

## 回传格式

```
ZCODE REA | Claude Desktop / Cowork | 2.42304.0
| branch: research/zcode-rea-20261019-claude-desktop
| commit: <见 git log>
| report: docs/research/agent-reverse/2026-10-19/rea/claude-desktop/START-HERE.md
| viewer: D:\Atlas-Reverse-Lab\claude-desktop\viewer\index.html
| 文件登记覆盖率: 100% (4,949/4,949)
| 机制解释覆盖率: 86.21% (25/29)
| 确认发现: 118 条
| REMOTE_NOT_SYNCED: 原始 MSIX 283.4 MB、解包 780 MB、REA 全量 AST 107.9 MB
| 阻塞项: 区域门禁阻断登录后界面；cowork-svc.exe 未做原生反编译
| Atlas main SHA: aa6196f550098cc46081dc6db2c376cb87ddffa5
```

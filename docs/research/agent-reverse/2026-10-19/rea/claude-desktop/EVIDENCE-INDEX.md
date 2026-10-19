# 证据索引 · Claude Desktop / Cowork 2.42304.0

每一条都能落到**具体文件 + 字节偏移**或**具体运行时观测**。
不能落地的在 §7「未查清单」里单列，不混进正文。

---

## 1. 样本身份（先证明「我在解的是哪个东西」）

| 项 | 值 | 获取方式 |
|---|---|---|
| 文件 | `claude-desktop-x64-2bf309665f.msix` | 认证 GitHub API asset 端点 + `Range:` 分段（`scripts/fetch-msix.ps1`） |
| 字节 | 297,191,037 | `Get-Item` |
| SHA-256 | `2bf309665f0de4eaa76a7e64033594e6f73ceb6413c60080f72f3ce640fa24ee` | `Get-FileHash`，分段重组后复验 |
| Identity | `Name="Claude"` `Version="2.42304.0.0"` `Publisher="CN=Anthropic PBC..."` | `AppxManifest.xml` |
| TargetDeviceFamily | `Windows.Desktop` `MinVersion 10.0.18362.0` | 同上 |
| buildType | `prod`（非 canary / 非 dev） | `.vite/build/index.pre.js` |
| commitHash | `e7f60e658f15cfece9efa384a78a39aec3c12845` | 同上 |
| commitTimestamp | `2026-10-15T05:54:05.000Z` | 同上 |
| appVersion | `2.42304.0` | 同上 |
| 产品名 | `Claude`，包名 `@ant/desktop` | `app.asar` 内 `package.json` |

> **采信理由**：`commitHash` 与 `commitTimestamp` 是内联在引导脚本里的构建期常量，
> 无法在运行期伪造，且与 `AppxManifest` 版本号一致。三条独立线索互洽。

**为什么用 MSIX 而不是 Consumer Setup 安装器**：
`https://claude.ai/api/desktop/win32/x64/setup/latest/redirect` → **HTTP 403 `region_unavailable`**；
`downloads.claude.ai` 连接超时。
MSIX 是当前环境唯一能拿到的官方完整分发物。这一点在 `evidence/00-ACQUISITION.md` 有原始记录。

---

## 2. 文件树与规模

| 路径 | 规模 | 说明 |
|---|---|---|
| MSIX 容器 | **4,443** 成员 / 695.1 MB | `indexes/msix-inventory.json`（1,993,039 B，逐成员大小/CRC） |
| `app.asar` | **506** 文件 / 548 条目 / 49,338,428 B | `indexes/asar-inventory.json`；`archive_sha256 8f4d3dec5e4f3ddffb150321060b18807d83a40f3a65618fe4f29325379da9db`；`header_bytes 136222`；`payload_base 136240` |
| `app.asar.unpacked/` | 6 文件 / 27.1 MB | 需原生加载的二进制 |
| `ion-dist/` | **4,224** 文件 / 190.3 MB | 独立前端树，`assets/v1/` 下 4,026 个 |
| `.vite/build/` | **369** JS / 19.8 MB | 主进程构建产物 |
| 解包总量 | **4,943** 文件 / 780,457,987 B | `Get-ChildItem -Recurse` |
| asar 内嵌 asar | **0** | REA 报告 `nested_asar_containers: 0` |

**大文件清单**（`app/`）：
`claude.exe` 245,756,240 · `app.asar` 49,338,428 · `smol-bin.x64.vhdx` 37,748,736 ·
`cowork-svc.exe` 13,761,360 · `resources.pak` · `icudtl.dat` · `ffmpeg.dll` · `vulkan-1.dll`

**关键构建产物**（`.vite/build/`）：
`index.pre.js` 930,575 · `index.chunk-lzaSYO3Q.js` 7,081,117 · `index.chunk-Bn6onBlX.js` 2,106,696 ·
`index.chunk-DNyequwM.js` 1,224,866 · `index.chunk-BlEfqh4Z.js` 917,018 ·
`mcp-runtime/directMcpHost.js` 613,700 · `file-index-worker/fileIndexWorker.js` 906,737 ·
`heavy-work-worker/heavyWorkWorker.js` 699,494

---

## 3. 逐条证据锚点（按发现编号索引）

| 编号 | 级别 | 文件 | 位置 |
|---|---|---|---|
| 001–002, 010–012 | S | `AppxManifest.xml` | 全文 |
| 003, 005–009 | S | `app/resources/` 目录树 | — |
| 004 | S | `app/resources/bundled-skills/manifest.json` | `agentSkillsRef` 字段 |
| 013 | S | `app.asar` → `package.json` | `main` / `devDependencies` |
| 014–028 | S | `.vite/build/index.pre.js` | 引导段（首个 200 KB） |
| 017 | S | 同上 | 16 元素数组 + `JZ()` 定义 |
| 018 | S | 同上 | `JZ(e)=>e.replace(/^(?:--|-|\/)/,"").toLowerCase().split("=",1)[0]` |
| 019 | S+R | 同上；实测 `--remote-debugging-port=9333` → `exit 1` | refusal 字符串 |
| 020–022 | S | 同上 | Ed25519 SPKI base64 |
| 023–024 | S | 同上 | `globalThis.ignoredUserDataDirEnv` |
| 025–028 | S | 同上 | Chromium 开关数组 |
| 029–033 | S | `.vite/build/index.pre.js` | `MZ` 枚举对象 |
| 034–038 | R | UIA | `indexes/uia-region-gate-full.json`（248 元素）、`uia-region-gate.json`（15） |
| 039–052 | S | `.vite/build/*.js` 全量 | `indexes/ipc-methods.json`（1,411 / 98）、`ipc-contract.json` |
| 053–070 | S | `.vite/build/index.chunk-DNyequwM.js` | **@1131100–1134600**（约 3,500 字符） |
| 071–080 | S | `.vite/build/index.chunk-Bn6onBlX.js` | **@62117** 起 |
| 081–090 | S | `cowork-svc.exe` Go 符号表 | `indexes/cowork-svc-go-symbols.json`（871 自有 / 4,412 标准库） |
| 091–099 | S | `.vite/build/index.chunk-lzaSYO3Q.js` | **@4319128–4341310** |
| 100–107 | S | `.vite/build/index.chunk-lzaSYO3Q.js` | 权限决策段 + @5698963（10 项权限集） |
| 108–109 | S | preload 产物 | `contextBridge` 19 节点 |
| 110 | S | `.vite/build/index.pre.js` | 启动拒绝原因枚举 |
| 111–112 | S | MCP zod schema | `type` 联合 + 字段表 |
| 113–115 | S | `indexes/feature-flags.json` | 130 flags / 58 prefs |
| 116 | S | 遥测构造代码 | 26 维字段 |
| 117–118 | S | 托管配置代码 | `surfaceGrants` / 4 通道 |

**三处最值钱的偏移，单独强调**：
- **`index.chunk-DNyequwM.js` @1131100–1134600** —— agent loop 不在桌面端的**决定性证据**。整段就是命令行构造器。
- **`index.chunk-lzaSYO3Q.js` @4319128–4341310** —— VM 运行时全部常量与 `startVM` 链路。
- **`index.chunk-Bn6onBlX.js` @62117** —— 33 个 hook 事件与 28 个 stream subtype。

---

## 4. 索引文件清单（`indexes/`，28 个）

| 文件 | 字节 | 内容 |
|---|---|---|
| `rea-js-app.json` | 107,902,353 | REA 全量 AST（**未上传，见 §6**） |
| `rea-digest.json` | 4,043,900 | AST 摘要 |
| `_rea-summary.txt` | 3,948,999 | REA 人类可读摘要 |
| `msix-inventory.json` | 1,993,039 | 4,443 成员逐条 |
| `structure.json` | 953,082 | 目录结构 |
| `ipc-surface.json` | 610,596 | ⚠️ **已弃用**，不可用作通道注册表 |
| `feature-census-ion.json` | 464,801 | ion-dist 4,026 资源特征普查 |
| `ipc-contract.json` | 441,126 | 通道名格式与契约 |
| `ipc-methods.json` | 424,656 | **1,411 方法 / 98 类** |
| `asar-inventory.json` | 287,693 | 506 文件 / 548 条目 |
| `cowork-svc-go-symbols.json` | 242,152 | 871 自有 + 4,412 标准库 |
| `cowork-svc-go-packages.json` | 206,374 | 6 包分布 |
| `enums.json` | 193,164 | **637 枚举**（键名 `items`） |
| `extract-all.json` | 156,236 | 环境变量 / 常量提取 |
| `uia-toggle-menu.json` | 133,068 | 菜单尝试（**失败记录**） |
| `uia-region-gate-full.json` | 129,829 | **248 元素**完整树 |
| `rea-facts.json` | 110,723 | REA 统计 |
| `uia-after-explore.json` | 86,063 | 254 元素（菜单展开后） |
| `feature-census-build.json` | 61,811 | 构建产物特征普查 |
| `_structure.txt` | 39,655 | 结构文本版 |
| `sdk-probe.json` | 19,280 | SDK 探测 |
| `feature-flags.json` | 15,532 | **130 flags / 58 prefs** |
| `_facts.txt` | 12,982 | 事实文本版 |
| `limitations.json` | 12,508 | 限制记录 |
| `uia-region-gate.json` | 7,184 | 15 元素（默认态） |
| **`coverage.json`** | **10,499** | **六项覆盖率 + 逐项判定明细** |
| `app-graph-census.json` | 1,488 | 1,674 节点 / 1,814 边 |
| `graph-kinds.json` | 721 | 图类型 |

---

## 5. REA 工具自身产出（可复核的统计）

`indexes/rea-facts.json` `statistics{}`：

| 字段 | 值 |
|---|---|
| `relevant_files` | 449 |
| `parsed_javascript_files` | **437** |
| `text_bytes_read` | 40,616,215 |
| `visited_ast_nodes` | **9,550,272** |
| `findings` | 6,604 |
| `parse_failures` | **0** |
| `nested_asar_containers` | 0 |
| `invalid_utf8_files` | 0 |
| `modules` | 0 |
| `visited_ast_nodes` 上限 | 100,000（语义图） |

语义图：45,298 节点 / 31,672 关系，`status: partial`，`truncated: true`（触达 100,000 上限）。
—— **这一条必须诚实标注**：语义图是**截断的**，不是全量。

REA 环境：`rea doctor` → `healthy: true`；Ghidra 12.1.4 在 `C:\Users\25011\.atlas-expert\tools\ghidra`；
Hopper / IDA **缺失**（macOS 工具 / 商业授权）。

---

## 6. 本地保留 vs 上传（REMOTE_NOT_SYNCED）

**上传到 Git 的**（本目录全部）：报告 6 份、`indexes/`（除下列大文件）、`viewer/`、
`screenshots/`（19 张 PNG）、脚本清单。

**只保留在本地 `D:\Atlas-Reverse-Lab\claude-desktop\` 的**：

| 对象 | 字节 | 不上传原因 |
|---|---|---|
| `input/claude-desktop-x64-2bf309665f.msix` | 297,191,037 | 283 MB，超 Git 单文件限制 |
| `extracted/`（全量解包） | 780,457,987 | 780 MB，且可从 MSIX 复现 |
| `indexes/rea-js-app.json` | 107,902,353 | 107.9 MB 全量 AST，可重跑 REA 得到 |
| `indexes/_rea-summary.txt` | 3,948,999 | 3.9 MB，与 digest 重复 |
| `progress/rea-js-app.err.log` | 80,652 | 中间日志 |

**复现命令**（任何人可重建）：
```powershell
& .\scripts\fetch-msix.ps1          # 从 GitHub 认证端点取 297 MB
& python .\scripts\extract_msix.py  # 解 4,443 成员
& python .\scripts\extract_asar.py  # 解 506 文件
& rea analyze ...                   # 重跑 AST
```

---

## 7. 未查清单（明确记录「没做什么」，附原因与解锁成本）

| # | 未查对象 | 原因 | 解锁最小成本 |
|---|---|---|---|
| 1 | `cowork-svc.exe` 函数体 | Ghidra 12.1.4 已就绪，**未执行** headless 反编译 | 1–2 小时一次批处理 |
| 2 | VM 内 guest agent | 在 `smol-bin.x64.vhdx`（37.7 MB）内，未挂载 | 需 VHDX 挂载工具 + 数小时 |
| 3 | 引擎二进制（Claude Code CLI） | **不在本样本内**，任务书明确属另一会话 | 需另一个样本 |
| 4 | Anthropic 服务端 | 网络服务 | 不可得，也不应获取 |
| 5 | CDP 授权私钥 | 设计上不在客户端 | 密码学不可得 |
| 6 | 登录后全部 UI | 区域门禁（产品主动限制） | 支持区域网络环境 |
| 7 | 原生菜单栏条目 | `Toggle menu` 无 `InvokePattern`，脚本缺合成点击回退 | ~30 分钟 |
| 8 | ion-dist 4,026 资源逐文件 | 已做特征普查，未逐个细读 | 数小时；优先级低于主进程 |
| 9 | Consumer Setup 安装器 | HTTP 403 `region_unavailable` | 支持区域下载环境 |
| 10 | 深色主题界面 | 实测环境为浅色，未切换验证 | 需过门禁 |
| 11 | 语义图全量 | REA 在 100,000 节点截断 | 调大上限重跑（内存代价高） |
| 12 | 2026-10-19 当日最新版 | `downloads.claude.ai` 连接超时 | 需可访问网络 |

**最重要的一条是 #3**：agent loop、工具实现、压缩算法、子代理调度器四条链断在同一处——
它们编译在引擎二进制里。这不是我漏了，是样本边界。

---

## 8. 官方文档（D 级，用于交叉校验）

| 主题 | URL | 用途 |
|---|---|---|
| Cowork 云端执行成为默认 | `https://support.claude.com/en/articles/16761823` | 解释为什么本地 VM 是过渡路径 |
| 侧栏内置浏览器 | `https://support.claude.com/en/articles/16607400` | 印证 `in-app-browser` 窗口角色 |
| Cowork 架构 | `https://support.claude.com/en/articles/14479288` | 印证 VM 隔离设计意图 |

**文档与代码的交叉验证结果**：
- 文档说「Cowork 默认云端」↔ 代码里本地 VM 仍在（`startVM` 完整存在）+ 保留给 2026-10-06 前的任务 → **一致**
- 文档说「侧栏有内置浏览器」↔ `MZ.IN_APP_BROWSER` 是一等窗口角色 + 31 个浏览器工具 → **一致**
- 文档说「VM 隔离」↔ `cowork-svc.exe` 871 函数 + `smir-bin.vhdx` + `efivars.fd` → **一致**

三处全部吻合，说明这个版本（2.42304.0，2026-10-15 构建）与 2026-10 的官方口径同步。

---

## 9. 证据级别分布

| 级别 | 含义 | 本报告条目数 |
|---|---|---|
| **S** | 源码/符号直接可见 | ~95 |
| **R** | 运行时实测 | ~18 |
| **D** | 官方文档 | 3 |
| **I** | 推断（已标依据） | ~8 |
| **U** | 不可得（已说明原因） | 12 项 |

「~」是估算，因为部分条目同时有 S 和 R 证据（如 019、023）。
精确逐条见 `DISCOVERY-LEDGER.md` 的「级」列。

---

## 10. 可复现脚本（`D:\Atlas-Reverse-Lab\claude-desktop\scripts\`，34 个）

| 脚本 | 作用 | 最近一次结果 |
|---|---|---|
| `fetch-msix.ps1` | 认证端点分段下载 | 297,191,037 B，SHA 校验通过 |
| `extract_msix.py` | 解 MSIX | 4,443 成员 |
| `extract_asar.py` | 解 asar | 506 文件 / 548 条目 |
| `go_symbols.py` | 抽 Go 符号 | 871 自有 / 4,412 标准库 |
| `go_packages.py` | 按包分组 | 6 包 |
| `ipc_scan.py` | 扫 eipc 通道 | — |
| `extract_ipc_methods.py` | 抽方法表 | **1,411 / 98** |
| `digest_rea_js.py` | AST 摘要 | 4,043,900 B |
| `feature_census.py` | 特征普查 | 需 2 参数 |
| `harvest_enums.py` | 枚举提取 | **637** |
| `extract_flags.py` | flag 提取 | **130 / 58** |
| `extract_all.py` | 环境变量 | 30 个 |
| `trace_chains.py` | 调用链 | — |
| `dump-uia.ps1` | **UIA 转储（可用）** | 15 → 248 元素 |
| `capture-window2.ps1` | **PrintWindow 截图（可用）** | 3 张 |
| `uia-invoke.ps1` | 控件调用 | ⚠️ `Toggle menu` 失败 |
| `build_viewer_data.py` | 构图鉴数据 | 需 2 参数 |
| `emit_viewer_js.py` | JSON→JS | `MISSING: none` |
| `build_coverage.py` | **算六项覆盖率** | 10,499 B |
| `patch_cov_page.py` | 注入 `P.cov` | 3,960 字符 |
| `check_viewer.py` | 静态校验 | **ALL CHECKS PASSED** |
| `render_viewer.py` | 16 页渲染 | **ALL 16 PAGES RENDER** |
| `diff_hooks.py` | **与 Atlas 比对 hook** | **双向差集 none** |
| `count_atlas_tools.py` | 数 Atlas 工具 | 12 个 |

复现全流程：
```powershell
$py = "C:\Users\25011\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
$R  = "D:\Atlas-Reverse-Lab\claude-desktop"
& $py "$R\scripts\build_coverage.py"
& $py "$R\scripts\patch_cov_page.py"
& $py "$R\scripts\check_viewer.py"
& $py "$R\scripts\render_viewer.py"
& $py "$R\scripts\diff_hooks.py"
```

---

## 11. 环境（让读者能判断证据的可信边界）

| 项 | 值 |
|---|---|
| OS | Windows（中文区域设置，影响 UIA 控件名本地化） |
| 时区 | Asia/Hong_Kong |
| Claude Desktop | **未安装为 MSIX 包**；R 级证据来自直接运行解包后的 Electron 树（`--no-sandbox`） |
| 侧加载 | 需要 Anthropic 签名证书，**超出范围** |
| Chrome | `C:\Program Files\Google\Chrome\Application\chrome.exe`（仅 `--headless=new` 调用会退出） |
| Python | 3.12.14（DSH 内置） |
| Node | 24.18.1 |
| ffmpeg | 8.1.2（GIF 未使用，理由见 `UI-AND-WORKFLOWS.md` §三） |
| 缺失 | 7z / strings / sqlite3（用 Python 替代） |

**未安装 MSIX 会影响什么**：不影响静态证据（S），但影响所有依赖「已登录产品态」的运行时证据（R）。
这也解释了为什么界面可视化覆盖率只有 2/12——不是没跑，是跑起来也只能到错误页。

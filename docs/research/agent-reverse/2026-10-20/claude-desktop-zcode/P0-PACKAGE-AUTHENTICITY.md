# P0 — 包获取、真实性、版本与完整性

> 执行者：ZCode（DeepSeek V4.1 Flash）  
> 执行日期：2026-10-20  
> 分支：`research/zcode-claude-desktop-anatomy-20261020`  
> 本阶段状态：**DONE（静态取证部分）**，版本“最新性”见 §2 的明确限定。

---

## 1. 逐字节复核结果（从原包重算，不继承旧结论）

| 对象 | 路径 | 字节数 | SHA256 | 与任务书基线 |
|---|---|---:|---|---|
| MSIX | `D:\Atlas-Reverse-Lab\claude-desktop\input\claude-desktop-x64-2bf309665f.msix` | 297,191,037 | `2bf309665f0de4eaa76a7e64033594e6f73ceb6413c60080f72f3ce640fa24ee` | **完全一致** |
| app.asar | MSIX 内 `app/resources/app.asar` | 49,338,428 | `8f4d3dec5e4f3ddffb150321060b18807d83a40f3a65618fe4f29325379da9db` | **完全一致** |
| cowork-svc.exe | MSIX 内 `app/resources/cowork-svc.exe` | 13,761,360 | `934e5b671813ef3d5684c0ee0d1d18835af74e9ecfb114575e0d8fdbb663ba8f` | **完全一致** |

同一 MSIX 在三个独立副本上哈希一致（`D:\agent-client-staging\release-assets\`、`D:\agent-client-staging\claude-codex\claude-desktop\`、`D:\Atlas-Reverse-Lab\claude-desktop\input\`），均为 297,191,037 bytes / 同 SHA。说明本地归档未被篡改或截断。

**Zip 完整性**：`zipfile` 顺序读取全部 4,443 个条目，全部 CRC 校验通过（读取时 Python 的 `ZipExtFile` 会在 CRC 不匹配时抛错，本次零异常）。

**解包复验**：把 4,443 个条目独立解到 `extract\`，再对每个文件重算 SHA256 与 SIZE，与 `FILE-LEDGER.tsv` 比对 → **mismatch = 0**。

## 2. 版本与发行通道（截至 2026-10-20 实际探测）

| 通道 | 端点 | 结果 | 结论 |
|---|---|---|---|
| Windows Squirrel (consumer/stable) | `https://storage.googleapis.com/osprey-downloads-.../nest-win-x64/RELEASES` | HTTP 200，6,664 bytes | 最新条目 `AnthropicClaude-0.14.10-full.nupkg` 131,185,172 bytes |
| Windows Squirrel (arm64) | `.../nest-win-arm64/RELEASES` | HTTP 200，6,662 bytes | 同构通道存在 |
| MSIX 目录桶 | `nest-win-x64-msix` / `-stable` / `-beta` | HTTP 404 | 无该桶 |
| Claude 官方下载页 | `https://claude.ai/download` | HTTP 302 → `claude.com/app-unavailable-in-region` | 本机地区不可用 |
| MSIX 直链 | `https://claude.ai/api/desktop/win32/x64/msix/latest/redirect` | HTTP 403，`X-Claude-Error-Code: region_unavailable` | 无法取得 consumer MSIX |

**版本的准确表述（不得含糊）**：
- 固定分析样本是企业/Store 线 **2.42304.0**（`AppxManifest Identity Version="2.42304.0.0"`，PE 版本资源 `2.42304.0`）。
- 本地另有 Squirrel 线 **2.42304.2** 完整 nupkg（asar `package.json` version=`2.42304.2`），可作同代补丁级比对。
- Squirrel 公开稳定通道当前最新为 **0.14.10**（与本地 `AnthropicClaude-0.14.10-full.nupkg` 字节数完全一致，131,185,172）。
- 因此存在**两条互不同步的版本线**：`0.14.x`（Squirrel consumer）与 `2.4230x`（MSIX/Store enterprise）。**不能用 0.14.10 的功能描述去证明 2.42304.0 有什么**，反之亦然。
- **对“官方最新版本”的限定**：MSIX 线的最新版本号本次未能验证（`region_unavailable`），只能写 **latest unverified**；0.14.10 是 Squirrel 线当前 RELEASES 末端，属于可验证事实。

## 3. 交付物清单（全部由原包重算生成）

| 文件 | 行数/条数 | 内容 |
|---|---:|---|
| `index/FILE-LEDGER.tsv` | 4,443 文件 | 每条：ID、版本、包 SHA、路径、size、compressed、SHA256、CRC32、格式嗅探、层级、扩展名 |
| `index/ASAR-FILE-LEDGER.tsv` | 548 路径（506 文件 + 42 目录） | 每条：ASAR 内 offset、size、SHA256、是否 unpacked、扩展名 |
| `index/ARCHIVE-NESTING.tsv` | 202 条 | MSIX → ASAR → `.skill` ZIP → 内部文件；以及 asar 内的独立二进制/库 |
| `index/SKILL-CONTAINER-LEDGER.tsv` | 188 条 | 6 个 `.skill` 内的每个文件路径/size/SHA256 |
| `index/PE-BINARIES.tsv` | 18 条 | 全部 PE 的架构、PE32+、子系统 |
| `index/PE-VERSION-SIGNATURE.json` | 9 条 | 版本资源 + Authenticode 状态 + 签名主体 |
| `index/P0-DIFF-VS-2026-10-19.tsv` | 0 added / 0 removed / 0 changed | 与上一轮 4,443 条基线逐行 diff |
| `index/P0-SUMMARY.json` / `P0-ASAR-SUMMARY.json` | — | 机器可读汇总 |

## 4. 实物结构（第一层解剖）

### 4.1 MSIX 内层级分布

| 层 | 条目数 | 说明 |
|---|---:|---|
| `resources` | 4,284 | 绝大多数是 Electron 的 `locales/*.pak` 与资源 |
| `app-shell` | 72 | `claude.exe` + Chromium/ANGLE/V8 运行时 DLL 与 pak |
| `assets` | 69 | Store 图标、磁贴 |
| `package-metadata` | 10 | `AppxManifest.xml`、`AppxBlockMap.xml`、`AppxSignature.p7x`、`resources*.pri` |
| `asar` | 7 | `app.asar` 本体 + `app.asar.unpacked/` 下 6 个外置原生文件 |
| `package-other` | 1 | `[Content_Types].old` |

格式分布：TEXT 4,052、BINARY 138、PNG 128、WOFF2 49、WOFF 20、PE 18、GIF 16、XML 12、JSON/ASAR 5、WASM 3、V8JSC/PYC 2。

### 4.2 ASAR 内结构

| 目录 | 说明 |
|---|---|
| `.vite/build/` | Electron **主进程 + preload + worker** 的 369 个 JS chunk，含 `index.pre.js`（主入口） |
| `.vite/renderer/` | **6 套**独立渲染器：`main_window`、`quick_window`、`buddy_window`、`about_window`、`find_in_page`、`local_exec_consent` |
| `node_modules/` | 运行时依赖（`@ant/claude-native`、`node-pty`、`ws`、`agent-base` 等） |
| `compile-cache/` | V8 code cache，含 `index.chunk-lzaSYO3Q.js.x64.jsc` 6.86 MB |
| `resources/` | `artifact-libs`、`bundled-skills`、`office365-mcp` |

ASAR 扩展名分布：js 431、css 16、woff2 21、html 6、json 6、skill 6、mjs 4、node 4、jsc 3、ts 2、md 2、exe 1、dll 1、png 1、无扩展 2。

### 4.3 18 个 PE（全部 x64，全部 Authenticode `Valid`，签名主体均为 `CN="Anthropic, PBC"`）

| 路径 | 字节 | 子系统 | 备注 |
|---|---:|---|---|
| `app/claude.exe` | 245,756,240 | GUI | Electron 主程序，FileVersion 2.42304.0 |
| `app/resources/cowork-svc.exe` | 13,761,360 | CUI | **Go 1.25.14**，CoworkVMService |
| `app/resources/claude-ssh-broker.exe` | 2,599,248 | CUI | Go 1.25.14 |
| `app/resources/claude-ssh-proxy.exe` | 1,976,144 | CUI | Go 1.25.14 |
| `app/resources/claude-ssh-askpass.exe` | 2,648,912 | CUI | Go 1.25.14 |
| `app/resources/chrome-native-host.exe` | 1,130,832 | CUI | 浏览器扩展 native messaging |
| `app/resources/app.asar.unpacked/.../claude-native-binding.node` | 3,778,896 | GUI | N-API 原生绑定 |
| `.../node-pty/prebuilds/win32-x64/conpty.node` | 312,144 | GUI | ConPTY |
| `.../conpty_console_list.node` | 155,472 | GUI | ConPTY 控制台列表 |
| `.../resources/github-mcp/github-mcp-server.exe` | 20,566,352 | CUI | 内置 GitHub MCP server |
| `.../resources/office365-mcp/msal-node-runtime.node` | 365,904 | CUI | MSAL 运行时 |
| `.../resources/office365-mcp/msalruntime.dll` | 3,261,536 | CUI | MSAL 原生库 |
| `app/d3dcompiler_47.dll` | 4,762,296 | CUI | Chromium 依赖 |
| `app/dxcompiler.dll` | 25,765,200 | CUI | Chromium 依赖 |
| `app/dxil.dll` | 1,530,560 | CUI | Chromium 依赖 |
| `app/ffmpeg.dll` | 3,134,288 | CUI | Chromium 媒体 |
| `app/vk_swiftshader.dll` | 5,541,200 | CUI | 软件 Vulkan |
| `app/vulkan-1.dll` | 960,336 | CUI | Vulkan loader |

## 5. AppxManifest 揭示的宿主契约（这是真实安装语义，不是猜测）

- **Identity**：`Name="Claude"`，`ProcessorArchitecture="x64"`，`Version="2.42304.0.0"`，Publisher 为 Anthropic 私有组织证书。
- **三个 Application 入口**：
  1. `Claude` → `app\Claude.exe`，`Windows.FullTrustApplication`，含 startupTask（`TaskId="ClaudeStartup"`，默认 `Enabled="false"`，参数 `--startup`）、`claude://` 协议、执行别名 `claude-desktop.exe`；
  2. `SshAskpass` → `app\resources\claude-ssh-askpass.exe`，别名 `claude-ssh-askpass.exe`，`AppListEntry="none"`；
  3. `SshProxy` → `app\resources\claude-ssh-proxy.exe`，别名 `claude-ssh-proxy.exe`，`AppListEntry="none"`。
- **Windows 服务**：`desktop6:Extension Category="windows.service"` → `app\resources\cowork-svc.exe`，`Name="CoworkVMService"`，`StartupType="auto"`，`StartAccount="localSystem"`。触发事件为 **ETW 自定义触发器**（`Subtype=1f81d131-3e60-4c76-9860-37334e4ffce3`，DataItem `\pipe\cowork-vm-service`），manifest 注释明确写了“pipe activity does not fire it，app 自己启动 stopped service”。
- **能力**：`runFullTrust`、`localSystemServices`、`packagedServices`、`unvirtualizedResources`、`internetClient`。
- **注册表虚拟化排除**（11 个键）：Chrome / Brave / Edge / PrismaAccess / Island / Chromium / Arc / Vivaldi / Opera 的 `NativeMessagingHosts\com.anthropic.claude_browser_extension`，两个 Chrome 扩展 ID（`fcoeoabgfenejglbffodgkkbkcdhcgfn`、`dngcpimnedloihjnnfngkgjoidhnaolf`），以及 Office add-in 的 `TrustedCatalogs`。
- **文件系统虚拟化排除**：`%LOCALAPPDATA%\Microsoft\Office\16.0\WEF`、`%LOCALAPPDATA%\Claude-3p`、`%LOCALAPPDATA%\Claude-Data`、`%LOCALAPPDATA%\Claude\logs`。注释直接说明 **1P userData 会被 `index.pre.ts` 移出包目录**，且 **VM service 在包外运行、需要真实路径**。
- **防火墙规则**：为 `Claude.exe` 与 `cowork-svc.exe` 各注册入站/出站 TCP 全放行。

> 这些是 P5（原生宿主/服务）与 P4（数据持久化）的直接锚点，已在 P0 记录，后续阶段按此追踪。

## 6. 与上一轮基线的 diff

`P0-DIFF-VS-2026-10-19.tsv`：**added=0, removed=0, changed=0**（4,443 vs 4,443）。  
ASAR：本轮独立解析得 **548 路径 = 506 文件 + 42 目录**，与旧记录一致。  
旧解析器声称“437 个 JS parse success” —— 本轮不继承该结论：ASAR 内实际 `.js` 为 **431** 个，另有 `.mjs` 4、`.jsc` 3、`.ts` 2。**“437 parse success”与本轮文件计数不可直接对齐，已列入待解释项（见 `12-UNKNOWN` 雏形）**。

## 7. 尚未取得 / 明确缺口

| 缺口 | 具体条件 | 补采办法 |
|---|---|---|
| Consumer MSIX 最新版 | `claude.ai` 对本机返回 `region_unavailable`（403 / 302） | 在允许地区网络或已登录账号下访问 `claude.ai/download`，记录版本与 SHA |
| macOS 版 | 未取得 | 需 macOS 环境；**不得以 macOS 线索冒充 Windows 实装** |
| 运行证据（R 级） | 本机**未安装** Claude Desktop：`Get-AppxPackage` 无 Claude、无 `claude*` 进程、无 `CoworkVMService` 服务 | P7 需在测试机安装 2.42304.0 MSIX（需证书信任/开发者模式）后采集 |
| 服务端内部实现 | 不可得 | 仅分析客户端可观察协议，标 CLOUD-UNKNOWN |

## 8. 本地材料绝对路径

```
D:\Atlas\_research\claude-desktop\2026-10-20\
├── scripts\        p0_ledger.py, p0_extract_verify.py, p0_pe.py, p0_pe_meta.py, p0_nesting.py
├── index\          FILE-LEDGER.tsv, ASAR-FILE-LEDGER.tsv, ARCHIVE-NESTING.tsv,
│                   SKILL-CONTAINER-LEDGER.tsv, PE-BINARIES.tsv, PE-VERSION-SIGNATURE.json,
│                   PACKAGE-MANIFEST.tsv, P0-DIFF-VS-2026-10-19.tsv, P0-SUMMARY.json, P0-ASAR-SUMMARY.json
├── extract\        4,443 条 MSIX 条目全文 + _asar\ (500 个 ASAR 内文件)
├── evidence\
└── runtime\        (P7 预留)
原包: D:\Atlas-Reverse-Lab\claude-desktop\input\claude-desktop-x64-2bf309665f.msix
```

复验命令（任何人可重跑）：

```bash
cd D:/Atlas/_research/claude-desktop/2026-10-20
python scripts/p0_ledger.py            # 重新生成 FILE-LEDGER / ASAR-FILE-LEDGER
python scripts/p0_extract_verify.py    # 解包并逐文件哈希复验 + 与旧基线 diff
```

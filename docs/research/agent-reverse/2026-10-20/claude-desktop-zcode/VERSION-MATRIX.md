# VERSION-MATRIX — Claude Desktop（Windows）

> 生成于 2026-10-20。所有“已验证”项均来自本地实物字节；所有“未验证”项明确标注来源与缺口。

## 1. 版本线

| 版本线 | 分发机制 | 本地实物 | 版本号来源 | 状态 |
|---|---|---|---|---|
| **MSIX / Store（enterprise）** | MSIX 包，AppxManifest + `windows.service` 扩展 | `claude-desktop-x64-2bf309665f.msix` 297,191,037 B<br>SHA `2bf30966…fa24ee` | `AppxManifest Identity Version="2.42304.0.0"`<br>`claude.exe` FileVersion `2.42304.0` | **已验证**（固定分析基准） |
| **Squirrel full nupkg（同代补丁）** | `.nupkg` + `RELEASES` | `AnthropicClaude-2.42304.2-full.nupkg` 262,853,497 B<br>SHA `b2914715…eae8cc` | asar `package.json` → `"version": "2.42304.2"` | **已验证**（本地实物） |
| **Squirrel full nupkg（公开稳定通道）** | `.nupkg` + `RELEASES` | `AnthropicClaude-0.14.10-full.nupkg` 131,185,172 B<br>SHA `0be53c64…0683fc` | `AnthropicClaude.nuspec` → `0.14.10` | **已验证**（本地实物，与官方 RELEASES 末行字节数一致） |
| **Squirrel bootstrapper** | `Setup.exe`，运行时按 RELEASES 拉包 | `Claude-Setup-x64.exe` 132,098,208 B<br>SHA `4a7fe5bc…c6aa9` | 内嵌 RELEASES 链 | **已验证**（本地实物） |

### 1.1 官方通道探测（2026-10-20 实况）

| 端点 | HTTP | 结果 |
|---|---|---|
| `https://storage.googleapis.com/osprey-downloads-c02f6a0d-347c-492b-a752-3e0651722e97/nest-win-x64/RELEASES` | 200 | 6,664 B；末行 `AnthropicClaude-0.14.10-full.nupkg 131185172` |
| `.../nest-win-arm64/RELEASES` | 200 | 6,662 B（arm64 通道存在） |
| `.../nest-win-x64-msix/RELEASES` | 404 | 无独立 MSIX 桶 |
| `https://claude.ai/download` | 302 → 200 | 跳转 `claude.com/app-unavailable-in-region` |
| `https://claude.ai/api/desktop/win32/x64/msix/latest/redirect` | 403 | `X-Claude-Error-Code: region_unavailable` |

**结论**：MSIX 线是否已有 >2.42304.0 的版本 **未验证（latest unverified）**。本次不编造。Squirrel 线可验证最新 = 0.14.10。

## 2. 两条版本线不是同一产品的同一数值空间

| 维度 | 0.14.10（Squirrel consumer） | 2.42304.0（MSIX enterprise） |
|---|---|---|
| 主入口 | `package.json` → `.vite/build/index.pre.js` | 同 |
| 包结构 | `.nupkg`（zip，`lib/net45/…`） | `.msix`（Appx） |
| 安装/服务语义 | Squirrel 注册表 + 登录项 | `windows.service` 扩展注册 `CoworkVMService`（localSystem, auto） |
| 注册表虚拟化 | 无 | 11 个 NativeMessagingHosts/扩展/Office 键被排除 |
| 文件虚拟化 | 无 | 4 个目录被排除（`Claude-3p`、`Claude-Data`、`Claude\logs`、Office WEF） |
| 协议/别名 | 登录项 `--startup` | `claude://`、`claude-desktop.exe`、`claude-ssh-askpass.exe`、`claude-ssh-proxy.exe` |

**硬规则**：任何功能结论必须绑定到具体版本线；不得用 0.14.10 证据证明 2.42304.0 的行为，反之亦然。

## 3. 跨版本内容对照（同代：2.42304.0 MSIX vs 2.42304.2 nupkg）

| 项 | 2.42304.0（MSIX） | 2.42304.2（nupkg） |
|---|---|---|
| asar 内 `package.json` name | 见 asar 原文件 | `@ant/desktop` |
| asar `desktopName` | — | `com.anthropic.Claude.desktop` |
| resources 组成 | artifact-libs / bundled-skills / office365-mcp / github-mcp | 同四类 |
| 是否含 `compile-cache` | 是（3 个 .jsc） | 是 |
| **差异状态** | — | **尚未逐文件 diff**（P6 处理） |

> 2.42304.2 的完整逐文件 diff 需要先解其 asar；列入 P1/P6 待办，不在 P0 虚报。

## 4. 平台

| 平台 | 取得情况 |
|---|---|
| Windows x64 | ✅ 三份实物（MSIX 2.42304.0、nupkg 2.42304.2、nupkg 0.14.10 + Setup） |
| Windows arm64 | ⚠️ 仅确认官方 RELEASES 通道存在（6,662 B），未下载实物 |
| macOS | ❌ 未取得，不做任何结论 |
| Linux | ❌ 未取得（asar 内有 `TrayIconLinux*.png` 资源，仅说明代码支持，不等于发布） |

## 5. 运行环境（P7 前置）

| 检查 | 结果 |
|---|---|
| `Get-AppxPackage` 含 Claude | ❌ 无 |
| `claude*` 进程 | ❌ 无 |
| `CoworkVMService` 服务 | ❌ 无 |
| `%LOCALAPPDATA%\Claude` | 仅 `logs\`，无安装体 |
| `%APPDATA%\Claude` | 存在 Chromium userData 残留（Cache/Crashpad/blob_storage 等），非安装证据 |

→ **P7 运行时取证前提不成立**；需先在本机或测试机安装 2.42304.0 MSIX（需签名信任）。已在 `P0-PACKAGE-AUTHENTICITY.md` §7 记为明确缺口。

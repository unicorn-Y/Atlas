# P5 — Windows 原生宿主与 cowork-svc 深入解剖

> 样本：`app/resources/cowork-svc.exe`，13,761,360 B，SHA256 `934e5b671813ef3d5684c0ee0d1d18835af74e9ecfb114575e0d8fdbb663ba8f`，Authenticode `Valid`
> 方法：自写 Go pclntab 解析器（不依赖 Ghidra），逐函数读取 `funcnametab` / `pclntab` / `moduledata`

---

## 1. 二进制身份（实测）

| 项 | 值 |
|---|---|
| 架构 | PE32+ x64, subsystem CUI |
| Go 版本 | **go1.25.14**（`Go buildinf:` 存在） |
| 主模块 | **`github.com/anthropics/cowork-win32-service`** |
| 入口包 | `.../cmd/cowork-svc` |
| 构建参数 | `-buildmode=exe -compiler=gc -ldflags="-s -w"` `CGO_ENABLED=1` `GOARCH=amd64` `GOOS=windows` `GOAMD64=v1` |
| 函数总数 | **15,181**（pclntab `nfunc=15181`） |
| 源文件数 | pclntab `nfiles` 已记录于 `GO-BUILDINFO.json` |
| 镜像基址 | `0x140000000` |

**注意**：`-ldflags="-s -w"` 剥离了 DWARF 与符号表，但 **pclntab 完整保留**，因此函数名/边界可 100% 恢复。

## 2. 四个 Go 二进制的全量函数账

| 二进制 | 字节 | 主模块 | 函数数 |
|---|---:|---|---:|
| `cowork-svc.exe` | 13,761,360 | `github.com/anthropics/cowork-win32-service` | **15,181** |
| `claude-ssh-askpass.exe` | 2,648,912 | `github.com/anthropics/ssh-askpass` | 2,865 |
| `claude-ssh-broker.exe` | 2,599,248 | `github.com/anthropics/ssh-askpass` | 2,786 |
| `claude-ssh-proxy.exe` | 1,976,144 | `github.com/anthropics/ssh-askpass` | 2,186 |
| **合计** | | | **23,018** |

输出：`GO-FUNCTIONS.tsv`（23,018 行，含 `entry_hex` 与 `size`）、`GO-PACKAGES.tsv`、`GO-DEPENDENCIES.tsv`（24 个模块）、`GO-BUILDINFO.json`。

## 3. 第一方包结构（cowork-svc 的真实内部划分）

```
github.com/anthropics/cowork-win32-service/
├── cmd/cowork-svc            入口
├── vm/                       VM 管理（最大）
│   ├── WindowsVMManager      StartVM / StopVM / installHostCACertificates
│   ├── HCS 封装              CreateComputeSystem / InitHCS / (*HCSSystem).Start|Shutdown
│   ├── HVSocketConn / NewHVSocketListener
│   ├── RPCServer             Start / Stop / SendGuestResponse / SendInstallCACertificates
│   │                         / SendNotification / SendRequestAndWait / handleEvent
│   │                         / handleMessage / handleResponse / writeFrameUnless
│   ├── mountSharesInGuest
│   ├── fetchPACScript / proxyAttempts
│   ├── LoadTrustedCACertificates
│   └── CleanupStaleVMs
├── pipe/                     命名管道服务
│   ├── Server                Start / Stop / acceptLoop / dispatch / dispatchVerified
│   │                         / dispatchWithSession / getOrCreateSession
│   │                         / InitSignatureVerification / verifyClientSignature
│   └── 业务 handler 见 §4
├── edrgate / edrpolicy       EDR 集成与策略（RunEdrExtension / RunEdrExtension）
└── logsink                   Writer（日志汇聚）
```

## 4. 命名管道 RPC 方法表（真实函数名，不是字符串猜测）

从 pclntab 恢复的 `pipe.(*Server)` 全部 handler：

```
handleConfigure            handleStartVM            handleStopVM
handleIsRunning            handleIsProcessRunning   handleWriteStdin
handleGetNetworkDrives     handlePassthrough        handlePersistentRPC
handleRefreshGuestProxy    handleSubscription       handleSendGuestResponse
handleRunEdrExtension      handleIsDebugLoggingEnabled   handleSetDebugLogging
```

会话与签名层：

```
InitSignatureVerification   verifyClientSignature   getOrCreateSession
getSessionForConn           setSessionForConn       removeConnSession
checkIdleSessions           idleSessionChecker      stopAllSessions
dispatch                    dispatchVerified        dispatchWithSession
acceptLoop                  handleConnection        edrAnswer / edrNotAnswered / edrRefused
```

**代码体量**：`handleConfigure` 单函数 **10,112 字节**（`0x14051a5e0`），是全服务最大的 handler —— 说明 VM 配置逻辑高度集中在这一个入口。

## 5. 对旧文档 6 条协议声明的逐条核验

| # | 旧声明 | 结论 | 证据 |
|---|---|---|---|
| 1 | 管道 `\\.\pipe\cowork-vm-service` | **VERIFIED** | AppxManifest `desktop6:StringData Value="\pipe\cowork-vm-service"`；`pipe.(*Server)` 包存在 |
| 2 | 4-byte big-endian JSON 帧 | **PARTIALLY VERIFIED** | 存在 `RPCServer.writeFrameUnless` / `handleMessage` / `handleResponse` 帧层；分帧字节序需指令级确认（`writeFrameUnless` 反汇编未逐条展开） |
| 3 | 10 MiB 上限 | **UNRESOLVED** | 未在已提取字符串中找到确切的 10 MiB 常量；需对 `handleMessage` 做常量扫描 |
| 4 | 方法 configure / startVM / stopVM / isRunning / isGuestConnected / spawn / kill / writeStdin | **大部分 VERIFIED，两个改名** | `handleConfigure`、`handleStartVM`、`handleStopVM`、`handleIsRunning`、`handleWriteStdin` 均存在；**未找到 `spawn` / `kill` / `isGuestConnected`**，对应能力由 `handlePassthrough` + `RPCServer.IsConnected` 承担 |
| 5 | 事件 stdout / stderr / exit / error / networkStatus / apiReachability / startupStep | **PARTIALLY VERIFIED** | `RPCServer.handleEvent` + `SendNotification` 存在；`fetchPACScript`、`proxyAttempts` 对应 networkStatus/apiReachability 语义；具体事件名需在 `handleEvent` 的字符串引用点确认 |
| 6 | 宿主服务由 MSIX 注册为 localSystem | **VERIFIED** | AppxManifest `desktop6:Service Name="CoworkVMService" StartupType="auto" StartAccount="localSystem"` |

## 6. VM 的实现技术栈（由依赖树反推，非猜测）

`GO-DEPENDENCIES.tsv` 中 cowork-svc 的 24 个模块，构成本次最重要的架构发现：

| 模块 | 版本 | 说明 |
|---|---|---|
| `github.com/Microsoft/go-winio` | v0.6.2 | Windows 命名管道 / AF_UNIX |
| `github.com/anthropics/win-httpproxy` | v0.0.0（本地 replace） | **第一方** HTTP 代理 |
| `github.com/containers/gvisor-tap-vsock` | v0.8.9（本地 replace） | **用户态网络栈**，把 VM 流量经 vsock 转成用户态 TCP/IP |
| `gvisor.dev/gvisor` | v0.0.0-20260413… | **gVisor**（沙箱化用户态内核） |
| `github.com/google/gopacket` | v1.1.19 | 抓包/包构造 |
| `github.com/google/btree` | v1.1.2 | gVisor 连接跟踪用 |
| `github.com/insomniacslk/dhcp` | v0.0.0-2026… | VM 内 DHCP |
| `github.com/miekg/dns` | v1.1.73 | VM 内 DNS 解析 |
| `github.com/linuxkit/virtsock` | v0.0.0-2022… | vsock 实现 |
| `github.com/inetaf/tcpproxy` | v0.0.0-2026… | 端口转发 |
| `github.com/pierrec/lz4/v4` | v4.1.14 | 传输压缩 |
| `github.com/u-root/uio` | v0.0.0-2024… | 低层 I/O |
| `github.com/sirupsen/logrus` | v1.10.2 | 结构化日志 |
| `golang.org/x/crypto` | v0.55.0 | 加密 |
| `golang.org/x/net` / `sys` / `time` / `exp` | — | 标准扩展 |

**结论（S）**：Cowork 的本地 VM 不是"简单跑个 Hyper-V 虚机"。它是：

```
Hyper-V HCS (CreateComputeSystem / HVSocket)
        ↕ vsock
gvisor-tap-vsock + gVisor 用户态网络栈
        ↕
win-httpproxy（第一方出网代理）+ PAC 脚本 + 宿主 CA 证书注入
```

即 **VM 的出网流量被第一方代理 + gVisor 网络栈接管**，配合 `installHostCACertificates` / `LoadTrustedCACertificates` 做 TLS 中间人信任，`fetchPACScript` 支持企业 PAC 代理。这与 P4 中的 `egressProxyUrl`/`egressProxyPacUrl`/`coworkEgressAllowedHosts` 三个策略 flag 完全对应。

## 7. EDR 集成（此前未被记录）

发现独立的 `edrgate` 与 `edrpolicy` 包，以及：
- `pipe.(*Server).handleRunEdrExtension`
- `pipe.(*Server).runEdrExtension`
- `pipe.(*Server).edrAnswer` / `edrNotAnswered` / `edrRefused`

与 P4 的 feature flag `coworkEDRIntegration` / `coworkEDRIntegrationVendor` 对应。说明存在**第三方 EDR（端点检测响应）产品接入协议**：服务把事件交给 EDR 扩展，EDR 可回答允许/拒绝/未回答。

## 8. SSH 三件套

三个二进制同源（`github.com/anthropics/ssh-askpass`），函数数分别 2,865 / 2,786 / 2,186。依赖只有 `go-winio` + `golang.org/x/sys`（broker/askpass 多一层），说明它们是**瘦客户端**：
- `claude-ssh-askpass.exe`：SSH 密码/口令交互的 GUI 替身（manifest 声明 `AppListEntry="none"`）。
- `claude-ssh-proxy.exe`：SSH 代理（manifest 别名 `claude-ssh-proxy.exe`）。
- `claude-ssh-broker.exe`：凭据代理（未在 manifest 的 Application 中单列，由 broker 被 proxy/askpass 拉起或由主进程调用）。

运行期日志 `[ClaudeSSHManager] Initialized with version 683cc6a9cd1d99430efd762587e02dd076fd5ada`（P7 run-01）确认 SSH 管理器在启动时即初始化。

## 9. 未解清单（诚实计数）

| 项 | 状态 | 原因 |
|---|---|---|
| 帧格式的字节序与长度前缀具体实现 | 部分 | `writeFrameUnless` 已定位（`0x1404f…`），未做逐指令反汇编 |
| 10 MiB 限制常量 | U | 未在字符串/常量扫描中确认 |
| `handleEvent` 的完整事件名枚举 | U | 事件名通过枚举常量生成，需定位其数据段 |
| HCS API 的具体导入（`vmcompute.dll`） | 部分 | PE 导入表已提取（`PE-IMPORTS.tsv`），但未逐项映射到 handler |
| `handlePassthrough` 的转发目标 | U | 函数存在（大小已记录），语义未展开 |
| `edrgate` 的协议细节 | U | 仅确认包与 handler 存在 |
| 尚未反汇编的函数 | 15,181 中绝大多数 | 本阶段目标是**全量函数账 + 关键链路**，不是逐函数反编译；所有函数名/地址/大小已可检索 |

## 10. 产物

```
index/GO-FUNCTIONS.tsv      23,018 行（binary/index/package/function/entry_hex/size/first_party）
index/GO-PACKAGES.tsv       按 (binary, package) 聚合的函数计数
index/GO-DEPENDENCIES.tsv   24 个 Go 模块及版本 / replace
index/GO-BUILDINFO.json     每二进制 gover + modinfo + pclntab 元数据
index/PE-IMPORTS.tsv        各 PE 的 DLL 导入表
index/PE-BINARIES.tsv       18 个 PE 的架构/子系统
index/work-P5/*.json        原始 pclntab 与字符串引用点转储（可复算）
index/work-P5/PARSERS/      解析器源码
```

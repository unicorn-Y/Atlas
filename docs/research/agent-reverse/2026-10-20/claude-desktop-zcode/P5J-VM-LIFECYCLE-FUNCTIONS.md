# P5J — `cowork-svc` 的 VM 生命周期：216 个函数的完整拆解

> 补全 `P5`/`P5B` 里 `vm` 包只说"463 个函数"的部分。这里按接收者类型分组，
> 把 VM 从创建到销毁的每一步都落到函数上。

---

## 1. 按类型分布（216 个）

| 类型 | 函数数 | 职责 |
|---|---:|---|
| `(*WindowsVMManager)` | **45** | VM 总控（最大） |
| `(*RPCServer)` | 15 | guest 侧 RPC |
| `(*HVSocketConn)` | 8 | vsock 连接 |
| `(*HCSSystem)` | 7 | HCS 计算系统封装 |
| `(*proxyAttempts)` | 6 | 代理重试 |
| `(*VirtualNetworkProvider)` | 5 | 虚拟网络 |
| `(*sockRef)` | 4 | socket 引用计数 |
| `(*ConsoleReader)` | 3 | 串口控制台读取 |
| 其余（类型与自由函数） | ~120 | 配置、磁盘、证书、PAC、GUID 等 |

## 2. VM 创建链（S，按调用顺序）

```
1. (*VMConfig).BuildHCSDocument            5,952 B   ← 生成 HCS 配置 JSON
2. vm.CreateDynamicVHDX                    1,792 B   ← 创建动态 VHDX
3. vm.InitVirtDisk                          —        ← 初始化 virtdisk
4. vm.CreateComputeSystem                  4,288 B   ← HCS 创建计算系统
5. (*HCSSystem).Start                      2,240 B   ← 启动
6. (*HCSSystem).ModifyComputeSystem        2,560 B   ← 运行时修改
7. (*HCSSystem).GetProperties              2,176 B   ← 取属性
```

### `BuildHCSDocument`（5,952 B）—— 这是 VM 的"定义"

这是第三大函数，负责把配置结构序列化成 **HCS（Host Compute Service）的 JSON 文档**。
HCS 是 Hyper-V 的现代 API，用 JSON 描述计算系统。字段可从 `json:"..."` 标签反推：

```
memoryMB / cpuCount / memoryGB   ← 资源
network / mac_address / ipv6     ← 网络
shares / mountName / subpath     ← 共享
bundlePath / userDataName / userDataRoot  ← 来源与数据
```

### `vm.volumeInfo` / `vm.diskState` / `vm.describeDiskState` / `vm.probeDisk`

一套**磁盘状态查询**：容量、状态描述、探测。配合 `CreateDynamicVHDX` 与 `findSessionDiskHyperV`（P5E），
构成每会话独立磁盘的完整管理。

## 3. 文件共享：两套机制

### 3.1 Plan9 共享（主路径）

```
(*WindowsVMManager).AddPlan9Share      4,000 B
vm.addPlan9Shares                       2,656 B
(*WindowsVMManager).mountGuestShares    1,408 B
(*WindowsVMManager).settleGuestShares   1,344 B
(*WindowsVMManager).RemovePlan9Share    1,120 B
vm.Plan9Share / vm.Plan9ShareInfo / vm.Plan9MountResult / vm.plan9ShareSettings
vm.redactSharePath                       —      ← 日志中脱敏共享路径
```

**这是宿主↔guest 的文件共享主通道**，用 9P 协议（对应 P5G 里的 `attach aname=`、`version msize=`）。
`redactSharePath` 说明共享路径在日志里会被脱敏。

### 3.2 网络驱动器

```
vm.NetworkDriveEntry / vm.NetworkDriveEntry
classifyNetworkLetter (pipe 包) / vm.SystemDriveLetter / systemDriveLetter
vm.EnumerateFixedDrives
```

盘符映射的驱动器（`handleGetNetworkDrives` 方法对应）。

## 4. 网络：三层

### 4.1 HCN（Host Compute Network）

```
vm.InitHCN / vm.OpenNetwork / vm.DeleteNetwork
vm.HCNNetwork / vm.EnumerateNetworks / vm.GetNetworkInfo
cleanupLegacyHCNNetworks (main 包)
```

### 4.2 VirtualNetworkProvider（自有实现）

```
vm.NewVirtualNetworkProvider / (*VirtualNetworkProvider).Start
(*VirtualNetworkProvider).acceptLoop
```

**这是一个独立的网络提供者**，带 accept loop —— 说明它可能在**代理 guest 的出网流量**。

### 4.3 代理配置（最复杂的一组）

```
vm.fetchPACScript              3,840 B   ← 拉取 PAC 脚本
(*proxyAttempts).connect       2,624 B
(*proxyAttempts).detectLater   1,568 B
(*proxyAttempts).refresh       1,472 B
vm.sendProxyParams             1,344 B
(*WindowsVMManager).sendHostProxyConfig 1,120 B
vm.loadWinINetProxy / vm.readProxyFromKey / vm.convertProxyOverride
vm.parseProxyServer / vm.splitLoopbackProxy / vm.detectPAC / vm.downloadPAC
vm.findPAC / vm.pacLookup / vm.pacScriptIn / vm.pacMemory / pacMemory
vm.readAutoConfigURL / vm.detectAutoProxyConfigURLBounded
vm.HostProxyConfigParams
```

**这是把 Windows 系统的代理设置（WinINet/PAC）传递进 VM 的完整链路**：

```
读系统代理 (WinINet / 注册表 AutoConfigURL)
  → detectPAC / findPAC / downloadPAC / fetchPACScript
  → parseProxyServer / splitLoopbackProxy / convertProxyOverride
  → sendProxyParams / sendHostProxyConfig
  → guest 内应用
```

`splitLoopbackProxy` 值得注意：**要单独处理 loopback 地址的代理绕过**（否则 guest 访问宿主服务会走代理失败）。
`detectAutoProxyConfigURLBounded` 的 "Bounded" 说明读取长度有上限（防超大注册表值）。

## 5. 证书注入（MITM 信任）

```
vm.LoadTrustedCACertificates    2,368 B
(*WindowsVMManager).installHostCACertificates  1,600 B
vm.enumerateCertStore           1,376 B
vm.certChainsToTrustedRoot        —      ← 证书链验证
vm.InstallCACertificatesResult    —
vm.isEncrypted / vm.isHardLinked / vm.isReparsePoint
```

**宿主把自己的 CA 证书装进 guest**，这样 guest 内的进程信任宿主的 MITM 代理。
`enumerateCertStore` 遍历 Windows 证书存储；`certChainsToTrustedRoot` 做链验证（只装可信的）。

这与 Linux 沙箱侧的 `InstallToTrustStore` → `/usr/local/share/ca-certificates/`（P5F）是同一设计的两端。

## 6. guest RPC 与事件

```
(*RPCServer).handleEvent        6,752 B   ← 最大
(*RPCServer).SendRequestAndWait 1,600 B
(*RPCServer).acceptLoop         1,312 B
(*RPCServer).handleConnection   1,312 B
(*RPCServer).handleMessage      1,120 B
vm.nextRequestID / vm.awaitReply[go.shape.*uint8]
vm.StdoutEventParams / StderrEventParams / ExitEventParams / ErrorEventParams
```

`handleEvent`（6,752 B）处理 7 类事件（P5 已验证：exit/error/ready/stderr/stdout/networkStatus/apiReachability）。
`awaitReply` 是**请求-应答配对**（带 requestID）。

## 7. 停止与清理

```
(*WindowsVMManager).StopVM      2,784 B
(*HCSSystem).Shutdown           1,376 B   ← 优雅关机
(*HCSSystem).Terminate          1,376 B   ← 强制终止
vm.CleanupStaleVMs              1,632 B   ← 清理残留 VM
vm.RemoveLegacyGuestLogs        1,536 B   ← 清理旧版 guest 日志
vm.EnumerateComputeSystems      1,632 B   ← 枚举现有 VM
vm.isOurVM / vm.isCurrentFormatVMID      ← 身份判定
```

`s_OurVM` + `isCurrentFormatVMID` 说明清理时会**先判定这个 VM 是不是自己的**，避免误杀他人 VM。

## 8. HVSocket（宿主↔guest 通道）

```
vm.NewHVSocketListener / (*HVSocketListener).Accept
vm.HVSocketConn / vm.HVSockAddr
vm.NetworkVsockServiceGUID
vm.ReadMessage / vm.WriteMessage
(*sockRef)  ×4
```

`NetworkVsockServiceGUID` 是 **vsock 服务标识**，`sockRef` 是引用计数（防提前关闭）。

## 9. 串口控制台

```
(*ConsoleReader).readLoop       1,888 B
vm.downloadPAC 等
```

对应 P5C 里 Linux 侧的 `logger.findVirtioConsolePath` —— **宿主通过串口/virtio console 读 guest 日志**。

## 10. 完整 VM 生命周期时序（还原，I）

```
StartVM
 ├ (*VMConfig).BuildHCSDocument          生成 HCS 文档
 ├ CreateDynamicVHDX                      建动态盘
 ├ InitVirtDisk / volumeInfo / diskState  盘初始化
 ├ InitHCN / OpenNetwork / NewVirtualNetworkProvider   建网络
 ├ fetchPACScript / loadWinINetProxy      取宿主代理
 ├ CreateComputeSystem                    创建 VM
 ├ (*HCSSystem).Start                     启动
 ├ WaitForOperationResult                 （HCS 异步）
 ├ NewHVSocketListener / Accept           连 guest
 ├ RPCServer.handleEvent                  收 ready
 ├ LoadTrustedCACertificates / installHostCACertificates   注入 CA
 ├ AddPlan9Share / mountGuestShares       挂共享
 ├ sendProxyParams / sendHostProxyConfig  下发代理
 └ 就绪

StopVM
 ├ (*HCSSystem).Shutdown（优雅）→ 超时则 Terminate
 ├ RemovePlan9Share
 ├ DeleteNetwork
 └ CleanupStaleVMs
```

## 11. 与 Linux 沙箱侧的完整对照

| 能力 | Windows 宿主（cowork-svc） | Linux 沙箱（sdk-daemon） |
|---|---|---|
| 隔离 | Hyper-V HCS VM | unshare/namespace + seccomp |
| 文件共享 | Plan9 (`AddPlan9Share`) | virtiofs + Plan9 + bindfs + hideFS + skeletonFS |
| 网络 | HCN + VirtualNetworkProvider | cgroup + 静态 IP 配置 |
| 代理 | WinINet/PAC 读取 → 下发给 guest | 自建 MITM（`generateCA`）+ PAC 求值 |
| CA 信任 | `LoadTrustedCACertificates` → guest | `InstallToTrustStore` → `/usr/local/share/ca-certificates/` |
| 身份 | 令牌 + MSIX 包 + WinTrust | `SO_PEERCRED` |
| 日志 | 串口控制台（`ConsoleReader`） | virtio console（`logger`） |
| 进程控制 | 无（整个 VM） | cgroup v2（`cgroup.kill`/`memory.events`） |

**两侧是同一套产品设计在两个平台上的落地**，机制不同但分层完全对应。

## 12. 产物

本报告即证据。函数体量来自 `ledgers/FIRSTPARTY-UNIQUE.tsv`（1,068 行）。

# P5I — `cowork-vm-service` 管道的客户端身份校验链（完整）

> 这是宿主侧那个 `localSystem` 服务最关键的**安全边界**：谁能连这个管道？
> 109 个 `pipe` 函数里，有近 40 个专门做身份识别与校验。本文把它们串起来。

---

## 1. 为什么这件事重要

`CoworkVMService` 以 **LocalSystem** 权限运行。如果任意进程能连上
`\\.\pipe\cowork-vm-service`，就等于拿到了 SYSTEM 级操作 Hyper-V 的通道。
所以命名管道本身的 ACL 不够 —— 服务必须**自己验证客户端**。

## 2. 完整校验链（按函数体量排序，S）

### 2.1 第一层：连接与句柄

```
acceptLoop                   1,088   接受连接
handleConnection             2,560   单连接处理
GetClientInfo                2,112   取客户端信息
getCurrentPackage            768     当前包身份
getPackageFamilyName         480     MSIX 包族名
resolvePackageRoot           416     包根目录
getUserProfileDirectory      416     用户 profile
(*ClientInfo).InServicePackage 896   是否在服务包内
(*ClientInfo).UserDataDirFor 2,976   该客户端的 userData 目录
```

**这一段在做的事**：从连接里反查**客户端的进程 → 包 → 用户**，并据此决定它的 userData 目录。

### 2.2 第二层：从连接反查进程与令牌

```
GetClientInfoFromConn       640
GetClientTokenFromConn      608
getClientToken              608
openTokenOfPeer             1,056   ← 打开对端进程令牌
openTokenOfPeer …           288
extractHandleFromConn       320
findHandleField             832     ← 找到连接句柄字段
openFinalDevicePath         832     ← 打开最终设备路径
queryFullProcessImageName   352     ← 进程映像路径
```

**`openTokenOfPeer`（1,056 B）** 是核心：通过管道句柄找到对端进程，打开其**令牌**，再从中取 SID / 完整性级别。
`openFinalDevicePath` + `findHandleField` 说明它甚至做了 **Windows 对象管理器层面的句柄解析**（防伪句柄）。

### 2.3 第三层：Authenticode 签名验证

```
InitSignatureVerification   5,088   ← 初始化校验环境（第二大函数）
verifyClientSignature       3,680   ← 校验客户端签名
VerifySignature             1,376
getSigningCertificateInfo   2,816
getCertNameString           384
calculateCertThumbprint     320
SignatureInfo               224
WINTRUST_DATA               128     ← WinTrust 结构体
WINTRUST_FILE_INFO          64
```

**这里是 Windows 原生的 Authenticode 校验**：
- `WINTRUST_DATA` / `WINTRUST_FILE_INFO` 是 `WinVerifyTrust` 的入参结构
- `calculateCertThumbprint` 算证书指纹
- `getSigningCertificateInfo` 取签名者信息

即：**客户端二进制必须带有可验证的 Authenticode 签名**，服务才会接受连接。

### 2.4 第四层：会话建立

```
getOrCreateSession          4,544
getSessionForConn           352
setSessionForConn           480
removeConnSession           672
checkIdleSessions           3,200
idleSessionChecker          544
stopAllSessions             1,472
(*vmSession).broadcast      608
(*vmSession).subscriberCount 320
(*vmSession).isConfigured   288
(*vmSession).setConfigured  288
```

校验通过后才建立 `vmSession`，并支持：
- **多订阅者**（`broadcast` / `subscriberCount`）
- **空闲回收**（`checkIdleSessions` + `idleSessionChecker`）
- **配置态**（`isConfigured`）

### 2.5 第五层：路径安全

```
pathIsUnder                 256     路径归属判断
validateBundlePathAsUser    256     以用户身份校验可写
ValidateWritePathAsUser     64
classifyNetworkLetter       256     盘符分类
systemDriveLetter           64      系统盘符
dirExists                   96
exactly                     128
```

`validateBundlePathAsUser` 说明：**写路径校验是在用户身份下做的**（不是 SYSTEM），避免 SYSTEM 权限写用户目录造成的越权。

## 3. 订阅与长连接

```
handleSubscription          4,320
streamEvents                1,152
handlePersistentRPC         4,288
```

`handlePersistentRPC`（4,288 B）与 `handleSubscription`（4,320 B）是两个独立的**长连接模式**：
- **持久 RPC**：一次连接内多次调用
- **事件订阅**：服务主动推事件（`streamEvents`）

对应 P5 里发现的 `subscribeEvents` 方法。

## 4. 完整调用时序（还原，I）

```
acceptLoop
  └ handleConnection
      ├ openTokenOfPeer          取对端令牌
      ├ GetClientInfo            进程/包/用户
      │   ├ getCurrentPackage → getPackageFamilyName
      │   ├ resolvePackageRoot
      │   └ getUserProfileDirectory
      ├ InitSignatureVerification
      │   └ verifyClientSignature
      │       └ VerifySignature → WINTRUST_DATA
      │           ├ getSigningCertificateInfo
      │           └ calculateCertThumbprint
      ├ getOrCreateSession
      │   └ setSessionForConn
      └ dispatch → dispatchVerified → dispatchWithSession
            └ handle{Configure,StartVM,StopVM,IsRunning,...}
```

## 5. 与 Linux 沙箱侧的对照

| 层 | Windows (管道) | Linux (unix socket) |
|---|---|---|
| 对端身份 | `openTokenOfPeer` + 令牌 SID | `SO_PEERCRED`（uid/gid/pid） |
| 二进制可信 | **Authenticode（WinTrust）** | **gpgv 验证 EDR 包** |
| 包/来源 | MSIX 包族名 + 包根 | 插件源路径白名单 |
| 会话 | `vmSession` + 空闲回收 | cgroup + 10 秒应答 |

**两侧都做到了"验证对端身份 + 验证代码来源"**，只是机制不同（Windows 用平台签名体系，Linux 用 GPG）。

## 6. 新增认知（相对 P5 的补充）

| 之前 | 现在 |
|---|---|
| 知道有 `verifyClientSignature` | 知道它走 **WinTrust Authenticode**，且有 `WINTRUST_DATA` 结构 |
| 知道管道有 ACL | 知道服务还**自己校验客户端令牌与包身份** |
| 知道有 session | 知道有**空闲回收 + 多订阅者广播 + 配置态** |
| 知道有 `handlePersistentRPC` | 知道它与 `handleSubscription` 是**两种长连接模式** |
| 不知道路径校验的权限上下文 | 知道 **`validateBundlePathAsUser` 以用户身份校验** |

## 7. 产物

本报告即证据。函数体量来自 `ledgers/FIRSTPARTY-UNIQUE.tsv`。

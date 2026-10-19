# 03 · Cowork 本地运行时（VM 沙箱）

> 证据等级：**S**=源码/符号直接可见，**R**=运行时观测，**D**=官方文档，**I**=推断，**U**=不可获得
> 主要证据：`cowork-svc.exe`（Go 符号表）、`index.chunk-lzaSYO3Q.js` @4319128–4341310

---

## 1. `cowork-svc.exe` 是什么

它不是 Electron 的 helper，是一个**独立的 Windows 服务**，用 **Go** 写成（不是 Rust、不是 C++）。

判定依据（S）：字符串表里的 Go module 路径

```
github.com/anthropics/cowork-win32-service
```

以及标准的 Go 构建残留（`go1.` 版本串、`runtime.` 符号、`goroutine` 栈格式）。

体量：13,761,360 B，**871 个自有符号**，分 6 个 package：

| package | 符号数 | 职责 |
|---|---|---|
| `vm` | 531 | Hyper-V / HCS 计算系统生命周期、VHDX、vsock 连接 |
| `pipe` | 244 | hvsock RPC 传输、帧编解码 |
| `edrgate` | 42 | EDR（端点检测响应）门禁 |
| `edrpolicy` | 29 | EDR 策略求值 |
| `logsink` | 17 | 日志汇聚到宿主 |
| `win-httpproxy` | 8 | 客户机内 HTTP 代理 |

在 `AppxManifest.xml` 里通过 `desktop6:Extension Category="windows.service"` 注册，并配了防火墙规则（`Claude.exe` 与 `cowork-svc.exe`）。

---

## 2. 关键符号（S，全部来自符号表）

### 2.1 HCS 计算系统
```
CreateComputeSystem
EnumerateComputeSystems
CreateDynamicVHDX
StartVMParams
```

`CreateComputeSystem` 是 **HCS（Host Compute Service）** API —— 即 Windows 容器/虚拟机统一管理层。Cowork 用的是 **Hyper-V 隔离 VM**，由 HCS 编排。`CreateDynamicVHDX` 说明磁盘是**动态扩展 VHDX**（初始小、按需增长）。

### 2.2 vsock 通信
```
NetworkVsockServiceGUID
VsockPortToServiceGUID
VMIDForSession
sessionHash
GetClientTokenFromConn
VerifySignature
```

这是最关键的一组。Cowork 的宿主↔客户机通信走 **Hyper-V 的 hvsock（Hyper-V Socket）**，不是 TCP、不是命名管道。

- `VMIDForSession` / `sessionHash` — **每个会话一个 VM**（或至少一个 VM 实例标识），由 session 派生。
- `VsockPortToServiceGUID` — 每个端口映射到固定的服务 GUID，形成静态端口协议。
- `GetClientTokenFromConn` / `VerifySignature` — **连接级认证**：客户机连上来时必须出示令牌，服务端验签。这防止宿主上其他进程冒充客户机。

### 2.3 共享目录与 EDR
```
mountSharesInGuest
Guarded
```

`mountSharesInGuest` —— 宿主目录以共享方式挂进客户机。前面提取到的 `p2r = ".cowork-adopted"`、`h2r = "smol-bin.vhdx"`、`m2r = "efivars.fd"`、`c2r = "claudevm.bundle"`、`s2r = "vm_bundles"` 说明 bundle 目录结构：

```
<userData>/vm_bundles/claudevm.bundle/
    ├── smol-bin.vhdx        ← 根文件系统镜像
    ├── efivars.fd           ← UEFI 变量
    └── .cowork-adopted      ← 采纳标记
```

`Guarded` + `edrgate` / `edrpolicy` package —— **EDR 门禁**：在企业环境里，如果终端装了 EDR 且策略不允许，Cowork VM 会被拦下。这是一个企业合规开关，不是技术限制。

### 2.4 其他
```
WriteStdinParams
SubscribeEventsParams
InstallCACertificatesResult
```

- `WriteStdinParams` — 客户机内进程的 stdin 写入走 RPC。
- `SubscribeEventsParams` — 事件订阅式推送（不是轮询）。
- `InstallCACertificatesResult` — **向客户机安装 CA 证书**，这是为了让客户机内的 HTTPS 流量可被代理/审计。

---

## 3. 宿主侧启动链（S，`index.chunk-lzaSYO3Q.js`）

`startVM` 函数（导出名 `mK`）的完整流程，代码原文可读：

```js
// 1. 读资源配置
let _ = A0r(),                      // 内存（GB）
    v = yv("vmCpuCount") || void 0; // CPU 核数（用户可配置）
Z.info(`[VM:start] memory=${_}GB`);

// 2. Windows 专用准备
if (process.platform === "win32") {
  await vl(5000);                              // 等 5 秒
  await Promise.race([qv(), Mm(5000)]);        // 等网络/服务，超时 5 秒

  let e = aK(),                                 // 架构后缀，如 "x64"
      t = join(process.resourcesPath, `smol-bin.${e}.vhdx`),
      r = join(bundleDir, "smol-bin.vhdx");

  if (existsSync(t)) {
    Z.info(`[VM:start] Copying smol-bin.${e}.vhdx to bundle: ${t} -> ${r}`);
    try {
      await pipeline(createReadStream(t), createWriteStream(r));
      Z.info(`[VM:start] smol-bin.${e}.vhdx copied successfully`);
    } catch (e) {
      let t = e?.code;
      if (t === "EBUSY" || t === "EACCES" || t === "EPERM")
        Z.warn(`[VM:start] smol-bin.vhdx locked by running VM (${t}), skipping copy`);
      else throw e;
    }
  } else {
    Z.warn(`[VM:start] smol-bin.${e}.vhdx not found at ${t}`);
  }

  // 3. 配置 Windows 服务
  if (g.configure) {
    Z.info("[VM:start] Configuring Windows VM service...");
    await g.configure();
    Z.info("[VM:start] Windows VM service configured");
  }
}

// 4. Linux 分支
if (process.platform === "linux" && g.configure) {
  Z.info("[VM:start] Configuring Linux VM helper...");
  await g.configure();
}

// 5. 启动
let y = await u, b = I0r(), x = z0r(b);
await g.startVM(i, _, v, "gvisor", G().vmApiReachabilityProbeTarget(), y, b, void 0);
```

几个必须指出的细节：

1. **`"gvisor"` 是硬编码字面量**——作为 `startVM` 的第 4 个参数传入。gVisor 是用户态内核沙箱，说明客户机内还有一层 gVisor 隔离（VM 内套沙箱）。
2. **每次启动都复制 VHDX**——如果 VM 在跑就跳过（`EBUSY`/`EACCES`/`EPERM`）。这保证了 bundle 镜像始终等于安装包里的镜像。
3. **`smol-bin.x64.vhdx` 只有 37,748,736 B（36 MB）**——极小。这不是完整的 Linux rootfs，而是一个类似 initramfs 的最小引导镜像，真正的用户态由 gVisor + 挂载提供。
4. **`process.resourcesPath`** 说明镜像来自安装目录，不是用户数据目录。

---

## 4. 启动失败归因（S）

`startVM` 的 catch 块把错误分成两类，并做 HCS 错误探测：

```js
catch (e) {
  let t = e instanceof Error ? e.message : String(e);
  Z.error(`[VM:start] VM boot failed: ${t}`);

  let n = t;
  if (U1r(t)) {                       // 疑似 HCS 错误
    let e = Pxr();                    // 探测可用性
    n = W1r(t, e.available) ?? t;     // 转成人类可读文案
    Z.error(`[VM:start] HCS error detected, available=${e.available}, ` +
            `missing=[${e.missingServices.join(",")}], sentinel=${n}`);
  }

  await m(nEn(e) ? "service_unavailable" : "vm_boot_error",
          "vm_boot", d, g, t);
  nK(n);
  throw ...;
}
```

`Pxr()` 会返回 `{available, missingServices}`——即检查 Hyper-V 相关 Windows 服务是否启用。这是**诊断到服务级**的降级逻辑。

VM 不可用的原因枚举（S，来自 `enums.json`）：

```
kvm_permission_denied          ← Linux 分支：/dev/kvm 权限
vhost_vsock_module_missing     ← Linux 分支：vhost_vsock 内核模块缺失
vhost_vsock_kernel_unsupported ← 内核不支持
not_enabled                    ← Windows：Hyper-V 未启用
os_version_too_new             ← 系统版本过新（HCS 行为变更）
```

注意 **`os_version_too_new`** —— 这是一个反向兼容检查：新版本 Windows 反而可能因为 HCS 行为变更导致不可用。

---

## 5. 客户机连接与超时（S）

启动成功后进入连接等待循环：

```js
eK(S_.Booting);
pG.emit("apiReachability", C_.Unknown);
pG.once("vmStopped", p);

let S = Date.now(), w = 0, T = Date.now();
while (Date.now() < s.connectDeadline(S)) {
  let e = f;
  if (e) {
    iK();
    let t = e.error ? `VM stopped unexpectedly: ${e.error}` : "VM stopped unexpectedly";
    await m("vm_stopped", s.lastCompletedStep ?? "vm_boot", d, g, t);
    nK(t);
    throw Error(t);
  }
  if (t?.signal.aborted) throw ...;
  w++;
  await KG();   // 轮询客户机就绪
  ...
}
```

状态机（S）：`S_` 枚举含 `Booting` / `Ready`，另有 `Downloading` 阶段（`tK` → `dispatchDownloadStatusChanged`）。

连接超时错误类（S）：

```js
class VMConnectionTimeoutError extends Error {
  constructor(e, t) { super(e); this.guestReady = t; this.name = "VMConnectionTimeoutError"; }
}
```

`guestReady` 字段让 UI 能区分"VM 起来了但客户机没就绪"和"VM 根本没起来"。

---

## 6. 网络状态与可达性（S）

两路独立探测：

```js
pG.on("networkStatus", e => {
  if (e === "CONNECTED") { iK(); if (ZG === "network_connection_failed") ZG = null; }
  else if (e === "NOT_CONNECTED") {
    rK ||= setTimeout(() => {
      rK = null;
      Z.warn("[VM:network] Network connection timeout reached");
      nK("network_connection_failed");       // 30 秒宽限
    }, 30000);
  }
});

pG.on("apiReachability", e => {
  if (e === "UNREACHABLE" || e === "PROBABLY_UNREACHABLE") { ... }
});
```

`C2r = 30000`（30 秒）——断网后有 30 秒宽限才报错，避免闪断导致误报。

`apiReachability` 有 4 态：`Unknown` / `Reachable` / `ProbablyUnreachable` / `Unreachable`。

---

## 7. VM 生命周期完整链路（S）

```
应用启动
  → scheduleStartupBundleSweep()          扫描/清理旧 bundle
  → isVMBundlePresent()  / isVMDownloaded()
  → 若无 bundle：getVMStartFailureBeingRetried() → 下载（进度经 dispatchDownloadProgress）
  → startVM(sessionId, memoryGB, cpuCount, "gvisor", probeTarget, …)
       ├─ [win32] 等 5s → 等网络/服务（5s 上限）
       ├─ [win32] 复制 smol-bin.<arch>.vhdx → bundle/smol-bin.vhdx（EBUSY 则跳过）
       ├─ [win32] g.configure()  → 配置 Windows 服务（注册/启动 cowork-svc.exe）
       ├─ [linux] g.configure()  → 配置 Linux helper
       └─ g.startVM(...)
             └─ cowork-svc.exe → CreateComputeSystem (HCS)
                                → CreateDynamicVHDX
                                → 挂 efivars.fd
                                → mountSharesInGuest
                                → hvsock 监听（NetworkVsockServiceGUID）
  → 状态 → Booting
  → 轮询 hvsock 直到客户机就绪（VerifySignature 验签）
  → 状态 → Ready → dispatchRunningStatusChanged
  → 运行期：WriteStdinParams / SubscribeEventsParams 走 RPC
  → stopVM() → 状态 → Stopped
                → lA("lam_vm_shutdown_failed", { vm_instance_id, bundle_version, duration_ms, trigger: "app_quit" })
```

监控埋点（S）：`lam_vm_shutdown_failed`，维度含 `bundle_version: QB.sha`、`vm_instance_id`、`duration_ms`、`trigger`。`QB.sha` 说明 **VM 镜像是按 commit sha 版本化的**。

---

## 8. 下载与 bundle 版本

```
var s2r = "vm_bundles", c2r = "claudevm.bundle", l2r = ".wvm-tmp-", u2r = ".partial"
class VMDownloadError extends Error { constructor(e) { ...; this.code = e?.code } }
```

`.partial` / `.wvm-tmp-` 后缀说明下载是**原子替换**：先写临时文件，校验后 rename。

`getVMBundlesDir` / `getVMDownloadProgress` / `isVMBundlePresent` / `isVMDownloaded` 是导出的 IPC 面（S）。

---

## 9. 与云端模式的关系

官方说明（D）：Cowork 已默认云端执行，本地执行只保留给 2026-10-06 之前启动的任务。

代码侧证据（S）：偏好设置里有一个 latch

```
coworkLocalTasksOffLatched
```

这是"本地任务已关闭"的**一次性闩锁**（latched）——记录该决策已经下发过，避免重复提示。整个 VM 代码路径**完整保留**，只是被策略关闭。同时 `secureVmFeaturesEnabled` / `vmMemoryGB` / `vmCpuCount` 仍在 schema 里，说明本地 VM 没有被废弃，只是当前默认不启用。

另有 flag `selfHostedCowork`（S）——自托管 Cowork，可能是企业版能力。

---

## 10. 边界

- **U**：客户机内部实现（gVisor 配置、镜像内的用户态组件、工具执行的具体隔离策略）——`smol-bin.vhdx` 只有 36 MB，是引导镜像，真正内容需要挂载分析；本次未做。
- **U**：`edrpolicy` 的具体策略求值规则——只有符号，没有字符串表可见的策略 DSL。
- **I**：`"gvisor"` 参数语义由名称推断为沙箱运行时选择器。
- **R 缺口**：本环境未启用 Hyper-V，VM 无法真实启动，无法观测 hvsock 握手。已在 `05-运行时观测.md` 记录。
- **未做**：`cowork-svc.exe` 的原生反编译（Ghidra 可用）。Go 符号表已提供 871 个函数名和 6 个 package 结构，作为**符号级**证据（S）；函数体级证据尚未产出，明确标记为缺口。

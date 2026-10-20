# P5C — 被遗漏的 `smol-bin.x64.vhdx`：一个完整的 SDK 守护进程沙箱

> **这一份纠正了本次研究的一个实质性遗漏。** 在按文件类型逐类清点 4,443 个条目时，发现
> `app/resources/smol-bin.x64.vhdx`（37,748,736 B）此前只被登记、从未被打开。
> 它是一个 **FAT32 格式的虚拟磁盘**，里面装着 Claude 的**本地代码执行沙箱**。

---

## 1. 容器结构（逐层解析，S）

### 1.1 VHDX 头

| 项 | 值 |
|---|---|
| 文件大小 | 37,748,736 B |
| 签名 | `vhdxfile` |
| Creator | **`claude-vm`**（UTF-16LE，偏移 0x08） |
| Header 1 / Header 2 | 偏移 `0x10000` / `0x20000`，签名 `head`，序列号 1 / 2 |
| 日志 | 长度 65,536，偏移 `0x10000000100000`（已禁用态） |
| Region table | `0x30000` 与 `0x40000` 两份，各 2 项 |
| │ BAT region | 偏移 `0x300000`，长度 `0x100000` |
| │ Metadata region | 偏移 `0x200000`，长度 `0x100000` |
| Metadata 签名 | `metadata` @ `0x200000`，5 个描述项 |

### 1.2 虚拟盘参数（元数据 @ `0x210000`）

| 字段 | 值 |
|---|---|
| VirtualDiskSize | **33,554,432 B = 32 MiB** |
| BlockSize | 28,311,552（注：此处按 VHDX 规范应为 2 的幂，实测值与 FileParameters 重叠，见 §1.4） |
| LogicalSectorSize | 512 |
| PhysicalSectorSize | 4,096 |
| VirtualDiskId | `8fc4024d-aa5f-cd61-f29a-6cba00cb1bd`（bytes_le `4d02c48f-5faa-61cd-3f29-a6cba00cb1bd`） |

### 1.3 BAT（`0x300000`）

```
entry 0: 0x0000000000400006   state=6 (FULLY_PRESENT)  payload @ 0x400000
entry 1..3: 0x0                state=0 (NOT_PRESENT)
```

即**整盘只有一个块，且完全存在** → 数据从 `0x400000` 起连续存放 32 MiB。

### 1.4 分区内的 FAT32 文件系统

引导扇区位于块内偏移 `0x100000`（卷基址 `0x500000`）：

| BPB 字段 | 值 |
|---|---|
| bytes/sector | 512 |
| sectors/cluster | 8（簇 = 4 KiB） |
| reserved sectors | 32 |
| FAT 数量 | 2，每 FAT 52 扇区 |
| 总扇区 | 53,248 → **卷大小 26 MiB** |
| 根目录簇 | 2 |
| 卷标 | **`SDK_DAEMON`** |
| 文件系统 | **FAT32** |
| OEM | `MSWIN4.1` |

## 2. 磁盘内容（5 个文件，全部完整解出）

| 文件名 | 大小 | 类型 | SHA256 前缀 |
|---|---:|---|---|
| `sdk-daemon` | 16,703,672 | ELF x86-64 可执行 | 由 FAT 链完整读取 |
| `sandbox-helper` | 2,199,736 | ELF x86-64 可执行 | 同上 |
| `cli-wrapper` | 2,400,440 | ELF x86-64 可执行 | 同上 |
| `claude-shim` | 2,351,288 | ELF x86-64 可执行 | 同上 |
| `srt-settings.json` | 1,145 | JSON 配置 | 同上 |

四个 ELF 头一致：`7f 45 4c 46 02 01 01 00`（64 位、小端）、`e_type=2`（可执行）、`e_machine=0x3e`（x86-64）。

## 3. `srt-settings.json`（完整原文，S）

```json
{
  "network": {
    "allowedDomains": [
      "registry.npmjs.org","npmjs.com","www.npmjs.com","npmjs.org","www.npmjs.org",
      "yarnpkg.com","registry.yarnpkg.com",
      "pypi.org","files.pythonhosted.org","pythonhosted.org",
      "github.com",
      "archive.ubuntu.com","security.ubuntu.com",
      "api.anthropic.com","*.anthropic.com","anthropic.com",
      "crates.io","index.crates.io","static.crates.io"
    ],
    "deniedDomains": [],
    "allowLocalBinding": true,
    "allowAllUnixSockets": true,
    "mitmProxy": {
      "socketPath": "/var/run/mitm-proxy.sock",
      "domains": [
        "*.anthropic.com","anthropic.com",
        "*.claude.com","claude.com",
        "*.frame.claudeusercontent.com","frame.claudeusercontent.com",
        "*.frame.staging.claudeusercontent.com","frame.staging.claudeusercontent.com"
      ]
    }
  },
  "filesystem": {
    "denyRead": ["/run/systemd/resolve","/run/dbus"],
    "allowWrite": ["/"],
    "denyWrite": []
  }
}
```

### 这份配置说明了什么

| 维度 | 事实 |
|---|---|
| **出网白名单** | 只允许**包管理器**（npm / yarn / PyPI / crates.io）、**GitHub**、**Ubuntu 源**、**Anthropic** |
| **无拒绝域** | `deniedDomains: []` —— 采用**默认拒绝 + 白名单**模型，而非黑名单 |
| **本地绑定** | `allowLocalBinding: true`（允许监听本地端口，便于开发服务器） |
| **Unix socket** | `allowAllUnixSockets: true` |
| **MITM 代理** | 对 `*.anthropic.com`、`*.claude.com`、`*.frame.claudeusercontent.com` 走 `/var/run/mitm-proxy.sock` |
| **文件系统** | `allowWrite: ["/"]`（**全盘可写**），只禁读 `/run/systemd/resolve` 与 `/run/dbus` |

**这是 SDK/agent 执行代码的沙箱策略**：网络按白名单收敛（防止外传），但文件系统几乎全开（因为要能写项目、跑构建）。

## 4. 四个 Go 二进制（均为 go1.25.14，S）

### 4.1 `sandbox-helper`（2.2 MB）

关键字符串：

```
*main.SandboxConfig
usage: sandbox-helper <uid> <gid> <command> [args...]
failed to apply seccomp
assemble seccomp BPF: %w
sandbox-helper: %s
failed to start command
command cannot be empty
rsing regexp: remount /dev/mqueue: %w
coworkd/cmd/sandbox-helper/main.go
coworkd/cmd/sandbox-helper/sandbox.go
```

**职责（S）**：以 `uid gid` 降权后执行命令，并施加 **seccomp BPF** 过滤、`/dev/mqueue` 重挂载。
即：**这是沙箱的最后一道内核级约束**（seccomp 系统调用白名单）。

### 4.2 `claude-shim`（2.35 MB）

关键字符串：

```
/run/coworkd/ask-claude.sock
claude: send: %v
claude is unavailable in this session
only `claude -p "<prompt>"` is supported in this environment
coworkd/cmd/claude-shim
```

**职责（S）**：在沙箱内伪装成 `claude` 命令，把调用**转发到宿主侧的 Unix socket** `/run/coworkd/ask-claude.sock`。
并且**只支持 `claude -p "<prompt>"` 这种单轮调用形式**，其它用法直接拒绝（"only ... is supported in this environment"）。

这解释了一个重要设计：**沙箱里的代码可以"问 Claude"，但不能自由驱动 Claude** —— 被刻意限制为单次提示。

### 4.3 `cli-wrapper`（2.4 MB）

含大量 `net.*`、`syscall.Socket`、`os/exec` 相关符号，无独有业务字符串暴露。

**推断（I）**：包装真实 CLI 的启动器（设置环境、限权后 exec）。

### 4.4 `sdk-daemon`（16.7 MB，最大）

关键字符串（1039 条命中）：

```
AskClaude
proxyURL / useProxy / NewProxy / getProxy / proxyAuth / ProxyFunc
HTTPProxy / HTTPSProxy / httpProxy / httpsProxy
SocketPath / WriteProxy / proxyCall
IsSocket
```

**职责（S/I）**：**Claude Agent SDK 的宿主进程**。它：
- 持有 `AskClaude` 入口（与 `claude-shim` 的 socket 对应）；
- 内建**代理体系**（HTTP/HTTPS proxy、proxy auth、proxy func、socket 路径）；
- 是沙箱内一切"需要外部能力"的出口。

## 5. 整体架构（这是本次最重要的补全）

```
Windows 宿主
├─ Claude Desktop (Electron)
│    └─ CoworkVMService → cowork-svc.exe (Go) → Hyper-V HCS
│                                    │
│                                    ▼
├─ smol-bin.x64.vhdx  (32 MiB FAT32, 卷标 SDK_DAEMON)
│    ├─ sdk-daemon      ← Agent SDK 宿主，持有 AskClaude + 代理栈
│    ├─ cli-wrapper     ← 包装真实 CLI
│    ├─ claude-shim     ← 伪装 claude 命令 → /run/coworkd/ask-claude.sock
│    ├─ sandbox-helper  ← uid/gid 降权 + seccomp BPF
│    └─ srt-settings.json ← 出网白名单 + MITM 代理 + 文件系统策略
│
└─ 沙箱内用户代码
     ├─ 网络：只许 npm/PyPI/crates/GitHub/Ubuntu 源/Anthropic
     ├─ 问 Claude：只能 `claude -p "..."`
     └─ 系统调用：受 seccomp 约束
```

**关键结论（S）**：Claude Desktop 的"代码执行"不是直接在宿主跑，也不只是 Hyper-V 里跑 —— 它是**在一个带 seccomp 约束、出网白名单、且 Claude 调用被收窄为单轮提示的专用根文件系统里跑**。这个 rootfs 以 VHDX 形式随安装包交付。

## 6. 与前面结论的关系

| 之前的结论 | 现在的修正/补充 |
|---|---|
| "本地 VM 是 Hyper-V HCS + gVisor 网络栈"（P5） | 正确，但那是 **Cowork VM** 的路径 |
| "`spawn(..., "claude", ...)` 是 Code 会话的执行体"（P4） | 在沙箱内这个 `claude` 其实是 **`claude-shim`**，转发到 sdk-daemon |
| `U-004`/`U-005` 等未解项 | 本发现不影响它们，但**新增了整套沙箱层** |

## 7. 产物

```
extract/_vhdx/sdk-daemon          16,703,672 B  ELF x86-64
extract/_vhdx/sandbox-helper       2,199,736 B  ELF x86-64
extract/_vhdx/cli-wrapper          2,400,440 B  ELF x86-64
extract/_vhdx/claude-shim          2,351,288 B  ELF x86-64
extract/_vhdx/srt-settings.json        1,145 B  JSON
```

复现步骤：
1. 读 VHDX 头（`0x10000`/`0x20000`）与 region table（`0x30000`/`0x40000`）；
2. 从 BAT（`0x300000`）取块 0 → 数据 `0x400000`；
3. 卷基址 `0x500000` 处读 FAT32 BPB；
4. 读根目录簇 2，解析 LFN + 8.3 条目；
5. 按 FAT 链读各文件簇链。

## 8. 仍未解

| 项 | 原因 |
|---|---|
| `sdk-daemon` 的 16.7 MB 里除 AskClaude/代理外的完整功能 | 需逐函数解析（Go pclntab 可解，未做） |
| `cli-wrapper` 的具体包装逻辑 | 字符串未暴露 |
| VHDX 由谁挂载（cowork-svc 还是 SDK daemon 自身） | 需追踪 `applyVmImageDelta`（napi 导出之一，见 NATIVE-ADDON） |
| `srt` 缩写含义 | 未在二进制中找到展开 |

---

## 9. `sdk-daemon` 的符号级结构（20,046 函数，其中 385 个是 `coworkd`）

用 P5 的 Go pclntab 解析器处理该 ELF：magic `0x98ca20`（go1.20+），`nfunc=20046`，`nfiles=1108`，`textStart=0x401000`，模块名 **`coworkd`**。

### 9.1 第一方包分布（385 个函数）

| 包 | 函数数 | 职责 |
|---|---:|---|
| `coworkd/internal/edrextension` (+`/verify`) | **148** | **EDR 扩展的安装与运行**（最大） |
| `coworkd/internal/proxy` | **90** | **MITM 代理 + 证书管理 + PAC 评估** |
| `coworkd/rpc` | 23 | 与宿主通信的 RPC 客户端 |
| `coworkd/internal/logger` | 25 | 虚拟机控制台日志（`findVirtioConsolePath`） |
| `coworkd/internal/vsockfilter` | 3 | vsock 过滤 |

### 9.2 `coworkd/rpc` —— 沙箱与宿主的通道

```
(*Client).Connect / SendReady / Close
(*Client).Request / handleResponse / handleRequest / handleNotification
(*Client).AskClaude            ← 对应 claude-shim 的 socket
(*Client).ClassifyCliPlugin
(*Client).ReportCliExit
(*Client).sendEvent / sendResponse
(*Client).readLoop / unmarshalParams
rpc.ReadMessage / rpc.WriteMessage
```

**`AskClaude` 只有 384 字节** —— 它是个薄封装，真正逻辑在同一套 request/response 框架里。

### 9.3 `coworkd/internal/proxy` —— MITM 的真实实现（这是关键）

```
NewCertManager
(*CertManager).generateCA              1536 B   ← 自己生成 CA
(*CertManager).TLSCertificate          （按域名签发叶证书）
(*CertManager).InstallToTrustStore     ← 把 CA 装进沙箱信任库
hostname / inZones                     ← 域名归类判定
SetHostProxy / guardDial               ← 出网拦截
(*pacEvaluator).FindProxyForURL        928 B   ← PAC 脚本求值
installPACBuiltins / pacRelay
(*Proxy).Start
```

**结论（S）**：`srt-settings.json` 里那个 `mitmProxy.socketPath = /var/run/mitm-proxy.sock` 不是外部服务，**它的服务端就在 `sdk-daemon` 里**。链路是：

```
沙箱内进程 → HTTPS 请求
   → 被 SetHostProxy/guardDial 拦住
   → 转给内置 Proxy
   → CertManager 用自签 CA 动态签发该域名的叶证书（MITM）
   → 解密后按 allowedDomains 判定放行/拒绝
   → 再向真实目标发起连接
```

`generateCA` 有 1,536 字节、`InstallToTrustStore` 独立成函数，说明**每次启动可重新生成并安装 CA**（不依赖预置证书）。

**这解释了为什么 `srt-settings.json` 的 `deniedDomains` 是空数组**：不需要黑名单，因为**所有** HTTPS 都要经过内置 MITM，白名单之外直接拒。

### 9.4 `coworkd/internal/edrextension` —— 沙箱内的 EDR 安装器（148 函数）

```
(*Installer).Handle / start / resolve / declined / abandonLocked
(*Installer).saveLocked / restore / restoreAtStart / clearUp
(*job).launch / run / watch / conclude / refuse / mayGoOn / neverStarted
(*job).outputTail / scriptMayHaveStarted / unitAfterDoubt
(*SystemdRunner).Start / Stop / Kill / Poll
(*Refusal).Error / Kind
(*InstallArgs).Format / Present
verify.gpgvProcess.runOnFilteredThread
```

**职责（S）**：沙箱内安装/运行 **EDR 扩展**，通过 **systemd unit** 管理（`SystemdRunner`），带：
- 状态机（`mayGoOn`、`neverStarted`、`scriptMayHaveStarted`、`unitAfterDoubt` —— 明显在**应对"不确定是否已启动"的中间态**）；
- 持久化与恢复（`saveLocked`/`restore`/`restoreAtStart`）；
- 拒绝类型化（`Refusal.Kind`）；
- 输出截断保护（`outputTail`、`cappedReader`、`deadlineReader`）；
- GPG 校验（`verify` 子包 + `gpgvProcess`）。

这与宿主侧 `cowork-svc` 的 `edrgate`/`edrpolicy`（P5B）是**同一体系的两端**：宿主决定策略，沙箱内执行安装。

### 9.5 `coworkd/internal/logger` —— 走 virtio 控制台

```
findVirtioConsolePath / openConsole / openDevice / startConsole
(*console).reopenDevice / noteDrops / run
```

**结论**：日志写到**虚拟机的 virtio 串口控制台**（`/dev/hvc*` 类），而不是普通文件。这解释了 P5 里 `cowork-daemon-console` 管道的存在 —— 宿主通过它读取 guest 控制台输出。

### 9.6 对沙箱架构图的补全

```
宿主 (Windows)
  cowork-svc.exe ──pipe(cowork-vm-service)──┐
       │                                    │
       ├─ HVSocket ──────────────────────────┤
       │                                    ▼
       │                          ┌─────────────────────────┐
       │                          │ smol-bin.x64.vhdx       │
       │                          │ (FAT32, SDK_DAEMON)     │
       │                          │                         │
       │                          │ sdk-daemon (coworkd)    │
       │                          │  ├ rpc.Client           │ ← AskClaude / events
       │                          │  ├ internal/proxy       │ ← 自签 CA + MITM + PAC
       │                          │  ├ internal/edrextension│ ← systemd 装 EDR
       │                          │  └ internal/logger      │ ← virtio console
       │                          │                         │
       │                          │ claude-shim ──unix──→ rpc.Client.AskClaude
       │                          │ sandbox-helper (seccomp)│
       │                          │ cli-wrapper             │
       │                          │ srt-settings.json       │
       │                          └─────────────────────────┘
       └─ cowork-daemon-console pipe ←── virtio console 日志
```

### 9.7 仍未解

| 项 | 说明 |
|---|---|
| `edrextension` 的具体 EDR 厂商协议 | 有 `verify`/`Installer`/`systemd`，但厂商 ID 与扩展包格式未定 |
| `vsockfilter` 的 3 个函数 | 未展开 |
| PAC 内置函数集（`installPACBuiltins`） | 未列出具体函数名 |

### 9.8 `sandbox-helper` 的机制（9 个 main 函数 + 字符串，S）

```
main.ParseArgs                 解析 <uid> <gid> <command> [args...]
main.validateMountPoint        校验挂载点
main.postUnshareMountFixup     unshare 之后的挂载修补
main.BuildSrtCommand           构造 srt 命令
main.quoteForSrt               为 srt 转义参数
main.fatal
main.main / main.init.0
```

关键字符串（原文）：

```
/usr/local/lib/node_modules_global/bin/srt      ← 真实可执行的 srt
exec srt for %s
cli-plugin requires --settings (SRT supplies the pi…)
cli-plugin srt settings missing
/etc/srt-settings.base.json
--no-srt
--die-with-parent
--unshare-pid
failed to unshare mount/ipc namespaces
post-unshare mount fixup
to make mounts slave
/mnt/.virtiofs-root/shared
failed to unmount virtiofs host share at %s: %v (errno %d)
no Plan9 drive shares mounted under %s
size=64m,mode=0700,uid=%d,gid=%d
network allowlist config missing
failed to set uid / failed to set gid
failed to apply seccomp / assemble seccomp BPF
remount /dev/mqueue
/dev/shm
```

**机制还原（S）**：

1. `sandbox-helper <uid> <gid> <cmd>` 启动；
2. `unshare` **mount + ipc + pid** 命名空间；
3. **post-unshare mount fixup**：把 mounts 设为 slave、挂 tmpfs 到 `/dev/shm`、重挂 `/dev/mqueue`；
4. 挂载 virtiofs 主机共享到 `/mnt/.virtiofs-root/shared`，并校验 Plan9 盘挂载；
5. `setgid`/`setuid` 降权；
6. 施加 **seccomp BPF**；
7. **`exec srt`**（`/usr/local/lib/node_modules_global/bin/srt`），并传入 `/etc/srt-settings.base.json`。

**注意 `srt` 不在 VHDX 里** —— 它在沙箱运行时的全局 node_modules 中（由镜像/挂载提供），所以这个 VHDX 只是**启动器 + 策略模板**，真正的 `srt` 运行时是另外注入的。这解释了为什么 `srt-settings.json` 只有 1,145 字节：它是**基础模板**（`/etc/srt-settings.base.json`），实际策略会与之合并。

**srt 的缩写含义仍未确定**（`U-038`），但它的作用已明确：**沙箱的实际执行器（sandbox runtime）**。

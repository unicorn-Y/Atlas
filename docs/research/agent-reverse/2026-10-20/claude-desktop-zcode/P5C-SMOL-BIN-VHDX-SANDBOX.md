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

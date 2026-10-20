# P5G — 沙箱内部机制的字符串级完整还原

> 解决 `U-040`（插件协议）与 `U-041`（派生步骤）的大部分。方法：对 `sdk-daemon` 全量提取
> 可读字符串并分类。以下每条都带原文。

---

## 1. 两个 unix socket 服务

```
/run/coworkd/ask-claude.sock        ← 对应 claude-shim 的转发目标
/run/coworkd/cli-plugin.sock        ← 插件服务
```

对两个 socket 都做了**同机进程身份校验**（`SO_PEERCRED`）：

```
[ask-claude] SO_PEERCRED: %v
[ask-claude] read header: %v
[ask-claude] accept loop done: %v
[cli-plugin] not a unix conn
[cli-plugin] SO_PEERCRED: %v
[cli-plugin] accept loop done: %v
[coworkd] failed to start cli-plugin server: %v
[coworkd] failed to start ask-claude server: %v
```

**`SO_PEERCRED`** 是 Linux 上查询对端进程 uid/gid/pid 的机制 —— 与 Windows 侧 broker 的
`GetNamedPipeClientProcessId`（P5/SSH-HELPERS）是同一种思路：**服务端自己验证调用者身份，不信任 socket 路径**。

## 2. CLI 插件机制（`U-040` 的主要答案）

### 2.1 目录与身份

```
HOME=/home/cli-plugin
CLAUDE_TMPDIR=/home/cli-plugin/tmp
TMPDIR=/home/cli-plugin/tmp
LANG=C.UTF-8
```

插件以**独立用户** `cli-plugin` 运行，有独立 HOME 与 TMPDIR。

### 2.2 插件来源与分类

```
pluginSources / pluginpath / stagedMounted / stagedMu
ClassifyCliPlugin / CliPluginClassifier / RecordPluginSource
rpc.ClassifyCliPluginParams / rpc.ClassifyCliPluginResult
.local-plugins / .remote-plugins / .local-plugins / .remote-plugin
```

插件分两类：**local** 与 **remote**，由 `ClassifyCliPlugin` 分类。

### 2.3 安装（staging）流程

```
mkdir staged bin: %w
bindfs staged bin: %w: %s
[coworkd] staged plugin bin %s -> %s for session %s
[coworkd] remove staged dir %s: %v
no plugin source recorded for mount %q
plugin source %q is not under the allowed root
unsafe plugin id from wrapperDir %q
unsafe path component: pluginId=%q cliName=%q
```

**这是一条完整的防逃逸链**：

| 检查 | 目的 |
|---|---|
| `plugin source %q is not under the allowed root` | 插件源必须在允许根目录下 |
| `unsafe plugin id from wrapperDir %q` | 插件 id 不能包含危险字符 |
| `unsafe path component: pluginId=%q cliName=%q` | 逐分量校验，防 `..` |
| `[hidefs] %s denied: %q in %q` | 隐藏文件系统层面的二次拦截 |

### 2.4 插件与 srt 的关系

```
cli-plugin requires --settings (SRT supplies the pi…)
cli-plugin srt settings missing
```

插件**依赖 srt 提供的 settings**，否则拒绝启动。

## 3. 文件系统：三层实现并存

| 层 | 证据 | 说明 |
|---|---|---|
| **hideFS** | `hidefs mount is missing nosymfollow`、`[hidefs] rmdir %s`、`prepareHideMount`、`hideDirStream` | 自定义 FUSE，**必须带 `nosymfollow`**（防符号链接穿越） |
| **skeletonFS** | `skeletonfs: create mount point: %w`、`mountSkeletonFS`、`MountSkeletonHome` | 提供"骨架"目录结构（空 home 的骨架） |
| **bindfs** | `/usr/bin/bindfs`、`bindfs staged bin: %w: %s` | 用系统 `bindfs` 做目录重映射 |
| **Plan9** | `attach aname=%q`、`version msize=%d version=%q`、`Rlerror ecode=%d (%v)` | 9P 协议（Plan9 共享） |
| **virtiofs** | `/mnt/.virtiofs-root`、`mount smol-bin on reconnect` | 宿主共享 |
| **ext4** | `/sbin/mkfs.ext4`、`e2fsck`、`root device is %s`、`no non-root NVMe disk` | **每会话独立 ext4 磁盘** |

`openat2 %q under %q: %v` 说明用了 **`openat2`** 系统调用（Linux 5.6+）做**受约束的路径打开**，这是比 `openat` 更强的防穿越机制。

## 4. cgroup 资源控制

```
[cgroup] initialized subtree at %s
failed to create cgroup parent: %w
failed to open cgroup fd: %w
failed to write to cgroup.kill: %w
[cgroup] could not read memory.events for %s: %w
[cli-plugin] cgroup OpenFD failed, falling back to direct kill
[process:%s] staged auth snapshot %v to %d processes in cgroup %s
/sys/fs/cgroup
```

**结论**：沙箱用 **cgroup v2** 管理进程组：
- 用 `cgroup.kill` 做整组终止（比逐个 kill 可靠）；
- 读 `memory.events` 监控 OOM；
- 持有 `cgroup fd` 以便可靠操作，失败时降级为直接 kill。

`staged auth snapshot ... to %d processes in cgroup` 说明**认证快照会注入整个 cgroup 的所有进程**。

## 5. 网络配置

```
sysctl net.ipv6.conf.%s.%s=0: %w
configureStaticIPOnInterface / configureStaticIPv6OnInterface
[sysctl] disable_ipv6
network interface vanished (renamed) during configuration
not a 48-bit MAC address: %q
/sys/class/net/%s/mtu
/etc/resolv.conf / systemd-resolved / /etc/protocols
```

沙箱会**主动配置静态 IP/IPv6、禁 IPv6、设 MTU、写 resolv.conf**，并处理"接口在配置过程中被重命名"的竞态。

## 6. 进程派生（`U-041`）

```
[process] creating user %s with home %s
groupadd for %s with gid …
[process:%s] mounted %s at %s (mode=%s)
[process:%s] staged auth snapshot ... 
[process:%s] unmounted ...
process %s not found / already exited
PROBABLY_UNREACHABLE
no answer in 10 s: %w
short frame, %d bytes, %s
[process] cgroup initialized
```

**派生一个受控进程的完整步骤**（由这些日志串还原）：

```
1. creating user %s with home %s      ← 建用户
2. groupadd for %s with gid           ← 建组
3. cgroup initialized subtree at %s   ← 建 cgroup
4. mounted %s at %s (mode=%s)         ← 挂载（多层）
5. staged auth snapshot               ← 注入认证
6. （启动进程，10 秒应答超时）
7. unmounted ...                      ← 退出清理
```

`no answer in 10 s` 是明确的**启动超时**；`PROBABLY_UNREACHABLE` 是网络探测状态。

## 7. 与 EDR 扩展的交叉

```
/etc/srt-settings.base.json
srt settings: %v
```

`writeSrtSettings` 生成的就是这个文件 —— 与 P5C 里 FAT32 中的 `srt-settings.json` 对应关系明确：
**包内的那份是模板，运行时由 `writeSrtSettings` 写出到 `/etc/srt-settings.base.json`**。

## 8. 更新机制

```
[updater] checking for updates from %s
CheckForUpdates / installSDKBinary
failed to install SDK binary: %w
```

`sdk-daemon` 自带更新检查与 SDK 二进制安装（与 P6F 的 CLI 发布清单对应）。

## 9. 仍未解（缩小后）

| 项 | 说明 |
|---|---|
| `match kind` 的枚举数值 | 已确认存在，取值可能是整数常量 |
| 插件包（.zip/.tar）的具体格式 | 看到 staging 与 wrapperDir，未见包结构解析 |
| `ClassifyCliPlugin` 的判定规则 | 只知道分 local/remote，未见判据 |

## 10. 产物

本报告即证据，原文位于 `extract/_vhdx/sdk-daemon` 的只读数据段。

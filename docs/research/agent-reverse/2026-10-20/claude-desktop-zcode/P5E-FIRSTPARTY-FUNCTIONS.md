# P5E — 1,830 个第一方函数的完整归类（去重后 1,068 个真实函数）

> 上一份 `P5D` 给出了 51,239 个函数的总账与零未分类结论，但第一方那 1,830 个只说了"约 700 个已解读"。
> 这一份把它做到底：**1,830 条 → 去重 1,068 个真实函数**，逐包归类，并给出每个包的职责。

---

## 1. 为什么是 1,830 → 1,068

`Go` 编译器为每个闭包、defer、goroutine 包装、`Printf` 日志点生成独立符号：

```
(*job).run                      ← 真实函数
(*job).run.(*job).run.func4.(*job).run      ← 嵌套闭包
(*job).run.Printf.func1         ← Printf 包装
(*Server).Start.gowrap1         ← goroutine 包装
(*Installer).Handle-fm          ← 方法值
```

按后缀模式（`.Printf.funcN`、`.funcN`、`.gowrapN`、`.deferwrapN`、`.OnceFunc*`、`-fm`）折叠后：

| | 数量 |
|---|---:|
| 原始条目 | 1,830 |
| **编译器生成的包装符号** | **762** |
| **真实第一方函数** | **1,068** |

代码体总量（含包装）约 **849 KB**。

## 2. 按包分布（1,068 个）

| 包 | 真实函数数 | 位置 |
|---|---:|---|
| `main.*` | **448** | 分散在 8 个二进制 |
| `cowork-svc/vm` | **216** | Windows 服务 |
| `coworkd/edrextension` | **160** | Linux 沙箱 |
| `cowork-svc/pipe` | **109** | Windows 服务 |
| `coworkd/proxy` | **56** | Linux 沙箱 |
| `cowork-svc/edr*` | **33** | Windows 服务 |
| `coworkd/logger` | **17** | Linux 沙箱 |
| `coworkd/rpc` | **16** | Linux 沙箱 |
| `cowork-svc/logsink` | **10** | Windows 服务 |
| `coworkd/vsockfilter` | **3** | Linux 沙箱 |

## 3. `main.*` 448 个按二进制拆分

| 二进制 | 函数数 |
|---|---:|
| **sdk-daemon** | **367** |
| cowork-svc.exe | 37 |
| claude-ssh-broker | 21 |
| claude-ssh-askpass | 10 |
| claude-ssh-proxy | 6 |
| sandbox-helper | 6 |
| claude-shim | 2 |

### 3.1 `cowork-svc.exe` 的 37 个（Windows 服务骨架，S）

| 函数 | 字节 | 职责 |
|---|---:|---|
| `main.main` | 20,256 | 入口：判定是服务还是交互运行 |
| `(*serviceHandler).Execute` | 4,224 | SCM 回调分发（`handleStatus`/`handleInstall`/`handleStart`/`handleStop`/`handleUninstall`） |
| `setupFileLogging` | 2,656 | 日志文件初始化 |
| `installService` / `uninstallService` | 2,400 / 2,208 | 服务注册/注销 |
| `runAsService` / `runService` / `stopService` / `startService` / `queryService` | 2,304 / 1,760 / 1,760 / 1,152 / 1,024 | 服务控制 |
| `configureRecovery` / `disarmRecovery` / `reportRecoveryFailure` | 1,856 / 1,600 / 512 | **崩溃恢复策略** |
| `cleanupLegacyHCNNetworks` | 1,760 | 清理旧版 HCN 网络 |
| `setACL` | 864 | 管道 ACL |
| `captureCrashOutput` | 416 | 崩溃输出捕获 |
| `configureEventSource` / `(*eventLogWriter).Write` | 384 / 160 | Windows 事件日志 |
| `isWindowsService` / `isHardLinked` / `isReparsePoint` / `getExecutablePath` | — | 环境探测（硬链接、重解析点） |
| `(*resilientMultiWriter).Write` | 288 | 多目标日志（文件+事件日志）容错写入 |
| `init.0` / `printUsage` / `stateToString` | — | 杂项 |

**新增认知**：`configureRecovery`/`disarmRecovery` 说明服务配置了 **SCM 恢复动作**（失败后自动重启），且能被主动"解除武装"（避免更新期间反复重启）；`cleanupLegacyHCNNetworks` 说明历史上用过 HCN 网络并需要迁移清理。

### 3.2 `sdk-daemon` 的 367 个（沙箱主程序，S）

按体量前 50 个揭示的子系统：

| 函数 | 字节 | 职责 |
|---|---:|---|
| `(*ProcessManager).Spawn` | 21,504 | **进程派生总入口**（最大函数） |
| `main.main` | 20,256 | 沙箱启动编排 |
| `mountSubpathForUser` | 6,240 | 按用户挂载子路径 |
| `(*cliPluginServer).handle` | 5,056 | **CLI 插件服务** |
| `pruneSessionCachesAt` | 4,480 | 会话缓存清理 |
| `(*cliPluginServer).spawn` | 4,224 | 插件进程派生 |
| `configureStaticIPOnInterface` | 4,192 | **静态 IP 配置** |
| `runP9Probe` | 4,096 | **Plan9 共享探测** |
| `(*askClaudeServer).handle` | 3,680 | **AskClaude 服务端**（与 claude-shim 对接） |
| `configureStaticIPv6OnInterface` | 3,264 | IPv6 配置 |
| `(*Process).waitForExit` | 3,136 | 进程等待 |
| `CheckForUpdates` | 3,136 | 自更新 |
| `installSDKBinary` | 2,880 | **安装 SDK 二进制** |
| `stageAuthSnapshot` | 2,848 | **认证快照暂存** |
| `openMountSourceNoSymlinks` | 3,136 | 防符号链接攻击的挂载源打开 |
| `(*hideNode).Create` | 2,592 | **隐藏文件系统节点** |
| `describeP9Frame` | 2,592 | Plan9 帧解析 |
| `mountSubpath` / `mountFixedPlan9Shares` / `mountPlan9Share` | 2,528 / 2,464 / 1,888 | Plan9 挂载家族 |
| `writeSrtSettings` | 2,496 | **生成 srt 配置** |
| `findSessionDiskHyperV` | 2,400 | 查找会话磁盘 |
| `recoverUserFromHomeDir` | 2,400 | 从 home 恢复用户 |
| `mountHideFS` / `prepareHideMount` / `validateHideEntry` / `(*hideRules).classifyName` / `(*hideNode).Lookup/Link/admitChild` | 2,272–1,312 | **隐藏文件系统（81 个含 hide 的函数）** |
| `mountSkeletonFS` | 2,240 | **骨架文件系统** |
| `mountStagedPluginRoot` / `(*Process).ensureStagedPluginMount` | 2,208 / 1,536 | 插件挂载 |
| `ensureUser` | 2,272 | 用户创建 |
| `(*Process).cleanupMounts` | 2,144 | 卸载清理 |
| `runSpawnStep[...]`（5 个泛型实例） | 1,792–2,112 | **派生步骤流水线** |
| `findNonRootNVMeDisk` / `probeDisk` / `prepareSessionDisk` / `getSessionsDiskInfo` / `deleteSessionDirs` | 1,344–2,400 | **会话磁盘管理（每会话独立盘）** |
| `removeEntriesOlderThan` / `removeSessionHomeDirAt` | 2,368 / 1,792 | 过期清理 |
| `copyFile` | 1,888 | 文件复制 |
| `(*ProcessManager).Kill` | 1,792 | 进程终止 |

**新增认知（重要）**：沙箱有一套**四层挂载体系**：

```
1. Plan9 共享     mountPlan9Share / mountFixedPlan9Shares / runP9Probe / describeP9Frame
2. 隐藏 FS        mountHideFS / hideNode / hideRules.classifyName  (81 个函数，体量第二大)
3. 骨架 FS        mountSkeletonFS / prepareSkeletonFS
4. 插件根         mountStagedPluginRoot
```

外加**每会话独立磁盘**（`prepareSessionDisk` / `findSessionDiskHyperV` / `findNonRootNVMeDisk`）与**按用户子路径挂载**（`mountSubpathForUser`）。

`openMountSourceNoSymlinks` 这个名字说明：**挂载源打开时拒绝符号链接**，是防目录穿越的措施。

## 4. 语义关键词覆盖统计（1,068 个函数）

| 关键词 | 函数数 | 含义 |
|---|---:|---|
| service | 383 | 服务框架（含 SCM 回调、`serviceHandler`） |
| vm | 225 | 虚拟机管理 |
| edr | 221 | EDR 扩展与策略 |
| pipe | 114 | 命名管道 RPC |
| **hide** | **81** | **隐藏文件系统（此前完全没发现）** |
| proxy | 78 | 代理与证书 |
| log | 49 | 日志 |
| mount | 45 | 挂载 |
| rpc | 37 | RPC |
| session | 33 | 会话 |
| **plan9** | **25** | **Plan9 文件共享** |
| spawn | 21 | 进程派生 |
| user | 19 | 用户管理 |
| plugin | 16 | 插件 |
| cert | 15 | 证书 |
| disk | 15 | 磁盘 |
| hcs | 12 | Hyper-V HCS |
| update | 5 | 自更新 |

## 5. 这份报告解决了什么

| 之前 | 现在 |
|---|---|
| "1,830 个第一方函数里约 700 个已解读" | **1,068 个真实函数逐包归类**，每包职责明确 |
| 未提及 Windows 服务的安装/恢复机制 | 37 个 `main.*` 全部列出（含 `configureRecovery`/`disarmRecovery`） |
| 只知道沙箱有 Plan9 与 virtiofs | 发现**四层挂载体系 + 隐藏 FS（81 个函数）+ 每会话独立磁盘** |
| 未知 `sdk-daemon` 如何派生进程 | `(*ProcessManager).Spawn`（21,504 B）+ 5 个 `runSpawnStep` 泛型实例 |

## 6. 产物

```
index/FIRSTPARTY-UNIQUE.tsv   1,068 行（function / wrapper_count / binaries / code_bytes）
index/GO-ALL-CLASSIFIED.tsv   51,239 行（全部函数含分类）
ledgers/GO-ALL-FUNCTIONS.tsv  原始函数表
```

## 7. 剩余的真实未知

| 项 | 说明 |
|---|---|
| 每个函数的**具体指令流** | 只有名字、地址、大小；未逐条反汇编（1,068 个全反汇编成本极高） |
| `hideRules.classifyName` 的隐藏规则集 | 需读其数据段常量 |
| `runSpawnStep` 泛型实例的具体步骤序列 | 需追踪调用点传入的 step 函数 |
| `(*cliPluginServer)` 的插件协议 | 需读其 handler 内部字符串 |

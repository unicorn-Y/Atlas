# P5H — EDR 扩展安装器的完整状态机（沙箱侧）

> 解决 `U-040` 的最后一部分与 EDR 扩展格式。方法：从 `sdk-daemon` 提取
> `edrextension` 相关的类型名、错误码与日志串。

---

## 1. 完整类型体系（27 个结构体，S）

```
*edrextension.Installer      *edrextension.job           *edrextension.Dirs
*edrextension.Request        *edrextension.RunSpec       *edrextension.RunResult
*edrextension.RunState       *edrextension.RunPhase      *edrextension.State
*edrextension.Staged         *edrextension.VerifiedPackage
*edrextension.Preconditions  *edrextension.InstallArgs   *edrextension.SharePath
*edrextension.StepLimits     *edrextension.UnpackLimits  *edrextension.SpaceMeter
*edrextension.FreeSpace      *edrextension.Runner        *edrextension.SystemdRunner
*edrextension.record         *edrextension.savedRecord   *edrextension.logEnd
*edrextension.Refusal        *edrextension.RefusalKind   *edrextension.FailureKind
*edrextension.cause          *edrextension.ownError      *edrextension.measureError
*edrextension.outcome        *edrextension.operation     *edrextension.Attempt
*edrextension.cappedReader   *edrextension.deadlineReader *edrextension.writerFunc
*edrextension.writeError     *edrextension.spaceMeter
```

配套的 RPC 类型：`*rpc.EdrVendor`、`*rpc.RunEdrExtensionParams`、`*rpc.EdrExtensionStatus`、`*rpc.EdrExtensionTimings`。

## 2. 扩展包格式（S）

**是 gzip + tar**（不是 zip）：
- 字符串里有 `gzip_header`、`gzip_checksum`、`GNU.sparse.na…`（tar 的稀疏文件扩展）
- 类型 `*tar.block`、`*tar.Header`、`*tar.Format`、`*tar.Reader`
- 错误码 `unpacking header`、`unpacking Queue`

**包内必需文件**：

| 文件 | 说明 |
|---|---|
| `install.sh` | 安装脚本（`install.sh was not started` 是失败码） |
| `install.log` | 安装日志（`create install.log` 是步骤名） |
| `status.json` | 状态文件（`status.json` 是文件名字面量） |
| 签名文件 | 独立于包（`read the signature file`、`signature_file_missing`） |

**路径安全**（`unpack_*` 系列错误码）：

```
unpack_path_too_deep          路径过深
unpack_entry_name_too_long    条目名过长
unpack_entry_name_not_plain   条目名非常规（疑似穿越）
unpack_entry_type_not_allowed 条目类型不允许（如设备文件/符号链接）
unpack_entry_duplicate        重复条目（tar 覆盖攻击）
unpack_too_many_entries       条目数超限
unpack_too_many_dirs          目录数超限
unpack_too_large / unpack_failed
```

**这是解包器的完整防护清单**，与常见 tar 抽取漏洞（Zip Slip、条目重复覆盖、符号链接逃逸）一一对应。

## 3. 完整失败原因码（S）

按生命周期排列：

| 阶段 | 原因码 |
|---|---|
| **包获取** | `package_missing`、`package_revoked`、`source_too_large`、`source_changed` |
| **解包** | `unpack_failed`、`unpack_path_too_deep`、`unpack_entry_*`（5 种）、`unpack_too_many_*`、`gzip_checksum` |
| **签名** | `signature_file_missing`、`signature_file_too_large`、`signature_file_malformed`、`signature_not_yet_valid`、`SignatureExpires`、`invalidpackage_revoked` |
| **验证** | `begin to verify`、`verifying`、`verifier's key`、`verifier's vendor`、`verifier's answer`、`goodsig_not_one`、`valid sig:`、`key_not_listed`、`vendor key %q: KeyID is empty` |
| **厂商** | `vendor_unknown`、`vendor_mismatch`、`expected_vendor` |
| **预检** | `Precondition Failed`、`it is empty`、`not_regular`、`symlink_in_path`、`too_many_dirs`、`FQDN too long` |
| **执行** | `script_missing`、`script_not_started`、`script_timeout`、`script_signaled`、`script_outcome_unknown`、`install.sh was not started` |
| **systemd** | `systemd_silent`、`systemd did not answer within`、`unit_gone`、`unit_already_ex…`、`unit_state_unreadable` |
| **状态** | `record_not_json`、`cause_malformed`、`status_too_long`、`host_time_not_applied`、`no_fork_in_doubt`、`start_unanswered`、`runner_unavailable` |
| **其它** | `daemon_update_pending`、`output too small`、`read the kernel boot id` |

**`valid sig:` / `goodsig_not_one` / `key_not_listed`** 是 **GPG 输出解析**的痕迹 —— 与 P5C 里发现的 `verify.gpgvProcess.runOnFilteredThread` 对应：EDR 包的签名用 **gpgv** 验证，而不是 Go 原生库。

## 4. systemd 集成细节（S）

字符串中出现的 systemd unit 指令：

```
Type=exec
ExecMainStatus
RuntimeMaxSec=
TimeoutStopSec=5
KillMode=control-group
OOMScoreAdjust=500
StandardInput=null
StandardOut… (截断)
EnvironmentFile=
LoadState
/usr/bin/systemctl
```

**结论**：EDR 扩展通过 **systemd transient unit** 运行：

- `Type=exec` —— 直接 exec，不 fork（便于精确跟踪主进程）
- `KillMode=control-group` —— 杀整个 cgroup
- `OOMScoreAdjust=500` —— 提高被 OOM 杀掉的优先级（保护主系统）
- `TimeoutStopSec=5` —— 停止 5 秒超时
- `StandardInput=null` —— 不给 stdin

## 5. 环境变量（S）

```
COWORK_EDR_INTEGRATION_DIR=
COWORK_EDR_INTEGRATION_API=1
COWORK_EDR_INTEGRATION_VENDOR=
COWORK_VM_ARCH=amd64
DEBIAN_FRONTEND=noninteractive
```

**这组变量直接对应 Windows 侧的注册表值名**（`coworkEDRIntegration` / `coworkEDRIntegrationVendor`，见 P5B）。同一条策略在两端用不同载体：
- Windows：`HKLM\SOFTWARE\Policies\Claude` 的 REG_SZ
- Linux 沙箱：环境变量 `COWORK_EDR_INTEGRATION_*`

## 6. 安装流程（由步骤名串还原，S）

```
1. read the request              读请求
2. prepare the …                 准备
3. copy the package              复制包
4. read our copy of the package  读副本
5. read the signature file       读签名
6. begin to verify               开始验证
7. look up the verifier's key    查验证者公钥
8. check the verifier's vendor   校验厂商
9. check the verifier's answer   校验结果
10. read the archive             读 tar
11. unpacking / unpacking header 解包
12. write the copy / write the install-args file
13. %s install.sh will be given %v  传参
14. create install.log           建日志
15. run（经 systemd）
16. answer the request           回包
```

## 7. 资源限制（S）

| 类型 | 字段/串 | 说明 |
|---|---|---|
| `StepLimits` | — | 每步超时/大小限制 |
| `UnpackLimits` | `unpack_too_many_entries`、`unpack_too_many_dirs` | 条目数与目录数上限 |
| `SpaceMeter` / `FreeSpace` | `FreeSpace`、`spaceMeter` | 磁盘空间计量 |
| `cappedReader` | — | 读上限 |
| `deadlineReader` | `no answer within %s` | 超时读 |
| `outputTail` | `output too small` | 输出尾部截取 |

## 8. 与 Windows 侧的对照

| 维度 | Windows (`cowork-svc`) | Linux 沙箱 (`sdk-daemon`) |
|---|---|---|
| 平台适配 | `raceStrings`/`selinux` 相关串出现在 `sandbox-helper` | systemd unit |
| 策略来源 | `HKLM\SOFTWARE\Policies\Claude` 的 REG_SZ | `COWORK_EDR_INTEGRATION_*` 环境变量 |
| 校验 | `InitSignatureVerification` / `verifyClientSignature` | `verify.gpgvProcess` |
| 门控 | `edrgate.CheapGates` / `systemDriveGate` / `shareGate` | `Preconditions` / `unpack_*` |
| 回答 | `edrAnswer` / `edrNotAnswered` / `edrRefused` | `RunState` / `Refusal` / `RefusalKind` |

**两端是同一条产品线的两个实现**，不是两套独立功能。

## 9. 产物

本报告即证据。原文位于 `extract/_vhdx/sdk-daemon`。

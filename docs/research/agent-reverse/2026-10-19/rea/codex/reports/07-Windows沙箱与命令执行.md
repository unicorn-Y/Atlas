# Windows 沙箱与命令执行代理（二进制级）

**证据等级：S**（`codex-command-runner.exe` 字符串 + 源码 `exec-server` / `windows-sandbox-rs`）。

---

## 1. 组件的角色

| 组件 | 大小 | 角色 |
|---|---|---|
| `codex-command-runner.exe` | 8,217,392 B | 在受限令牌下**实际 spawn 子进程**的代理 |
| `codex-windows-sandbox-service.exe` | 55,824,688 B | 常驻服务，管理沙箱账户/ACL/网络规则 |
| `codex-windows-sandbox-setup.exe` | 17,700,144 B | 一次性安装：创建账户与网络规则 |
| `exec-server`（Rust crate） | 66,845 行 | 上层：决定策略、启动 runner、转发 IO |

## 2. 通信协议（命令行 + 帧格式）

### 2.1 启动参数（字符串实证）

```
--pipe-in <name>
--pipe-out <name>
```

runner 通过**命名管道**与父进程通信，而不是 stdio。原因：受限令牌下标准句柄可能不可继承。

### 2.2 帧格式

首帧必须是 `spawn_request`，否则报错：
```
runner: expected spawn_request, got ...
runner: pipe closed before spawn_request
runner: no pipe-in provided
runner: no pipe-out provided
```

`spawn_request` 载荷字段（serde 结构体名与字段全部可见）：

```
SpawnRequest {
  command, cwd, env,
  permission_profile,
  workspace_roots,
  codex_home, real_codex_home,
  cap_sids,
  network_proxy_restricting_sid,
  timeout_ms,
  tty,
  stdin_open,
  private_desktop_name
}
```

后续帧类型（internally tagged enum `Message`）：

```
spawn_child      → 创建子进程
write_spawn_ready→ 回写 SpawnReady{ process_id }
output           → 子进程输出
stdin / close_stdin
resize
exit             → ExitPayload{ exit_code, timed_out }
error            → ErrorPayload{ message, stage, windows_error_code }
terminate
```

即：**父进程先发 `spawn_request`，runner 回 `spawn_ready` 带 PID，然后双向流式转发 IO**。

## 3. Windows 安全机制（字符串实证）

### 3.1 受限令牌 + 能力 SID

```
resolve permission profile token mode
ConvertStringSidToSidW failed for capability SID
runner: empty capability SID list
SetTokenInformation(TokenDefaultDacl) failed
SetEntriesInAclW failed
S-1-3-4  ← SECURITY_CAPABILITIES 的 capability SID 前缀
```

→ runner 为子进程构造**低权限令牌**，并通过 capability SID 授予最小能力（类似 UWP 的 capability 模型）。

### 3.2 私有桌面（防止窗口注入/截屏）

```
runner: missing parent-owned private desktop
private_desktop_name
spawned ConPTY is missing its process job
```

→ 每个沙箱进程跑在**独立 Desktop** 上，父进程必须是该 Desktop 的拥有者。这是防止其他进程发送窗口消息/读取屏幕的标准做法。

### 3.3 Job Object（进程树生命周期）

导入/调用：
```
CreateJobObjectW
SetInformationJobObject
TerminateJobObject
```
→ 用 Job Object 约束整个进程树，超时或父进程退出时统一杀灭（避免孤儿进程）。

### 3.4 ConPTY

```
kernel32.dll
this system does not support conpty.  Windows 10 October 2018 or newer is required
spawned ConPTY is missing its process job
```
→ TTY 模式使用 ConPTY，且 ConPTY 必须挂在 Job Object 下。

### 3.5 ACL 与读隔离

```
Local\CodexSandboxReadAcl
failed to probe ACL mutex state
DenyReadAcl / deny_read_acl.rs / deny_read_walker.rs / deny_read_resolver.rs
```

→ 用**命名互斥体** + 显式 deny-read ACL 实现"禁止读某些路径"，而不是只靠令牌。

### 3.6 原生 API 使用

```
NtCreateNamedPipeFile   (ntdll)
CreateNamedPipeW / CreateFileW / CreatePipe
GetNamedPipeInfo
Socketpair / Socket / Bind / Connect / Accept   (Unix 兼容层)
```

## 4. 策略输入：PermissionProfile

`exec-server/src/process_sandbox.rs:60`：
```rust
struct ... {
    permission_profile: PermissionProfile,
    network_proxy_restricting_sid: Option<String>,
    ...
}
```
`windows_sandbox_spawn_request()`（同文件 :70）把这些字段组装成 runner 的 `SpawnRequest`。

### 4.1 网络限制

`network_proxy_restricting_sid` 与 `ManagedProxyRouting::SharedIngress`（`process_sandbox.rs:415`）配合：

- 沙箱进程只能通过一个**受限 SID 的本地代理**出网
- 代理按域名白名单放行
- 这就是 `NetworkDomainPermission` / `NetworkUnixSocketPermission` 协议类型的落地

### 4.2 文件系统策略

`protocol/src/protocol.rs:1178`：
```rust
pub enum SandboxPolicy {
    DangerFullAccess,
    ReadOnly { network_access },
    ExternalSandbox { network_access },
    WorkspaceWrite { network_access, writable_roots, ... },
}
```
`WorkspaceWrite` 还带 `exclude_tmpdir_env_var`、`exclude_slash_tmp` 等细化项（见同文件 1204 起）。

## 5. 命令策略：execpolicy

`execpolicy` crate（2,975 行）用 **Starlark** 写前缀规则：

```
PrefixRule / PrefixPattern / PatternToken
NetworkRuleProtocol
Decision（allow / deny / ask）
RequirementsExecPolicy
```

用途：在沙箱之前先做"这条命令是否允许执行"的判断，例如：
- 允许 `git status`
- 拒绝 `rm -rf /`
- `curl` 需要网络审批

CLI 有 `codex execpolicy` 检查命令（`ExecPolicyCheckCommand`）。

## 6. 完整执行链路

```
模型 function_call: exec_command
  → ToolRouter → ToolRegistry
  → exec-server 判定 sandbox policy + execpolicy 规则
  → 若需审批：发 ExecCommandApprovalParams 给客户端，等响应
  → 组装 SpawnRequest
  → 创建命名管道 --pipe-in / --pipe-out
  → 启动 codex-command-runner.exe（受限令牌 + 私有桌面）
  → 写 spawn_request 帧
  → runner: 设置 ACL/Job Object/ConPTY → spawn 子进程
  → runner: 回 spawn_ready{process_id}
  → 双向转发 output / stdin / resize
  → 子进程退出 → runner 回 exit{exit_code, timed_out}
  → exec-server 汇总 → FunctionCallOutputPayload
  → 通知 item/commandExecution/outputDelta → 前端渲染
```

## 7. 与其他平台对比

| 平台 | 机制 | crate |
|---|---|---|
| Windows | 受限令牌 + capability SID + 私有桌面 + Job Object + ACL + 代理 SID | `windows-sandbox-rs`、`windows-sandbox-service` |
| Linux | Landlock + seccomp + PID namespace（可选 bwrap） | `sandboxing/landlock.rs`、`linux-sandbox`、`bwrap` |
| macOS | Seatbelt (`sandbox_init`) + `.sbpl` 策略文件 | `sandboxing/seatbelt*.sbpl` |

macOS 有 6 个 `.sbpl` 策略文件：`seatbelt_base_policy`、`seatbelt_network_policy`、`seatbelt_preferences_policy`、`seatbelt_read_only_platform_defaults`、`seatbelt_scratch`。

## 8. 判断

Codex 的沙箱强度明显高于多数竞品：
- 不是"容器外跑命令 + 提示词约束"，而是**OS 级强制隔离**
- Windows 侧做到了私有桌面 + Job Object + capability SID + deny-read ACL 四层
- 网络默认走受限 SID 的代理，不是简单放行

代价是实现复杂度极高（runner + service + setup 三个二进制 + 66k 行 exec-server）。

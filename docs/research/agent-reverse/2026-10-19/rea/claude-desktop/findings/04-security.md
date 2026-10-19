# 04 · 安全模型与信任边界

> 证据等级：**S**=源码直接可见，**R**=运行时观测，**D**=官方文档，**I**=推断，**U**=不可获得
> 本文件是逆向中"防御设计"证据最密集的部分。

---

## 1. 启动守卫：拒绝调试与网络改写开关

`index.pre.js` 在应用启动前执行一段硬检查（S）：

```js
const forbidden = [
  "remote-debugging-port", "remote-debugging-pipe", "ignore-certificate-errors",
  "host-resolver-rules", "host-rules", "disable-web-security", "log-net-log",
  "net-log-capture-mode", "ssl-key-log-file", "renderer-cmd-prefix",
  "utility-cmd-prefix", "gpu-launcher", "zygote-cmd-prefix",
  "ppapi-plugin-launcher", "nacl-loader-cmd-prefix", "browser-subprocess-path"
];

const JZ = e => e.replace(/^(?:--|-|\/)/, "").toLowerCase().split("=", 1)[0];
const YZ = e => /* 任一 argv 命中 forbidden */;

if (YZ(process.argv) && !iQ()) {
  process.stderr.write("Claude: refusing to start — a debugging or network-override " +
                       "switch is present on the command line.\n");
  process.exit(1);
}
```

**这是我在运行时实际撞到的**（R）：

```
$ claude.exe --remote-debugging-port=9333
Claude: refusing to start — a debugging or network-override switch is present on the command line.
[exit code: 1]
```

三个细节值得注意：

1. **归一化**：`--`/`-`/`/` 三种前缀都识别，且大小写不敏感，且只取 `=` 前的部分。所以 `-REMOTE-DEBUGGING-PORT=1` 和 `/remote-debugging-port` 都会被拦。
2. **列表覆盖面很广**：不只是调试端口，还包括 TLS 拦截（`ignore-certificate-errors`、`ssl-key-log-file`）、DNS 劫持（`host-resolver-rules`、`host-rules`）、同源绕过（`disable-web-security`）、子进程注入（`renderer-cmd-prefix`、`utility-cmd-prefix`、`gpu-launcher`、`browser-subprocess-path`）。
3. **有且只有一个逃生门**：`iQ()`。

---

## 2. 逃生门 `iQ()`：Ed25519 签名的 CDP 授权

这是整个逆向里最精巧的一段。`iQ()` 的完整条件（S）：

```js
function iQ() {
  // 必须同时有这两个环境变量
  if (!process.env.CLAUDE_CDP_AUTH) return false;
  if (!process.env.CLAUDE_USER_DATA_DIR) return false;

  const token = process.env.CLAUDE_CDP_AUTH;
  const parts = token.split(".");          // 必须正好 3 段
  if (parts.length !== 3) return false;

  const [ts, payload, sig] = parts;

  // payload 必须 base64 解码后正好等于 userData 路径
  if (Buffer.from(payload, "base64").toString() !== process.env.CLAUDE_USER_DATA_DIR)
    return false;

  // 时间窗口：0 ≤ now - ts ≤ 300000 ms（5 分钟）
  const age = Date.now() - Number(ts);
  if (!(age >= 0 && age <= 3e5)) return false;

  // Ed25519 验签
  return crypto.verify(
    null,
    Buffer.from(`${ts}.${payload}`),
    pinnedPublicKey,                        // SPKI
    Buffer.from(sig, "base64")
  );
}
```

固定公钥（SPKI，base64）：

```
MCowBQYDK2VwAyEAxONNYxuoQ4/PkjI7rdBmfpsWn1Ohfuqx9VMIsLwlTQY=
```

拆开看：`MCowBQYDK2VwAyEA` 是 DER 前缀（`SEQUENCE { SEQUENCE { OID 1.3.101.112 } BIT STRING }`，1.3.101.112 = Ed25519），后 32 字节是公钥。

**安全评估**：

| 属性 | 评价 |
|---|---|
| 算法 | Ed25519，无已知实用攻击 |
| 时间窗口 | 5 分钟，抗重放 |
| 绑定目标 | token 绑死 userData 路径——换个用户目录就不生效 |
| 私钥位置 | **不在客户端**（不在安装包里，不在任何提取出的文件中） |
| 结论 | 只有持有 Anthropic 私钥的内部构建才能开启 CDP |

**这就是为什么本项目的运行时内省必须走 UI Automation 而不是 CDP**——不是偷懒，是设计上不可能。

**边界**：我曾尝试 `--remote-debugging-port`，被明确拒绝（R，见上）。**未尝试**伪造 token——私钥不可得，伪造需要破解 Ed25519，超出范围且不道德。

---

## 3. 子进程环境变量清洗

即使 `iQ()` 通过，环境变量也会被处理（S）：

```js
// index.pre.js，打包态且非授权时
if (app.isPackaged && !iQ()) {
  delete process.env.CLAUDE_USER_DATA_DIR;
  delete process.env.SSLKEYLOGFILE;
  delete process.env.sslkeylogfile;
}
```

被删的原始值会被记到 `globalThis.ignoredUserDataDirEnv`（S）——这既是审计痕迹，也说明开发者知道这些变量敏感。

`SSLKEYLOGFILE` 的删除尤其重要：它是 Wireshark 解密 TLS 的标准手段。

---

## 4. 启动硬化参数（S）

主进程主动加的 Chromium 开关：

```
--enable-features=IsolatesPriorityUseProcessPriority
--dnsPrefetchingEnabled=false
--disable-features=ConnectionAllowlists
```

另外：

```js
process.env.NoDefaultCurrentDirectoryInExePath = "1";   // 防 DLL/EXE 搜索路径劫持
Error.stackTraceLimit = 20;
```

arm64 上还有 `L0` GPU 家族禁用逻辑。

`NoDefaultCurrentDirectoryInExePath=1` 是 Windows 特有的加固：默认情况下 Windows 会在当前目录找 DLL/EXE，这会被"下载目录里放个恶意 DLL"攻击利用。设为 `1` 后关掉这个行为。

`--dnsPrefetchingEnabled=false` 关掉 DNS 预取——减少侧信道泄漏（预取会暴露用户可能访问的域名）。

---

## 5. 进程隔离矩阵

拆开后能看到 **6 类隔离边界**：

| 边界 | 机制 | 证据 |
|---|---|---|
| Web 内容 ↔ 主进程 | `contextBridge`，19 个暴露节点，无 `nodeIntegration` | S |
| 模型生成的 artifact ↔ 宿主 | `cowork` bridge + `navigator.userActivation.isActive` 门控 | S |
| 引擎进程 ↔ 主进程 | 子进程 + stdio NDJSON，env 清洗 | S |
| MCP 宿主 ↔ 主进程 | 独立进程 `directMcpHost.js`（`"Custom 3P MCP Host"`） | S |
| Cowork 代码 ↔ 宿主机 | Hyper-V VM + gVisor + hvsock + 签名校验 | S |
| EDR ↔ VM 启动 | `edrgate` / `edrpolicy` 门禁 | S |

**第四条值得强调**：第三方 MCP server 跑在**独立进程**里，不是主进程内的模块。这是明确的信任分级——第三方代码不和主进程共享地址空间。

---

## 6. 企业管控面

### 6.1 策略来源（S）

```
MDM profile
GPO registry policy
/etc/claude-desktop/managed-settings.json
managed configuration
```

四条通道对应四类企业部署方式。

### 6.2 界面面开关（S）

`surfaceGrants` 按桌面模式给出细粒度授权：

```
standard:  { chat: true, fileAnalysis: true, cowork: true  }
simple:    { chat: true, fileAnalysis: true, cowork: false }
"no-vm":   { chat: true, fileAnalysis: true, cowork: false }
off:       { chat: false, fileAnalysis: false, cowork: false }
```

强制约束（S）：

```
"At least one surface must remain enabled; ${x} has been re-enabled."
```

即管理员**不能把三个面全关**——至少留一个。

另有 `coworkTabEnabled` / `chatTabEnabled` / `isClaudeCodeForDesktopEnabled` 三个总开关。

### 6.3 插件策略（S）

`plugin:${cliName}:${toolName}` 是策略粒度键。策略生效时的失败处理：

```
"${d} Plugin MCP scan failed while an MCP policy is active; refusing to start session with unenforced plugin"
```

**拒绝启动**而不是降级运行——这是 fail-closed 设计。

策展来源（S）：`anthropics/knowledge-work-plugins`（"Cowork plugins"）。

### 6.4 遥测开关

`disableEssentialTelemetry` 通过 `desktop-managed-config=` 前缀（偏移 25）的 JSON 下发；渲染进程只能看到布尔值 `desktopEssentialTelemetryDisabled`。

---

## 7. 隐私分级与崩溃

### 7.1 HIPAA 通道

运行时 stderr 实际出现过（R）：

```
MaxListenersExceededWarning: Possible EventEmitter memory leak detected.
11 coworkHipaaRestricted listeners added to [EventEmitter]
```

`coworkHipaaRestricted` 是一个**事件通道名**，说明 HIPAA 限制是通过事件标记传播的，不是配置开关。全局还有 `__coworkHipaaCrashDumps`（S）控制崩溃转储是否允许。

### 7.2 崩溃分类（S）

```
process_crashed  bun_crash  bun_stack_overflow  segfault  cli_fastfail
renderer_cascade  process_interrupted  stream_ended_no_result
```

良性变体：`cli_shutdown_crash_benign`

**启动拒绝类**（不可重试，直接报错）：

```
process_crashed  managed_sideload_disabled  sandbox_required_unavailable
managed_settings_refused  gateway_signin_required  gateway_access_denied
remote_settings_required_unavailable  org_*
```

这组名字信息量很大：

- `managed_sideload_disabled` — 企业禁用侧载
- `sandbox_required_unavailable` — 强制沙箱但沙箱不可用 → 拒绝启动
- `managed_settings_refused` — 策略拉取被拒
- `gateway_signin_required` / `gateway_access_denied` — 企业网关认证

`renderer_cascade` 说明渲染进程级联崩溃会被识别为独立类别（不是 N 次独立崩溃）。

---

## 8. SSH 子系统

三个独立可执行文件 + 独立特性：

```
claude-ssh-askpass.exe    ← SSH_ASKPASS 机制，用于密码/口令交互
claude-ssh-broker.exe
claude-ssh-proxy.exe
```

对应 feature flag：`chillingSlothSshShell` `chillingSlothSshWorktreeLocation` `chillingSlothSshPuttyKeyConversion` `chillingSlothRemoteFilePreview` `chillingSlothSshHost`（`ccdMcpTurnOnSshHost`）。

`chillingSlothSshPuttyKeyConversion` —— **PuTTY 密钥格式转换**，Windows 特有（PuTTY 用 .ppk，OpenSSH 用 PEM）。

偏好键 `ccSshHostToolGrants` 说明 SSH 主机授权是**按主机+工具**记忆的。

---

## 9. 浏览器扩展桥

`chrome-native-host.exe` + `claude-browser-shim.js` + 一个注册项：

```
com.anthropic.claude_browser_extension
```

两个扩展 ID（S，来自 AppxManifest 的 ExcludedKeys）：

```
fcoeoabgfenejglbffodgkkbkcdhcgfn
dngcpimnedloihjnnfngkgjoidhnaolf
```

**这段 manifest 特别值得注意**：MSIX 默认会虚拟化注册表写入，但这里显式**关闭了虚拟化**并为 7 个浏览器（Chrome / Brave / Edge / Prisma / Island / Chromium / Arc / Vivaldi / Opera）列出 `ExcludedKeys`。原因是：原生消息宿主必须写到**真实**注册表，浏览器才看得到；写进 MSIX 虚拟层浏览器读不到。

这是一个典型的"MSIX 打包与浏览器集成的冲突"，Anthropic 选择逐浏览器枚举排除。

`ChromeExtension` IPC 类有 7 个方法（S），另有 `chromeExtensionEnabled` 偏好（`security` 分类）和 `chromeExtensionInstall` flag。

`importChromeLogins` / `listChromeImportProfiles` / `listChromeImportSites` / `removeImportedChromeLogins`（S，`Launch` 类）—— 能从 Chrome 导入登录态，这是 Cowork 浏览器自动化的凭据来源。

---

## 10. 内置浏览器的权限模型

`Launch` 子系统 111 个方法里有大量与"允许什么"相关的：

```
addPreviewAllowedOrigin          removePreviewAllowedOrigin
clearPreviewAllowedOrigins       getPreviewAllowedOrigins
previewExternalLinkRequested     openExternalLinkInPreview
resolveRoutedLinkConfirm         routedLinkConfirmRequested
recordRemotePaneOriginDecision   admitRemotePaneOriginOnce
setPreviewLinkRouting            setPreviewChromeFocus
isJitlessForced                  previewJitlessKillSwitchEngaged
```

偏好键（S）给出更完整的图景：

```
launchPreviewAllowedOrigins
launchPreviewAllowedDomainTransitions
launchPreviewPrivateNetworkReadOrigins
launchPreviewPrivateNetworkReadPins
launchPreviewPrivateNetworkTrustedOrigins
launchPreviewPrivateNetworkTrustPins
launchPreviewPersistedWorkspaces
launchPreviewSessionScopedSessions
```

这 8 个键合起来说明内置浏览器有：

1. **源白名单**（allowedOrigins）
2. **域名跳转白名单**（allowedDomainTransitions）—— 防 SSRF 式重定向
3. **私有网络访问控制**（privateNetworkRead*，4 个键分来源/信任/pin）—— 这是 **PNA（Private Network Access）** 防护，防止模型让浏览器访问内网 192.168.x.x / localhost
4. **工作区持久化** 与 **会话级隔离** 两档

`isJitlessForced` + `previewJitlessKillSwitchEngaged` —— **强制 JIT-less 模式**：内置浏览器里禁用 JIT 编译，这是针对 JIT 喷射类漏洞的缓解措施（和 Chrome 的 V8 JIT-less 模式同源思路）。

这是一个成熟到少见程度的浏览器安全模型，比大多数 Electron 应用的内嵌浏览器严格得多。

---

## 11. 权限模式

`ToolPermissionBroker` 里出现的模式字面量及其出现次数（S）：

| 模式 | 次数 | 含义 |
|---|---|---|
| `default` | 24 | 每次询问 |
| `auto` | 21 | 自动判定 |
| `ask` | 18 | 询问 |
| `bypassPermissions` | 4 | 跳过全部 |
| `acceptEdits` | 2 | 自动接受文件编辑 |
| `plan` | 2 | 计划模式（只读） |

`bypassPermissions` 只在 4 处出现且需 `--allow-dangerously-skip-permissions` 才传给引擎——双重门槛。

---

## 12. 代号安全特性（S）

偏好设置里有一批**从未公开**的功能，全部以 `.meta(eg("security"))` 归类，默认关闭：

| 偏好键 | 默认 | 可推断语义 |
|---|---|---|
| `hardwareBuddyEnabled` | false | 硬件伙伴设备（对应 `buddy.js` 窗口、`Buddy` IPC 14 方法） |
| `sableOtterEnabled` | false | 系统级语音/听写助手，带 8 个子配置 |
| `quietPenguinEnabled` | false | — |
| `louderPenguinEnabled` | false | — |
| `rubberDuckEnabled` | false | — |
| `velvetFinchEnabled` | false | — |
| `hushedHeronKey` | `"off"` | 一个快捷键绑定，schema 为 `off` 或 `{accelerator, account}` |
| `chillingSlothLocation` | `"default"` | 位置策略 |

`sableOtter` 的完整配置面（S）最能说明它是什么：

```
sableOtterEnabled            : false
sableOtterTalkHold           : "right-control+right-shift"   ← 按住说话
sableOtterCardHold           : "right-option"                ← 按住唤卡片
sableOtterDictateHold        : "right-control"               ← 按住听写
sableOtterDictationCount     : 0
sableOtterModel              : "default"
sableOtterWindowContext      : "ask"                         ← 是否读取窗口上下文
sableOtterWindowApps        : {}
sableOtterExcludedApps      : []
sableOtterTerms             : []                             ← 自定义词表
```

**这是 macOS 上 Siri/Dictation 的等价物**：按住右 Option 键唤出、按住右 Control 听写、按住右 Control+右 Shift 对话、读取当前窗口上下文、可排除指定应用、支持自定义术语表。

`right-option` 这个键名是 **macOS 专属命名**（Windows 叫 Alt）。所以这套功能是跨平台共享代码，Windows 版本也在包里。

`quietPenguin` / `louderPenguin` 成对出现，且都有对应 feature flag——这是一对互斥的语音行为变体（安静 vs 响亮），但无法确定具体语义。

**边界**：`rubberDuck` / `velvetFinch` / `quietPenguin` / `louderPenguin` / `yukonSilver` / `copperLark` / `humbledSky` / `violinBow` 等代号**只能确认存在**，语义为 **I/U**。flag 表里没有描述字段，偏好里只有布尔默认值。

---

## 13. 透明与审计

**S** 级可见的审计痕迹：

- `globalThis.ignoredUserDataDirEnv` — 记录被清除的敏感 env
- `lam_vm_shutdown_failed` 等结构化埋点
- `desktop_third_party_history_import` 事件
- `desktop_ccd_delegated_ask_allowed` 事件（权限委派）
- Sentry debug id 硬编码：`sentry-dbid-9cf4e251-4f17-48c2-88cd-201ac3410330`

26 个遥测维度键（S）：`product_surface, desktop_variant, deployment_mode, config_source, config_source_remote, inference_provider, inference_host_kind, app_version, commit_hash, platform, arch, os_version, os_release, os_build, linux_distro_id, linux_distro_version_id, linux_session_type, linux_desktop_environment, cpu_model, app_session_id, organization_id, vm_network_mode, error_code, error_kind, backend_error_code, nest_local_user`

注意 `cpu_model` 和 `linux_desktop_environment` —— 遥测粒度到了硬件型号和桌面环境。

---

## 14. 边界与未做

- **U**：`cowork-svc.exe` 内 `edrpolicy` 的策略 DSL —— 只有符号，没有可见字符串。
- **U**：服务端信任判断（哪些请求合法、组织策略如何签名）—— 服务端不可得。
- **未做**：Ed25519 私钥获取（设计上不可得，且不尝试）。
- **未做**：绕过区域门禁。本环境被区域限制，这是产品行为，记录为边界而非绕过。
- **I**：`sableOtter` 的语义由键名+默认值推断为系统级语音助手，无运行时验证（功能默认关闭且需 macOS 按键）。

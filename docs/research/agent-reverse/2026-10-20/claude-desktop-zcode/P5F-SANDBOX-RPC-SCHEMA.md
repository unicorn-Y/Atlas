# P5F — 沙箱 RPC 的完整字段 schema（143 个 JSON 标签）

> 解决 `U-039`/`U-040`/`U-041` 的数据结构部分。方法：从 `sdk-daemon` 的 `.rdata`
> 提取全部 `json:"..."` 标签，配合类型名（`rpc.HideEntry`、`HideEntry`、`MountSkeletonHome` 等）
> 还原宿主 ↔ 沙箱之间的完整消息契约。

---

## 1. 全部 143 个字段（按语义分组，S）

### 1.1 隐藏文件系统（`rpc.HideEntry` / `main.hideRule`）

| 字段 | 说明 |
|---|---|
| `hide` | 隐藏项数组（`json:"hide,omitempty"`） |
| `mountName` | 挂载名 |
| `mountPoint` | 挂载点 |
| `mountSkeletonHome` | 是否把 skeleton 挂到 home |
| `rootKind` | 根类型（区分 home / root / 自定义） |
| `prefixLength` | 网络前缀长度（与 IP 相关） |
| `subpath` / `sdkSubpath` / `sourceRoot` | 子路径与源根 |
| `additionalMounts` | 额外挂载（沙箱启动时追加） |
| `failedMounts` | 失败挂载列表 |

**`hide` 字段的存在证实**：宿主通过 RPC 向沙箱**下发要隐藏的路径列表**，而不是沙箱硬编码规则。`hideRules.classifyName` 负责把下发的条目分类成规则。

### 1.2 挂载与文件共享

`shares`、`sources`、`sourceRoot`、`copy`、`copyMs`、`prestatDepth`、`includeSessionTmp`、`sessionTmpOlderThanSeconds`
→ 说明挂载支持**预统计（prestat）**与**拷贝耗时统计**，并为会话临时目录设了**年龄阈值**。

### 1.3 会话与磁盘（会话独立盘）

```
sessionName  sessions  prunedSessions  skippedSessions  deleted
freeBytes  sizeBytes  totalBytes  availableBytes  minAvailableBytes  lowWaterBytes
freedBytes  peakBytes  onlyIfFreeBytesBelow
```

**关键**：`onlyIfFreeBytesBelow` + `minAvailableBytes` + `lowWaterBytes` 构成一套**低水位清理策略** —— 只有当可用空间低于阈值时才清理，且保证清理后不低于最低水位。`prunedSessions`/`skippedSessions` 说明清理是**按会话**进行的，并记录跳过原因。

### 1.4 EDR 扩展（与 P5C §9.4 对应）

```
vendor  vendorVerified  expectedVendor  verifiedVendor  verifiedKeyId
signatureExpires  packageSha256  verify  verifyMs  unpack  unpackMs
installArgs  installArgsPassed  scriptOutput  scriptMayHaveStarted  startInDoubt
errorKind  errorStep  errorOperation  errorCause  refusal  failure
```

**这组字段揭示了 EDR 安装的完整状态机**：

| 字段 | 语义 |
|---|---|
| `verifiedKeyId` / `signatureExpires` | 验签用的是哪个 key、签名何时过期 |
| `vendorVerified` / `verifiedVendor` | 厂商 ID 是否通过校验 |
| `scriptMayHaveStarted` / `startInDoubt` | **脚本可能已启动的中间态**（与 `(*job).unitAfterDoubt` 对应） |
| `errorStep` / `errorOperation` / `errorKind` | **错误定位三元组**（哪一步、什么操作、哪类错误） |
| `installArgsPassed` | 参数是否已传给安装器 |

### 1.5 代理解析（PAC / MITM）

```
noProxy  httpProxy  httpsProxy  gateway  pacScript  apiProbeURL
certificates  network  dns  ip  port
```

`pacScript` 字段确认 **PAC 脚本经 RPC 下发**（对应 `fetchPACScript` 与 `installPACBuiltins`）。
`apiProbeURL` 用于连通性探测（对应 `apiReachability` 事件）。

### 1.6 进程与执行

```
argv  args  command  cwd  env  stdin  state  exitCode  signal  processId
running  status  bootId  hostTime  wallMs  ranMs  timingsMs
oneShot  isResume  isResume  operation  method  params  result
```

`oneShot` 字段直接对应 `claude-shim` 的"只允许 `claude -p`"限制 —— **单次调用是有显式标记的**。
`isResume` 说明进程/会话支持恢复。

### 1.7 同步与校验

```
sha256  expected  match  keys  keyCount  sourcesContent  content  text
identity  token  oauthToken  tokenEnvVar
```

`sourcesContent` 是 **sourcemap 的字段名**（对应 P5D 发现的 `dlclark` 误判后归零、实际 sourcemap 支持来自别处）。

### 1.8 其它

`line`、`column`、`offset`、`mode`、`size`、`modTime`、`filePath`、`displayName`、`version`、`requestId`、`cliName`、`wrapperDir`、`map`、`names`、`sections`、`mappings`、`unpack`、`mountSkeletonHome`。

## 2. 与已有发现的对应关系（交叉验证）

| 已发现的函数 | 对应字段 | 一致性 |
|---|---|---|
| `mountHideFS` / `hideRules.classifyName` | `hide`、`mountName` | ✅ 宿主下发 hide 列表 |
| `prepareSessionDisk` / `pruneSessionCachesAt` | `prunedSessions`、`onlyIfFreeBytesBelow`、`lowWaterBytes` | ✅ 低水位按会话清理 |
| `edrextension.(*job).unitAfterDoubt` | `startInDoubt`、`scriptMayHaveStarted` | ✅ 中间态有字段承载 |
| `(*askClaudeServer).handle` | `oneShot`、`prompt` | ✅ 单轮调用显式标记 |
| `fetchPACScript` / `installPACBuiltins` | `pacScript` | ✅ PAC 经 RPC 下发 |
| `proxy` 包 | `noProxy`、`httpProxy`、`httpsProxy`、`certificates` | ✅ 代理配置完整 |
| `vm.(*RPCServer).handleEvent` 的 `apiReachability` | `apiProbeURL` | ✅ 探测 URL 是输入 |

**七处交叉验证全部吻合** —— 说明这份字段表不是零散字符串，而是真实的消息契约。

## 3. 完整的 RPC 消息形态（推断结构，I）

```jsonc
// 宿主 → 沙箱
{
  "method": "...", "params": {...}, "requestId": "...",
  "hide": [{...}],              // 隐藏项
  "additionalMounts": [...],
  "mountSkeletonHome": true,
  "onlyIfFreeBytesBelow": 2147483648,
  "minAvailableBytes": 1073741824
}

// 沙箱 → 宿主
{
  "result": {...} | "error": "...",
  "errorKind": "...", "errorStep": "...", "errorOperation": "...",
  "prunedSessions": [...], "skippedSessions": [...],
  "freedBytes": 0, "peakBytes": 0
}
```

（结构由字段共现关系推断，`I` 级；字段本身是 `S` 级。）

## 4. 隐藏规则的真实形态（已解出，S）

对 `main.validateHideEntry`（1,568 B）做指令级字符串引用解析，得到四条**规则校验错误串**：

```
%w: unknown match kind %q for %q
%w: '*' outside the last component of %q
%w: negative prestatDepth for %q
%w: unknown match kind %q for %q
```

**这解答了隐藏规则的形态**：

1. **规则有"match kind"（匹配种类）** —— 不是纯名字比较，而是带类型的模式。
2. **`'*'` 只允许出现在最后一个路径分量** —— 这是明确的通配符约束（例如 `/home/u/*` 合法，`/*/x` 非法）。这条限制用于**防止通配符跨越目录层级造成意外隐藏**。
3. **`prestatDepth` 必须非负** —— 与 §1.2 的 `prestatDepth` 字段对应，说明隐藏前会做**预统计（prestat）**以决定处理方式。

配合 `hideRules.classifyName`（2,176 B）内部**无任何字符串引用、仅有 `'0'` 与 `'$'` 两个字符立即数**，可判断 `classifyName` 处理的是**字符级判定**（如判断首字符是否为 `.`），而**具体模式由宿主经 RPC 下发**（`hide` 字段 + `match` + `rootKind`）。

### 4.1 与 RPC 字段的闭环

| 字段 | 作用 |
|---|---|
| `hide[]` | 隐藏项数组（宿主下发） |
| `mountName` / `mountPoint` | 挂在哪 |
| `rootKind` | 根类型 |
| `prestatDepth` | 预统计深度（非负校验） |
| 规则内的 match kind | 匹配方式（含 `*` 后缀通配） |

## 5. CA 证书的安装路径（新发现，S）

同一批字符串里出现：

```
/usr/local/share/ca-certificates/
/usr/sbin/update-ca-certificates
failed to install SDK binary: %w
```

**这确认了 P5C §9.3 的 `InstallToTrustStore` 在 Linux 侧的具体做法**：
把生成的 CA 写入 `/usr/local/share/ca-certificates/`，再调用 `/usr/sbin/update-ca-certificates` 更新系统信任库。
这是 Debian/Ubuntu 系的标准 CA 安装流程。

同时可见：
```
/mnt/.virtiofs-root
/sys/bus/vmbus
/sys/fs/cgroup
vmw_vsock_virtio_transport
```
→ 确认沙箱通过 **virtiofs + vmbus + vsock** 与宿主相连（与 P5C 的 HVSocket 一致）。

## 6. 仍未解

| 项 | 说明 |
|---|---|
| 每字段的**具体类型与嵌套结构** | 只有标签名，未解出 Go structtype 的完整布局（Go 1.25 编码未攻克） |
| match kind 的**枚举全集** | 已确认存在，但取值列表未在字符串中出现（可能是数字常量） |
| `cliPluginServer` 的插件包格式 | 字段表里有 `wrapperDir`、`cliName`，但包结构未定 |

## 5. 产物

本报告即证据。原文位置：`extract/_vhdx/sdk-daemon` 的 `.rdata` 段，143 个 `json:"..."` 字面量。

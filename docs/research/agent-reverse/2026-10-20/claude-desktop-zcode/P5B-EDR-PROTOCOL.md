# P5B — EDR 接入协议（`edrgate` / `edrpolicy`）

> 解决 `U-009`。全部来自 `cowork-svc.exe` 的 pclntab 函数名、结构体类型名与 JSON 标签。

---

## 1. 两个包的分工

| 包 | 函数 | 职责 |
|---|---|---|
| `edrpolicy` | `ParseInstallArgsFile`、`InstallArgs.{Format,Reveal}`、`HostPath.String`、`VendorID.String`、`refuseHostPath`、`hasReservedStem`、`hasShortNameShape` | **纯策略解析**：从策略源读 `HostPath` / `VendorID` / `InstallArgs`，做路径合法性判断（保留前缀、8.3 短名形态） |
| `edrgate` | `ParseCaller`、`Decide`、`CheapGates`、`systemDriveGate`、`shareGate`、`newGuestSubpath`、`classifyShare`、`ArgsFile.installArgs`、`PolicyValue.refusal`、`NewRefusal`、`DecodeRegSZ`、`GuestRequest.Params` | **门控决策**：对 guest 发起的安装请求逐项判定，产出允许或拒绝理由 |

`pipe` 包负责把它们串起来：

```
pipe.readEdrPolicy            → 读取策略
pipe.(*edrPolicyParser).ParseHostPath / ParseVendorID / ParseInstallArgsFile
pipe.(*Server).handleRunEdrExtension
   ├─ pipe.readEdrArgsFile
   ├─ pipe.(*Server).runEdrExtension
   └─ 三种回答：
        pipe.(*Server).edrAnswer        ← 放行
        pipe.(*Server).edrNotAnswered   ← 无策略/未回答
        pipe.(*Server).edrRefused       ← 拒绝
pipe.(*edrLogMemory).logOnce / firstTime   ← 同一条拒绝只记一次日志
pipe.edrRefusalLogLine / edrNotAnsweredLogLine
```

## 2. 策略来源（注册表）

字符串证据：`SOFTWARE\Policies\Claude`（category = `registry`）。

读取链：`pipe.edrValueFromRegistry` → `pipe.readEdrValue` → `pipe.readEdrPolicy` → `pipe.(*edrPolicyParser).Parse*`。
`edrpolicy.DecodeRegSZ` 说明值以**REG_SZ** 形式存放并自行解码。

**这是标准的 Windows 组策略位置**：EDR 策略由企业通过 GPO/MDM 下发到 `HKLM\SOFTWARE\Policies\Claude`，服务以 `localSystem` 身份读取。

## 3. 门控顺序（由函数名还原）

```
edrgate.Decide
  ├─ edrgate.CheapGates          ← 先做廉价判断（纯字符串/路径比较），失败即拒
  │    ├─ edrgate.systemDriveGate    ← 拒绝对系统盘路径的操作
  │    └─ edrgate.shareGate          ← 检查该 share 是否在白名单
  ├─ edrgate.classifyShare       ← 对 share 归类
  ├─ edrgate.newGuestSubpath     ← 为 guest 生成受限子路径
  └─ edrgate.NewRefusal          ← 构造拒绝理由
```

`edrpolicy.hasReservedStem` / `hasShortNameShape` 说明它防的是**路径逃逸技巧**：Windows 保留设备名（CON/PRN/AUX/NUL/COM1…）与 8.3 短名别名。

## 4. 数据结构（类型名 + JSON 标签）

| 结构体 | 字段（来自 json tag） |
|---|---|
| `*edrgate.GuestRequest` | `method`、`params`（+ `edrgate.(*GuestRequest).Params`） |
| `*edrgate.Attempt` | `attempt`、`outcome`、`hostTime` |
| `*edrgate.Refusal` | `code`、`message`（`NewRefusal` 构造，`String()` 序列化） |
| `*edrgate.Wait` | `Wait.Error` —— 表示"等待回答"状态 |
| `*edrgate.ServedShare` | share 服务条目（`classifyShare` 产出） |
| `*edrgate.InstallArgs` | `installArgs`、`expectedVendor` |
| `*edrgate.HostPath` / `*edrgate.VendorID` | 解析后的策略值，均有 `String()` |
| `*edrpolicy.ArgsFault` | 参数解析失败的类型化错误 |
| `*vm.EdrSnapshot` | VM 侧的 EDR 快照（`vm.(*WindowsVMManager).EdrSnapshot`，带 `forward` 与 `edrForwardError`） |

**注入到管道协议的字段**（`SVC-STRINGS.tsv` 中确认存在于 JSON 标签集）：

```
expectedVendor     ← 期望的 EDR 厂商 ID
installArgs        ← 安装参数
AccessName         ← 访问名
ResourcePath       ← 资源路径
```

## 5. 三种回答的语义（S）

| 回答 | 函数 | 含义 |
|---|---|---|
| `edrAnswer` | `pipe.(*Server).edrAnswer` | 策略判定完成，返回明确结果（允许/拒绝） |
| `edrNotAnswered` | `pipe.(*Server).edrNotAnswered` | 没有可用的 EDR 策略或 EDR 未响应 → 走默认（日志有专门行 `edrNotAnsweredLogLine`） |
| `edrRefused` | `pipe.(*Server).edrRefused` | 主动拒绝 → 日志 `edrRefusalLogLine`，并**每条只记一次**（`edrLogMemory.logOnce/firstTime`） |

错误串证据：`edrExtension refused: `、`[EDR] the VM answered the install request with an error of its own, which was passed on to the app; its text is not logged`。
后者说明：**VM 侧 EDR 返回的错误文本被刻意不记录**（避免把宿主不信任的内容写进日志）。

## 6. 与 feature flag 的对应

| flag | 对应实现 |
|---|---|
| `coworkEDRIntegration`（开关） | `pipe.readEdrPolicy` 是否启用 |
| `coworkEDRIntegrationVendor`（厂商 ID） | `edrpolicy.VendorID` / `expectedVendor` 字段 |

## 7. 注册表值名已定位（指令级，S）

对 `pipe.readEdrPolicy`（入口 `0x14050ee40`，608 B）做 LEA 目标解析，得到两条关键字符串：

| LEA 目标 VA | 解出的字符串 |
|---|---|
| `0x14072d376` | **`SOFTWARE\Policies\Claude`** |
| `0x1407278fe` | **`coworkEDRIntegration`** |
| `0x14072fc1d` | **`coworkEDRIntegrationVendor`** |

**结论**：注册表值名**就是 GrowthBook flag 名本身**。即：

```
HKLM\SOFTWARE\Policies\Claude
   ├─ coworkEDRIntegration        (REG_SZ, 开关)
   └─ coworkEDRIntegrationVendor  (REG_SZ, 厂商 ID)
```

这是一个非常干净的设计：**策略键名与产品 flag 名统一**，运维只需看一套命名。也印证了 `edrpolicy.ParseVendorID` / `ParseHostPath` 的存在（后者可能来自同一键下的其它值）。

## 8. 仍未取到的点（诚实）

| 项 | 原因 |
|---|---|
| `Refusal.code` 的枚举全集 | 需要 `NewRefusal` 的调用点逐个读立即数 |
| EDR 扩展二进制的加载格式 | `InstallArgs` 存在，但扩展本身的 PE/MSI 结构未定 |
| `HostPath` 对应的注册表值名 | 本次 7 个 LEA 目标里未出现，可能在 `readEdrValue` 的另一分支 |

这三条已记录在 `12-UNKNOWN-AND-BLOCKERS.tsv`（U-009 保留为 PARTIAL，附上述具体子项）。

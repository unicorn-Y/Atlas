# P2B — 硬件 Buddy 的 BLE 链路

> 解决 `U-020`。全部来自 `index.chunk-CzY1tCPL.js`（buddy 窗口 bundle）与 `BuddyBleTransport` 服务定义。

---

## 1. 架构：浏览器侧选设备，主进程侧做桥

```
buddy_window (renderer)
   │  调用 navigator.bluetooth.requestDevice(...)   ← 标准 Web Bluetooth
   ▼
Electron 触发 webContents 的 "select-bluetooth-device" 事件（在主进程）
   │
   ▼
主进程 g(e, deviceList, callback)：
   ├─ 1. 过滤：deviceName 小写后以 "nibblet" 或 "claude" 开头
   ├─ 2. 若处于"列设备"模式（_)：把命中设备写入 _.found 并暂存 callback，稍后统一返回
   ├─ 3. 否则按已选设备 id 精确匹配；命中 → 记日志 "picked X (id) after N round(s)" → callback(deviceId)
   └─ 4. 第一轮未命中 → 起 15,000 ms 超时；超时记 "scan timeout — saw N stick(s), none matched" 并 callback("")
```

即 **BLE 传输实现在渲染层**（Chromium 的 Web Bluetooth），主进程只负责**设备选择策略**与**配对确认**。

## 2. 设备名白名单（S）

```js
const t = (e.deviceName || "").toLowerCase();
return t.startsWith("nibblet") || t.startsWith("claude");
```

- `nibblet` —— 硬件产品的代号（日志里称设备为 "stick"）
- `claude` —— 兼容前缀

**没有 GATT service UUID 过滤**：筛选只靠广播名，靠名字前缀而非 UUID 白名单。这解释了为什么代码里搜不到特征 UUID —— 由渲染层的 Web Bluetooth 代码决定，不在这个 chunk 里。

## 3. 配对（S）

```js
e.session.setBluetoothPairingHandler((request, cb) => {
  if (HIPAA_RESTRICTED) { cb({confirmed:false}); return; }
  if (request.pairingKind !== "providePin") { cb({confirmed: request.pairingKind === "confirm"}); return; }
  if (!pinPromptTarget || !selectedDevice) { log("passkey requested with no prompt target"); cb({confirmed:false}); return; }
  // 交给 UI 弹 PIN 输入，等用户提交
  pendingPinCb = cb; pinPromptTarget(selectedDevice.name ?? request.deviceId);
});
```

- 仅支持两种配对：`confirm`（自动确认）与 `providePin`（要用户输入 PIN）。
- **HIPAA 限制模式下直接拒绝配对**。

## 4. 连接状态与重连（S）

```js
function te(state, name) {
  connected = (state === Connected);
  if (connected && HIPAA_RESTRICTED) { log("connected while HIPAA-restricted — dropping link"); disconnect(); return; }
  if (connected) { retry = 0; clearTimeout(retryTimer); }
  else { retry = 0; scheduleRetry(); }
}

function scheduleRetry() {
  if (!enabled || !selectedDevice || connecting || connected || !bridgeReady) return;
  const delay = Math.min(2000 * 2 ** retry, 60000);   // 2s,4s,8s… 封顶 60s
  retryTimer = setTimeout(() => { ... retry++ ... }, delay);
}
```

**指数退避重连**：2s 起，每次翻倍，上限 60s；成功即清零。

## 5. RPC 面（S）

`BuddyBleTransport` 服务（namespace `claude.buddy`，sender 校验 `xSe` = 顶层 frame）：

| 方法 | 参数 |
|---|---|
| `rx` | `line` |
| `reportState` | `state`, `name` |
| `log` | `msg` |

| 事件 | 参数 |
|---|---|
| `tx` | `line` |

**传输格式是"行"**（`line`）—— 即 BLE 上跑的是**文本行协议**，不是二进制帧。主进程侧：
- `dispatchTx(line)` 把主进程要发的行推给渲染层；
- `setImplementation({rx, reportState, log})` 接收渲染层上报。

## 6. 安装包容量限制（S）

```js
const K = 18e5;   // 1,800,000 bytes
...
if (total > K) throw Error(`Folder is ${Math.round(a/1024)}KB; device limit is ${Math.round(K/1024)}KB`);
```

- 向设备安装"文件夹"（内容包）时，**总大小上限 1.8 MB**。
- 文件夹不能为空，忽略点开头文件；若含 `manifest.json` 会被解析。
- 另有 `pickFolder` / `preview` / `install` 三个 RPC，对应 Buddy 服务。

## 7. 与 feature flag 的对应

| flag | 作用点 |
|---|---|
| `hardwareBuddyEnabled` | `mQ("hardwareBuddyEnabled")` 总开关；配对成功时 `gQ("hardwareBuddyEnabled", true)` 并持久化 `paired` |
| HIPAA 限制（`coworkHipaaRestricted`） | 配对拒绝 + 已连接时强制断链 |

配对状态持久化：`a.set("paired", device)` / `a.delete("paired")`。

## 8. 证据

| 断言 | 锚点 |
|---|---|
| 设备名过滤 | `index.chunk-CzY1tCPL.js`：`startsWith("nibblet")\|\|t.startsWith("claude")` |
| 15s 扫描超时 | 同上：`},15e3)` 与 `scan timeout — saw ${c.length} stick(s)` |
| 配对 handler | 同上：`setBluetoothPairingHandler`、`pairingKind!=="providePin"` |
| 指数退避 | 同上：`Math.min(2e3*2**d,6e4)` |
| 1.8 MB 上限 | 同上：`var K=18e5` |
| 行协议 | `EIPC-METHODS.tsv` 中 `BuddyBleTransport.rx/tx` 参数均为 `line` |

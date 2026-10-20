# P7B — 状态迁移的静态可推导部分

> 部分解决 `U-015`。运行时序无法静态观测，但**触发条件与判定逻辑**可以完整还原。
> 这里只写能从代码读出来的规则，不推测时序。

---

## 1. 最重要的一个状态机：后台节流开关

代码（`index.chunk-lzaSYO3Q.js`）：

```js
if (!e.isMainViewAlive()) return;
let n = e.countVisiblePopouts(),
    r = e.isGlowVisible(),
    i = e.isCuLockHeld(),
    a = e.isBooting(),
    o = e.isDisplayCaptureLive();
let s = n === 0 && !r && !i && !a && !o;      // s = 应当"恢复正常节流"
if (s !== t) {
  t = s;
  e.logInfo(`mainView backgroundThrottling ${s ? "restored" : "disabled"} ` +
    `(visible popouts: ${n}, glow: ${r?"visible":"hidden"}, cu lock: ${i?"held":"free"}, ` +
    `boot: ${a?"in progress":"done"}, display capture: ${o?"live":"off"})`);
  e.applyBackgroundThrottling(s);
}
```

**这是"关闭窗口后仍继续工作"的真正实现机制**：

背景节流（Chromium 的 `backgroundThrottling`）默认会把后台页面的定时器降频到 1Hz。这里在 **5 个条件任一成立时关闭节流**：

| 条件 | 含义 | 为什么需要关节流 |
|---|---|---|
| `visiblePopouts > 0` | 有可见的弹出会话窗 | 弹窗里的流式输出不能卡 |
| `isGlowVisible()` | 计算机操作的"光晕"覆盖层可见 | 覆盖层要实时跟随 |
| `isCuLockHeld()` | 计算机操作持有锁 | 正在操控桌面，不能降频 |
| `isBooting()` | 启动中 | 启动阶段不能降频 |
| `isDisplayCaptureLive()` | 屏幕采集进行中 | 采帧是连续的 |

**结论（S）**：这不是"偷偷在后台跑"，而是**五个明确的业务条件触发节流关闭**，且每次状态切换都有带完整上下文的日志。这是可以审计的设计。

## 2. 计算机操作的状态锁

`isCuLockHeld()` 与 `isDisplayCaptureLive()` 是两个独立的布尔状态，说明计算机操作有：

```
cu lock:    free ↔ held      （独占锁，防止并发操控）
capture:    off  ↔ live      （屏幕采集开关）
glow:       hidden ↔ visible （视觉指示）
```

日志里这三者的组合值会被打印，便于诊断"为什么还在耗电"。

## 3. 预热生命周期（WarmLifecycle）

代码中存在三个具名实例（日志中的 `Initialized (arm=when-hidden)`）：

```
WarmLifecycle:session    — 会话预热
WarmLifecycle:preview    — 预览预热
WarmLifecycle:cowork     — Cowork 预热
```

`arm` 字段的取值：`when-hidden`（窗口隐藏时武装）、`configured`（已配置）。
这是一个**延迟到窗口隐藏才启动的预热机制**，目的是让用户第一次点开时已经热了。

> 注意：`arm` 在代码里还有另一处含义（预览的"武装"对象 `{hostWc, frameProcessId, frameRoutingId, arm target, armedAt, expiry}`），那是**行为绑定**：把某个 frame 与某个目标绑定，带超时失效。两处 `arm` 不复用结构，已分开记录。

## 4. 应用生命周期钩子的触发条件（S）

| 钩子 | 代码行为 | 可推导语义 |
|---|---|---|
| `second-instance` | 若 `TA()` 为真直接 return；否则 `Dq()` 后交给深链处理器，并打印 `second-instance: suppressing duplicate` | 有"抑制重复"的节流 |
| `before-quit` | 若 handler 未跑过则 `preventDefault()` + 清理，完成后放行 | 保证清理至少执行一次 |
| `before-quit-for-update` | 设 `bA = true` | 更新专用退出路径 |
| `will-quit` | 两个监听：清定时器+关 `BMr` 列表窗口；另一个触发 `willQuit` | 双阶段清理 |
| `window-all-closed` | 调 `HAn()`（不直接 quit） | 允许驻留托盘 |
| `session-end`（Windows） | `wA()` | 系统注销/关机 |
| `render-process-gone` | 三处独立监听 | 分窗口恢复策略 |

## 5. 深链的状态机（S，最窄的一条）

严格校验器只接受三种形态：

```
claude:claude.ai/new?q=...
claude:cowork/new?q=...
claude:claude.ai/{chat,project}/<uuid>
```

不接受其它 query key，不接受 hash。超长 argv 会先 `app.relaunch({args:[...e, mIa]})` 再 `app.exit(0)` —— 即**重启自身以携带截断后的参数**。

## 6. 静态不可推导的部分（保留 U）

| 项 | 原因 |
|---|---|
| 各状态的实际迁移**顺序与耗时** | 依赖真实异步调度，只能观测 |
| 节流状态切换的**频率** | 同上 |
| 五个条件在真实使用中的**典型组合** | 同上 |
| `TA()` / `Dq()` / `HAn()` 的具体实现 | 已定位调用点，未逐个展开函数体 |

**本节的态度**：把"能确定的判定规则"和"不能确定的时间序"分开写，不把前者包装成后者。

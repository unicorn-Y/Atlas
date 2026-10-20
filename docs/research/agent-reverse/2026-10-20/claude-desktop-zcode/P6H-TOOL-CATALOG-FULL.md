# P6H — 内建工具全表（来自遥测脱敏白名单，411 个名字）

> 追加发现。在 `ion-dist/assets/rumEncoder.worker-*.js`（64,947 B，RUM 遥测编码 worker）里
> 发现两份**完整的工具名清单**：设备工具 14 个、计算机操作工具 41 个。
> 它们原本用于遥测脱敏（避免把工具名当 PII 上传），但正好构成权威的工具枚举。

---

## 1. 为什么这份清单可信

该 worker 的职责是**在数据离开客户端前做脱敏/归一化**。它维护两份白名单：

```js
const s = ["list_devices", ..., "project_memory_write"];
const c = "computer_resolve_access.computer_request_access....".split(".");
const l = new Set([...s, ...c]);     // 白名单集合
```

配套的检测逻辑：

```js
// 会话 id 形态：session_* / cse_* 需被判为需要脱敏
function a(e){ for (const [,t] of e.matchAll(/(?:^|[^A-Za-z0-9])((?:session|cse)_[A-Za-z0-9_]*)/gi))
               if (!i(t)) return true; return false; }
const o = /^sha256_[0-9a-f]{64}$/;     // 文件内容哈希形态
```

因此这份集合是**开发者手写的真实工具名白名单**，不是从别处爬来的字符串。

## 2. 设备工具（14 个）

```
list_devices                 get_device_info
device_list_dir              device_stage_files
device_commit_files          device_bash
device_request_folder_access device_request_delete_permission
create_artifact              update_artifact
list_artifacts               list_legacy_live_artifacts
project_memory_read          project_memory_write
```

### 这组工具揭示的能力

| 工具 | 说明 |
|---|---|
| `list_devices` / `get_device_info` | **枚举设备**（多设备场景，与 `DeviceRegistry` 服务对应） |
| `device_list_dir` | 列出某设备上的目录 |
| `device_stage_files` / `device_commit_files` | **两阶段文件写入**：先暂存、再提交（保证原子性） |
| `device_bash` | **在设备上执行 shell** |
| `device_request_folder_access` / `device_request_delete_permission` | 权限申请（可见权限是**按需申请**而非预授权） |
| `create_artifact` / `update_artifact` / `list_artifacts` / `list_legacy_live_artifacts` | Artifact 的创建/更新/列举，含**旧版 live artifact** 兼容 |
| `project_memory_read` / `project_memory_write` | 项目级记忆读写 |

**关键点**：`device_bash` 与 `device_commit_files` 说明**工具是跨设备执行的** —— 模型可以在"另一台设备"上跑命令、写文件。这与 `RemoteControlServing`、`CloudMove`、`device_*` 三条线互相印证。

## 3. 计算机操作工具（41 个）

```
computer_resolve_access          computer_request_access
computer_release_lock            computer_screenshot
computer_zoom                    computer_left_click
computer_double_click            computer_triple_click
computer_right_click             computer_middle_click
computer_type                    computer_key
computer_scroll                  computer_left_click_drag
computer_mouse_move              computer_open_application
computer_switch_display           computer_list_granted_applications
computer_list_apps               computer_read_clipboard
computer_write_clipboard         computer_wait
computer_cursor_position         computer_hold_key
computer_left_mouse_down         computer_left_mouse_up
computer_batch                   computer_release_full_control
computer_request_full_control    computer_app_list_windows
computer_app_ax_find             computer_app_screenshot
computer_app_zoom                computer_app_click
computer_app_type                computer_app_key
computer_app_scroll              computer_app_focus
computer_app_drag                computer_app_menu
computer_app_batch               computer_app_release
computer_app_bring_to_current_space
```

### 分层结构（S）

这 41 个工具明显分为**三层**：

| 层 | 工具前缀 | 语义 |
|---|---|---|
| **屏幕级** | `computer_screenshot` / `_zoom` / `_switch_display` / `_cursor_position` | 全屏视角 |
| **输入级** | `computer_left_click` / `_double_click` / `_triple_click` / `_right_click` / `_middle_click` / `_type` / `_key` / `_scroll` / `_mouse_move` / `_hold_key` / `_left_mouse_down` / `_left_mouse_up` / `_left_click_drag` | 原子输入事件 |
| **应用级** | `computer_app_*`（18 个） | **按窗口/应用操作**：list_windows、ax_find（无障碍树查找）、screenshot、zoom、click、type、key、scroll、focus、drag、menu、batch、release、bring_to_current_space |

**`computer_app_ax_find`** 尤其重要：**"ax" = accessibility**，即通过**无障碍树**精确定位元素，而不是靠像素坐标。这与 P4B 里 Simulator 的 `describeAccessibility` 是同一套思路。

**`computer_batch` / `computer_app_batch`**：支持把多个动作合并成一次调用，减少往返。

### 权限模型（S）

```
computer_resolve_access      解析当前可访问范围
computer_request_access      申请访问
computer_request_full_control / release_full_control   全控制权（可申请/释放）
computer_release_lock        释放锁
```

这是**显式的、可申请可释放的控制权模型**，与 P7B 发现的 `isCuLockHeld()`（计算机操作锁）直接对应。

## 4. 与前面结论的交叉验证

| 前面记录 | 这里的证据 |
|---|---|
| `ComputerUseLivePreview`、`ComputerUseTcc`、`FramebufferPreview` 服务 | 41 个 `computer_*` 工具就是它们的工具面 |
| `CuTeach` / `CuWatchRecordChooser` | 教学与录制是围绕这批工具的外围 |
| `chicago` 配置（P7，8 个子开关：mouseAnimation、hideBeforeAction、clipboardGuard、adaptiveResolution 等） | 正好对应 `computer_mouse_move`（动画）、`computer_screenshot`（动作前隐藏）、`computer_read/write_clipboard`（剪贴板守卫）、`computer_zoom`（自适应分辨率） |
| `Simulator.describeAccessibility` | 与 `computer_app_ax_find` 同一技术路线 |

**这是一次强交叉验证**：配置层（chicago 8 开关）与工具层（41 个工具）互相解释了对方的存在理由。

## 5. 与 P6D 的关系

P6D 记录了 19 个**内置 CLI 工具**（Bash/Read/Write/Edit/Glob/Grep/Task/TodoWrite/WebFetch/WebSearch/AskUserQuestion/NotebookEdit/ExitPlanMode/Skill/Cron×3/ScheduleWakeup/Artifact）。

本节记录的是**另一套**：**远程/设备与计算机操作工具**（14 + 41 = 55 个）。
两者合计构成 Claude Desktop 可用的完整工具面：

```
本地 CLI 工具    19（P6D）
设备工具         14（本节）
计算机操作工具   41（本节）
──────────────────────
合计             74
```

## 6. 同一 worker 里还有 URL 脱敏规则（S）

该 worker 维护路径分段白名单，用于对 URL 做结构化脱敏：

```js
const e = ["api","v1","v2","edge-api"];
const h = [
  [join, org, SEG], [join, SEG],
  [enterprise, order, SEG], [user-profiles, enrollment, SEG],
  [offers, SEG], [referral, SEG], [provision, SEG],
  [admin-settings, claude-tag, connectors, github, SEG],
  [admin-settings, claude-tag, connectors, SEG],
  [export, audit-logs, SEG, download, SEG],
  [export, account, download, SEG],
  [export, domain-capture, SEG],
  [export, SEG, download, SEG],
  [settings, privacy, export, SEG],
  [api, organizations, SEG, ...],
  ...
];
```

即：它知道 `/export/audit-logs/:id/download/:id`、`/admin-settings/claude-tag/connectors/github/:id` 这类路径的**精确形状**，从而只对其中真正的 ID 段做脱敏。

**附带价值**：这份规则顺手确认了一批**真实存在的服务端路由**（`export/audit-logs`、`export/domain-capture`、`settings/privacy/export` 等），与 P1C 的 103 条 SPA 路由互相补充。

## 7. 产物

```
（本报告即全部证据；原文位于 ion-dist/assets/rumEncoder.worker-D8GGzwpc.js 偏移 ~660）
```

## 8. 本轮意义

这份清单把"计算机操作"从**服务名与方法名**提升到了**具体工具级**：
- 之前只知道有 `ComputerUseLivePreview` 服务和 `chicago` 配置；
- 现在知道它能做 **41 种具体动作**，包括无障碍树查找、应用级批量操作、全控制权申请/释放。

同样，"设备"从 `DeviceRegistry` 服务名提升到了 `device_bash`（远程执行）、`device_commit_files`（两阶段写入）这种具体能力。

---

## 9. 同目录下其它 4 个 worker 的身份（补齐）

`ion-dist/assets/` 根级（不在 `v1/` 下）还有 6 个文件，此前只被计入"SPA 资源"未单独识别：

| 文件 | 大小 | 身份 |
|---|---:|---|
| `rumEncoder.worker-*.js` | 64,947 | **RUM 遥测编码器**，同时携带 §2/§3 的工具白名单与 URL 脱敏规则 |
| `highlightWorker-*.js` | 1,576,704 | 代码高亮 worker（最大） |
| `worker-portable-*.js` | 213,617 | **Shiki 语法高亮引擎**（字符串含 `ShikiError`、`editor.foreground`、`terminal.ansi`） |
| `wasm-*.js` | 622,327 | **内联 base64 的 Oniguruma WASM**（解码后 466,610 B，magic `0061736d`） |
| `framebufferCanvasWorker-*.js` | 2,094 | 帧缓冲 → Canvas 渲染（`offscreen`、`canvas`、`unbind/release`） |
| `completionGzipWorker-*.js` | 591 | 用 `CompressionStream` 压缩补全数据 |

### Oniguruma WASM 的解码验证（S）

```js
const e = Uint8Array.from(atob("AGFzbQEAAAABoQEWYAJ/fwF/YAF/AX9gA39/fwF/…"))
```

解码后 466,610 字节，导出符号：

```
getLastOnigError  createOnigScanner  freeOnigScanner
findNextOnigScannerMatch  findNextOnigScannerMatchDbg
emscripten_memcpy_big  emscripten_get_now  emscripten_resize_heap
wasi_snapshot_preview1  fd_write  __wasm_call_ctors
```

**结论**：这是 **Oniguruma 正则引擎**（TextMate 语法的标准匹配引擎），被 Shiki 用于代码高亮的语法解析。它**不是**此前 P1B 记录的那 3 个 `.wasm` 文件，而是**内联在 JS 里的第 4 个 WASM**。

### 对 P1B 的修正

P1B 记录"3 个 WASM（clarkdown_editor / tree-sitter / c2pa）"。**实际是 4 个**：
第 4 个（Oniguruma）以 base64 内联在 `assets/wasm-*.js` 中，不在 `assets/v1/*.wasm` 里。

| # | WASM | 位置 | 用途 |
|---|---|---|---|
| 1 | clarkdown_editor | `assets/v1/c35955a62-*.wasm`（1.36 MB） | Rust 编辑器内核 |
| 2 | tree-sitter | `assets/v1/c571a2685-*.wasm`（205 KB） | 语法解析 |
| 3 | c2pa | `assets/v1/cf4728005-*.wasm`（8.25 MB） | 内容溯源签名 |
| 4 | **Oniguruma** | **`assets/wasm-*.js` 内联 base64（466 KB）** | **正则引擎（Shiki 高亮用）** |

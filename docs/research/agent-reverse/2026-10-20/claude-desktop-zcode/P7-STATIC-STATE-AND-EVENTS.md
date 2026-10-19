# P7（静态版）— 状态与事件还原

> 全部来自 bundle 的枚举表、RPC 方法表、注册点。无动态观测。

---

## 1. 状态机：由字符串枚举还原（S）

打包器保留了 127 个字符串枚举表，共 **1,179 个成员**（`STRING-ENUMS.tsv`）。其中直接构成状态机的是：

| 枚举（原变量名） | 成员 | 语义 |
|---|---|---|
| `GY` | `starting` / `running` / `error` / `stopped` | **VM / 服务生命周期** |
| `Zh` | `initializing` / `running` / `failed` | **初始化态** |
| `hLi` | `connected` / `working` / `editing` / `disconnected` | **会话/协作状态** |
| `FRi` | `ready` / `connected` / `disconnected` | **连接状态** |
| `El` | `hotkey` / `login` / `claude.ai` / `preview` / `cowork` / `code` / `debug-handoff` / `sable-otter` | **应用表面（surface）标识** |
| `jHr` | `compact` / `comfortable` | 界面密度 |
| `ygt` | `system` / `light` / `dark` | 主题 |
| `X1i` | `person` / `app` | 参与者类型 |
| `o8` | `in` / `out` / `fit` / `physical` | 图像缩放模式 |
| `N7t` | `unknown` / `android` / `ios` / `desktop_app` / `web_claude_ai` / `web_console` / `web_custom_agents` / `web_trust_portal` / `web_admin` / `web_auth` | **客户端平台标识**（服务端识别用） |

`N7t` 这一支尤其说明：同一个后端服务多种前端（移动/桌面/网页/管理台），Desktop 通过该枚举向服务端自报身份。

## 2. 事件通道（S）

| 类别 | 数量 | 来源 |
|---|---:|---|
| eipc 服务事件 | 162 | `EIPC-EVENTS.tsv` |
| `webContents` 浏览器事件 | 60 | `WEBCONTENTS-EVENTS.tsv` |
| 纯推送服务（只有事件无方法） | 3 | `DeepLink`、`Navigation`、`Toast` |

### 2.1 `webContents` 事件明细（这不是 IPC 缺口）

| 事件 | 次数 | 性质 |
|---|---:|---|
| `destroyed` | 9 | Electron 窗口销毁 |
| `did-start-navigation` | 8 | 导航开始 |
| `did-navigate` | 8 | 导航完成 |
| `will-navigate` | 6 | 导航拦截（安全相关） |
| `will-redirect` | 4 | 重定向拦截 |
| `render-process-gone` | 4 | 渲染进程崩溃 |
| `did-navigate-in-page` | 4 | 页内路由 |
| `did-finish-load` | 4 | 加载完成 |
| `ready-to-show` | 2 | 首帧就绪（控制白屏） |
| `context-menu` | 2 | 右键菜单 |
| `before-input-event` | 2 | 键盘拦截（快捷键） |
| `will-prevent-unload` | 1 | 阻止关闭确认 |
| `enter/leave-html-full-screen` | 2 | 全屏切换 |
| `dom-ready` / `did-stop-loading` / `did-fail-load` / `did-create-window` | 4 | 其它 |

**结论**：60 条全部是 Electron 原生事件，**不需要** 渲染端 `ipcRenderer.on` 与之配对。此前 `STATIC-GAPS.json` 把它计为"无监听者"，此处更正其性质：它们本就不是 IPC。

## 3. 双向差集结果（S）

| 检查 | 结果 |
|---|---|
| RPC 方法/事件总数 | 1,332 |
| 有可达调用者 | 1,332 |
| 无调用者的 handler | **0** |
| 无 namespace 的孤岛服务 | **0** |
| 主进程 chunk 总数 | 354 |
| 未被静态 import 边引用 | **0**（此前唯一候选 `index.chunk-BK7U1e7z.js` 经查是引导壳：`require("./index.chunk-D4B44ehk.js")`，而该共享 runtime 被 **251** 个 chunk 引用，属打包器结构，非业务孤儿） |
| 渲染层出现但非 eipc 方法的名字 | 331 个唯一名（`clonePosition`、`bind`、`round`、`floor`、`apply`、`bump`…）—— 全部是库内部方法，**不构成 IPC 缺口** |

产物：`UNRESOLVED-CALL-EDGES.tsv`（1,215 行，逐条带 `confidence`）、`STATIC-GAPS.json`。

## 4. 状态持久化与恢复的静态证据（S）

| 状态 | 落盘位置 | 依据 |
|---|---|---|
| 窗口几何/位置 | `window-state.json` | 字符串 + `WindowState` 服务 |
| 应用偏好 | `claude_desktop_config.json` | 配置文件名 + `AppPreferences` 服务 |
| 版本/首启时间 | `config.json` | `updaterLastSeenVersion`、`first_launch_at` |
| 会话 | `.claude/projects/` | 路径字符串 + `transcript-read` 模块名 |
| Cowork 空间 | `spaces.json` | 字符串 + `CoworkSpaces` |
| 定时任务 | `scheduled-tasks.json` | 字符串 + `CoworkScheduledTasks` |
| Artifact 索引 | `artifacts.json` | 字符串 + `CoworkArtifacts` |
| 弹出会话 | session popouts 文件 | `popout-restore` 阶段名 |
| 认证 | `auth.json`、`msal-cache.json` | 字符串 |
| 插件安装态 | `installed_plugins.json`、`known_marketplaces.json` | 字符串 |
| 3P 导出 | `claude-3p-export.json` | 字符串 + `ClaudeAiImport` 服务 |

**恢复语义的四条代码路径**（均为 RPC，S）：
1. `confirmImportedSessionResume` —— 历史导入后的确认恢复；
2. `canAutoResume` / `retryStart` / `warmSession` —— 进程内续跑；
3. `restartRemoteSession` / `restartRemoteHelper` / `reinstallRemoteClaudeCode` —— 跨进程冷恢复；
4. `RemoteControlServing` / `CloudMove` —— 云端侧执行，客户端只订阅。

## 5. 不可证实项（U）

| 项 | 原因 |
|---|---|
| 各状态迁移的真实触发时序 | 需运行，已按新规不做 |
| `store` 镜像（`getState` / `update<X>Store`）的实际同步方向 | 已知是双向镜像，但主从关系需指令级追踪 |
| 事件在 UI 上的最终表现 | 远程 UI 不在包内 |
| 服务端状态机 | `CLOUD-UNAVAILABLE` |

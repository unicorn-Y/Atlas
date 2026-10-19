# Codex Micro：未公开的实体硬件控制台

**证据等级：S**（`webview/assets/codex-micro-*.js` 共 12 个 chunk，含完整 i18n 文案与无障碍描述）

---

## 1. 这是什么

Codex Micro 是一个**实体硬件键盘/控制台**，用来控制本机的 Codex Agent。官方文档从未提到它，但前端里有一整套完整实现：设备发现、按键映射、灯光、状态灯、 onboarding、设置页。

关键原文（onboarding 欢迎语）：

> **"Congrats on getting your hands on the original Creator Micro 2, the base platform on which the Codex Micro was built!"**

→ Codex Micro 是 **Work Louder「Creator Micro 2」** 硬件平台的定制版。同一个前端同时支持两个设备：
- `Creator Micro`（原版）
- `Codex Micro`（联名/定制版）

## 2. 硬件布局（从文案还原）

| 部件 | 数量 | 作用 |
|---|---|---|
| **Agent Keys** | 6 个（磨砂） | 每个键绑定一个 chat/agent，用颜色显示状态 |
| **Command Keys** | 若干 | 绑定常用 Codex 动作 / 快捷键 / keycap / skill |
| **Encoder 旋钮** | 1 个 | 支持 `Turn left` / `Turn right` / `Press`（长按打开设备设置） |
| **Analog stick** | 1 个 | 四个方向各自可映射动作 |
| **Lighting** | — | 亮度可调 + 自动熄灭（inactivity auto-off） |
| **keycap** | 可替换 | 键帽槽位可自定义显示内容 |

## 3. Agent Key 的六种状态（原文）

| 颜色 | 状态 | 原文 |
|---|---|---|
| 白 | 空闲 | `White – Idle` |
| 蓝 | 思考中 | `Blue – Thinking` |
| 绿 | 完成 | `Green – Complete` |
| 琥珀 | 需要输入 | `Amber – Requires input` |
| 红 | 出错 | `Red – Error` |
| 灭 | 未分配 | `Off – No Assigned Agent` |

另有四个状态文案：
```
Working           Working status for a Codex Micro agent key
Unread            Unread status
Awaiting approval Awaiting approval status
Awaiting response Awaiting response status
TextUpdate        Idle status
```

## 4. 交互手势（原文）

> "The 6 frosted Agent Keys give you a live status of your Codex chats/agents. **Single-tap a key to focus it in the background**, or **double-tap** ..."

其他手势（从 chunk 名与文案）：
- `short-press` / `long-press`
- `push-to-talk-press` / `push-to-talk-release`（对应 `realtimeVoice.toggleMicrophoneMute`、`realtimeVoice.endCall`）
- `encoder-press` / `encoder-release`
- 摇杆：`Move farther to trigger` → `Direction reached` → 动作派发
- **划圈手势**：`Keep circling · {progress}` → 触发 mini-game（见下）

## 5. 专用 keycap 与命令（原文）

```
Push to talk
Open OpenAI docs
Write :yolo: in the composer
Write :yeet: in the composer
```

- `YOLO` 和 `YEET` 是**两个实体键帽的丝印文字**
- 按下会在输入框写入 `:yolo:` / `:yeet:`（emoji 短码风格）
- `Push to talk` 对应实时语音的按住说话
- `Open OpenAI docs` 直接开文档

## 6. 隐藏小游戏（重要）

`codex-micro-mini-games-b387bd725562.js` 定义了三款游戏：

```
brick-breaker
asteroids
snake
```

触发方式（joystick HUD 文案）：
> `Title shown while the Codex Micro mini-game activation gesture is in progress`
> `Category label shown while the Codex Micro mini-game activation gesture is in progress` → **"Secret game"**
> `Keep circling · {progress}`

→ **在摇杆上持续划圈**即可激活"Secret game"。`codex-micro-mini-game-composer` 还提供了在输入框里嵌入小游戏的组件。

## 7. 设备连接与权限

| 项 | 原文 |
|---|---|
| 设备发现 | `ChatGPT couldn't check for your {deviceName}` |
| 连接失败 | `ChatGPT couldn't communicate with your {deviceName}` |
| 移除确认 | `Remove {deviceName}?` / `This removes {deviceName} from ChatGPT w...` |
| 输入监控权限 | `Codex Micro needs Input Monitoring permission to respond when you press a key` |
| macOS 专用 | `Open System Settings` / `Show {appName} in Finder` / 拖拽 app 到权限页 |
| 设备标识 | `codex_micro_hid`（USB HID） |

→ 走 **USB HID**，macOS 上需要「输入监控」权限，且提供了完整的权限引导流程。

## 8. 设置页（`codex-micro-settings`，842 条字符串）

设置项分类（原文 section heading）：

| 分类 | 说明 |
|---|---|
| `Chat` | 任务动作 |
| `Navigation` | 导航动作 |
| `Panels` | 面板动作 |
| `Workspace` | 工作区动作 |
| `Skill actions` | 技能管理 |
| `Settings` | 设置 |
| `App` | 应用动作 |

其他设置：
```
Analog stick / Choose what each direction triggers
Configure {deviceName} knob actions
Adjusts the brightness of all {deviceName}
Turns lighting off after inactivity
Reset keyboard layout?
Choose what appears on {slotId}
Search actions and skills
Assign agent key {position}
Search {chats | shortcuts | keycaps | skills}
```

→ 每个物理控件（6 Agent Keys + 旋钮 + 摇杆 4 方向 + Command Keys）都可以独立映射到：
**chat / shortcut / keycap / skill / 内置动作**。

## 9. 与后端的连接

`codex-micro-bridge-a5aa8d621054.js` 揭示桥接层：

```
realtimeVoice.toggleMicrophoneMute
realtimeVoice.endCall
composer.startVoiceMode
codexMicro.command.unavailable
codex-micro-command-unavailable
keycap / command / skill / threadKey
```

→ 硬件事件最终映射到**真实的 Codex 动作**：开新会话（`newThread`）、开新任务（`newTask`）、切换语音、往输入框插文本、执行 skill。`electron-only` 标记说明部分能力只在桌面端可用。

## 10. 为什么这是个重要发现

1. **它是一条完整的产品线**，不是彩蛋：12 个 chunk、842 条设置文案、完整 onboarding、权限引导、灯光控制、状态机。
2. **它把 Agent 并发可视化搬到了物理世界**：6 个键 = 6 个 agent 的实时状态灯。
3. **它支持 4 个并发 agent**（提示层写的 concurrency slots = 4），但硬件给了 6 个 Agent Key——说明预留了扩展。
4. **它内置了三款小游戏**，用摇杆划圈触发，官方从未宣传。
5. **它和 `codex-mobile` 是同一套"远程控制"能力的两端**：手机遥控 + 硬件键盘控制。

## 11. 未解

- 实际硬件是否已量产、售价、发售渠道：**U**（包内只有软件实现）
- 摇杆划圈的判定阈值与具体手势算法：需读 `codex-micro-joystick-feedback` 的实现（本轮只提取了文案）
- 三款小游戏的玩法规则：chunk 里只有名称，逻辑在其他 chunk（**I**）

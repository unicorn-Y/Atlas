# P6B — 语音链路（SableOtter / Dictation / 语音选择）

> 解决 `U-019`。结论先行：**包里没有 ASR 引擎，也没有 TTS 引擎**。语音能力是"本地采集 + 云端识别/合成 + 本地播放"，包内只有录音/播放的胶水代码与试听音频。

---

## 1. `audio/voice/` 的真实内容（27 个文件）

```
audio/voice/audioSinkWorklet.js          ← 唯一的代码文件（AudioWorklet 播放端）
audio/voice/onboarding/{airy,buttery,glassy,mellow,round}/
    intro.mp3 / pre_voice.mp3 / pre_recommendations.mp3
    recommendations.mp3 / final.mp3
audio/voice/selection/{airy,buttery,glassy,mellow,round,rounded}.mp3
```

**这 5 个名字是语音音色（voice），不是语言**：`airy`（轻盈）、`buttery`（顺滑）、`glassy`（清亮）、`mellow`（温和）、`round`（圆润）。

`onboarding/` 下每个音色有 3–5 段脚本化试听（`intro` → `pre_voice` → `pre_recommendations` → `recommendations` → `final`），用于**首次使用时让用户挑音色**。文件大小 150–240 KB 每段，合计约 3.1 MB。

`audioSinkWorklet.js` 是 `AudioWorkletProcessor`，负责把收到的 PCM 送进 `AudioContext` 播放 —— 说明播放侧用 **Web Audio + Worklet**（低延迟、可与主线程解耦）。

## 2. 语音输入（SableOtter）

### 2.1 触发方式：按住键（hold-to-talk）

配置项（来自 `AppPreferences` 的 schema，`meta(eg("security"))` 标记为安全类）：

| 键 | 默认值 | 含义 |
|---|---|---|
| `sableOtterEnabled` | `false` | 总开关 |
| `sableOtterTalkHold` | `right-control+right-shift` | 对话按住键 |
| `sableOtterCardHold` | `right-option` | 卡片按住键 |
| `sableOtterDictateHold` | `right-control` | 听写按住键 |
| `sableOtterModel` | `"default"` | 使用的模型 |
| `sableOtterWindowContext` | `"ask"` | 是否把当前窗口内容作为上下文（`ask` = 每次询问） |
| `sableOtterWindowApps` | `{}` | 各应用的窗口上下文策略 |
| `sableOtterExcludedApps` | `[]` | 排除的应用（不读其窗口内容） |
| `sableOtterTerms` | `[]` | **自定义术语表**（提升专有名词识别率） |
| `sableOtterDictationCount` | `0` | 听写次数（`ui_state`，用于引导） |

**三种不同手势对应三种行为**（talk / card / dictate），说明这不是单一"语音输入"，而是：

- **talk**：按住边说话边送；
- **card**：唤起卡片式交互；
- **dictate**：纯听写（把语音转成文本填入输入框）。

### 2.2 HUD 窗口

`SableOtterHud` 服务 + `W-SABLEOTTER-HUD` 离屏窗口（460×72，`alwaysOnTop:"pop-up-menu"`，无边框、透明、点击穿透除非有输入框）。
预加载脚本 `computerUseTeach.js`（与计算机操作共用），说明 HUD 与计算机操作共享渲染基础设施。

### 2.3 窗口上下文读取

`sableOtterWindowContext` / `sableOtterWindowApps` / `sableOtterExcludedApps` 说明：语音输入时可以**读取当前前台窗口的内容**作为上下文（对应 `ComputerUseTcc` 的屏幕录制权限），并按应用逐个允许/排除。

## 3. 听写（Dictation）

独立的 feature flag `dictationEnabled`，`category:"connection"`，`remotePolicy:{hybrid:{scope:"excluded"}}`（即 hybrid 部署下排除）。
配置 `dictationShortcut` 支持 `"default"` / `"off"` / 自定义 accelerator 三种形态。
持久化路径常量：`user/dictation`。

## 4. 包里没有的东西（明确）

| 项 | 结论 | 依据 |
|---|---|---|
| ASR 引擎（本地） | **没有** | 全包无 `SpeechRecognition` / `webkitSpeechRecognition` / whisper / vosk / sherpa 相关符号 |
| TTS 引擎（本地） | **没有** | 全包无 `speechSynthesis` / piper / coqui / onnx TTS 符号；`audioSinkWorklet.js` 只负责**播放**收到的音频 |
| 声学模型文件 | **没有** | `audio/` 下只有 26 个 mp3 试听 + 1 个 worklet |
| 麦克风采集 | 有（浏览器 API） | 走 `getUserMedia`（Chromium 内置），代码在远程 UI 或 SPA 内 |

**因此语音链路的真实形态是**：

```
按住键 → getUserMedia 采集 → 上行到服务端（ASR）
                              ↓
                       文本进对话 / 指令
                              ↓
                       服务端（TTS）下行音频
                              ↓
                    audioSinkWorklet → AudioContext 播放
```

即 **ASR 与 TTS 都在云端**，本地只做采集、播放与 UI。这也解释了为什么 `ion-dist` 里没有模型文件。

## 5. 与硬件 Buddy 的关系

`sableOtter` 与 `hardwareBuddy` 是两个独立开关，但共用 HUD 与 preload。Buddy 通过 BLE 提供**外部麦克风/按钮**（见 `P2B-BUDDY-BLE.md`），SableOtter 是软件侧的手势与模型配置。二者可组合：Buddy 提供采集设备，SableOtter 提供交互模型。

## 6. 证据

| 断言 | 锚点 |
|---|---|
| 27 个语音文件、5 种音色 | `extract/app/resources/ion-dist/audio/voice/` 目录树 |
| 播放用 AudioWorklet | `audio/voice/audioSinkWorklet.js` |
| 三种按住手势 | `AppPreferences` schema：`sableOtterTalkHold`/`CardHold`/`DictateHold` |
| 无 ASR/TTS 符号 | 对全部 `.vite/build/*.js` 与 `ion-dist/assets/v1/*.js` 搜索 `SpeechRecognition`/`speechSynthesis` 均为 0 命中 |

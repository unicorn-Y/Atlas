# 05 · 运行时观测（R 级证据）

> 本文件只记录**实际执行过**的观测。每条都标注了获取方法与可复现步骤。
> 证据等级：**S**=源码，**R**=运行时观测，**D**=官方文档，**I**=推断，**U**=不可获得

---

## 1. 为什么不能用 CDP

Claude Desktop 内建了 Ed25519 签名的 CDP 授权门（见 `04-安全与信任边界.md` §2）。运行时实测：

```
$ claude.exe --remote-debugging-port=9333
Claude: refusing to start — a debugging or network-override switch is present on the command line.
[exit code: 1]
```

**R**，可复现。私钥不在客户端，伪造需要破解 Ed25519 —— 不做。

因此运行时内省走两条路：

1. **窗口截图** —— `PrintWindow(hwnd, hdc, PW_RENDERFULLCONTENT)`，不受遮挡影响
2. **UI Automation** —— `System.Windows.Automation`，`ControlViewWalker` 递归遍历

第二条是关键突破口，见下。

---

## 2. 启动方式（可复现）

从解包目录直接运行，**不安装** MSIX：

```powershell
& "D:\Atlas-Reverse-Lab\claude-desktop\extracted\msix\app\claude.exe" `
    --no-sandbox --force-renderer-accessibility
```

- `--no-sandbox`：解包态没有 MSIX 容器身份，Chromium 沙箱需要它才能起（**不在** forbidden 列表里）
- `--force-renderer-accessibility`：**关键**。默认关闭渲染进程可访问性，UIA 只能看到 Chromium 的外壳控件；打开后能看到完整 DOM 语义树

进程实测：窗口标题 `Claude`，工作集约 **227 MB**。

### 2.1 stderr 实际输出（R，原文）

```
MaxListenersExceededWarning: Possible EventEmitter memory leak detected.
  11 coworkHipaaRestricted listeners added to [EventEmitter]

MaxListenersExceededWarning: Possible EventEmitter memory leak detected.
  31 destroyed listeners added to [WebContents]

ExperimentalWarning: vm.USE_MAIN_CONTEXT_DEFAULT_LOADER
```

三条都有信息量：

- `coworkHipaaRestricted` **11 个监听器** —— HIPAA 标志被反复订阅（这是一个真实的小缺陷，或至少是设计异味）
- `destroyed` **31 个监听器**挂在 `WebContents` 上 —— 窗口销毁路径的监听器未清理
- `vm.USE_MAIN_CONTEXT_DEFAULT_LOADER` —— 用了 Node 的 `vm` 模块自定义 loader，说明主进程里有动态代码加载

---

## 3. UIA 树规模对比（R）

| 启动参数 | UIA 元素数 | 能看到什么 |
|---|---|---|
| `--no-sandbox` | **15** | 仅 Chromium 外壳：`Chrome_WidgetWin_1` / `RootView` / `NonClientView` / `WinFrameView` / `WinCaptionButton` / `Intermediate D3D Window` / `Document`(`RootWebArea`) |
| `--no-sandbox --force-renderer-accessibility` | **248** | 完整 DOM 语义树：标题、按钮、文本、菜单项 |
| + 点开 Explore here 弹层 | **254** | 多了 6 个菜单项节点 |

这是本次逆向最重要的**方法学发现**：Electron 应用的 UIA 默认几乎不可用，`--force-renderer-accessibility` 是打开它的钥匙，而这个开关**不在** forbidden 列表里。

---

## 4. 实际界面：区域门禁页（R）

首次运行渲染的不是产品界面，而是**区域限制页**（本环境所在区域不可用）。

### 4.1 完整可见文本（R，UIA 提取，逐字）

```
Claude
Toggle menu

App unavailable in region | Explore here ▾

App unavailable

Unfortunately, Claude is only available in certain regions right now.
Please contact support if you think you're getting this message in error.

[View supported countries]
```

窗口 **Document 标题**（R）：

```
App unavailable in region | Claude by Anthropic
```

应用下方是**内置浏览器**加载的 `claude.ai` 营销页脚（R）：

```
Products: Claude · Claude Code · Claude Cowork · @Claude · Claude Science
Privacy · Usage Policy · DPA
Data Processing Agreement: US K-12
```

### 4.2 结构说明

这个页面本身就暴露了产品的窗口骨架：

1. **顶栏**：应用名 `Claude` + `Toggle menu` 按钮
2. **面包屑**：`App unavailable in region` + `Explore here ▾`（下拉）
3. **主内容区**：标题 + 说明 + CTA 按钮
4. **下方**：**内嵌的 in-app browser**，已经在加载外部网站

第 4 点很关键 —— 即使在错误页，内置浏览器也在工作，且渲染的是真实 `claude.ai` 内容。这**R 级证实**了 `IN_APP_BROWSER` 窗口角色和 `Launch` 子系统的存在。

### 4.3 Explore here 弹层（R）

点击 `Explore here ▾` 后，UIA 多出 6 个节点（15 → 254 含主树），菜单内容：

```
Menu "Explore here"
  MenuItem "Ask questions about this page"
  MenuItem "Copy as markdown"
```

这两项是**内置浏览器的页面操作**：向当前页提问、把当前页转 Markdown。对应 `Launch` 类的方法 `previewModelScreenshot`、`capturePreviewScreenshot`、`getPreviewLastFrame` —— 即"读取当前页内容并喂给模型"的完整链路。

### 4.4 截图

| 文件 | 内容 | 说明 |
|---|---|---|
| `screenshots/live/00-launch-window.png` | 区域门禁页，616×608 | 干净，可用 |
| `screenshots/live/01-explore-here.png` | Explore here 弹层展开 | 可用 |
| `screenshots/live/00-launch-first-window.png` | 首帧 | **被遮挡，不可用，已标注** |
| `screenshots/live/02-toggle-menu.png` | 尝试展开 Toggle menu | **失败，与 01 字节数相同，菜单未打开** |

第 4 条如实记录：`Toggle menu` 是 `Toggle` 控件类型，`InvokePattern` 不支持（R 报错：`调用"GetCurrentPattern"并传入"1"个参数时发生异常："不支持的模式。"`），脚本没有合成鼠标点击回退，所以菜单没开。这是**工具缺陷**，不是产品限制。

---

## 5. 窗口与控件类名（R，完整）

UIA 在无渲染可访问性时暴露的 Chromium 内部类名，逐层：

```
Chrome_WidgetWin_1                 ← 顶层窗口类
  RootView
    NonClientView
      WinFrameView
        WinCaptionButtonContainer
          WinCaptionButton   ×3   ← 最小化 / 最大化 / 关闭
    ...
  Intermediate D3D Window          ← GPU 合成层
    Document  (automationId = RootWebArea)
```

系统按钮文字被本地化为中文（R）：`最小化` / `最大化` / `关闭` —— 来自 OS 语言，不是应用字符串。

---

## 6. 未能完成的运行时观测（如实记录）

| 目标 | 状态 | 原因 |
|---|---|---|
| 登录后的真实产品界面（Cowork 标签、聊天、artifact） | **未获取** | 区域门禁，无法登录 |
| 一次真实的 tool_use 往返 | **未获取** | 同上 |
| Cowork VM 实际启动 / hvsock 握手 | **未获取** | 本机未启用 Hyper-V |
| 原生菜单栏（File/Edit/View…）内容 | **未获取** | `Toggle menu` 需合成点击，脚本缺回退 |
| 权限弹窗（`host_dialog`） | **未获取** | 需要一次真实工具调用 |
| Quick Entry 悬浮窗 | **未获取** | 需全局快捷键 + 登录态 |
| 设置面板 | **未获取** | 区域门禁 |
| 内置浏览器的地址栏 / 标签栏 | **部分** | 只见页面内容，未见 chrome UI |

这些都是**边界**，不是遗漏。每一条都写进了 `ATLAS-GAP.md`。

---

## 7. 复现脚本清单

| 脚本 | 作用 | 状态 |
|---|---|---|
| `scripts\capture-window2.ps1` | `PrintWindow` 截图（抗遮挡） | ✅ 可用 |
| `scripts\dump-uia.ps1` | UIA 递归导出 JSON | ✅ 可用 |
| `scripts\uia-invoke.ps1` | 按名称查找并调用元素 | ⚠ 缺合成点击回退 |
| `scripts\show_uia.py` | UIA dump 美化打印 | ✅ 可用 |
| `scripts\capture-window.ps1` | `CopyFromScreen` 截图 | ❌ 受遮挡污染，已弃用 |

`capture-window2.ps1` 用法：

```powershell
.\capture-window2.ps1 -TitleLike "Claude" -Out "shot.png"
# → CAPTURED <path> WxH pid=N method=PrintWindow title='...'
```

`dump-uia.ps1` 用法：

```powershell
.\dump-uia.ps1 -TitleLike "Claude" -Out "uia.json" -MaxDepth 40
# 上限 4000 元素
```

---

## 8. 从运行时观测得到的产品结论

即使只看到错误页，也能确定：

1. **应用有原生顶栏**（不是纯网页），带应用名和菜单按钮 —— 对应 `desktopTopBar` flag
2. **有面包屑导航** —— 说明产品是多层级视图，不是单一聊天页
3. **内置浏览器在首屏就已加载**，且能渲染真实外网内容 —— 内置浏览器是**常驻**的，不是按需挂载
4. **错误页也有完整 chrome**（顶栏+面包屑+内容区+浏览器区）—— 说明这是**统一的窗口骨架**，内容区是可替换的部分
5. **文案里有 "Please contact support"** —— 区域限制是产品级策略，不是 bug

第 4 点尤其重要：它意味着真实的产品界面也是这个骨架，只是内容区不同。这让我们能对未见到的界面做出**有依据**的结构推断（标 **I**）。

---

## 9. 关于 GIF / 视频

ffmpeg 8.1.2 可用，但**本次未录制视频**。原因：可交互范围只有错误页和一个两项下拉菜单，录 GIF 的信息增量接近于零，且会制造"看起来很完整"的假象。

替代方案见 `viewer/` —— 用可操作 HTML 复刻门禁页与弹层交互，标注每个元素的来源与事件，比录一段假动画更有信息量。

**这一条是明确的取舍，不是遗漏。**

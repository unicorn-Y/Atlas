# 专题 1：电脑操作与浏览器（2026-09-30）

问题：Agent 怎么操作用户的电脑和网页，谁做得最好，Atlas 要超过它们还差什么。

## 一、当前最强做法（逐项）

### 1. 按精确度分层选路：先连接器，再浏览器，最后才动屏幕
- **Claude Cowork**（最完整）：有连接器（Gmail、Drive、M365、Slack…）就走连接器，最快也最稳；没有就用桌面端内置浏览器，或者通过 Claude in Chrome 用你自己的 Chrome；实在不行才直接看屏幕、点鼠标。
- **UI-TARS Desktop**：浏览器操作可以选「看截图」、「读 DOM」或两者混合。
- 共识：看屏幕点鼠标是最后手段——最慢、最贵、最容易错。

### 2. 在后台操作，不抢用户的鼠标
- **Claude（9-02）**：在隐藏的后台窗口里点击、输入、打开应用，不占用你的鼠标键盘；你正在打字时它会等。界面上显示「正在操作你的电脑」和已用时间，可以展开看细节。目前只支持 macOS 15+，默认关闭。
- **Microsoft Copilot Actions**（Windows 上最强的隔离做法）：Agent 在「Agent 工作区」里干活，本质是**远程桌面子会话**（比虚拟机轻，但和用户桌面隔离，Agent 看不到也碰不到你的桌面）；用**专用的普通权限 Windows 账户**运行，系统能区分 Agent 和人的操作，并用文件权限（ACL）限制它；用户可以随时看、暂停、接管。
- **Copilot Studio**：内置凭据库，网站和桌面应用的登录可以在多个 Agent 之间复用，运行中不用再弹登录。

### 3. 本地电脑和云电脑随时切换
- **豆包工作（9-09）**：任务执行中不用新开对话，就能切到另一台本地电脑，或者切到云电脑继续跑；在一台已登录的电脑上可以给其他已登录设备下指令。
- **Manus 2.0**：可以买专属云电脑，长期挂着跑自动化。
- **Windows 365 for Agents MCP**：让 Agent 完全控制一台云电脑，包括桌面、浏览器和语义化界面检查。
- **Cursor（9-23）**：子 Agent 各自跑在自己的虚拟机里。

### 4. 演示一次，变成可重复的技能
- **豆包工作（9-09）**：在豆包浏览器里演示一遍（点击、填写、上传），自动整理成可以复用的 Skill，比如「商品上架」。
- **Stagehand v3**：AI 生成的操作可以预览、缓存，重放时**不调用模型**；网站改版导致重放失败时，再让 AI 接手。又快又省钱。
- **Cloudflare Browser Run**：录制和重放整个会话。

### 5. 用你已经登录的浏览器
- **Claude in Chrome（8-26 正式版）**：直接用你 Chrome 里的登录状态，自主浏览、填表。
- **Perplexity Comet**：全平台免费，能自主浏览、填表、下单。
- ChatGPT Atlas 浏览器 8-09 停服，能力并入 ChatGPT 内置浏览器和 Chrome 扩展。结论：**独立 AI 浏览器不是方向，「内置浏览器 + 接入用户自己的 Chrome」才是**。

### 6. 防网页里的提示注入
- **Claude in Chrome**：页面交给模型之前，先用探针和分类器扫描恶意指令，号称注入成功率降到 0%。
- 行业共识：提示注入仍是头号风险，没有根治办法。能做的是隔离会话、分步校验、完整录像留痕。

### 7. 让人随时接手
- **Cloudflare Browser Run**：实时画面 + 人工介入。
- **Copilot Actions**：可以随时暂停和接管。
- 登录、验证码、付款这类步骤交还给人，已经是标配。

### 8. 底层技术
- **browser-use** 2026 年初从 Playwright 换成**直接用 CDP**，加了事件驱动的监控架构；允许 Agent 自己写 JavaScript 操作页面。SDK 3.0 定位为「浏览器里的 Claude Code」。
- 模型水平：Simular Sai 在 OSWorld 2.0 上 73%（8 月），Agent S3 首个超过人类（72.6%）；开源模型里 OpenCUA-72B 在 OSWorld-Verified 上 45%。

## 二、Atlas 现状

| 能力 | Atlas | 和最强的差距 |
| --- | --- | --- |
| 看屏幕、操作鼠标键盘 | ✅ `computer_observe / mouse / keyboard / window / clipboard`（`tools/computer_use.py`，截图 + UIA） | **在前台抢用户的鼠标**；没有隔离，没有专用账户 |
| 浏览器自动化 | ✅ Playwright / chrome-devtools MCP、`browser_use` 能力、内置浏览器面板 | 没有「先连接器、再浏览器、最后屏幕」的选路策略 |
| 用户自己的 Chrome | 🟡 chrome-devtools MCP 能连，用户没有开关（第六波第 2 节） | Claude in Chrome 是扩展形式，体验更好 |
| 人工接管 | ❌（第六波第 2 节） | |
| 演示一次变技能 | ❌ | 豆包、Stagehand 都有 |
| 缓存重放、不调用模型 | ❌ | Stagehand |
| 云电脑 / 切换设备 | 🟡 有 SSH 远程目录（第三波），只能跑命令 | 豆包、Manus 能切换完整桌面 |
| 提示注入防护 | ❌ 没有专门扫描 | Claude in Chrome |
| 操作录像回放 | ❌ | Cloudflare |

## 三、Atlas 要超过它们该做的（按性价比排序）

1. **后台操作（Windows）**：学 Copilot Actions——用远程桌面子会话或独立桌面（`CreateDesktop`）加专用低权限账户让 Agent 在后台操作，用户照常用电脑，界面上能实时看、暂停、接管。这在 Windows 上目前只有微软自己做了，**开源里没有人做**，做到就是领先。退一步的方案：至少做到「用户动鼠标就自动暂停」和前台操作时的明显提示。
2. **选路策略写进系统提示和工具描述**：有连接器或 API 就不用浏览器，有浏览器就不看屏幕。
3. **演示录制成技能 + 缓存重放**：在内置浏览器里录一遍 → 生成技能（步骤 + 选择器）→ 重放时不调用模型，失败了再让模型接手。把豆包的「录制」和 Stagehand 的「缓存重放」合在一起。
4. **浏览器交接 + 复用用户 Chrome**：第六波第 2 节已经写了，保留。可以考虑再做一个 Chrome 扩展，效仿 Claude in Chrome。
5. **注入扫描**：网页内容交给模型之前，先用规则和小模型扫一遍，可疑指令标出来，并在界面上提示。
6. **操作留痕**：每一步的截图和动作存下来，任务结束后可以像看录像一样回放。
7. **切到远程机器继续跑**：在已有 SSH 基础上，把「整个任务搬到另一台机器（比如主机）继续」做成一个按钮。

## 资料

- [Claude 在 Cowork 里使用你的电脑（官方帮助）](https://support.claude.com/en/articles/14128542-let-claude-use-your-computer-in-cowork)
- [Claude 后台电脑操作（2026-09）](https://explainx.ai/blog/claude-background-computer-use-cowork-code-macos-september-2026)、[WinCentral 报道](https://thewincentral.com/claude-computer-use-cowork-code-background/)
- [Copilot Actions 与 Agent 工作区（BleepingComputer）](https://www.bleepingcomputer.com/news/microsoft/microsoft-debuts-copilot-actions-for-agentic-ai-driven-windows-tasks/)、[Agent 工作区是远程桌面子会话](https://windowsforum.com/threads/agent-workspace-for-copilot-on-windows-11-ai-actions-in-a-separated-session.391071)
- [Copilot Studio 电脑操作](https://learn.microsoft.com/en-us/microsoft-copilot-studio/computer-use)
- [豆包工作：本地 Office 编辑、浏览器录制与回放、执行环境切换（2026-09-09）](https://news.qq.com/rain/a/20260909A09O4W00)
- [Stagehand、UI-TARS 等（Turing Post）](https://www.turingpost.com/p/computer-use-ai-agents)、[UI-TARS Desktop](https://github.com/bytedance/UI-TARS-desktop)
- [browser-use 更新日志](https://browser-use.com/changelog)、[Cloudflare Browser Run](https://blog.cloudflare.com/browser-run-for-ai-agents/)
- [2026 浏览器 Agent 现状：解决了什么、还没解决什么](https://www.testmuai.com/blog/state-of-ai-browser-agents-2026/)
- [Claude in Chrome 正式版](https://gigazine.net/gsc_news/en/20260827-claude-chrome-available/)
- [Agent S](https://github.com/simular-ai/agent-s)、[OpenCUA](https://opencua.xlang.ai/)

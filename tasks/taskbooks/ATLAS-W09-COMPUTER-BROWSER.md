# ATLAS-W09-COMPUTER-BROWSER（第九波：电脑与浏览器）

STATUS: READY（W06 交付后即可开始）
PROTOCOL: +1
先读：`docs/plan/SOURCE-MAP.md` E 节、`docs/research/2026-09-30-landscape/01-computer-and-browser.md`
主要来源：cua（`trycua/cua` 的 `libs/cua-driver`，MIT）、H（Hermes）的电脑操作接入层和浏览器工具全套、Stagehand（操作缓存）

## 本波目标

调研结论：
- 最好的电脑操作是**在后台做、不抢你的鼠标**（Claude 9 月、Copilot Actions）。Atlas 现在在前台抢鼠标。cua-driver 已经在 Windows 上实现了后台操作，Hermes 已经接好了。
- 浏览器：用你已登录的浏览器、遇到登录和验证码交还给人、密码不经过模型、操作可以缓存重放。

---

## 1. 后台电脑操作：cua-driver（后端，依赖 + 从 H 搬接入层）

**来源**：
- cua `libs/cua-driver`（Rust，带 Python 绑定 `libs/cua-driver/python/src/cua_driver/`）。技术要点（见 cua 博客 `blog/inside-windows-computer-use.md`）：优先用 UI Automation 的控件模式（Invoke、Toggle、Value、RangeValue、ExpandCollapse）和 PostMessage，**不动真实鼠标、不抢前台**；老程序走 MSAA；后台截图用 PrintWindow（传统窗口）和 Windows.Graphics.Capture（新式应用），窗口被遮挡时用区域截图并标明；只有必须前台的情况（游戏、自绘界面、个别控件）才报 `background_unavailable`，要求显式切到前台模式；光标是一个透明、点不到的覆盖层，不是你的鼠标；用命名管道守护进程解决「从 SSH 或服务启动时没有桌面」的问题。
- H `tools/computer_use/`：`tool.py`（904 行，工具入口、返回格式）、`cua_backend.py`（430 行，通过 stdio MCP 驱动 cua-driver）、`cua_backend_session.py`、`_driver.py`、`_capture.py`、`_input.py`、`_parse.py`、`cua_backend_daemon.py`、`permissions.py`（就绪检查：Windows 上就是驱动健康）、`vision_routing.py`（主模型不支持图片时先用辅助视觉模型转成文字）、`doctor.py`、`schema.py`。

**做法**：
1. 依赖 cua-driver：优先用 Python 绑定（`cua_driver` 包，从 PyPI 或 cua 的发布页安装，**锁定版本**）；不行就用驱动程序 + stdio MCP（H 的方式）。安装包要带上驱动（`dist:win` 打包流程里加一步）。
2. 搬 H 的 `tools/computer_use/` 接入层到 `core/atlas/tools/computer_use/`，替换 Atlas 现有的 `tools/computer_use.py`（1092 行，前台 UIA + 真鼠标）的执行路径：
   - 默认**后台模式**；驱动报 `background_unavailable` 时，工具结果告诉模型「这一步需要占用前台和鼠标」，并发事件 `computer.foreground_required {reason}`；用户在卡片上同意后才切前台（这一次运行内有效）。
   - 前台操作期间：屏幕边缘显示提示条「Atlas 正在操作，动一下鼠标就暂停」；检测到用户动鼠标或键盘就暂停，发 `run.paused`。
   - 保留 Atlas 现有工具名（`computer_observe / mouse / keyboard / window / clipboard`）作为兼容别名，内部改走新实现；新增 H 的工具形态（按元素索引点击、`capture_after`）。
3. 搬 `vision_routing.py`：主模型不支持图片时，截图先交给辅助视觉模型（配置 `agents.vision_model`）转成文字。
4. `GET /api/computer/status`（就绪、驱动版本、诊断信息，照 H `doctor.py`）。
5. 电脑操作照常过 W06 智能审批（`computer_*` 写操作）。
6. **操作留痕**：每一步的截图（缩略图）和动作存进运行记录，任务结束后可以按步骤回看。

**测试**：搬 H `tests/tools/` 下 computer_use 测试（mock 驱动）。真机测试单独标记，默认跳过（和 `test_computer_use.py` 一样）。

**真机**：让 Atlas「打开记事本，写一段话，保存到桌面」，**你同时在用浏览器打字**，确认你的鼠标和键盘没被抢；再让它操作一个只能前台的程序，确认会先征得同意。

## 2. 浏览器工具全套（后端，从 H 搬）

**来源**：H `tools/browser_tool.py`（1364 行）+ `browser_tool_*.py` 兄弟文件（cdp、cloud、session、snapshot、vision、lifecycle、install、origin、eval_policy、real_profile）；`browser_supervisor.py`（552 行）+ `_dialogs.py`、`_frames.py`；`browser_cdp_tool.py`、`browser_dialog_tool.py`；`browser_camofox.py`、`browser_lightpanda.py`（可选后端）。底层是 `agent-browser` 命令行（`npm install -g agent-browser`），Atlas 安装包里已经带了 Node 22，可以一起打包。

**H 已有、要搬到的行为**：每个任务一个浏览器会话；无障碍树快照，元素用 `@eN` 引用（比截图省 token 也更准）；多后端（本机 Chromium、用户提供的 CDP、Browser Use / Browserbase 云、Camofox 反检测）；常驻 CDP 连接捕获弹窗和多帧（iframe、跨域框架）；自动清理。

**做法**：
1. 对照 Atlas 现有浏览器能力（`capabilities/browser/browser_use.py`、playwright / chrome-devtools MCP），用 H 的浏览器工具作为主路径，保留 browser-use 作为「整段任务交给浏览器 Agent」的选项。
2. **复用你的浏览器配置**：搬 `browser_tool_real_profile.py`（把你默认的 Chromium / Chrome / Edge 配置复制一份给 Agent，用真实浏览器程序打开，**不碰原配置**）。设置 `browser.mode: "atlas"|"real_profile"|"cdp"|"extension"`；`cdp` 时 `browser.cdp_url` 只允许回环地址。
3. **浏览器扩展**（类似 Claude in Chrome）：搬 H `gateway/browser_control_broker.py`（512 行，票据短期、一次性、按身份绑定）和 `tools/browser_extension_router.py`（137 行，失败一律关闭，不乱跳后端）。扩展本身：看 H 仓库里是否有扩展源码（搜 `manifest.json` / `browser-extension`），有就搬，没有就照协议写一个最小扩展（Chrome MV3）。扩展连接后端走本机 WebSocket，用一次性配对码配对（**新增一种受信方式，不能放宽 OriginGuard 现有规则**）。
4. 浏览器工具结果过 W06 威胁扫描（网页注入）。
5. **选路策略**写进系统提示和工具描述：有连接器、API 或 MCP 能做的不用浏览器；浏览器能做的不用屏幕点击（照 Claude Cowork）。

**测试**：搬 H 对应测试。

## 3. 登录、验证码交还给人 + 模型看不见的密码（后端）

**来源**：H `tools/browser_vault_tool.py`（770 行）、`agent/vault_store.py`、`agent/vault_login_classifier.py`；交接卡片 H 没有独立模块，自己写。

**做法**：
1. **凭据库**（搬 H）：`browser_vault_list` 只返回句柄和元信息（登录名不算秘密），**永远不返回密码**；`browser_vault_fill` 由后端直接把密码 / 银行卡 / 地址填进当前页面，银行卡填之前要用户确认。凭据本身存系统凭据库（keyring），H 的存储层换成 keyring。设置里管理条目。
2. **交接**（自己写）：新工具 `browser_handoff {reason, url?}`；run 进入等待，发 `browser.handoff_required {event_id, reason, url}`；用户点「我弄好了，继续」（WS `{type: "browser.handoff", run_id, event_id, done: true, note?}`）或「做不了」；超时 30 分钟算做不了。交接期间 Agent 的浏览器工具一律拒绝（「正在等你操作浏览器」）。系统提示：遇到验证码、二次验证、付款确认先看凭据库能不能填，不能就交接，不要尝试绕过。

## 4. 操作缓存、自愈、演示录制成技能（后端，照 Stagehand 移植）

**来源**：Stagehand（TypeScript，MIT）的缓存机制：第一次执行某个自然语言动作时记下解析出的选择器和动作；之后直接重放，不调用模型（每步 1–3 秒降到 0.15–0.3 秒）；选择器失效时等一下再试，还不行就让模型重新解析，成功后更新缓存；缓存按页面结构特征判断失效。参考 `browserbase/stagehand` 仓库的 cache 相关源码和 `docs.stagehand.dev` 的 caching 文档。豆包工作的「演示一次变技能」作为产品形态参考。

**做法**：
1. 浏览器动作缓存：键 = (站点, 页面结构特征, 动作描述)；值 = 元素引用和动作；存数据目录 `browser-cache/`。
2. **演示录制**：用户在内置浏览器面板里点「录制」，正常操作一遍（点击、填写、上传、翻页）；停止后 Atlas 把步骤整理成技能（SKILL.md + 步骤文件），参数化可变的部分（比如商品名、价格），用户确认后保存。
3. 运行技能时按步骤重放（走缓存，不调模型）；某步失败就让模型接手这一步，成功后更新步骤。
4. 接口：`POST /api/browser/recordings`（开始 / 停止）、`GET /api/browser/recordings/{id}`、`POST /api/browser/recordings/{id}/to-skill`。

## 5. 前端

1. **电脑操作**：`computer.foreground_required` 卡片（「这一步需要占用鼠标：<原因>」+ 允许 / 拒绝）；前台操作时的屏幕边缘提示条（Electron 透明置顶窗口，点不到）；任务结束后「回看操作」：按步骤看截图和动作。设置 → 电脑操作：驱动状态、诊断、视觉模型。
2. **浏览器**：设置 → 浏览器：四种模式、连接状态、「安装浏览器扩展」说明和配对码、凭据库管理（添加 / 删除登录、银行卡、地址；密码输入后不再显示）。
3. **交接**：`browser.handoff_required` 卡片：原因、「在浏览器面板打开」、「我弄好了，继续」（可附说明）、「做不了」；桌面通知「Atlas 需要你操作浏览器」。
4. **录制**：浏览器面板工具栏加「录制」按钮；录制中显示步骤列表；停止后弹出「存成技能」表单（名字、参数）。

## 6. 验收

| 项 | 最强的是 | Atlas 要做到 |
| --- | --- | --- |
| 电脑操作 | Claude 后台操作（只有 macOS）、Copilot Actions（隔离会话） | **Windows 后台操作、不抢鼠标**；必须前台时先征得同意；动鼠标就暂停；操作可回看 |
| 浏览器 | Claude in Chrome、Hermes | 四种模式；扩展；网页注入提示 |
| 登录 | Copilot Studio 凭据、Hermes 凭据库 | 密码不经过模型；验证码交还给人 |
| 缓存与录制 | Stagehand、豆包工作 | 演示一次 → 技能 → 不调模型重放 → 失败自愈 |

**真机**：第 1 节的真机场景；用复制的浏览器配置打开一个你已登录的网站；在需要登录的网站上用凭据库自动填密码；遇到验证码交还给你；录制一个三步操作存成技能并重放。

## 7. 交付

同 W06。

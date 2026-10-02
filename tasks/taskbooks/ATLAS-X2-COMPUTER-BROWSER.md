# ATLAS-X2：电脑与浏览器

> 取代 `ATLAS-W09-COMPUTER-BROWSER.md`（旧任务书仍可参考它列的来源和设计细节）。前提：C6R 验收通过。
> 先读：`docs/plan/ROADMAP-TO-PRODUCT.md`、`docs/plan/EXECUTION-GUIDE.md`、`docs/research/2026-09-30-landscape/01-computer-and-browser.md`、旧任务书 W09。
> 用户决定（2026-10-02）：外部功能先做 X2 和 X4，做完进入 O1「对标 Hermes 优化」。

## 本波目标

让 Atlas 能真正操作电脑和浏览器，而且达到「每天能用」的程度：
- Windows 上在后台操作，不抢鼠标；
- 用自己的浏览器配置，保留登录状态；
- 遇到登录或验证码交还给人；
- 密码不经过模型；
- 演示一遍，就能存成可以重放的技能。

**笔记本是 Atlas 自己的电脑**（用户决定），真机验收就在笔记本上做。

## 0. 先盘点（第一块，主控自己做）

列一张表：Hermes 内核里和电脑、浏览器有关的能力，对照 Atlas 现有的能力，标出哪个更强、准备怎么合并。写进结果文件。

- **Hermes 侧**：
  - `tools/computer_use/`：`tool.py`、`cua_backend*.py`、`vision_routing.py`、`doctor.py`、`permissions.py`；
  - `tools/browser_tool*.py`：cdp、session、snapshot、vision、lifecycle、install、origin、eval_policy、real_profile、lightpanda、camofox；
  - `tools/browser_supervisor*.py`、`browser_dialog_tool.py`、`browser_cdp_tool.py`；
  - `tools/browser_vault_tool.py`、`agent/vault_store.py`、`agent/vault_login_classifier.py`；
  - `tools/browser_extension_router.py`、`gateway/browser_control_broker.py`（如果存在）。
- **Atlas 侧**：
  - `core/atlas/tools/computer_use.py`（前台 UIA，用真鼠标）；
  - `core/atlas/capabilities/browser/browser_use.py`；
  - Playwright 和 chrome-devtools 两个 MCP；
  - 前端的浏览器面板（`<webview>`，分区 `persist:atlas-browser`）、元素点选、框选批注。

## 1. 后台电脑操作

- **主路径**：启用 Hermes 的 `computer_use`，后端用 cua-driver（看 `cua_backend*.py` 怎么安装和管理驱动，**锁定版本**）。
- **默认在后台操作**。只有驱动明确报「这一步后台做不了」时：
  1. 发事件 `computer.foreground_required {reason}`；
  2. 前端弹卡片，用户同意后才切到前台；
  3. 前台操作期间，屏幕边缘显示提示条；用户一动鼠标或键盘就暂停。
- Atlas 原有的工具名（`computer_observe/mouse/keyboard/window/clipboard`）保留，作为别名改走新实现；新增 Hermes 的「按元素编号点击」「执行后截图」两种用法。
- 主模型看不了图时，截图先交给视觉模型转成文字（Hermes `vision_routing.py`）。
- `GET /api/computer/status`：照 Hermes `doctor.py` 返回就绪状态、驱动版本、诊断信息。
- **操作留痕**：每一步存缩略图和动作，任务结束后可以按步骤回看。

## 2. 浏览器全套

- **主路径**：Hermes 的浏览器工具。无障碍树快照、元素用 `@eN` 引用、每个任务一个浏览器会话。
- **四种模式**，在设置 → 浏览器里选：
  1. Atlas 自带的独立浏览器；
  2. 复制用户的浏览器配置（`browser_tool_real_profile.py`：复制一份，不碰原配置）；
  3. 连接用户已经打开的浏览器（CDP）；
  4. 浏览器扩展。
- **和 Atlas 现有能力去重**：
  - Playwright 和 chrome-devtools 两个 MCP 默认不再暴露给模型，免得工具重复、白占上下文；用户可以手动打开；
  - browser-use 保留成「整段任务交给浏览器 Agent」的选项。
- **浏览器面板联动**：模型操作的是哪个页面，Atlas 的浏览器面板就能看到，用户可以随时接手。
- **选路规则**写进工具描述：有连接器、API 或 MCP 能做的，就不用浏览器；浏览器能做的，就不用屏幕点击。

## 3. 登录、验证码交还给人，密码不经过模型

- **凭据库**：用 Hermes 的 `browser_vault_*`。
  - 列表只返回句柄和元信息，**永远不返回密码**；
  - 填写时由后端直接把密码填进页面；
  - 凭据存在系统凭据库（keyring）里。
- **交还给人**：新工具 `browser_handoff {reason, url?}`。
  1. 运行进入等待，发事件 `browser.handoff_required`；
  2. 前端卡片上有三个按钮：「在浏览器面板打开」「我弄好了，继续」「做不了」；同时弹桌面通知；
  3. 用户处理完，任务从原处接着做。
- **不做**：凭据的安全审查和防注入设计，按约定由用户亲自负责。

## 4. 操作缓存，演示一遍存成技能

- **来源**：Stagehand（TypeScript，MIT）的动作缓存和自愈：第一次执行时记下选择器和动作，以后直接重放、不调模型；网站变了才让模型接手。还有 Grok Bot 的「录一遍屏就学会」。
- **做法**：
  1. **浏览器动作缓存**：键 =（站点，页面结构特征，动作描述），存在数据目录的 `browser-cache/` 下。
  2. **录制**：浏览器面板加一个「录制」按钮。用户操作一遍后，整理成技能（SKILL.md + 步骤文件），可变的地方参数化（比如搜索词、日期）。
  3. **运行技能时**：按步骤重放，走缓存不调模型；某一步失败，就让模型接手这一步，成功后更新这一步的记录。
  4. 接口：`POST /api/browser/recordings`（开始、停止）、`GET /api/browser/recordings/{id}`、`POST /api/browser/recordings/{id}/to-skill`。
  5. 生成的技能进入 C4 合并后的技能体系。

## 5. 前端

- 电脑操作：前台确认卡片、屏幕边缘提示条（Electron 透明置顶窗口，鼠标点不到）、操作回放。
- 设置 → 浏览器：四种模式、连接状态、凭据库管理（添加、删除；密码输入后不再显示）。
- 交还给人的卡片；录制按钮和录制中的步骤列表；「存成技能」表单。
- 界面要美观，放不下的做成可折叠的；四项前端检查；无头 Edge 截图。

## 6. 测试和验收

- **假模型和假驱动测试**：后台和前台切换、动鼠标就暂停、凭据永远不出现在工具结果和日志里、交还给人后继续、缓存命中不调模型、失败一步后自愈。
- **真机验收**（在笔记本上做，**开始前先问用户**，用用户指定的模型）：
  1. 「打开记事本写一段话存到桌面」，同时用户在用别的程序，确认鼠标和键盘没被抢；
  2. 用复制的浏览器配置打开一个已登录的网站，完成一个三步操作；
  3. 遇到验证码时交还给人；
  4. 录制一个三步操作，存成技能，再重放一次，确认不调模型；
  5. 改一下页面，触发自愈。

  每一项记下结果、截图和耗时。
- 更新 CORE-PARITY：新开「外部功能」一节，写 X2 的各行；同步 PARITY（F138–F141 等）。

## 7. 交付

- 结果文件 `tasks/results/ATLAS-X2-COMPUTER-BROWSER.result.md`：盘点表、每节做了什么、真机验收记录、全量测试汇总行。
- 每个修复一个提交；改了 fork 的，先推 fork 再更新 Atlas 里的固定提交号。

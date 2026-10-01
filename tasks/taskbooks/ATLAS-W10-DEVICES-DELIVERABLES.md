# ATLAS-W10-DEVICES-DELIVERABLES（第十波：跨设备与产出物）

STATUS: READY（W08 交付后）
PROTOCOL: +1
先读：`docs/plan/SOURCE-MAP.md` I、J 节；`docs/research/2026-09-30-landscape/03-deliverables.md`、`08-interaction-and-surfaces.md`
主要来源：OpenClaw（设备配对、会话分享的设计）、Hermes（配对码安全参数、Agent 操作界面的工具、Office 技能、图像视频生成）、Univer（`dream-num/univer`，Apache-2.0，网页里编辑表格 / 文档 / 幻灯片）

## 本波目标

- **手机当窗口**（照 Claude Code Remote Control）：手机上看到的就是电脑上正在跑的会话，能发消息、批准、停止；**设备卡片**：笔记本和主机都在列表里，点哪台就在哪台开会话。
- **产出物能直接改**：生成的表格、文档、幻灯片在 Atlas 里打开就能编辑，也能选中一段让 Atlas 改（Claude Docs / Slides、豆包本地 Office 编辑）。
- **分享**：导出单文件网页、可撤销的只读链接。
- **Atlas 能指给你看**：在浏览器面板里标注元素、打开预览、切换窗格。

---

## 1. 局域网网页版 + 设备配对（后端，照 OpenClaw 移植 + 自己写）

**为什么不用 Hermes 的网页控制台**：它是把终端界面通过 PTY 嵌进网页，原生 Windows 上不可用；Atlas 前端本身就是网页，直接用它。

**来源**：O `extensions/device-pair`（配对码 + 二维码 + 待审批列表 + 清理未用的码）；H `gateway/pairing.py`（配对码安全参数：用 `secrets` 生成、去掉易混字符、限时、失败锁定、不写日志）。

**做法**：
1. 默认关闭。`GET/PUT /api/remote` → `{enabled, port, bind: "127.0.0.1"|"lan", url, devices: [{id, name, kind: "phone"|"atlas", paired_at, last_seen}]}`。开启 `lan` 时在指定端口（默认 8766）起**第二个监听**，只提供：前端构建产物（`frontend/dist`，找不到就返回说明页）+ 下面的 API 子集 + 运行 WebSocket。
2. 配对：`POST /api/remote/pairing`（桌面端调用，需现有 token）生成配对码（照 H：8 位、无歧义字母表、5 分钟有效、一次性）和二维码内容（`url + code`）；手机打开页面输入码或扫码 → `POST /remote/pair {code, device_name}` → 设置 `HttpOnly; SameSite=Strict` 会话 cookie（随机 32 字节，库里只存哈希）。连续 5 次错码锁定 10 分钟。`DELETE /api/remote/devices/{id}` 撤销。
3. OriginGuard：第二个监听上**只**认配对设备的 cookie，且 Origin 必须是该监听自己的地址；不认 `X-Atlas-Api-Token`，不开放 Vite 开发来源。8765 的规则完全不变。
4. 手机能用的 API：对话列表和消息、发起和停止运行、回答审批 / 提问 / 信任 / 交接、看改动列表、看产出物（只读）。不能：改设置、看密钥、Hooks、脚本工具、插件、MCP、连接器、文件原文下载、终端。
5. 手机发起的运行默认「改前问我」，会话标 `source: "remote"`。
6. **Atlas 之间互联（设备卡片）**：同样的配对流程，`kind: "atlas"`。配对后，笔记本的 Atlas 可以通过主机 Atlas 的第二监听调用「对话 / 运行」API：在主机上开会话、看主机上正在跑的任务。笔记本前端的侧栏顶部显示设备卡片（本机、主机），点哪台就把对话开在哪台。互联请求也只走第二监听、只认配对凭据。
7. 不在同一局域网时：**推荐 Tailscale**（BSD-3，用户自己装），设置页检测到 Tailscale 地址就显示出来；不自建中转。

**测试**：未配对拒绝、错码锁定、配对后可用、撤销后失效、子集外接口拒绝、token 头在第二监听无效、Origin 不符拒绝、Atlas 互联只能调允许的接口。

## 2. 分享：导出网页 + 只读链接（后端）

1. **导出单文件网页**（自己写）：`GET /api/conversations/{id}/export?format=html`：内联样式（跟随系统深浅色），用户消息、Atlas 回复（Markdown 渲染，代码块保留语言）、每轮的步骤摘要、产物列表；页脚写导出时间和「由 Atlas 导出」。**不能带脚本**：不允许 `<script>`、事件属性、`javascript:` 链接，Markdown 里的原始 HTML 一律转义；响应头 `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; img-src data:`、`Content-Disposition: attachment`。可选 `redact=true`：用户目录换成 `~`，看起来像密钥的值（`sk-`、`ghp_`、`Bearer ` 等）隐去。
2. **只读分享链接**（照 O `extensions/session-share` 的设计）：`POST /api/conversations/{id}/share` → `{share_id, url}`；在第二监听上提供 `/s/{share_id}`（只读网页，同样的无脚本规则）；可设过期；`DELETE` 撤销后立即失效。只有用户明确分享的对话可见。
3. 测试：XSS 载荷（`<script>`、`<img onerror>`、`javascript:`）全部被转义；redact 生效；撤销后 404。

## 3. Atlas 能操作自己的界面（后端从 H 搬 + 前端）

**来源**：H `desktop_ui` 工具集：`tools/preview_tool.py`（预览窗格的打开 / 关闭 / 读取合并成一个工具，省 token）、`annotate_preview_tool.py`（在内置浏览器里给元素加持续的标注框，跟着元素滚动）、`drive_preview`（一次性高亮）、`apply_layout_tool.py`（切换布局）、`focus_pane_tool.py`、`read_terminal_tool.py`、`read_window_tool.py`。

**做法**：搬这组工具，只在桌面端会话里提供；工具调用通过新事件 `ui.request {event_id, action, args}` 交给前端执行，前端用 WS `{type: "ui.respond", run_id, event_id, result}` 回复（照 H 的 `preview.act` 桥）。动作：打开网址到浏览器面板、读取当前页面、标注元素（选择器或文字）、清除标注、切换检查器标签页、读终端最后 N 行。

## 4. 产出物可以直接改（前端为主，依赖 Univer）

**来源**：Univer（`dream-num/univer`，TypeScript，Apache-2.0，定位是「给 AI Agent 用的 Office 底座」：表格、文档、幻灯片、画布、PDF）；H `skills/productivity/{docx,powerpoint,xlsx,pdf}`（Office 技能，对照补强 Atlas 现有的 `create_document / create_spreadsheet / create_presentation`）。

**做法**：
1. 前端集成 Univer：文件面板里打开 `.xlsx`、`.docx`（`.pptx` 看 Univer 当前支持程度，不支持就只预览）时，用 Univer 编辑器替代现在的只读预览。保存时写回原文件格式（**导出保真度要实测**：用 Atlas 生成的文件和用户真实文件各测几份，结果写进结果文件）。
2. **选中让 Atlas 改**：编辑器里选中单元格区域 / 段落，右键「让 Atlas 改」→ 输入要求 → 发起一轮，带上文件路径和选区；Atlas 用 Office 工具改完，编辑器重新加载并高亮改动。
3. 后端：对照 H 的 Office 技能补强 Atlas 的生成工具（样式、表格、图表、幻灯片版式）；新增「幻灯片版式检查」：生成后把每页渲染成图片（LibreOffice 无头模式，有就用；没有就跳过并提示），检查文字溢出和重叠，有问题让模型修一次。
4. 图像 / 视频生成：搬 H `plugins/image_gen`、`plugins/video_gen`、`tools/image_generation_tool.py` 的服务商接入（按用户配置的服务商启用）。

## 5. 本地发布的自动刷新仪表盘（后端，自己写）

- Atlas 生成的网页应用（HTML 产物）可以「发布」：`POST /api/publish {path, name}` → 在第二监听上提供 `/p/{name}/`（沙箱 CSP，可以有脚本但不能访问 Atlas API）。
- 可以绑定一个定时或事件触发器（W08），重新生成数据文件，页面自动刷新（页面里轮询自己目录下的 `data.json`）。
- 这是 ChatGPT Sites 的本地版，不依赖云。

## 6. 前端

1. **手机网页版**：同一份前端在窄屏下的布局（对话列表 → 对话 → 审批卡片），隐藏手机不能用的功能；首次打开显示配对页（输入码）。
2. **设置 → 手机与设备**：开关、端口、局域网地址、二维码（`qrcode` 库）、已配对设备列表和撤销、Tailscale 检测结果。
3. **设备卡片**：侧栏顶部「本机 / 主机 …」切换；在别的设备上的对话标出设备名。
4. **分享**：对话菜单「导出为网页」「创建分享链接」（显示链接、过期时间、撤销）。
5. **界面操作**：处理 `ui.request`（打开网址、读页面、标注、切换标签页、读终端），浏览器面板的标注覆盖层。
6. **Univer 编辑器**：见第 4 节。
7. **发布**：HTML 产物的「发布」按钮、已发布列表。

## 7. 验收

| 项 | 最强的是 | Atlas 要做到 |
| --- | --- | --- |
| 手机 | Claude Code Remote Control（手机是电脑上会话的窗口、设备卡片） | 同样体验，局域网直连 + 二维码配对；**额外：两台 Atlas 互联** |
| 产出物 | Claude Docs / Slides、豆包本地 Office 编辑、ChatGPT Sites | Univer 直接编辑 + 选中让 Atlas 改 + 本地发布的自动刷新仪表盘 |
| 分享 | Claude Docs 链接、OpenClaw 可撤销只读链接 | 单文件网页 + 可撤销链接，无脚本 |
| 界面操作 | Hermes 桌面端 `desktop_ui` | Atlas 能打开、标注、切换，指给你看 |

**真机**：手机扫码配对后，在手机上看电脑正在跑的任务并批准一步；笔记本上点「主机」卡片在主机上开一个会话；生成一个表格后在 Univer 里改一格并让 Atlas 改一列；发布一个仪表盘并绑定每小时刷新；让 Atlas「在这个页面上指出登录按钮在哪」。

## 8. 交付

同 W06。

# ATLAS-X：外部功能阶段（X1–X6）

> 前提：T1 和 T1F 完成，主体在实测里不输。
> 这一阶段把冻结的外部功能逐项解冻。**原来的任务书（W08–W13）是按旧内核写的**，所以每一波都分两步：
> 1. **重写任务书**：Sol 主控先对照 Hermes 内核里已经有的东西，把对应的旧任务书改写成 `tasks/taskbooks/ATLAS-Xn-*.md`。这一步只写任务书、不写代码，写完提交，**用户看过再继续**。
> 2. **施工和验收**：照常用 Sol 主控 + 独立验收。

## 一、通用规则（每一波都适用）

1. **先查 Hermes 有没有**：Hermes 内核里已经有大量外部能力，见下表。有的话，优先接通 Hermes 的实现，再看还差什么、别家（OpenClaw、cua、Stagehand 等）哪里更强。
2. 旧任务书里的「从 H 搬」，现在多半变成「在 fork 里启用并接到 Atlas 的界面和事件上」，工作量会小很多。
3. 安全审查依旧由用户亲自做；不要沙箱；不做视频生成。
4. 每波都要在 CORE-PARITY 里新开一节「外部功能」，逐行写谁最强、从哪里拿、Atlas 现状，照主体部分的格式。
5. 每波都要用真实场景验收一次（用户的账号和设备，要用户配合），因为外部功能用假服务测不出真实问题。验收前先问用户可不可以。

## 二、各波内容

### X1：连接外部世界（原 W08，`ATLAS-W08-CONNECT-WORLD.md`）

| 内容 | Hermes 现有 | 还要做 |
| --- | --- | --- |
| MCP 新规范：HTTP、OAuth、Tasks | `tools/mcp_tool*.py`、`mcp_oauth*.py`（C1 已接入客户端） | 远端 HTTP 和 OAuth 的真实服务验收；设置页接入授权流程 |
| MCP Apps（对话里的交互界面） | 没有 | 照旧任务书，依赖 MCP 官方的 ext-apps SDK |
| 连接器目录（国内优先） | `tools/connectors/`（目录、账号、授权）、`optional-mcps/`、`plugin-catalog/` | 补国内条目：飞书文档、钉钉、企业微信、语雀、腾讯文档等；做目录页 |
| 聊天渠道：飞书、钉钉、邮件、企业微信 | `plugins/platforms/`：feishu、dingtalk、email、wecom、telegram、slack 等二十多个；`gateway/` | 接通 Hermes 的网关；Atlas 现有的 Telegram 渠道改成走 Hermes 的；设置页统一管理 |
| 触发器：Webhook、新邮件、条件触发、网页监控 | `gateway/platforms/webhook*.py`；`cron/`（有 monitor 模式：没有变化时不调用模型） | 和 Atlas 的调度器（`core/atlas/scheduler`）合成一套，前端用 Atlas 的自动化页 |

### X2：电脑与浏览器（原 W09，`ATLAS-W09-COMPUTER-BROWSER.md`）

| 内容 | Hermes 现有 | 还要做 |
| --- | --- | --- |
| 后台电脑操作（不抢鼠标） | `tools/computer_use/`（cua 后端：驱动、截图、输入、守护进程） | 和 Atlas 现有的 UIA/CUA 操作（`core/atlas/tools/computer_use.py`）比较，择优合一；在 Windows 上真机验收 |
| 浏览器全套 | `tools/browser_tool*.py`（CDP、快照、视觉、对话框、真实配置、camofox、lightpanda） | 接到 Atlas 的浏览器面板；和现有的 Playwright / chrome-devtools MCP 去重 |
| 模型看不见的密码自动填写 | `tools/browser_vault_tool.py`、`agent/vault_*` | 接系统凭据库；设置页管理 |
| 登录和验证码交还给人 | 旧任务书 | 照旧任务书；配合浏览器面板 |
| 操作缓存、演示录制成技能 | 没有（Stagehand 的思路） | 照旧任务书，参考 Stagehand v3 的源码 |

### X3：跨设备与产出物（原 W10，`ATLAS-W10-DEVICES-DELIVERABLES.md`）

| 内容 | Hermes 现有 | 还要做 |
| --- | --- | --- |
| 局域网网页版和扫码配对 | `web/`（仪表盘前端）、`tui_gateway/hosted_room_*`、`gateway/platforms/api_server*.py` | 用 Atlas 自己的前端做网页版（同一套 React 代码），配对和凭据照 OpenClaw 的设计；必须过 OriginGuard |
| 主机和笔记本两台 Atlas 互联 | `plugins/platforms/a2a` | 设备卡片；任务交给另一台机器去跑 |
| 导出网页、只读分享链接 | 旧任务书 | 照旧任务书 |
| Atlas 操作自己的界面 | `tools/desktop_ui.py`、`focus_pane_tool.py`、`read_window_tool.py`、`preview_tool.py` 等 | 接到 Atlas 的 Electron 界面 |
| 产出物直接编辑（Univer）、自动刷新的仪表盘 | 没有 | 照旧任务书 |

### X4：技能市场（原 W11 第 3 节）

| 内容 | Hermes 现有 | 还要做 |
| --- | --- | --- |
| 技能市场 | `tools/skills_hub*.py`（clawhub、GitHub、skills.sh、官方源）、`skills_sync*.py` | 接到 C4 合并后的技能体系；前端做市场页。安装前的安全扫描由用户负责 |

### X5：自我进化（原 W12，`ATLAS-W12-SELF-EVOLUTION.md`）

| 内容 | Hermes 现有 | 还要做 |
| --- | --- | --- |
| 跟踪上游代码 | 没有 | Atlas 自己定期 `git fetch` Hermes 上游和其他参考仓库，看已搬入文件的变化，生成「建议合并」的报告和任务书草稿，用户批准后执行（照 ROADMAP 第七节的手动流程做成自动） |
| 跟踪各家产品动态 | 没有 | 按 `docs/research/2026-09-30-landscape/10-tracking-sources.md` 的信息源，定期抓取和总结，对照 CORE-PARITY 生成「新增行」的建议 |
| 技能自学 | `agent/curator.py`、`learn_prompt.py`、`background_review.py`、`skill_manager_tool.py` | 接通；用户确认后才保存成技能。安全阀由用户负责 |

### X6：补全（原 W13，`ATLAS-W13-COMPLETION.md`）

| 内容 | Hermes 现有 | 还要做 |
| --- | --- | --- |
| 语音：说话输入、边说边干、朗读 | `tools/voice_mode.py`、`voice_live.py`、`wake_word*.py`、`tts_*`、`transcription_*`；Atlas W06 已有 sherpa-onnx 后端 | 前端接入；本地优先 |
| 统一入口（自动判断是聊天还是干活） | 旧任务书 | 照旧任务书 |
| 远程子 Agent（A2A，主机和笔记本） | `plugins/platforms/a2a` | 和 X3 的设备互联一起做 |
| 群聊接任务、多人协作 | Hermes Bot Mode、bot 之间互发消息 | 只做用户自己用得上的部分 |
| 图像和音频创作 | `tools/image_generation*.py`、`tts_*` | 接入；不做视频 |
| 命令行无界面运行（F210）、共享状态（F201） | Hermes 的 CLI 和 TUI | Atlas 的 `cli.py` 改成走新内核，和桌面端共用同一个后端 |

### X7：常驻个人 Agent（2026-10-02 用户决定：主体能用后，把这一类全部抄过来）

对标对象（都是 2026 年 5–9 月的新品，做之前按当月资料重查一遍）：OpenAI **dots**（9-29）、Meta **Muse**（9-08）、xAI **Grok Bot**（8-11）、Google **Gemini Spark**（5-19，后续更新）、Microsoft **Autopilot**（原 Scout）、Manus **Cue**、Perplexity **Computer**、Claude Cowork 的云端定时任务和后台电脑操作。

**Atlas 自己的电脑**：用户的**笔记本**专门给 Atlas 用，作为它常驻的「自己的电脑」，相当于各家的云端虚拟机。主机是用户日常工作和开发的机器，通过 X3 的设备互联、聊天渠道、手机给笔记本上的 Atlas 派活。笔记本上的 Atlas 用安装包版（R1 之后）或固定的开发版常驻运行，开机自启、断线自动重连。

| 要抄的能力 | 最强的是谁 | 说明 |
| --- | --- | --- |
| 一直在线，追长期目标，关掉界面也接着干 | dots、Spark、Grok Bot | 接 Atlas 现有的后台常驻（Hub）和 Goal；笔记本当执行机 |
| 三档自主权：自己办 / 要批准 / 禁止 | dots | 按事情的类别（花钱、发消息、删东西、对外发布……）设定，和权限档位并存 |
| 多渠道派活：IM、邮件、电话 | dots（能打电话）、Spark（有专属 Gmail 地址）、Muse（WhatsApp）、Cue（有自己的邮箱和电话） | 给 Atlas 一个专属邮箱（X1 的邮件渠道）；国内 IM 走 X1；语音通话走 X6 |
| 录一遍屏就学会 | Grok Bot（录屏 → 可以重复执行的技能，带决策逻辑和审批阈值） | 和 X2 的「演示录制成技能」合并 |
| 多个 Agent 拉群协作 | Grok Bot（2–6 个 Bot 互发消息、交接任务，各有角色记忆）、Hermes Bot Mode | 和 X6 的「群聊接任务」合并 |
| 用你自己的浏览器和已登录的账号 | Spark（Chrome）、Muse（自带浏览器） | 和 X2 合并：用笔记本上专给 Atlas 的浏览器配置 |
| 技能可以叠加，可以带参考文件 | Gemini Skills（9-30） | 补进 C4 合并后的技能体系 |
| 接很多应用 | dots（4000 多个）、Muse（六大类生活服务） | 和 X1 的连接器目录合并，国内优先 |
| 主动性：盯着事情变化，自己提醒或者自己去办 | Autopilot（盯频道、跟进讨论、准备会议）、dots | 接 X1 的触发器和监控 |
| 凭据保护：模型只拿替身令牌，出口再填真凭据；验证码和重置链接对模型不可见；花钱必须人确认 | Muse 的 Sentinel 设计 | **属于安全设计，按约定由用户亲自决定做不做、怎么做**；这里只登记，不施工 |

顺序：放在 X1–X6 之后，或者和对应的那一波合并着做（表里写了合并到哪一波）。开工前同样先写任务书，写清每项「对方怎么做的」和出处，用户看过再施工。

## 三、顺序

X1 → X2 → X3 → X4 → X5 → X6 → X7（X7 有不少项可以并进前面对应的波次）。如果用户更急着要某一项，可以调整顺序，但 X5 最好放在 X4 之后，因为技能自学要用到技能体系。

## 四、阶段验收

六波都做完以后，跑一次精简版的 T1：只跑和外部功能有关的新任务，比如「收到一封邮件后自动整理成飞书文档」「从手机给主机派一个活」，确认这些功能真的能用。

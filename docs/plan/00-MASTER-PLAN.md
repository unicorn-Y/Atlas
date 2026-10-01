# Atlas 总计划书（2026-10 起）

写给任何接手的 Agent（Claude、Codex 或其他）和用户本人。阅读顺序：
1. 本文件
2. [SOURCE-MAP.md](SOURCE-MAP.md)：每个能力从哪个开源仓库的哪个文件拿代码
3. [EXECUTION-GUIDE.md](EXECUTION-GUIDE.md)：环境、命令、规则、审查清单
4. 然后按顺序执行 `tasks/taskbooks/ATLAS-W06…W12-*.md`

调研依据：`docs/research/2026-09-30-landscape/`（2026-09-30，40 多个产品、9 个能力专题，都有出处）。

---

## 一、用户要什么（原话整理）

1. **全能 Agent**，全部功能都要，越多越好；主要给自己用。
2. **每个功能都要当下最新、最好的做法**，「对标每个 agent……像把它彻底吃掉，各种细节都比它强」。
3. **有现成代码就拿过来改**（GitHub 上的开源项目），不要从零写——做 Atlas 就是为了省开发时间。
4. **持续进化**：以后 Atlas 自己跟踪各家更新、自己补上（第 12 波做成 Atlas 的功能；用户明确说不要另外建定时任务）。

## 二、路线：移植（用户 2026-09-30 拍板）

保留 Atlas 现有的后端（Python / FastAPI）和前端（Electron / React / Tailwind v4），**从最强的开源项目里逐块搬代码改**。

- **首选来源是 Hermes Agent**（`NousResearch/hermes-agent`）：Python + React 19 / Tailwind 4 / Electron，技术栈和 Atlas 一样；MIT 许可；约 25 万星；每天都有大量提交；几乎覆盖 Atlas 规划里的所有能力（提示缓存、智能审批、工具按需加载、子 Agent、MCP OAuth、连接器、20 多个聊天渠道、30 多个模型服务商、cua 后台电脑操作、浏览器、本地语音、技能市场、看板、定时任务……）。
- **第二来源是 OpenClaw**（TypeScript、MIT、约 39 万星）：自动化（入站 Webhook、IMAP、条件触发）、记忆、设备配对、会话分享的设计最完整，照逻辑移植成 Python。
- 其他：cua（Windows 后台电脑操作驱动）、sherpa-onnx（本地语音）、Stagehand（浏览器操作缓存）、MCP 官方 ext-apps（对话里的交互界面）、Codex / OpenCode / OpenHands / Gemini CLI（各自的强项）。完整清单见 SOURCE-MAP。
- 只有找不到能用的实现时才自己写。

## 三、已定的决定（不要推翻）

| 决定 | 含义 |
| --- | --- |
| FULL_ACCESS 是默认 | 不做逐工具弹窗；安全靠「智能审批（只在危险操作时介入）+ 检查点」 |
| 记忆系统冻结 | 不扩展记忆功能；只做安全相关的小改动（外部内容不进长期记忆） |
| 外部 Agent（ACP 认证）先跳过 | |
| 调度器已合并 | 定时和事件触发都走 `core/atlas/scheduler` |
| 所有 HTTP / WS 过 OriginGuard | 只能加新的受信方式，不能放宽 |
| 中文 | 界面、提示、回复用中文；代码和提交信息可以英文 |
| 走移植路线 | 不用 Hermes 整体替换 Atlas 后端 |

## 四、七波路线

| 波 | 主题 | 主要搬什么 | 依赖 |
| --- | --- | --- | --- |
| **W06** | 地基与安全 | 第五波遗留；H 提示缓存、工具输出上限、用量计价、模型失败切换与限流冷却；H 危险命令识别 + 智能审批 + 威胁模式扫描（加 Atlas 检查点兜底）；H 停止前校验；外部内容不进长期记忆；**前端**：sherpa-onnx 本地语音 | 无 |
| **W07** | 子 Agent 与编排 | H 委派（后台、进度、结果、worktree）；子 Agent 定义文件（兼容 Claude Code / OpenCode / Codex / Copilot）；6 种内置类型；并行验收；H 看板与待办；H 多模型会诊；快 / 强模型；项目记事本 | W06 智能审批（子 Agent 也要过审） |
| **W08** | 连接外部世界 | H MCP 客户端（HTTP、OAuth、健康、采样）；MCP Apps（前端）；H 连接器目录 + 国内 MCP 清单；H 聊天渠道（飞书、钉钉、企业微信、邮件）；O 入站 Webhook、IMAP、条件触发 | W06 威胁扫描（外部事件内容不可信） |
| **W09** | 电脑与浏览器 | cua 驱动 + H 电脑操作接入（后台、不抢鼠标）；H 浏览器工具全套（CDP、真实配置、凭据库、对话框）；浏览器交接；Stagehand 式操作缓存与自愈；演示录制成技能 | W06 |
| **W10** | 跨设备与产出物 | H 网页控制台 + 中转 + 配对（手机当窗口、设备卡片）；O 会话分享；H 产物预览工具；H Office 技能对照补强；图像 / 视频生成 | W08 |
| **W11** | 效率、编程、技能 | H 工具按需加载；H 上下文压缩（微压缩、归档）；H 技能市场（skills.sh、ClawHub、GitHub）+ 技能安全扫描；H 模型服务商插件（国内全套）；H LSP；依赖漏洞检查；PR 审查视图 | W08 |
| **W12** | 自我进化 | 跟踪已搬代码的上游更新（`VENDORED.md` 里登记的每个文件）+ 跟踪各家产品动态 → 自动生成「可以搬的新东西」清单和任务书草稿；技能自学（H 后台复盘 + 安全扫描） | W11 |

**以后再说**：记忆透明化（要解冻记忆）、多人协作、视频和游戏制作、远程子 Agent（A2A）。

## 五、每一项的验收：「比最强的那家好」

1. 来源项目做到的细节，Atlas 全部做到（搬过来的代码带上它的测试）。
2. 再加至少一个它没有的点（通常来自 Atlas 的条件：检查点兜底、两台电脑、国内服务、可视化界面）。
3. 用真实模型、真实场景跑一次，记录结果。

## 六、谁来做

- 用户的默认分工：前端 Claude，后端交给主机上的 Codex（省配额）。
- 配额不够时，任何 Agent 都可以接手整波。任务书按「后端 / 前端 / 验收」分节，可以拆给不同的 Agent。
- 做后端的不改 `frontend/`、`backend-adapter/`；做前端的不改 `core/`，除非任务书明确写了。
- 每波交付后按 EXECUTION-GUIDE 第五节审查。

## 七、协议版本

后端运行事件协议现在是 1.7，W06 → 1.8，之后每波加 1。新事件和字段只增不改。

## 八、文件索引

| 文件 | 内容 |
| --- | --- |
| `docs/plan/00-MASTER-PLAN.md` | 本文件 |
| `docs/plan/SOURCE-MAP.md` | 能力 → 开源代码来源 |
| `docs/plan/EXECUTION-GUIDE.md` | 环境、命令、规则、搬代码的方法、审查清单 |
| `docs/plan/VENDORED.md` | 已搬进来的代码登记（来源、提交号、许可证、改动） |
| `tasks/taskbooks/ATLAS-W06-FOUNDATION-SAFETY.md` … `ATLAS-W12-SELF-EVOLUTION.md` | 各波任务书 |
| `docs/research/2026-09-30-landscape/` | 调研依据 |
| `docs/PARITY.md` | F001–F210 对标表（每波做完更新） |
| `tasks/HANDOFF.md` | 用户这台笔记本 + 主机的操作细节 |

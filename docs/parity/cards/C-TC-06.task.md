你是施工者。任务：Atlas 功能对标任务卡 C-TC-06（渠道、Browser 和远程服务），一次做完。

背景：Atlas 是 Electron + React 前端、Python 后端的桌面 AI Agent。这张卡来自「剩余工作总账」（仓库 docs/parity/LEDGER.md），列的是对标 ZCode / OpenCode / Codex / Claude Code 后 Atlas 还缺或只做了一部分的功能。

规矩：
1. 建工作树，不要改 D:\Atlas（用户在用），不碰别的 D:\atlas-* 目录：
   git -C D:\Atlas fetch origin
   git -C D:\Atlas worktree add D:\atlas-card-c-tc-06 -b card-c-tc-06 origin/memory-v1
2. 每条先确认 Atlas 现在实际怎样（读代码，不要只信表格），再照上游做：ZCode（github.com/zai-org/ZCode，界面在 packages/ui、packages/desktop）和 OpenCode（github.com/anomalyco/opencode，packages/app、packages/core）开源就读源码移植，文件头写 `// Ported from owner/repo@<sha>: <path> (License)`；Codex / Claude Code 照官方文档行为做。THIRD_PARTY_NOTICES.md 只追加。
3. 缺后端接口或 Electron 主进程能力就自己补，放新文件优先；共享文件（App.tsx、store/useAtlasStore.ts、core/atlas/server.py、core/atlas/api/application.py、config/atlas.example.toml）只做追加式小改动。
4. 真做不了的条目写清原因，不许做假按钮、假数据。
5. 不写测试、不跑测试套件。只确认：后端能启动（cd core 后 `set ATLAS_UPSTREAM_AUTO=0` 再 `python -m uvicorn atlas.server:app --port 28796`，/api/health 返回 ok 后关掉）；`npm --prefix frontend run build` 通过。
6. 只读需要的文件和代码段，不要整份读大文件（省额度）。
7. 完成后 git add -A、git commit、git push origin card-c-tc-06。在 docs/parity/cards/C-TC-06.md 写结果：每条编号做了什么 / 没做的原因，以及提交号。不要推 memory-v1。

## 本卡条目

- **C040 Agent 消息平台 gateway、平台策略、平台 toolset 和定时任务投递**〔部分｜P1｜L〕缺：已有 channels registry 和策略 API，缺部分渠道真实适配器及完整投递/配置表单。  抄：[Hermes messaging](https://github.com/NousResearch/hermes-agent/blob/66605471e9f0b0832abbefaf625ce08e948ca540/website/docs/user-guide/messaging/index.md), [OpenClaw channels](https://docs.openclaw.ai/channels), [Hermes cron delivery](https://github.com/NousResearch/hermes-agent/blob/66605471e9f0b0832abbefaf625ce08e948ca540/website/docs/user-guide/features/cron.md)  Atlas 位置：待定
- **C044 远端反馈/诊断中心、附件截图、工单跟踪与补充材料**〔部分｜P1｜S〕缺：诊断报告可复制，缺远端反馈附件与工单跟踪服务。  抄：ZCode `packages/ui/src/feedback/{FeedbackCenter,FeedbackSubmitForm,TicketDetail}.tsx`; Codex [troubleshooting](https://learn.chatgpt.com/docs/reference/troubleshooting); Claude [feedback](https://code.claude.com/docs/en/commands)  Atlas 位置：待定
- **C067 浏览器控制开关、Chrome profile/cookie/localStorage 导入、清理**〔没做｜P1｜M〕缺：有 Browser 面板，缺 Chrome profile/cookie/localStorage 导入与站点数据清理 API。  抄：V5 VIII-A BrowserSettingsSection（U）；ZCode settings 文案  Atlas 位置：待定
- **C083 Home session 跨消息渠道汇聚与 dock**〔没做｜P1｜M〕缺：缺跨渠道 DM 适配、长期会话路由和页面上下文快照注入  抄：OpenClaw `docs/concepts/main-session.md`  Atlas 位置：待定
- **C084 常驻 Bot 名册及群聊协作**〔没做｜P1｜L〕缺：缺 Bot profile/长期聊天、名册分组和 Bot 间 @ 消息路由  抄：Hermes `website/docs/user-guide/bot-mode.md`  Atlas 位置：待定
- **C089 Claude Preview Server 多配置**〔没做｜P1｜M〕缺：缺 Preview Server 多 profile 配置、切换和状态显示  抄：[H](https://code.claude.com/docs/en/desktop)  Atlas 位置：待定

## 总账里这张卡的说明
### C-TC-06｜渠道、Browser 和远程服务（6 条）

- **包含编号：** C040, C044, C067, C083, C084, C089
- **Atlas 拟修改文件/目录：** **待定**
- **要读的上游文件/文档：**
  - [Hermes messaging](https://github.com/NousResearch/hermes-agent/blob/66605471e9f0b0832abbefaf625ce08e948ca540/website/docs/user-guide/messaging/index.md), [OpenClaw channels](https://docs.openclaw.ai/channels), [Hermes cron delivery](https://github.com/NousResearch/hermes-agent/blob/66605471e9f0b0832abbefaf625ce08e948ca540/website/docs/user-guide/features/cron.md)
  - ZCode `packages/ui/src/feedback/{FeedbackCenter,FeedbackSubmitForm,TicketDetail}.tsx`; Codex [troubleshooting](https://learn.chatgpt.com/docs/reference/troubleshooting); Claude [feedback](https://code.claude.com/docs/en/commands)
  - V5 VIII-A BrowserSettingsSection（U）；ZCode settings 文案
  - OpenClaw `docs/concepts/main-session.md`
  - Hermes `website/docs/user-guide/bot-mode.md`
  - [H](https://code.claude.com/docs/en/desktop)
- **派工顺序：** Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。

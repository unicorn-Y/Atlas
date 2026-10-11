你是施工者。任务：Atlas 功能对标任务卡 B-TC-05（Composer：模型、附件与上下文），一次做完。

背景：Atlas 是 Electron + React 前端、Python 后端的桌面 AI Agent。这张卡来自「剩余工作总账」（仓库 docs/parity/LEDGER.md），列的是对标 ZCode / OpenCode / Codex / Claude Code 后 Atlas 还缺或只做了一部分的功能。

规矩：
1. 建工作树，不要改 D:\Atlas（用户在用），不碰别的 D:\atlas-* 目录：
   git -C D:\Atlas fetch origin
   git -C D:\Atlas worktree add D:\atlas-card-b-tc-05 -b card-b-tc-05 origin/memory-v1
2. 每条先确认 Atlas 现在实际怎样（读代码，不要只信表格），再照上游做：ZCode（github.com/zai-org/ZCode，界面在 packages/ui、packages/desktop）和 OpenCode（github.com/anomalyco/opencode，packages/app、packages/core）开源就读源码移植，文件头写 `// Ported from owner/repo@<sha>: <path> (License)`；Codex / Claude Code 照官方文档行为做。THIRD_PARTY_NOTICES.md 只追加。
3. 缺后端接口或 Electron 主进程能力就自己补，放新文件优先；共享文件（App.tsx、store/useAtlasStore.ts、core/atlas/server.py、core/atlas/api/application.py、config/atlas.example.toml）只做追加式小改动。
4. 真做不了的条目写清原因，不许做假按钮、假数据。
5. 不写测试、不跑测试套件。只确认：后端能启动（cd core 后 `set ATLAS_UPSTREAM_AUTO=0` 再 `python -m uvicorn atlas.server:app --port 28795`，/api/health 返回 ok 后关掉）；`npm --prefix frontend run build` 通过。
6. 只读需要的文件和代码段，不要整份读大文件（省额度）。
7. 完成后 git add -A、git commit、git push origin card-b-tc-05。在 docs/parity/cards/B-TC-05.md 写结果：每条编号做了什么 / 没做的原因，以及提交号。不要推 memory-v1。

## 本卡条目

- **B027 Composer 模型、模式、推理档位与上下文用量**〔部分｜P0｜M〕缺：模式/推理档位只能接 Atlas 真实模型 API，尚未覆盖上游所有切换项。  抄：ZCode `packages/ui/src/v4/composer/V4ComposerToolbar.tsx`、`ModelConfigSelect.tsx`、`ChatModeSwitchControl.tsx`、`ThoughtLevelCycleControl.tsx`；OpenCode composer; Codex [models](https://learn.chatgpt.com/docs/model-selection)；Claude [model config](https://code.claude.com/docs/en/model-config)  Atlas 位置：待定
- **B028 Composer 附件：选择、粘贴、拖放、进度、失败重试、移除**〔部分｜P0｜M〕缺：附件基础交互已具备，缺上传进度和失败重试的完整 API/界面状态。  抄：ZCode `packages/ui/src/v4/composer/{useComposerAttachments.ts,attachmentUpload.ts,conversationDropTarget.ts}`；OpenCode session composer；Codex [image inputs](https://learn.chatgpt.com/docs/app)；Claude [desktop](https://code.claude.com/docs/en/desktop)  Atlas 位置：Composer.tsx；DrawingPad.tsx；App.tsx
- **B030 `@` 文件与会话引用、文件树拖入引用**〔部分｜P0｜M〕缺：@ 文件/mention 已按会话隔离，但 $skill 结构化引用未完成（另见 B031）。  抄：ZCode `packages/ui/src/mentions/providers/{fileMentionProvider.ts,sessionsMentionProvider.ts}`；OpenCode composer suggestions；Codex [prompting](https://learn.chatgpt.com/docs/prompting)；Claude [interactive mode](https://code.claude.com/docs/en/interactive-mode)  Atlas 位置：Composer.tsx；App.tsx
- **B031 `$skill` 消息级结构化引用（区别于全局 active skill 开关）**〔没做｜P0｜L〕缺：缺消息级 $skill 结构化引用、提交协议传递及与全局 active skill 的区分。  抄：ZCode 固定 SHA `aac4755666d09fdcd70272fcf063c077a639015f`：`packages/ui/src/mentions/providers/skillsMentionProvider.ts`、`packages/ui/src/mentions/mentionMarkdown.ts`；Codex [skills](https://learn.chatgpt.com/docs/build-skills)；Claude [skills](https://code.claude.com/docs/en/skills)  Atlas 位置：待定
- **B034 Codex `/fast` / fast mode**〔没做｜P1｜M〕缺：无 Atlas provider 能力可执行 fast mode  抄：[model selection](https://learn.chatgpt.com/docs/model-selection)，2026-09-22/09-29/10-08 changelog  Atlas 位置：待定
- **B036 Codex `/model` / `/reasoning` 模型与推理选项**〔部分｜P1｜M〕缺：已有 /model，推理档位展示依赖 Atlas 模型 API 是否暴露对应强度。  抄：[model selection](https://learn.chatgpt.com/docs/model-selection)；ZCode `ModelConfigSelect.tsx`、`ThoughtLevelCycleControl.tsx`；Claude [model config](https://code.claude.com/docs/en/model-config)  Atlas 位置：待定
- **B043 Enter 发送偏好与 Queue/Steer 默认行为设置**〔部分｜P1｜M〕缺：发送/排队状态已展示，缺 Queue/Steer 默认行为的完整持久化偏好。  抄：Codex [reference settings](https://learn.chatgpt.com/docs/reference/settings)、[long-running work](https://learn.chatgpt.com/docs/long-running-work)；ZCode `ConversationQueuePanel.tsx`；Claude [desktop](https://code.claude.com/docs/en/desktop)  Atlas 位置：待定
- **B049 Add menu：附件、Goal、Workflow 等快捷插入**〔部分｜P1｜S〕缺：附件与引用可快速插入，Goal/Workflow 等菜单项须逐项对齐真实可执行入口。  抄：ZCode `packages/ui/src/prompt-editor/ChatPromptActionMenu.tsx`；OpenCode composer attachments  Atlas 位置：Composer.tsx；DrawingPad.tsx
- **B070 输入框插件/扩展资源上下文引用（V5 B93）**〔没做｜P0｜M〕缺：缺输入框插件/扩展资源上下文的结构化协议和可调用入口。  抄：固定 SHA `aac4755666d09fdcd70272fcf063c077a639015f`：`packages/ui/src/mentions/components/PluginMentionOptionContent.tsx`、`packages/ui/src/mentions/mentionMarkdown.ts`  Atlas 位置：待定

## 总账里这张卡的说明
### B-TC-05｜Composer：模型、附件与上下文（9 条）

- **包含编号：** B027, B028, B030, B031, B034, B036, B043, B049, B070
- **Atlas 拟修改文件/目录：** `Composer.tsx`；`DrawingPad.tsx`；`App.tsx`
- **要读的上游文件/文档：**
  - ZCode `packages/ui/src/v4/composer/V4ComposerToolbar.tsx`、`ModelConfigSelect.tsx`、`ChatModeSwitchControl.tsx`、`ThoughtLevelCycleControl.tsx`；OpenCode composer; Codex [models](https://learn.chatgpt.com/docs/model-selection)；Claude [model config](https://code.claude.com/docs/en/model-config)
  - ZCode `packages/ui/src/v4/composer/{useComposerAttachments.ts,attachmentUpload.ts,conversationDropTarget.ts}`；OpenCode session composer；Codex [image inputs](https://learn.chatgpt.com/docs/app)；Claude [desktop](https://code.claude.com/docs/en/desktop)
  - ZCode `packages/ui/src/mentions/providers/{fileMentionProvider.ts,sessionsMentionProvider.ts}`；OpenCode composer suggestions；Codex [prompting](https://learn.chatgpt.com/docs/prompting)；Claude [interactive mode](https://code.claude.com/docs/en/interactive-mode)
  - ZCode 固定 SHA `aac4755666d09fdcd70272fcf063c077a639015f`：`packages/ui/src/mentions/providers/skillsMentionProvider.ts`、`packages/ui/src/mentions/mentionMarkdown.ts`；Codex [skills](https://learn.chatgpt.com/docs/build-skills)；Claude [skills](https://code.claude.com/docs/en/skills)
  - [model selection](https://learn.chatgpt.com/docs/model-selection)，2026-09-22/09-29/10-08 changelog
  - [model selection](https://learn.chatgpt.com/docs/model-selection)；ZCode `ModelConfigSelect.tsx`、`ThoughtLevelCycleControl.tsx`；Claude [model config](https://code.claude.com/docs/en/model-config)
  - Codex [reference settings](https://learn.chatgpt.com/docs/reference/settings)、[long-running work](https://learn.chatgpt.com/docs/long-running-work)；ZCode `ConversationQueuePanel.tsx`；Claude [desktop](https://code.claude.com/docs/en/desktop)
  - ZCode `packages/ui/src/prompt-editor/ChatPromptActionMenu.tsx`；OpenCode composer attachments
  - 固定 SHA `aac4755666d09fdcd70272fcf063c077a639015f`：`packages/ui/src/mentions/components/PluginMentionOptionContent.tsx`、`packages/ui/src/mentions/mentionMarkdown.ts`
- **派工顺序：** P0 优先，完成后接 P1；Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。

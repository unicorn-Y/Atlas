你是施工者。任务：Atlas 功能对标任务卡 C-TC-02（模型、Provider、用量与网络），一次做完。

背景：Atlas 是 Electron + React 前端、Python 后端的桌面 AI Agent。这张卡来自「剩余工作总账」（仓库 docs/parity/LEDGER.md），列的是对标 ZCode / OpenCode / Codex / Claude Code 后 Atlas 还缺或只做了一部分的功能。

规矩：
1. 建工作树，不要改 D:\Atlas（用户在用），不碰别的 D:\atlas-* 目录：
   git -C D:\Atlas fetch origin
   git -C D:\Atlas worktree add D:\atlas-card-c-tc-02 -b card-c-tc-02 origin/memory-v1
2. 每条先确认 Atlas 现在实际怎样（读代码，不要只信表格），再照上游做：ZCode（github.com/zai-org/ZCode，界面在 packages/ui、packages/desktop）和 OpenCode（github.com/anomalyco/opencode，packages/app、packages/core）开源就读源码移植，文件头写 `// Ported from owner/repo@<sha>: <path> (License)`；Codex / Claude Code 照官方文档行为做。THIRD_PARTY_NOTICES.md 只追加。
3. 缺后端接口或 Electron 主进程能力就自己补，放新文件优先；共享文件（App.tsx、store/useAtlasStore.ts、core/atlas/server.py、core/atlas/api/application.py、config/atlas.example.toml）只做追加式小改动。
4. 真做不了的条目写清原因，不许做假按钮、假数据。
5. 不写测试、不跑测试套件。只确认：后端能启动（cd core 后 `set ATLAS_UPSTREAM_AUTO=0` 再 `python -m uvicorn atlas.server:app --port 28792`，/api/health 返回 ok 后关掉）；`npm --prefix frontend run build` 通过。
6. 只读需要的文件和代码段，不要整份读大文件（省额度）。
7. 完成后 git add -A、git commit、git push origin card-c-tc-02。在 docs/parity/cards/C-TC-02.md 写结果：每条编号做了什么 / 没做的原因，以及提交号。不要推 memory-v1。

## 本卡条目

- **C010 模型参数、模态能力、推理等级、effort/fast mode、provider 参数**〔部分｜P0｜M〕缺：已有 effort 与自定义模型，缺能由运行时执行的 Fast mode/元数据路由合同。  抄：ZCode `settings/model-provider-section/{ModelEditorAdvanced,ProviderModelMetadataDialog,ProviderModelModalityOptions,ProviderModelReasoningLevelEditor}.tsx`; OpenCode `providers/models/variant.tsx`; Codex [config reference](https://learn.chatgpt.com/docs/config-file/config-reference); Claude [model configuration](https://code.claude.com/docs/en/model-config), [fast mode](https://code.claude.com/docs/en/fast-mode)  Atlas 位置：待定
- **C013 用量、Token 趋势、模型归因、热图、预算/额度状态**〔部分｜P0｜M〕缺：已有 Token/费用统计，热图、统一预算及外部计划额度 API 仍不完整。  抄：ZCode `settings/usage-stats/{AppUsagePanel,CodingPlanUsagePanel,UsageHeatmap}.tsx`; Codex [Settings](https://learn.chatgpt.com/docs/reference/settings), [changelog](https://learn.chatgpt.com/docs/changelog); Claude [costs](https://code.claude.com/docs/en/costs), [monitoring usage](https://code.claude.com/docs/en/monitoring-usage); OpenCode `settings/providers/`  Atlas 位置：待定
- **C008 Provider 多账号、OAuth、环境变量/配置凭据来源及账号切换**〔部分｜P1｜L〕缺：目前仅可切换静态 Key，缺第三方 OAuth 账号会话/刷新/登出与来源统一管理。  抄：OpenCode `settings/providers/{providers,connect,credentials}/`; Codex [auth](https://learn.chatgpt.com/docs/auth); Claude [authentication](https://code.claude.com/docs/en/authentication)  Atlas 位置：待定
- **C074 网页搜索 Provider 选择**〔部分｜P1｜M〕缺：缺可被运行时消费的搜索 Provider 设置  抄：V5 §C 扩展 LSP / Web search / Experimental 行；Atlas `LspStatusSection.tsx`, `workspace_router.py`  Atlas 位置：待定
- **C100 代理软件开销诊断**〔没做｜P1｜M〕缺：缺代理相关耗时、资源与配置开销诊断视图  抄：[Z](https://github.com/zai-org/ZCode/blob/aac4755666d0/packages/ui/src/i18n/locales/zh-CN.ts) · [C](https://github.com/openai/codex/blob/6c0c6759d061/codex-rs/tui/src/slash_command.rs)  Atlas 位置：待定

## 总账里这张卡的说明
### C-TC-02｜模型、Provider、用量与网络（5 条）

- **包含编号：** C010, C013, C008, C074, C100
- **Atlas 拟修改文件/目录：** **待定**
- **要读的上游文件/文档：**
  - ZCode `settings/model-provider-section/{ModelEditorAdvanced,ProviderModelMetadataDialog,ProviderModelModalityOptions,ProviderModelReasoningLevelEditor}.tsx`; OpenCode `providers/models/variant.tsx`; Codex [config reference](https://learn.chatgpt.com/docs/config-file/config-reference); Claude [model configuration](https://code.claude.com/docs/en/model-config), [fast mode](https://code.claude.com/docs/en/fast-mode)
  - ZCode `settings/usage-stats/{AppUsagePanel,CodingPlanUsagePanel,UsageHeatmap}.tsx`; Codex [Settings](https://learn.chatgpt.com/docs/reference/settings), [changelog](https://learn.chatgpt.com/docs/changelog); Claude [costs](https://code.claude.com/docs/en/costs), [monitoring usage](https://code.claude.com/docs/en/monitoring-usage); OpenCode `settings/providers/`
  - OpenCode `settings/providers/{providers,connect,credentials}/`; Codex [auth](https://learn.chatgpt.com/docs/auth); Claude [authentication](https://code.claude.com/docs/en/authentication)
  - V5 §C 扩展 LSP / Web search / Experimental 行；Atlas `LspStatusSection.tsx`, `workspace_router.py`
  - [Z](https://github.com/zai-org/ZCode/blob/aac4755666d0/packages/ui/src/i18n/locales/zh-CN.ts) · [C](https://github.com/openai/codex/blob/6c0c6759d061/codex-rs/tui/src/slash_command.rs)
- **派工顺序：** P0 优先，完成后接 P1；Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。

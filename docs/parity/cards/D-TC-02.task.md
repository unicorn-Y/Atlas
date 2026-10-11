你是施工者。任务：Atlas 功能对标任务卡 D-TC-02（Agent 委派、计划与任务生命周期），一次做完。

背景：Atlas 是 Electron + React 前端、Python 后端的桌面 AI Agent。这张卡来自「剩余工作总账」（仓库 docs/parity/LEDGER.md），列的是对标 ZCode / OpenCode / Codex / Claude Code 后 Atlas 还缺或只做了一部分的功能。

规矩：
1. 建工作树，不要改 D:\Atlas（用户在用），不碰别的 D:\atlas-* 目录：
   git -C D:\Atlas fetch origin
   git -C D:\Atlas worktree add D:\atlas-card-d-tc-02 -b card-d-tc-02 origin/memory-v1
2. 每条先确认 Atlas 现在实际怎样（读代码，不要只信表格），再照上游做：ZCode（github.com/zai-org/ZCode，界面在 packages/ui、packages/desktop）和 OpenCode（github.com/anomalyco/opencode，packages/app、packages/core）开源就读源码移植，文件头写 `// Ported from owner/repo@<sha>: <path> (License)`；Codex / Claude Code 照官方文档行为做。THIRD_PARTY_NOTICES.md 只追加。
3. 缺后端接口或 Electron 主进程能力就自己补，放新文件优先；共享文件（App.tsx、store/useAtlasStore.ts、core/atlas/server.py、core/atlas/api/application.py、config/atlas.example.toml）只做追加式小改动。
4. 真做不了的条目写清原因，不许做假按钮、假数据。
5. 不写测试、不跑测试套件。只确认：后端能启动（cd core 后 `set ATLAS_UPSTREAM_AUTO=0` 再 `python -m uvicorn atlas.server:app --port 28798`，/api/health 返回 ok 后关掉）；`npm --prefix frontend run build` 通过。
6. 只读需要的文件和代码段，不要整份读大文件（省额度）。
7. 完成后 git add -A、git commit、git push origin card-d-tc-02。在 docs/parity/cards/D-TC-02.md 写结果：每条编号做了什么 / 没做的原因，以及提交号。不要推 memory-v1。

## 本卡条目

- **D013 计划模式入口/退出**〔部分｜P0｜M〕缺：有 update_plan，但缺显式 EnterPlanMode/ExitPlanMode 工具与状态转换  抄：Claude EnterPlanMode/ExitPlanMode；ZCode 同名工具；Codex `update_plan.rs`  Atlas 位置：待定
- **D014 询问用户 / 结构化问题**〔部分｜P0｜M〕缺：仅返回字符串；缺标题、选项描述、多选结果的结构化传递  抄：Claude AskUserQuestion；ZCode AskUserQuestion；OpenCode `plugin/question.ts`  Atlas 位置：待定
- **D016 代理创建和委派**〔部分｜P0｜M〕缺：委派参数缺调用级模型、reasoning effort 与最大深度控制  抄：Codex `handlers/multi_agent.rs`、TUI task tools；Claude Agent；ZCode Agent/Task；OpenCode `plugin/subagent.ts`  Atlas 位置：待定
- **D017 子代理消息、恢复、等待、中断、关闭**〔部分｜P0｜L〕缺：缺模型侧等待/取消/恢复/关闭/结果升级，以及跨会话 Agent registry、消息路由与权限校验（合入 F1-unassigned）  抄：Codex multi-agent v1/v2 handlers；Claude SendMessage/Agent teams；ZCode SendMessage/RespondToCoordinator/submit_result/escalate/ReplyToChannel/TaskStop  Atlas 位置：待定
- **D018 会话上下文读取/工具历史**〔部分｜P0｜M〕缺：缺当前运行工具历史读取；new_context 依赖 Hermes handoff callback  抄：ZCode `ReadSessionContext` handler；Codex `get_context_remaining` / `new_context`  Atlas 位置：待定
- **D042 工具审批范围/理由**〔部分｜P0｜M〕缺：审批事件未统一携带显式 scope/resource 与 reason；部分 PreToolUse 分支丢失理由  抄：Claude permissions docs；ZCode `packages/ui/src/PermissionDialog.tsx`, `lib/permissionRequest.ts`；OpenCode `packages/app/src/session/requests/`  Atlas 位置：待定
- **D115 本地定时任务管理**〔没做｜P1｜L〕缺：缺 CronCreate/List/Update/Delete 模型工具及 Atlas 可持久化调度 CRUD；现有前端 Automation 不提供同等 callable  抄：ZCode `apps/zcode-cli/packages/core/src/tool/handlers/cron.ts`；Claude [tools reference](https://code.claude.com/docs/en/tools-reference)  Atlas 位置：待定
- **D118 会话唤醒调度**〔没做｜P1｜M〕缺：缺 ScheduleWakeup callable；普通 clock.sleep 不提供持久化的会话唤醒  抄：Claude [tools reference](https://code.claude.com/docs/en/tools-reference)  Atlas 位置：待定
- **D122 结束会话**〔没做｜P1｜M〕缺：缺结束当前 Agent 会话的显式模型工具与用户可见结束原因  抄：Claude [tools reference](https://code.claude.com/docs/en/tools-reference)  Atlas 位置：待定
- **D125 结构化审查发现**〔没做｜P1｜M〕缺：缺 ReportFindings 的结构化 finding/severity/location/evidence 接收与持久化 callable  抄：Claude [tools reference](https://code.claude.com/docs/en/tools-reference)  Atlas 位置：待定

## 总账里这张卡的说明
### D-TC-02｜Agent 委派、计划与任务生命周期（10 条）

- **包含编号：** D013, D014, D016, D017, D018, D042, D115, D118, D122, D125
- **Atlas 拟修改文件/目录：** **待定**
- **要读的上游文件/文档：**
  - Claude EnterPlanMode/ExitPlanMode；ZCode 同名工具；Codex `update_plan.rs`
  - Claude AskUserQuestion；ZCode AskUserQuestion；OpenCode `plugin/question.ts`
  - Codex `handlers/multi_agent.rs`、TUI task tools；Claude Agent；ZCode Agent/Task；OpenCode `plugin/subagent.ts`
  - Codex multi-agent v1/v2 handlers；Claude SendMessage/Agent teams；ZCode SendMessage/RespondToCoordinator/submit_result/escalate/ReplyToChannel/TaskStop
  - ZCode `ReadSessionContext` handler；Codex `get_context_remaining` / `new_context`
  - Claude permissions docs；ZCode `packages/ui/src/PermissionDialog.tsx`, `lib/permissionRequest.ts`；OpenCode `packages/app/src/session/requests/`
  - ZCode `apps/zcode-cli/packages/core/src/tool/handlers/cron.ts`；Claude [tools reference](https://code.claude.com/docs/en/tools-reference)
  - Claude [tools reference](https://code.claude.com/docs/en/tools-reference)
- **派工顺序：** P0 优先，完成后接 P1；Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。

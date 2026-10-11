你是施工者。任务：Atlas 功能对标任务卡 D-TC-01（文件读写与本机进程接口），一次做完。

背景：Atlas 是 Electron + React 前端、Python 后端的桌面 AI Agent。这张卡来自「剩余工作总账」（仓库 docs/parity/LEDGER.md），列的是对标 ZCode / OpenCode / Codex / Claude Code 后 Atlas 还缺或只做了一部分的功能。

规矩：
1. 建工作树，不要改 D:\Atlas（用户在用），不碰别的 D:\atlas-* 目录：
   git -C D:\Atlas fetch origin
   git -C D:\Atlas worktree add D:\atlas-card-d-tc-01 -b card-d-tc-01 origin/memory-v1
2. 每条先确认 Atlas 现在实际怎样（读代码，不要只信表格），再照上游做：ZCode（github.com/zai-org/ZCode，界面在 packages/ui、packages/desktop）和 OpenCode（github.com/anomalyco/opencode，packages/app、packages/core）开源就读源码移植，文件头写 `// Ported from owner/repo@<sha>: <path> (License)`；Codex / Claude Code 照官方文档行为做。THIRD_PARTY_NOTICES.md 只追加。
3. 缺后端接口或 Electron 主进程能力就自己补，放新文件优先；共享文件（App.tsx、store/useAtlasStore.ts、core/atlas/server.py、core/atlas/api/application.py、config/atlas.example.toml）只做追加式小改动。
4. 真做不了的条目写清原因，不许做假按钮、假数据。
5. 不写测试、不跑测试套件。只确认：后端能启动（cd core 后 `set ATLAS_UPSTREAM_AUTO=0` 再 `python -m uvicorn atlas.server:app --port 28797`，/api/health 返回 ok 后关掉）；`npm --prefix frontend run build` 通过。
6. 只读需要的文件和代码段，不要整份读大文件（省额度）。
7. 完成后 git add -A、git commit、git push origin card-d-tc-01。在 docs/parity/cards/D-TC-01.md 写结果：每条编号做了什么 / 没做的原因，以及提交号。不要推 memory-v1。

## 本卡条目

- **D001 文件读取（路径、范围、编码/大文件保护）**〔部分｜P0｜M〕缺：缺按行范围/字节范围读取及大文件硬上限；当前一次读完整文件  抄：Claude [tools reference](https://code.claude.com/docs/en/tools-reference)；ZCode `apps/zcode-cli/packages/core/src/tool/handlers/read.ts`；OpenCode `packages/core/src/tool/plugin/read.ts`；Codex core handler index 未列独立 text Read handler  Atlas 位置：待定
- **D002 文件写入**〔部分｜P0｜M〕缺：缺工作区路径限制与越界拒绝；当前 local_file 可写本机任意路径  抄：Claude tools reference；ZCode `handlers/write.ts`；OpenCode `plugin/write.ts`；Codex core handler index 未列独立 Write handler  Atlas 位置：待定
- **D003 文件编辑、批量编辑**〔部分｜P0｜M〕缺：edit 仅单文件，多文件 patch 不具事务性；缺批量校验及原子回执  抄：Claude tools reference + [changelog](https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md)；ZCode `handlers/edit.ts`；OpenCode `plugin/edit.ts`；Codex 通过 `apply_patch`/shell 组合  Atlas 位置：待定
- **D011 后台进程启动、等待、输入、输出、停止**〔部分｜P0｜M〕缺：缺 Claude TaskOutput/TaskStop 兼容 callable 名称与运行映射  抄：Codex `handlers/exec_command.rs`, `write_stdin.rs`；Claude TaskOutput/TaskStop（TaskOutput 有文档弃用冲突）；ZCode `handlers/{bash,task_output,task_stop}.ts`；OpenCode `plugin/shell.ts`  Atlas 位置：待定
- **D046 OpenCode session rename/move 与 worktree 生命周期**〔部分｜P1｜L〕缺：缺跨 workspace 活动会话 handoff；worktree 自动清理/回收流程不足（合入 F1-unassigned）  抄：`packages/core/src/tool/plugin/opencode.ts`  Atlas 位置：待定
- **D127 向客户端发送文件**〔没做｜P1｜M〕缺：缺受授权的本地文件传至客户端 callable 与成功/失败回执  抄：Claude [tools reference](https://code.claude.com/docs/en/tools-reference)  Atlas 位置：待定

## 总账里这张卡的说明
### D-TC-01｜文件读写与本机进程接口（6 条）

- **包含编号：** D001, D002, D003, D011, D046, D127
- **Atlas 拟修改文件/目录：** **待定**
- **要读的上游文件/文档：**
  - Claude [tools reference](https://code.claude.com/docs/en/tools-reference)；ZCode `apps/zcode-cli/packages/core/src/tool/handlers/read.ts`；OpenCode `packages/core/src/tool/plugin/read.ts`；Codex core handler index 未列独立 text Read handler
  - Claude tools reference；ZCode `handlers/write.ts`；OpenCode `plugin/write.ts`；Codex core handler index 未列独立 Write handler
  - Claude tools reference + [changelog](https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md)；ZCode `handlers/edit.ts`；OpenCode `plugin/edit.ts`；Codex 通过 `apply_patch`/shell 组合
  - Codex `handlers/exec_command.rs`, `write_stdin.rs`；Claude TaskOutput/TaskStop（TaskOutput 有文档弃用冲突）；ZCode `handlers/{bash,task_output,task_stop}.ts`；OpenCode `plugin/shell.ts`
  - `packages/core/src/tool/plugin/opencode.ts`
  - Claude [tools reference](https://code.claude.com/docs/en/tools-reference)
- **派工顺序：** P0 优先，完成后接 P1；Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。

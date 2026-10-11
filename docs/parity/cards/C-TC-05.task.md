你是施工者。任务：Atlas 功能对标任务卡 C-TC-05（Electron 桌面、无障碍与语音），一次做完。

背景：Atlas 是 Electron + React 前端、Python 后端的桌面 AI Agent。这张卡来自「剩余工作总账」（仓库 docs/parity/LEDGER.md），列的是对标 ZCode / OpenCode / Codex / Claude Code 后 Atlas 还缺或只做了一部分的功能。

规矩：
1. 建工作树，不要改 D:\Atlas（用户在用），不碰别的 D:\atlas-* 目录：
   git -C D:\Atlas fetch origin
   git -C D:\Atlas worktree add D:\atlas-card-c-tc-05 -b card-c-tc-05 origin/memory-v1
2. 每条先确认 Atlas 现在实际怎样（读代码，不要只信表格），再照上游做：ZCode（github.com/zai-org/ZCode，界面在 packages/ui、packages/desktop）和 OpenCode（github.com/anomalyco/opencode，packages/app、packages/core）开源就读源码移植，文件头写 `// Ported from owner/repo@<sha>: <path> (License)`；Codex / Claude Code 照官方文档行为做。THIRD_PARTY_NOTICES.md 只追加。
3. 缺后端接口或 Electron 主进程能力就自己补，放新文件优先；共享文件（App.tsx、store/useAtlasStore.ts、core/atlas/server.py、core/atlas/api/application.py、config/atlas.example.toml）只做追加式小改动。
4. 真做不了的条目写清原因，不许做假按钮、假数据。
5. 不写测试、不跑测试套件。只确认：后端能启动（cd core 后 `set ATLAS_UPSTREAM_AUTO=0` 再 `python -m uvicorn atlas.server:app --port 28795`，/api/health 返回 ok 后关掉）；`npm --prefix frontend run build` 通过。
6. 只读需要的文件和代码段，不要整份读大文件（省额度）。
7. 完成后 git add -A、git commit、git push origin card-c-tc-05。在 docs/parity/cards/C-TC-05.md 写结果：每条编号做了什么 / 没做的原因，以及提交号。不要推 memory-v1。

## 本卡条目

- **C033 屏幕阅读器、全屏/终端适配、语音听写与可访问性偏好**〔部分｜P1｜M〕缺：缺面向全应用的读屏/语音/无障碍偏好与输入适配。  抄：Claude [accessibility](https://code.claude.com/docs/en/accessibility), [fullscreen](https://code.claude.com/docs/en/fullscreen), [voice dictation](https://code.claude.com/docs/en/voice-dictation); ZCode `settingsPageHelpers.tsx`  Atlas 位置：待定
- **C046 多语言文案和设置/命令翻译覆盖**〔部分｜P1｜S〕缺：缺覆盖设置、命令、错误提示的完整中英文翻译体系。  抄：ZCode `packages/ui/src/i18n/locales/{en-US,zh-CN}.ts`; OpenCode `packages/app/src/runtime/i18n/`, `packages/ui/src/i18n/`  Atlas 位置：待定
- **C079 系统托盘驻留**〔没做｜P1｜L〕缺：缺 Electron 托盘及关闭窗口后的驻留行为  抄：V5 §C Windows tray / prevent sleep 行  Atlas 位置：待定
- **C080 任务期间防休眠**〔没做｜P1｜M〕缺：缺任务运行期 power-save blocker 控制  抄：V5 §C Windows tray / prevent sleep 行  Atlas 位置：待定
- **C081 项目/工作区独立多窗口**〔没做｜P1｜L〕缺：缺每项目独立 Electron 窗口生命周期、恢复和导航  抄：ZCode `packages/desktop/src/main/desktopApplicationMenu.ts`；Claude [Desktop](https://code.claude.com/docs/en/desktop)  Atlas 位置：待定
- **C101 语音听写自定义词典**〔没做｜P1｜M〕缺：缺词典管理/纠错持久化；语音听写本身已有  抄：Codex 官方 Desktop 更新（F1-B.md 第 137 行）  Atlas 位置：待定

## 总账里这张卡的说明
### C-TC-05｜Electron 桌面、无障碍与语音（6 条）

- **包含编号：** C033, C046, C079, C080, C081, C101
- **Atlas 拟修改文件/目录：** **待定**
- **要读的上游文件/文档：**
  - Claude [accessibility](https://code.claude.com/docs/en/accessibility), [fullscreen](https://code.claude.com/docs/en/fullscreen), [voice dictation](https://code.claude.com/docs/en/voice-dictation); ZCode `settingsPageHelpers.tsx`
  - ZCode `packages/ui/src/i18n/locales/{en-US,zh-CN}.ts`; OpenCode `packages/app/src/runtime/i18n/`, `packages/ui/src/i18n/`
  - V5 §C Windows tray / prevent sleep 行
  - ZCode `packages/desktop/src/main/desktopApplicationMenu.ts`；Claude [Desktop](https://code.claude.com/docs/en/desktop)
  - Codex 官方 Desktop 更新（F1-B.md 第 137 行）
- **派工顺序：** Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。

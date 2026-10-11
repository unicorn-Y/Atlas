你是施工者。任务：Atlas 功能对标任务卡 A-TC-01（会话侧栏状态、导航与项目动作），一次做完。

背景：Atlas 是 Electron + React 前端、Python 后端的桌面 AI Agent。这张卡来自「剩余工作总账」（仓库 docs/parity/LEDGER.md），列的是对标 ZCode / OpenCode / Codex / Claude Code 后 Atlas 还缺或只做了一部分的功能。

规矩：
1. 建工作树，不要改 D:\Atlas（用户在用），不碰别的 D:\atlas-* 目录：
   git -C D:\Atlas fetch origin
   git -C D:\Atlas worktree add D:\atlas-card-a-tc-01 -b card-a-tc-01 origin/memory-v1
2. 每条先确认 Atlas 现在实际怎样（读代码，不要只信表格），再照上游做：ZCode（github.com/zai-org/ZCode，界面在 packages/ui、packages/desktop）和 OpenCode（github.com/anomalyco/opencode，packages/app、packages/core）开源就读源码移植，文件头写 `// Ported from owner/repo@<sha>: <path> (License)`；Codex / Claude Code 照官方文档行为做。THIRD_PARTY_NOTICES.md 只追加。
3. 缺后端接口或 Electron 主进程能力就自己补，放新文件优先；共享文件（App.tsx、store/useAtlasStore.ts、core/atlas/server.py、core/atlas/api/application.py、config/atlas.example.toml）只做追加式小改动。
4. 真做不了的条目写清原因，不许做假按钮、假数据。
5. 不写测试、不跑测试套件。只确认：后端能启动（cd core 后 `set ATLAS_UPSTREAM_AUTO=0` 再 `python -m uvicorn atlas.server:app --port 28790`，/api/health 返回 ok 后关掉）；`npm --prefix frontend run build` 通过。
6. 只读需要的文件和代码段，不要整份读大文件（省额度）。
7. 完成后 git add -A、git commit、git push origin card-a-tc-01。在 docs/parity/cards/A-TC-01.md 写结果：每条编号做了什么 / 没做的原因，以及提交号。不要推 memory-v1。

## 本卡条目

- **A002 新建会话及空白草稿生命周期**〔部分｜P0｜M〕缺：首条消息前仍直接持久化会话，缺临时空白草稿的生命周期。  抄：ZCode 新会话命令与 UI 注册；OpenCode app session commands；Codex Desktop 文档；Claude Desktop 文档  Atlas 位置：待定
- **A007 按状态筛选（运行、等待、完成、错误、未读）**〔部分｜P0｜M〕缺：缺等待/完成/错误等统一筛选所需的持久化状态字段；目前只具备运行与未读状态。  抄：ZCode task list status 与 locale；Codex 活动/优先级视图文档；Claude Desktop、Agent view 及 v2.1.207、v2.1.257、v2.1.287 changelog  Atlas 位置：待定
- **A008 按项目、环境、工作树筛选**〔部分｜P0｜M〕缺：已有项目/工作区筛选，但缺完整环境、工作树状态字段与对应筛选。  抄：ZCode task scope/project 列表；OpenCode Projects 与 Servers 页面；Codex session picker cwd/all 和官方 Projects 文档；Claude Desktop、Manage sessions  Atlas 位置：待定
- **A025 运行、等待输入、未读提示**〔部分｜P0｜M〕缺：运行与未读可展示，缺持久化 waiting-input 状态来源。  抄：ZCode task status badges；Codex Activity/Priority 文档；Claude Agent view、Desktop、v2.1.207 与 v2.1.257 changelog  Atlas 位置：待定
- **A027 运行中/等待输入/完成通知与活动视图**〔部分｜P0｜M〕缺：侧栏可显示现有状态，缺跨会话 Activity 归一化及原生通知投递联动。  抄：ZCode row status；Codex Activity view 文档；Claude Desktop notifications、Agent view、v2.1.210/v2.1.295/v2.1.296 changelog  Atlas 位置：待定
- **A029 快捷键打开搜索/选择器、切换会话组**〔部分｜P1｜M〕缺：已有全局绑定系统，缺侧栏搜索/组导航独立的快捷键动作。  抄：ZCode shortcut registry/keybindings setting；OpenCode app keybind registry/settings；Codex TUI keymap 与官方 shortcuts；Claude commands 与 v2.1.288  Atlas 位置：待定
- **A011 拖动会话排序或移入分组**〔部分｜P0｜M〕缺：组内排序已增加，可跨组拖入的范围仍有限。  抄：ZCode draggable task/group/project UI；OpenCode project reorder；Claude Agent view reorder  Atlas 位置：待定
- **A018 右键菜单、键盘菜单键与触屏长按**〔部分｜P0｜S〕缺：右键/键盘菜单已补，触屏长按的 Electron 交互仍待核实。  抄：ZCode task context menu；OpenCode session context menu 支持 right-click/Shift+F10/long-press  Atlas 位置：待定
- **A013 项目创建、重命名、导入/关闭、最近关闭**〔部分｜P1｜M〕缺：项目导航/归属已接，项目导入、关闭与最近关闭等动作未完成完整 UI/Git 工作流。  抄：OpenCode Projects 页面与项目命令；Codex Desktop Projects 文档；Claude Desktop  Atlas 位置：待定
- **A036 OpenCode 项目颜色/图标自定义**〔没做｜P1｜S〕缺：缺项目颜色、图标编辑和侧栏呈现  抄：OpenCode `packages/app/src/settings/search-catalog.ts`（V5 E 项；仅用于功能发现）  Atlas 位置：待定

## 总账里这张卡的说明
### A-TC-01｜会话侧栏状态、导航与项目动作（10 条）

- **包含编号：** A002, A007, A008, A025, A027, A029, A011, A018, A013, A036
- **Atlas 拟修改文件/目录：** **待定**
- **要读的上游文件/文档：**
  - ZCode 新会话命令与 UI 注册；OpenCode app session commands；Codex Desktop 文档；Claude Desktop 文档
  - ZCode task list status 与 locale；Codex 活动/优先级视图文档；Claude Desktop、Agent view 及 v2.1.207、v2.1.257、v2.1.287 changelog
  - ZCode task scope/project 列表；OpenCode Projects 与 Servers 页面；Codex session picker cwd/all 和官方 Projects 文档；Claude Desktop、Manage sessions
  - ZCode task status badges；Codex Activity/Priority 文档；Claude Agent view、Desktop、v2.1.207 与 v2.1.257 changelog
  - ZCode row status；Codex Activity view 文档；Claude Desktop notifications、Agent view、v2.1.210/v2.1.295/v2.1.296 changelog
  - ZCode shortcut registry/keybindings setting；OpenCode app keybind registry/settings；Codex TUI keymap 与官方 shortcuts；Claude commands 与 v2.1.288
  - ZCode draggable task/group/project UI；OpenCode project reorder；Claude Agent view reorder
  - ZCode task context menu；OpenCode session context menu 支持 right-click/Shift+F10/long-press
  - OpenCode Projects 页面与项目命令；Codex Desktop Projects 文档；Claude Desktop
  - OpenCode `packages/app/src/settings/search-catalog.ts`（V5 E 项；仅用于功能发现）
- **派工顺序：** P0 优先，完成后接 P1；Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。

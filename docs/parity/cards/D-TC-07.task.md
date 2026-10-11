你是施工者。任务：Atlas 功能对标任务卡 D-TC-07（Workflow、Provider、应用与 Git 执行），一次做完。

背景：Atlas 是 Electron + React 前端、Python 后端的桌面 AI Agent。这张卡来自「剩余工作总账」（仓库 docs/parity/LEDGER.md），列的是对标 ZCode / OpenCode / Codex / Claude Code 后 Atlas 还缺或只做了一部分的功能。

规矩：
1. 建工作树，不要改 D:\Atlas（用户在用），不碰别的 D:\atlas-* 目录：
   git -C D:\Atlas fetch origin
   git -C D:\Atlas worktree add D:\atlas-card-d-tc-07 -b card-d-tc-07 origin/memory-v1
2. 每条先确认 Atlas 现在实际怎样（读代码，不要只信表格），再照上游做：ZCode（github.com/zai-org/ZCode，界面在 packages/ui、packages/desktop）和 OpenCode（github.com/anomalyco/opencode，packages/app、packages/core）开源就读源码移植，文件头写 `// Ported from owner/repo@<sha>: <path> (License)`；Codex / Claude Code 照官方文档行为做。THIRD_PARTY_NOTICES.md 只追加。
3. 缺后端接口或 Electron 主进程能力就自己补，放新文件优先；共享文件（App.tsx、store/useAtlasStore.ts、core/atlas/server.py、core/atlas/api/application.py、config/atlas.example.toml）只做追加式小改动。
4. 真做不了的条目写清原因，不许做假按钮、假数据。
5. 不写测试、不跑测试套件。只确认：后端能启动（cd core 后 `set ATLAS_UPSTREAM_AUTO=0` 再 `python -m uvicorn atlas.server:app --port 28793`，/api/health 返回 ok 后关掉）；`npm --prefix frontend run build` 通过。
6. 只读需要的文件和代码段，不要整份读大文件（省额度）。
7. 完成后 git add -A、git commit、git push origin card-d-tc-07。在 docs/parity/cards/D-TC-07.md 写结果：每条编号做了什么 / 没做的原因，以及提交号。不要推 memory-v1。

## 本卡条目

- **D044 Workflow 动态编排**〔部分｜P1｜L〕缺：缺持久化、可复用的命名 workflow 定义注册表与 save/list/get 生命周期  抄：Claude Workflow；ZCode workflow tools；OpenCode CodeMode `packages/core/src/codemode`  Atlas 位置：待定
- **D047 OpenCode model/provider 发现**〔部分｜P1｜M〕缺：仅查 Atlas 配置与静态 provider catalog；缺完整 provider/model 动态发现和过滤分页  抄：`packages/core/src/tool/plugin/opencode.ts`  Atlas 位置：待定
- **D048 应用生成生命周期**〔部分｜P1｜M〕缺：只管理 HTML 文件，没有独立 app/window 创建、运行和关闭生命周期  抄：`crates/goose/src/agents/platform_extensions/apps.rs`  Atlas 位置：待定
- **D049 交互式数据可视化**〔部分｜P1｜S〕缺：仅支持 bar/line/donut/radar，无其他矩阵图类和界面内交互展示器  抄：`crates/goose-mcp/src/autovisualiser/mod.rs`  Atlas 位置：待定
- **D052 无头/SDK/app-server 调用**〔部分｜P1｜M〕缺：ACP 只支持文本 session；缺按 session 注入 MCP、loadSession 和 free-text elicitation  抄：Codex `codex exec` / app-server 官方文档；Claude Code `claude -p` CLI 文档；[ACP v1 session setup](https://github.com/agentclientprotocol/agent-client-protocol/blob/main/docs/protocol/v1/session-setup.mdx)；Codex app-server 文档  Atlas 位置：待定
- **D053 Git 平台 PR 创建与评论**〔部分｜P1｜M〕缺：已有 PR 创建/评论 callable，缺可信 PR 状态查询/徽章数据工具（合入 F1-unassigned）  抄：GitHub CLI `gh pr create` / `gh pr comment` 官方文档；Atlas `api/workspace_router.py` 现有 PR 创建 API  Atlas 位置：待定

## 总账里这张卡的说明
### D-TC-07｜Workflow、Provider、应用与 Git 执行（6 条）

- **包含编号：** D044, D047, D048, D049, D052, D053
- **Atlas 拟修改文件/目录：** **待定**
- **要读的上游文件/文档：**
  - Claude Workflow；ZCode workflow tools；OpenCode CodeMode `packages/core/src/codemode`
  - `packages/core/src/tool/plugin/opencode.ts`
  - `crates/goose/src/agents/platform_extensions/apps.rs`
  - `crates/goose-mcp/src/autovisualiser/mod.rs`
  - Codex `codex exec` / app-server 官方文档；Claude Code `claude -p` CLI 文档；[ACP v1 session setup](https://github.com/agentclientprotocol/agent-client-protocol/blob/main/docs/protocol/v1/session-setup.mdx)；Codex app-server 文档
  - GitHub CLI `gh pr create` / `gh pr comment` 官方文档；Atlas `api/workspace_router.py` 现有 PR 创建 API
- **派工顺序：** Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。

## 四、P2 排队清单（不切卡）

**A 区：**无。

**B 区：**B042 Codex `/local`、`/cloud`、`/cloud-environment` 执行位置选择、B072 按场景主动推荐任务（V5 B100）、B135 系统资源监视展示、B136 OpenCode 触屏适配、B137 Codex TUI Vim 模式、B138 Codex TUI 宠物、B139 Codex Security 扫描工作台。

**C 区：**C005 系统与运行环境偏好（代理、证书、shell、终端、休眠、托盘、硬件加速）、C021 插件远端同步、服务器/桌面端安装情况、C025 Skills User/Workspace/Plugin scope、frontmatter、按 Agent 权限和远端同步、C038 远程控制会话、设备配对、远端状态/同步和 QR 会话、C055 更新通道（stable/beta/nightly）、C060 云任务与外部集成入口、C065 Off-peak 低峰任务、C075 实验功能开关、C077 数据库目录迁移、C078 模型 I/O 完整保留策略、C082 会话公开分享服务与访问控制、C085 Claude 手机 Dispatch 开发任务、C086 Claude Cloud Projects 持续任务、C087 OpenCode Web pair 设备授权、C088 状态栏/标题栏自定义、C090 Claude Connectors 统一管理、C091 Claude Mods 自定义交互面、C092 OpenCode V2 cli.json 配置兼容、C093 OpenCode V2 CLI 本地插件加载、C094 OpenCode V1→V2 插件迁移、C095 Codex Sites 托管网页项目、C096 Codex Chronicle 屏幕上下文记忆、C097 Codex Micro 外设映射与状态、C098 Codex Daybreak 模式、C099 Codex 调试沙箱设置。

**D 区：**D056 Android 创建应用、D082 iOS 创建应用、D110 ZCode image-search 插件、D111 ZCode documents/pdf/presentations/spreadsheets 插件 skills、D114 Codex Security plugin scan、D116 离峰任务管理、D117 远程 Routine 触发、D120 回复外部频道、D121 托管 Artifact 发布、D124 推送通知、D126 用户反馈草稿、D128 分享入门指南。

## 五、来源追踪与执行纪律

1. 每个源功能保留 `F1-A/B/C/D.md` 行号或 V5 矩阵章节/附录标记，参看伴随的 `Atlas-功能状态索引.csv`；已做/原有在 CSV 里可查询，不在正文重复列。
2. 每卡执行前阅读对应上游源码/文档及 Atlas 本地实际文件，先复核主分支是否已经合并这些 F1 分支产物；**材料列为已做不代表 main 已合并**。若实现已存在则在结果中标记“免施工”。
3. 官方闭源 GUI 只提供文档，不能下发“复制其内部源码”任务；开源源码移植按各 F1 文件所述固定 SHA/许可证保留来源与 THIRD_PARTY_NOTICES 归属。
4. 施工时只补真实运行链路；不要只加按钮、空命令、假状态。平台/套餐专属能力受条件限制，优先以 P2 作为待评估而非立即上马。
5. 每卡提交一次结果：实现文件、上游依据、所接 API/事件、仍有缺口、Git 提交、可复核路径。不要用功能请求或界面文案推断产品真实执行能力。

---
**阅读分段顺序：** 第一节统计 → 第二节 A、B、C、D 剩余 → 第三节 P0/P1 任务卡 → 第四节 P2。

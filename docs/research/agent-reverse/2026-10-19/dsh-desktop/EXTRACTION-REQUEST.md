# 精确原始归档/发行物补采任务书 — 状态追记

**状态（2026-10-19）：源码归档采集及静态机械提取已完成；动态运行仍 NOT-RUN。** 任务书指定的 A/B ZIP 均按精确 URL 下载，byte size / SHA-256 与 manifest 一致，ZIP CRC、路径规范、重复名检查通过，已完整解包至 lane worktree 外 scratch。报告分支只含压缩包元数据、文件摘要、符号索引与原创分析，不含源包或上游源码 payload。详细核验见 `extracted/ASSET-VERIFICATION.md` 和 `extracted/READ-ME-FIRST.md`。

下方原始采集规范作为可复核的任务输入留存；除动态运行与源文件控件级 UI 映射仍 U 外，不再是待执行下载任务。

**执行仓库** unicorn-Y/Atlas。
**唯一提交分支** research/agent-reverse-20261019-dsh-desktop。
**目标目录** docs/research/agent-reverse/2026-10-19/dsh-desktop/extracted/。
**目的**：本会话已真正读固定 upstream 源码，然而 GitHub text API 无法在此读取 222MB 二进制归档并解压；也没有 Windows 实机启动。请做机械独立 SHA 校验、精确符号/调用映射和尽可能的隔离运行证据。**不要修改 Atlas 正式业务代码，不要替换源提交，不要擅自写竞品结论，不要提交整个大 ZIP。**

## 必须精确下载与验证的输入

A：
https://github.com/unicorn-Y/Atlas/releases/download/agent-client-packages-20261019/dsh-desktop-anywhere-labs-03d18d13bb.zip

- 预期文件长度 222488979 字节。
- SHA-256 03d18d13bb4a5bbfe79e3cd340d465d415a24f69968828c045efb5ea234b0a31。
- pinned upstream 6a63b9730b82cf4e858b9a11ac9783da9a5a0c3a；Next 2.0.19-next。

B：
https://github.com/unicorn-Y/Atlas/releases/download/agent-client-packages-20261019/dsh-desktop-dongdong-agent-1dd3b7ded3.zip

- 预期文件长度 5400611 字节。
- SHA-256 1dd3b7ded3646abf5245f46b76e214d33908ac563d1c796d1a9baf592a9f5dc6。
- pinned upstream 0aea85f01acd4583bb3fcebaa8c51586b08833a1；0.1.15。

如果任何一份 SHA 不匹配，**停止用该包做任何可确证结论**，记录 filename/size/expected/actual/error，避免悄悄换最新版本。

## 机械提取工序

1. 在独立临时目录保存两个 ZIP，直接计算 SHA256 与原始 byte size。用 Python zipfile 或 7-Zip 完整列 zip entry：路径、压缩后/原始字节、CRC、compression type；检查路径规范/重复名，总原始大小。写 extracted/ASSET-VERIFICATION.md、A-package-tree.tsv 和 B-package-tree.tsv。校验后才能解压。
2. A 针对 **dsh-desktop-next** 全部 src/*.ts、src/**/*.tsx、package、Cordis patches、配置、Electron/preload/Host；枚举文件 sha256/path/size，写 A-code-sha256.tsv。对 legacy **dsh-plugin-desktop**、dsh-plugin-desktop-beta、community-market、community-fabric 只编各自独立摘要，**不与 Next 2.0.19-next 合并**。
3. A 逐文件静态抽取符号到 A-symbol-index.md：src/main.ts 全部 ipcMain.handle/on、app/window/tray hooks 与 DesktopCommand switch/handlers；src/client/ 下全部 slots.inject/register；src/host/index.ts 中插件加载、Cordis patches 和 runProfile；src/host-process.ts 的所有消息类型、reply、onError 与关闭；src/webserver.ts 的 route/registerUpgrade；src/recovery.ts checkpoint 文件/恢复；更新 task inspect/lock/unlock、graceful stop 的所有入口。输出“原文件路径:精确行号:符号:它调用谁”，不要只列搜到的关键字。
4. B 编 B-code-sha256.tsv 与 B-symbol-index.md：src-tauri/src/lib.rs 每个 Rust #[tauri::command]、Tray action、顶层 navigate/初始 cookie 注入；src/App.tsx 启动/卸载 React 和 manage/restart route；src/lib/dshEngine.ts 每个 spawn/ref/ownership/retry/probe/restart；src/lib/engineAuth.ts 的 Cookie 生成接口名（**不得复制 secret**）；src/lib/enginePatch.ts /updater.ts；tools/codebuddy-mcp、tools/dsh-balance、tools/dsh-tauri-dir-picker 的真实 package 入口、注册和是否有运行时加载条件。
5. A 抽 vendor/dsh-runtime 各目录的版本与可识别 package manifest；列 vendored AA tarball 内的前端/后台模块、协议入口、license 名称/manifest，**不要上传 222MB 原包或所有 vendor 二进制**。官方 DSH 0.2.1-rc.2 是否和 Next 的实际装配一致，必须按真实 bundle table/版本索引证明；不要用 0.2.0-rc.2 CLI 混答。出 LICENSE-MAP.tsv：源路径、原 attribution/license file path、包名、是否 third party。
6. 如果 Windows 上可单独启动这两个包和自有临时 DSH Profile，可选做 1 父 2 子、子任务运行/Stop/追加指令/点击 child Session、关闭并重开、用量更新的最小人工/自动运行记录。写 RUNTIME-OBSERVATIONS.md：可复现步骤、安装版本、是否真加载插件、UI 和 IPC/WS 事件字段、错误/恢复输出和实际结果；不测就填 NOT-RUN，禁止模拟或伪造截图。任何账号/API key、Cookie、私有 Session 路径、真实用户日志须脱敏；不要向 Git 推送凭据。
7. 证据文件统一保留 source commit 和真实 path:line 标签，写 extracted/READ-ME-FIRST.md 说明每份文件来历/哈希/运行状态。文本总量目标不超过 5MB，必要 fragment 按路径拆分，不把归档、海量 node_modules、账号目录推到 Git。

## 交付清单与返回格式

必须：ASSET-VERIFICATION.md、A-package-tree.tsv、B-package-tree.tsv、A-code-sha256.tsv、B-code-sha256.tsv、A-symbol-index.md、B-symbol-index.md、LICENSE-MAP.tsv、RUNTIME-OBSERVATIONS.md、READ-ME-FIRST.md。

只在 research/agent-reverse-20261019-dsh-desktop 的 extracted/ 下添加机械证据后 commit+push，返回该 commit SHA 和 READ-ME-FIRST.md 的 GitHub 路径；无任何业务源码改动。之后研究会话读取结果再将 U 转 S/R，并继续追缺口，而不是把提取任务书当作研究已完成。

# 3.15.3 实物补证 — 本地 Codex 精确机械提取任务

> **执行状态（2026-10-19 checkpoint）：PARTIAL, committed on the lane branch.** 三个 release asset 的大小/SHA 已重新核验；真实 3.15.3 CJS 已 Acorn 解析并记录 AST/UTF-8 byte-offset；retained app.asar extracted `out` 中部分 main/host/preload/plugin-sandbox bundles 已重哈希并静态追踪到 typed host RPC 与 MCP Apps sandbox registry。输出在 `extracted-3153/`，其中 `EXTRACTION-LOG.md` 写出完整限制。全量 file/package inventory、ASAR per-entry integrity、完整 renderer/UI 调用链、运行验收仍待补；REA app.asar/whole-app 分析与独立 open_binary 均 300s timeout，另已发现一个 unpacked node-pty integrity mismatch。禁止因此把本工作改写为已完成全包验证。

> **执行者：用户本地拥有完整 Release 资产及 Windows 文件系统的 Codex。作用仅是补完机械证据；禁止修改 Atlas main/正式业务文件、禁止由提取者冒充已经完成整体架构研究。** 结果提交到独立分支 research/agent-reverse-20261019-zcode，目录 docs/research/agent-reverse/2026-10-19/zcode/extracted-3153/；若此研究分支已有其他修改，只新增机器索引和提取记录，不覆写本报告。需自行开独立 worktree。

## 一、下载/输入资产的确切身份（未核验即停止提取并报告）

1. 安装包：https://github.com/unicorn-Y/Atlas/releases/download/agent-client-packages-20261019/zcode-desktop-v3.15.3-bc8100ba43.exe ，期望 181367144 bytes；SHA256 bc8100ba4377256fbe1531d549b4775f18e3ba21768b6294ca50751cd461faca。原官方分发：https://cdn-zcode.z.ai/zcode/electron/releases/3.15.3/windows-x64/ZCode-3.15.3-win-x64.exe。
2. 预提 Runtime：https://github.com/unicorn-Y/Atlas/releases/download/agent-client-packages-20261019/zcode-agent-runtime-embedded-v3.15.3-31965ce1d5.cjs ，15,127,039 bytes；SHA256 31965ce1d5d4a808ef156784f67996de42ccab335591d2386a61ea8f6f506a54。原包内路径 resources/glm/zcode.cjs。
3. 公开源码（对照，不应假装同版）：https://github.com/unicorn-Y/Atlas/releases/download/agent-client-packages-20261019/zcode-source-main-aac4755-45034cfbc0.zip ，SHA256 45034cfbc064716a34a06a117af6aed359012927834a3e40c24cf89682ef8ab1；git ref zai-org/ZCode@aac4755666d09fdcd70272fcf063c077a639015f，root package.json=3.15.1。
4. 若 staging 还在，先复用 D:\agent-client-staging\opencode-zcode\ZCode\desktop\extracted-installer\application\resources\glm\zcode.cjs；也可以从 Release 重新下载。只能在大小+哈希匹配后称之为目标 3.15.3 CJS；若两者不同记录真实情况。

PowerShell 核验示例（路径按实际放置改）：

    Get-Item 'D:\agent-client-staging\opencode-zcode\ZCode\desktop\extracted-installer\application\resources\glm\zcode.cjs' | Select-Object FullName,Length
    Get-FileHash -Algorithm SHA256 'D:\agent-client-staging\opencode-zcode\ZCode\desktop\extracted-installer\application\resources\glm\zcode.cjs'

无 Windows 依赖的摘要核验也可用 Python hashlib.sha256 按块读取，不需执行 CJS。

## 二、只做机械提取，不运行未知安装包

**P0：发行结构证据**
- 先确认采集已有 app-64.7z/application/resources/app.asar 及已抽目录。优先使用留存完整 extracted-installer/application；缺失时可用受控解包工具查看 NSIS 结构（7z、asar 专用解包工具），**不需要安装/运行 EXE**。
- 递归枚举 app.asar、app.asar.unpacked、resources/glm、node_modules 及 browser extension/assets：输出相对路径、文件大小、sha256、文件类型、asar inside/outside、source map 标记；忽略资产内容，仅报告 package name/version/license。输出 FILETREE.tsv、PACKAGES.tsv、PACKAGE-SUMMARY.md、ASSET-HASHES.txt。
- 提取 Appx/PE/Electron/NSIS 产品版本/签名/包信息，具体 UI/main/renderer 主入口所在相对路径，输出 RELEASE-METADATA.md；“publisher 签名有效”必须有本机 Authenticode 或官方可信签名证据，不能仅写清单 SHA。

**P1：同版 CJS 扫描（必须单独研究，不靠旧版源码猜）**
- 原样保留 zcode.cjs，不把 15MB 全量复制进 Git 的报告目录（已有 Release）。读取其文本，不在宿主执行它，不要求绕过登录/许可。
- 使用 Node/Babel、Acorn 或 TypeScript Parser 解析为 AST（以源文件能成功 parse 为前提）；若 parse 失败，留解析器版本/错误偏移、自动降级为固定词扫描，不能伪称 AST。输出 CJS-MODULE-INDEX.tsv：webpack/esbuild/Bun runtime wrapper/模块 registration if detectable、出入模块、symbol start/end byte/line-offset；对无法可靠反混淆的名称写 unknown。
- 以原始字节偏移扫描字符串（同时可记录 Unicode UTF-8 解码的字符 offset，二者不可混淆），至少命中以下家族：runtime event / session / message / child agent / subagent / task registry / background / cancellation / branch generation / context/compact / model usage / tools / MCP / skills / plugins / cron/offpeak / dynamic workflow / actor / ask / journal / SQLite / replay / concurrency / seed / rate limit / retry-after / UI/IPC / hook。输出 CJS-STRING-OFFSETS.tsv，字段 token,kind,start_byte,end_byte,utf8_decode_status,context_sha256。
- 每个候选点只提短片段（例如 max 2 KB 原字节/段、上限 8 段/家族）；去重后输出 CJS-SLICES.md（附 source sha、offset、2 行前后或等价字符上下文）和 CJS-FAMILY-HITS.json。每条标记：exact code seen / string only / unproven。若 bundles 压缩成单行，不按“行号”为精度，必须用 byte offset。
- 用 3.15.1 源文件中的稳定字符串、公开 API 方法名、数据类型、错误标识和 event names 做逐项对照；仅在 3.15.3 CJS 找到实际实现锚点时标 matched，纯字符串只能标 possible。输出 RUNTIME-DIFF-ANCHORS.md，对照每项 old source path / old symbol / new exact offset / evidence / changed|unknown。

**P2：同版 Desktop Main/Renderer IPC 与全菜单枚举**
- 定位 main/preload/renderer entry 和 chunk，列 Electron ipcMain.handle/on、ipcRenderer.invoke/send、MessagePort、HostMessageTypes、Event Types、WebSocket/RPC channels。输出 IPC-CHANNELS.tsv，必须同时列 sender/receiver/handler 字符串或 symbol 路径；只有单端找到的标 half-wired，不凭 UI 推断另一端。
- 扫所有 UI routes、sidebar/tabs、command/actions/context menu、feature flag、keyboard shortcuts、settings、agent profile、workflow artifact、MCP App components；输出 UI-SURFACES.tsv 字段 entry,action,screen,source_file,consumer,backend_handler,evidence,unknown_reason。
- 按完整链构建至少 3 份局部调用图，格式为 Mermaid 或 DOT：Agent Send→Model→Tools→Subagent→Background→Parent；CreateWorkflow→ChildScript→AskScheduler→SQLite→Replay；MCP App→Sandbox→MessagePort→Host→Model Context。输出 TRACE-3153-*.md，每个箭头至少需 exact file and offset。找不到的箭头标 UNKNOWN，不画为事实。
- 特别核对 3.15.3 发布公告的“并行 Agent / 高并发模型请求失败修复”：列 error/connection retry/transport policy 的新证据位置，若不能与 3.15.1 明确 diff 则标 undecidable。

**P3：在不污染任何真实用户数据前提下可选运行验收**
- 如确有干净测试工作区、受授权的安装环境，可用全新空会话启动 ZCode v3.15.3，抓匿名事件、PID、任务生命周期、journal 状态与 UI screen；账号、cookie、key、用户会话数据与个人文件**一律不采集**。无需强制登录才能完成机械 P0-P2。
- 最少测试：一条工具调用的 queued/executing/settled；一个前台转后台 agent；并发四个子 actor 的 status；host 进程断开后的 stopped/interrupted 区分；重启 resume；插件 UI 如果有无需敏感权限的演示。把**实际未跑**项目留为 NOT_RUN，不能合并为 PASS。

## 三、提交格式/证据约束

新增文件统一：
- extracted-3153/README.md（系统/提取工具/版本/输入 SHA / 输出名与数目/未解决）；
- extracted-3153/FILETREE.tsv、PACKAGES.tsv、ASSET-HASHES.txt、RELEASE-METADATA.md；
- extracted-3153/CJS-MODULE-INDEX.tsv、CJS-STRING-OFFSETS.tsv、CJS-SLICES.md、CJS-FAMILY-HITS.json、RUNTIME-DIFF-ANCHORS.md；
- extracted-3153/IPC-CHANNELS.tsv、UI-SURFACES.tsv、TRACE-3153-AGENT.md、TRACE-3153-WORKFLOW.md、TRACE-3153-PLUGIN-UI.md；
- extracted-3153/EXTRACTION-LOG.md（命令、工具版本、退出码、错误、不能提取的原因、是否存在 false positives）。

若部分文件不适用，可建 1 行带表头并写 reason=N/A 在 README；**不能编造 offset、路径、SHA 或成功数**。脚本若出现大量匹配行，可只提交全量可复算 TSV 文件和摘要，不把 15MB CJS 全粘入 Markdown 导致研究会话爆炸。GitHub commit message research(zcode): extract 3.15.3 evidence，push 同一独立分支，返回完整 SHA 与各文件入口；禁止向 main、现有分发 Release 或任务书分支推送业务修改。

## 四、本地执行者交回后主研究人员继续做的部分

1. 审核 ASSET-HASHES 与 CJS byte offset 可重复计算；不接受只给词频/网上介绍的“逆向”。
2. 对照本目录 DISCOVERY-LEDGER ZCODE-001..027，分别把 S(3.15.1) 升级为 S(3.15.3)、保留 U、或发现矛盾；增加新的 ZCODE-028+ 能力，标来源。
3. 新增真正的 3.15.3 UI→IPC→Host→Runtime→DB 追踪、逐功能 Atlas main 缺口，更新 START-HERE 和 REUSE-CANDIDATES；不得自动修改 Atlas 正式代码。
4. 如果提取失败，仅交证据不足项清单和**下一条更精确本地命令**，不要用推测填报告。

研究移交给本地 Codex 时可以直接让它打开本文件与统一 PROTOCOL，**不需要另写概括任务书**。

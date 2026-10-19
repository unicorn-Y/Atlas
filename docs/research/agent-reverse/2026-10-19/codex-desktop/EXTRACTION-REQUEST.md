# EXTRACTION REQUEST — 本机 Codex 只做机械取证，不代替研究

## 状态更新（2026-10-19）

原始机械包/文件树请求已在本研究会话以已有精确原始包材料完成：输入 MSIX size 和 SHA 与请求完全一致；REA 解包校验 3,651 regular files、2,346,419,207 bytes、零提取 mismatch。已静态抽取 35 个 `.vite/build` JS 模块和 41 个定向 webview chunks。**不再需要重复下载或重复解包同一资产。**

仍待补采，但不是这份机械请求的已完成内容：

1. 完整 `app.asar` 深析（REA 超时；观察到其外置 `better-sqlite3.node` 与 ASAR integrity manifest 不一致，需保留此状态，不应直接修补或重打包）。
2. 组件名/交互动作覆盖全部 20,362 webview assets，并闭环一项具体 UI action → preload/main IPC → JSON-RPC → app-server 请求/通知 → renderer state。
3. 若获准且有隔离 Windows 环境，对无真实账户/用户数据的启动与功能做 R 级运行观察，记录进程树、命令行（去敏）、pipe/socket 类型和版本握手；不要在此文档放入 token、Cookie 或私有对话。

目前只可报告 S 级静态包证据，应用未启动（R=0）。`IMPLEMENTATION-TRACE.md` 与 `EVIDENCE-INDEX.md` 是后续研究分析入口，不代表本 extraction request 要求本机会话只机械上传完就结束。

**重要**：本研究会话已经创建分支 research/agent-reverse-20261019-codex-desktop，并完成 App Server 源码和 Atlas main 对照。请本地 Windows Codex **只提取、机械索引、上传小体积证据**，不要总结能力/自行写研究报告/改业务代码，不要自动运行登录的用户程序、上传 Token/Cookie/对话或完整私有用户数据。

## 准确输入

- 私有 GitHub repo：unicorn-Y/Atlas；分支：research/agent-reverse-20261019-codex-desktop。
- 官方采集资产：https://github.com/unicorn-Y/Atlas/releases/download/agent-client-packages-20261019/ChatGPT-x64.msix
- 文件 size：948993815 bytes。
- SHA-256：e2d892e6c22310e4b1a2928b0d3a29a066e0863d3a333754d6585c77cdafbe7f。
- Package Identity：OpenAI.Codex；Version：26.1013.4894.0。
- 解包主入口 app/ChatGPT.exe，辅助 app/resources/codex-command-runner.exe。
- 输出到当前研究分支的 docs/research/agent-reverse/2026-10-19/codex-desktop/evidence/，不修改其它目录（尤其 main、程序源文件）。

## 机械步骤（优先，本机 PowerShell）

在本地独立工作区执行；如 D:\Atlas 有其他会话的未提交工作，创建 worktree，不覆盖它们。建议脚本如下；命令如 Windows 环境版本略有差异，可就地调整，**把实际执行命令/错误记录到提取日志**。

    $ErrorActionPreference = "Stop"
    $Root = "D:\Atlas-codex-package-research"
    New-Item -ItemType Directory -Force $Root | Out-Null
    gh release download agent-client-packages-20261019 -R unicorn-Y/Atlas -p "ChatGPT-x64.msix" -D $Root
    $Msix = Join-Path $Root "ChatGPT-x64.msix"
    (Get-Item $Msix).Length
    (Get-FileHash $Msix -Algorithm SHA256).Hash
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Expanded = Join-Path $Root "unpacked"
    New-Item -ItemType Directory -Force $Expanded | Out-Null
    [System.IO.Compression.ZipFile]::ExtractToDirectory($Msix, $Expanded)
    $Zip = [System.IO.Compression.ZipFile]::OpenRead($Msix)
    try {
        $Zip.Entries | ForEach-Object { "$($_.FullName)$([char]9)$($_.Length)$([char]9)$($_.CompressedLength)" } | Set-Content -Encoding utf8 (Join-Path $Root "msix-tree.tsv")
    } finally { $Zip.Dispose() }
    Get-ChildItem $Expanded -Recurse -File | Sort-Object FullName | Select-Object -ExpandProperty FullName | Set-Content -Encoding utf8 (Join-Path $Root "unpacked-files.txt")
    Get-Content (Join-Path $Expanded "AppxManifest.xml") -Raw | Set-Content -Encoding utf8 (Join-Path $Root "AppxManifest.xml")
    Get-Item (Join-Path $Expanded "app\ChatGPT.exe"), (Join-Path $Expanded "app\resources\codex-command-runner.exe") | Select-Object FullName,Length,VersionInfo | Format-List | Out-File (Join-Path $Root "executables-version.txt")
    Get-AuthenticodeSignature (Join-Path $Expanded "app\ChatGPT.exe"), (Join-Path $Expanded "app\resources\codex-command-runner.exe") | Format-List | Out-File (Join-Path $Root "executables-signature.txt")

注意：首先确认大小+SHA 一致，**不符就停止分析该包**。上面的 ExtractToDirectory 如果输出目录不空，先另起一个空目录，不删除用户文件。只读解包；禁止改签名、破解验证、改 exe。

## 源码/资源的优先提取

1. 对 app/resources 和全包再生成层级索引：各 extension、文件数、字节数、入口 HTML/JS、asar、pak、dll、node、wasm、map、SQL/JSON/db schemas、localized resources。复制公开的无敏感 AppxManifest、package.json、ASAR 解包清单、明显的预置 UI schema；对于闭源大型资源保留**短上下文摘录+文件路径+文件 SHA**，不要上传几百 MB 的二进制/整包。
2. 如果有 app/resources/app.asar 或多个 asar，用已安装的 @electron/asar、7z 或可用的等价工具机械列目录/解包到本地独立目录；记录工具版本和命令。不存在则报告“不存在”，绝不假装 Electron。
3. 对 bundle JS/HTML/TS/JSON/CSS 做关键词与导出分析，生成按文件/模块归属的精确报告：message/messageType、component registry、render、card、action、widget、mcpAppUi、resourceUri、webview/iframe、electron IPC、runner/spawn/stdio/pipe/websocket、handshake、thread/turn、queue/review/approval、worktree/automation、plugin/App/skill、update、feature gate、persist/state/session；每个命中至少给相对路径、行/偏移、周围短段、相关 import/callsite。对压缩 JS 先切 bundle 模块/反混淆索引，仅机械展开；绝不可只上传一个巨大 grep 字符串清单。
4. Source map（若存在）列 count/paths 并解出精确 module names、sourcesContent 映射；只上传少量与 UI 入口/动作有关的短摘录以及 module map；如果是官方已公开源码可附 commit 和 URL。
5. 对 ChatGPT.exe 与 codex-command-runner.exe 作 PE 版本资源、hash、签名、imports、strings/RTTI/静态协议关键词的**受限索引**。可用工具：dumpbin /imports 或 sigcheck / strings64（如可用）；无工具就输出缺口，**不把 strings 推断为函数实现**。尤其看 runner 是 helper、PTY command, pipe server, spawn child 还是其他；当前未知。
6. 从解出的入口和所有 IPC/事件注册处**双向**索引：renderer action→host bridge→executor→storage；又从 process launch/handler/event→UI callsites。把入口追踪表放到 evidence/CLIENT-ENTRYPOINTS.md，每项符号和短引用；所有猜测标 unknown。

## 可交付目录（只上传精简/去敏证据）

    evidence/
      PACKAGE-VERIFY.md
      msix-tree.tsv
      AppxManifest.xml
      BINARIES-AND-STRINGS.md
      ASAR-AND-BUNDLES.md
      FRONTEND-MODULES.md
      CLIENT-ENTRYPOINTS.md
      IPC-RPC-EVENTS.md
      COMPONENT-REGISTRY.md
      FEATURE-FLAGS-AND-UPDATER.md
      EXTRACTION-LOG.md

每份非空；不适用则写无该形态及检查方法。附工具命令、文件 SHA、版本、相对路径、起止行号或 byte offset。不上传凭据/本机真实对话数据、Profile、登录态或堆转储；如果输出泄露内部私密信息先裁剪。尽量小而完整的引用，保留原始包在本地供复核。**研究报告文件（START-HERE、LEDGER 等）由本 ChatGPT 负责，不要代写。**

## 可选 R 级运行数据（不阻塞静态提取）

只有在可隔离的测试配置和用户已授权运行时，观察启动前后 Process Explorer / TCPView / loopback/命名 pipe/启动命令、切换会话、审批卡、任务退出与恢复。只采测试线程生成的去敏事件 schema、时间戳和状态流；不要导出真实对话/口令/网络令牌，不开启无法控制的全局抓包。此步骤没有条件可标 U。

## Git push

使用单独 worktree 指向**既有** research/agent-reverse-20261019-codex-desktop，不要另开分支；先 git fetch origin，并确认不会覆盖别的会话在本分支的最新研究提交。只 stage evidence/。commit 信息：research(codex-desktop): attach verified MSIX static extraction evidence，然后 git push origin research/agent-reverse-20261019-codex-desktop，返回 commit SHA 和 evidence/CLIENT-ENTRYPOINTS.md 链接。本地 Codex 不得修改 main 或覆盖本会话已提交的报告。

**完成后由本研究会话重新阅读证据，升级 CODEX_DESKTOP-NNN 等级、沿真实组件/IPC 深挖。**

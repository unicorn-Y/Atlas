# 固定包取证任务书与执行状态（2026-10-19）

**原始取证要求已由本 lane 执行并分阶段推送。** 任务条目保留为验收清单，当前状态以文末执行记录和 `evidence/README.md` 为准；不再处于“等待提取”的初始阻塞状态。

## 固定输入
- 仓库 `unicorn-Y/Atlas`。
- 工作分支 **仅** `research/agent-reverse-20261019-claude-desktop`。先 `git fetch` 并 checkout 当前分支的最新 HEAD，避免覆盖本会话已有报告；如本地工作树已有更改，不可强制 reset。
- 归档：<https://github.com/unicorn-Y/Atlas/releases/download/agent-client-packages-20261019/claude-desktop-x64-2bf309665f.msix>；已经在采集电脑缓存时优先复用本地 `claude-desktop/Claude-2.42304.0-x64.msix`。
- 必须先核对 **SHA256 `2bf309665f0de4eaa76a7e64033594e6f73ceb6413c60080f72f3ce640fa24ee`**、size 297191037。若不符立即标阻塞，不用“最新版”代替。
- 不启动登录应用、不读取用户账号/会话/Token/Cookie/电脑私有目录、不绕过签名/认证；仅处理用户合法取得的安装包。
- 输出全部位于 `docs/research/agent-reverse/2026-10-19/claude-desktop/evidence/`，不要修改 Atlas 程序源码。不要把整份闭源 app.asar、完整 unpacked JS 或 EXE 重新提交仓库；上传**文件索引、调用点短片段、符号、参数模式、哈希和可复查定位**即可。

## Stage 1：真实解包/身份（必做）
1. MSIX 是 ZIP 容器：用 7-Zip / `python zipfile` 解开到本地临时目录；输出按路径/大小/SHA256 的 `msix-tree.tsv`，和 `AppxManifest.xml` 的可公开关键字段（包 identity、main executable、fullTrust/extension declarations），以及验证摘要 `identity.json`。
2. 定位全部 `*.asar`、`*.asar.unpacked`、`cowork*.exe`、`*.dll`、`*.pak`、`*.map`，记录实际路径/大小/hash。**如果任务书给定路径与实物不符，用真实路径纠正**。
3. 用本地 `npx --yes @electron/asar list <真实 app.asar>` 列全体 ASAR 路径生成 `asar-tree.txt`；解压到临时目录而不是将完整代码推 Git。列出 package.json main、Electron main、preload、renderer HTML/JS/CSS、source maps。另出 `entrypoints.md`：实际 main 入口 + script imports + 加载哪些 URL/webview/window。

## Stage 2：可分析代码摘录（必做）
4. 在解包 JS/HTML/CSS 中**全目录扫描**注册定义和引用：`ipcMain.handle/on`, `ipcRenderer.invoke/send/on`, `contextBridge.exposeInMainWorld`, `BrowserWindow`, `webContents`, `child_process.spawn/exec/fork`, `WebSocket`, `fetch`, `EventSource`, `grpc`, `protobuf`, `localhost`, `named pipe`, `sqlite`, `IndexedDB`, `localStorage`, `zustand`, `redux`, `cowork`, `mcp`, `tool`, `task`, `subagent`, `resume`, `checkpoint`, `permission`, `feature flag`, `experiment`。
5. 如已混淆/打包到少量巨大 JS 文件：用 source map（若存在）还原模块索引；否则用 JS parser / prettier 机械格式化，将**每一个 match 对应 ±15~30 行短引用、文件路径、字节/字符 offset、原文件 SHA**写到 `trace-snippets/*.md`。注意每份源码的重发布版权：只保留实现链路所需少量片段，不要拷整段大文件。
6. 生成结构化 `ui-route-action.tsv`（route/component/action/callback/IPC or endpoint/state write/source file+offset）、`ipc-map.tsv`（direction/channel/registerer/caller/params/response/error/filename+offset）、`runtime-map.tsv`（tool/agent/task/event/handler/state/persist/recovery/filename+offset），每项必须从真实声明+引用自动关联；无法关联留空。
7. 查出所有 task cards、clickable step/actions、prefill flows、context panes、artifact editors、subtask views、progress/notification hooks 的 render 位置和回调；不局限已给关键词。把 event type / state union / reducers 列 `event-schema.tsv`。

## Stage 3：Cowork service（必做）
8. 对真实 `cowork-svc.exe` 做**纯静态** PE headers/签名、imports、sections、版本、Go/Rust/.NET 识别（如能可靠识别），可用 `dumpbin /imports`、`llvm-readobj` 或 Python `pefile`；可选 `strings` 和 `llvm-objdump`。输出 `svc-identity.json`、`svc-imports.txt`、与 IPC/RPC/VM/db/cache/start/stop/health/log/tool 相关的 `svc-symbols.tsv`。strings 仅是字符串，不算执行链证明。
9. 回到 main/preload 代码搜索真正怎样 **spawn / install / connect / stop / recover** 这个服务，列“父进程→参数→transport→受信/权限→事件上报→保存/恢复”短摘录和定位。列出 service 有无注册 HTTP/WS/gRPC/pipe/socket 的**证据**；不能把字符串等同可用功能。
10. 识别 cloud/local 模式分支、是否是旧 VM 兼容代码、什么 feature flag 决定执行所有权。不得从“存在 exe”推导“所有 Cowork 都本地跑”。

## Stage 4：最小动态抽样（仅测试环境允许时）
- 独立空白 Windows test profile，无用户历史；只做启动、关闭、最小化、重开、非隐私测试任务/断网的进程/本地服务观察。记录 task ID（脱敏）、UI 操作步骤与事件时间线；不需要大规模自动回归。
- 若运行需要私人登录或付费账号、设备策略/地区限制，就标 `U`，不要求绕过。

## 输出与提交
- 必填 `evidence/README.md`：静态/动态完成了哪些，源文件版本/hash，无法抽出哪些，严格区分 S/R/U。
- 输出 `msix-tree.tsv`、`asar-tree.txt`、`entrypoints.md`、`ipc-map.tsv`、`ui-route-action.tsv`、`runtime-map.tsv`、`event-schema.tsv`、`svc-identity.json`、`svc-symbols.tsv`、`trace-snippets/`（不存在/失败项注明原因，不能造空白“完成”文件）。
- 完成一个小阶段就 `git add docs/research/agent-reverse/2026-10-19/claude-desktop/evidence && git commit && git push origin research/agent-reverse-20261019-claude-desktop`。
- 返回 **commit SHA + evidence/README.md 路径 + 真实抽取件数 + 关键阻塞**；之后由本 ChatGPT 会话进一步逐模块实证追踪，并增补前述报告。

## 2026-10-19 执行状态（不删除原要求）

- Stage 1：固定 MSIX、SHA/size、manifest identity、4,443 条文件树与 548 条 ASAR 路径列表完成；入口清单识别 package main、main/preload/renderer。ASAR companion 某 native addon 解包存在 `%40ant` 编码路径不匹配，但 ASAR 静态分析已直接进行。
- Stage 2：全包静态解析得到 437 个 JS、15 BrowserWindow、1,535 IPC操作（动态通道占多数）；已闭合 Cowork artifact runScheduledTask/MCP tool handler 与 legacy VM client 的部分协议链。仍未完成 exhaustive handler/caller/params、所有 routes/state、event union 与跨会话恢复。索引中的 U/空值保持未解决。
- Stage 3：cowork-svc PE/签名/imports/Go/Hyper-V 静态元数据完成；main bundle 已追到命名管道协议和 fail-closed native connector gate。service 安装/启动父进程、Go handler 完整 body/call graph 尚 U。纯字符串项不当作执行链。
- Stage 4：未运行应用或服务，R=0；没有采用用户账号或私人配置。
- 禁止把本 checkpoint 视作 COMPLETE。后续继续从 IPC handler pairing、worker/runtime、service function call graph、Atlas 同主题源码对照推进。

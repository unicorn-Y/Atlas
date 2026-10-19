# Codex CLI / Code Mode Host Windows 二进制最小机械取证请求

## 2026-10-19 接管续工状态

**状态：EXACT_ASSETS_RESOLVED。** 原请求中的 CLI ZIP、Code Mode Host ZIP 与固定源码 ZIP 均从本机既有归档缓存读取，并逐一重算大小和 SHA-256，三者与 `manifest.json` 完全匹配。两个程序包已真实展开；安全执行的仅是 CLI `--version`、CLI `--help` 和 Host `--help`，完整结果、二进制清单、逐文件 tree/hash、导入库和字符串偏移分别见同级 `extractions/`。原请求下列不可执行/待观察项已更新：没有 `dumpbin`，以局部只读 PE parser 读取导入表；未发现 voice/CLI 私人数据，也未做会话登录或发起 Agent turn。**运行时 RPC/gRPC 交互、认证后行为、断线/取消和恢复仍为 U；本状态不是端到端运行验收。**

本次运行记录：Windows 11 Pro 10.0.26200 x64，2026-10-19 Asia/Hong_Kong。可复核报告：`extractions/ARCHIVE-HASHES.json`、`EXTRACTED-TREE.txt`、`BINARIES.json`、`CLI-HELP.txt`、`HOST-HELP.txt`、`PE-IMPORTS.txt`、`SYMBOL-STRINGS.txt`、`EXTRACTION-STATUS.md`。

**触发原因**：本 ChatGPT 会话通过 GitHub 接口读取了固定版本 Rust 源码，但 GitHub 连接器只返回有限 UTF-8 文本，无法下载/解包 EXE ZIP 的真实二进制字节或在 Windows 启动。以下任务只让本机 Codex **提取并上传证据**；由本 ChatGPT 继续判断机制。禁止 Codex 自行脑补研究结论或重写主报告。

## 执行人、分支、目录

在拥有 GitHub Release 访问权限的 Windows 开发机上执行；仓库 D:\Atlas，分支 **research/agent-reverse-20261019-codex-cli**（先 fetch + checkout 本分支，不得切 main 写入）。
唯一输出目录：docs/research/agent-reverse/2026-10-19/codex-cli/extractions/。
禁止修改其他路径/业务代码，禁止保存/上传用户凭据、授权数据、聊天记录、个人文件、任何 Codex 登录配置。不要运行有副作用的 Agent 任务，动态采集仅可执行 --version/--help；不做复杂测试。

本阶段两个精确目标（manifest 原值）：

1. https://github.com/unicorn-Y/Atlas/releases/download/agent-client-packages-20261019/openai-codex-cli-x64-dabdb4d16a.zip
   期望 ZIP SHA256：dabdb4d16aaf10fea40b74811c96efddcd9138f122163b69ed604fcb3eb704c3；size 167080091 bytes。
2. https://github.com/unicorn-Y/Atlas/releases/download/agent-client-packages-20261019/openai-codex-code-mode-host-x64-bc82fa6d8f.zip
   期望 ZIP SHA256：bc82fa6d8f449c818292eac35bd7400c4f7dae08908fc9bc67bfbad8c4a3de68；size 28217604 bytes。

固定源码参考 ZIP（可选只验证摘要、不复制 9176 文件到研究分支）：
https://github.com/unicorn-Y/Atlas/releases/download/agent-client-packages-20261019/openai-codex-source-36fda4e61c.zip
SHA256：36fda4e61c251d805c2d68203c3a34b0f6881a88846e12776ca02fb13d6e67c7。
对应上游固定 Git tag rust-v0.163.0，commit 83086188ae0614bd882818ff1aa23f3194962012。

## 可直接执行的机械步骤（PowerShell 7，按机上工具适配）

1. 从 Release 拉两个 ZIP 到一个 **仓库外** 临时目录（例：$env:TEMP\atlas-codex-cli-evidence），不要将大二进制再写 Git 仓库。GitHub 登录访问走现有 gh CLI 的 gh release download，不把 token 复制出来；若无 gh 则手动用 GitHub UI 下载。
2. Get-Item 记录 filename、Length；Get-FileHash -Algorithm SHA256 记录 ZIP 哈希。**任何一个不符合上面的期望值则立即停止，报告 HASH_MISMATCH；不能继续把不同包当 0.163.0**。
3. Expand-Archive 各解到临时目录。Get-ChildItem -File -Recurse 列相对路径、大小、SHA256；单独确认 CLI zip 约 47 个条目、Host ZIP 约 1 个（以真解包结果为准）。
4. 对 CLI 和 Host 真实 EXE 分别采集：
   - Get-Item ... | Select-Object Name,Length,@{Name='FileVersion';Expression={$_.VersionInfo.FileVersion}},@{Name='ProductVersion';Expression={$_.VersionInfo.ProductVersion}}；
   - Get-AuthenticodeSignature，并记录 Status、SignerCertificate.Subject（有签名不等于一定是 OpenAI 构建；不要因此宣称等价）。
   - dumpbin /headers /imports /exports（只有 VS 工具已安装才执行；未安装写 NOT_AVAILABLE，不安装重量依赖）。
   - 可用时，用 Sysinternals strings64.exe（或现成安全 strings 工具）提取最多 300 条有命中证据的字符串（例如 grpc+stdio、code-mode-host、exec、rollout、session、thread、tool、otel、transport、upgrade、v8、HTTP/2、feature），每项注明 EXE 名+偏移+文本；不能将巨量通用字符串输出整个仓库，也不附用户数据。
5. 不启动需要认证或联网的功能。只执行 CLI EXE --version、--help，Host EXE --help（each with 10s cap），保存 stdout/stderr、exit status、elapsed_ms。命令可能不支持：记录原样，禁止反复试到成功。标记“源代码参数”与“真实包 help”是否一致。
6. 采集 Windows 下进程实际名称与 Host 是否为单独 exe 的发行包结构；仅通过静态 import/strings 和 --help **不宣称**已抓到实际 Code Mode gRPC 流量。实际 IPC/故障恢复要后续专门经授权的无凭据测试记录。
7. 输出文件（UTF-8，必须标注本机提取时间、Windows 版本、执行的原命令、是否失败）：ARCHIVE-HASHES.json、EXTRACTED-TREE.txt、BINARIES.json、CLI-HELP.txt、HOST-HELP.txt、PE-IMPORTS.txt（可空但写理由）、SYMBOL-STRINGS.txt、EXTRACTION-STATUS.md。每个证据必须关联 Archive 名与 SHA。
8. 严禁包含私密环境变量值、GitHub token、OpenAI 密钥、session rollout、~/.codex、聊天内容。检查后 Git add **仅** extractions/ 文本/JSON，git commit，再 push 当前独立分支；回传 commit SHA。不要上传 exe/zip 本体（Release 已有）。不得顺手改报告、main 或其他研究分支。

## 这轮取证对接的待定问题

- 当前 Windows CLI ZIP 内真实入口 EXE 的文件名、版本、imports、关联 companion 资源、是否有 Code Mode Host 的启动路径。
- Host ZIP 单 EXE 是否接受 grpc+stdio://、grpc://、legacy framed stdio，在 Windows 上真实 --help 有什么可见 transport 参数。
- source tag 的 Rust 路径只是源码存在还是与已发布 EXE 具体相符；初次文件/版本/字符串关联只能增强证据，还不能做完运行级验证。
- 如果二进制内无符号，明确报告 stripped。不要捏造函数偏移。
- 如果 Windows EXE 需要账户才能运行 agent，不做登录或执行来“补齐”，保持 U 状态。

本机 Codex 是**机械采集者**，研究判定由本会话后续做。此请求本身属于提交成果的一部分。

## 二次续工附注（G0–G7）

已按新完工门槛继续做 release runtime smoke，而非重复下载/help：隔离 CODEX_HOME 下真实 CLI app-server JSON-RPC initialize/thread/start/turn-start；以及真实 Host legacy framed stdio V1 hello。观测范围和未通过部分见 `END-TO-END-TRACES.md` / `FINISH-GATES.md`。没有模型/工具完整结果，没有账户凭据，也没有运行已有用户会话。

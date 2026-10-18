# Codex 任务书｜Agent 客户端、引擎与扩展原包集中采集（2026-10-19）

> **执行人：Codex / Luna high（可以并行子代理）**
> **任务性质：原始资料采集、归档和机械提取，不是功能调研，也不是 Atlas 开发。**
> **仓库：`unicorn-Y/Atlas`**
> **工作分支：`research/agent-client-packages-20261019`**
> **优先级：现在执行；一轮做完后直接 push，通知审查方接手拆包。**

## 0. 为什么做

之前只调查了厂商文档或桌面 UI，遗漏了客户端打包的真实代码、后端 Agent 引擎、CLI、扩展和插件。现在需要**尽可能完整地收齐实际软件发行包**，交给后续审查方逐个拆包、分析机制、对照 Atlas。不能因为用户只提了某项功能就只下载该功能有关的程序。

**本轮完成的含义仅是：下载、验证、上传、列清版本与文件位置。** 不允许把“拿到安装包”写成“功能已调研/已吸收/Atlas 已实现”。

## 1. 目标范围与采集顺序

先做 P0 的所有产品，再做 P1。**Windows 11 x64 的最新稳定正式发行版优先**；如某个独特的新机制只在公开测试版，额外收测试版并明确标注。查下载当天的最新版本，**不要把本文日期当成版本号**。对功能来源不是 Windows 客户端的，还要取原来的 CLI/引擎/扩展包。不要机械地给所有产品都下载 Mac/Linux 安装包；确有独有实现才补。

### P0：必须逐一处理（桌面端 + 实际 Agent 核心）

| 产品 | 必收对象 | 官方/上游起点 |
| --- | --- | --- |
| **Claude** | Claude Desktop Windows x64 原安装包；能独立获取的 Claude Code CLI Windows 发行内容/扩展，以及版本和资源清单。区分 Desktop Chat、Cowork、Code 与 CLI 代码位置 | https://claude.com/download ；官方 Claude Code 安装文档 |
| **OpenAI Codex** | Windows **Codex Desktop App**（不是 ChatGPT 普通桌面端，也不是只下 CLI）；官方可取得的 MSIX/MS Store 安装包或已安装的程序包副本；`openai/codex` 最新稳定 CLI Windows 二进制/发行包和源码快照或 commit | https://openai.com/index/introducing-the-codex-app/ ；https://github.com/openai/codex/releases |
| **OpenCode** | OpenCode Desktop Windows x64、当前发行线的 CLI npm/binary、项目源码快照/固定 commit；如果存在新版 v2 要认准当前官网，而非过期仓库 | https://opencode.ai/download ；https://github.com/anomalyco/opencode |
| **ZCode** | 官方 ZCode Windows x64 桌面安装包、Agent CLI/Runtime 发行物、对应源码 commit；注意不要用同名第三方项目代替官方产品 | https://zcode.z.ai/en/docs/install ；https://github.com/zai-org/ZCode |
| **DeepSeek Harness (DSH)** | **官方核心引擎** `@deepseek-ai/dsh` 的当前 npm tarball、官方 `deepseek-ai/deepseek-harness` 源码固定 commit、官方 Web UI 构建产物；再额外收 DSH 社区桌面封装，不得将封装误判为官方 Harness 源码 | https://github.com/deepseek-ai/deepseek-harness ；https://www.npmjs.com/package/@deepseek-ai/dsh ；https://github.com/dongdong-agent/DSH-Desktop ；https://github.com/anywhere-labs/dsh-desktop |

**特别注意：**如果 Microsoft Store 提供的 Codex 桌面包无法通过常规方式导出，优先利用合法可用的 Store/winget 包获取方式，或采集本机已安装应用的程序目录中可读取的**程序文件**，明确标记该项为 `installed-files` 而不是 `official-installer`。不要假装 CLI 发行包就是桌面安装包，不要绕过登录/付费/DRM。

### P1：同批次扩展，避免只局限熟悉的五家

| 对象 | 重点 |
| --- | --- |
| **Cursor** | Windows x64 桌面客户端 + 可单独获得的 Agent CLI/扩展；https://cursor.com/download |
| **Windsurf** | Windows x64 客户端和独立 Agent/扩展发行物；使用当前官方站点核验 |
| **Cline、Roo Code、Kilo Code、Continue** | 官方 VSIX/npm 包、宿主扩展代码、后端或 Agent runtime（如果单独发布）；官网/官方 GitHub Releases/VS Code Marketplace/Open VSX |
| **Hermes Agent、Pi、Goose 等** | 正式发行的 CLI/桌面/服务端/运行时包、当前官方源码快照和依赖位置；如果没有安装器，不要编造安装器 |
| **其他重要项目** | 在官方下载/官方仓库中发现真正有不同 UI 或底层机制的 Agent、组件宿主、工作台或扩展生态时主动补充到 candidates 表并尽可能获取发行物。不要仅因本文没有列名就忽略 |

插件/Skills/MCP 生态：优先获取**宿主可实际加载的代表性 UI 插件、可视化、Token/上下文工具、子任务观察工具的发行包或源码 commit**，并单独记录“扩展提供，不是宿主原生”。这些只是举例，不是只找这几种。

**来源优先级：**官方下载安装页 → 官方 GitHub Releases/Registry/Marketplace → 已确认的官方源码仓库 → 明确标注身份的社区项目。第三方“绿色版/破解版/重打包包”不用。每个包记录真实厂商与 upstream repo，不把社区封装写成官方。

## 2. Codex 应执行的工作

1. **查当前版本并建目录。** 自动解析官网真实下载目标、GitHub Releases、npm registry、VSIX 发行地址。记录下载日期、平台架构、稳定/预览、具体版本、URL、项目上游及选取原因；固定源码 commit SHA。遇到动态下载链接，可由浏览器实际下载并记录最终链接或官方页面。
2. **下载实际完整字节。** 除桌面安装器，还要 CLI、内嵌引擎、插件/扩展发行包及相关 Web UI 产物，避免只拿安装器小壳而漏掉安装后下载的大型 runtime。识别引导式安装器并在允许时取得其最终程序包；区分什么是原始文件、安装后的文件和开源仓库快照。
3. **做轻量机械归档。** 对每个文件计算 SHA-256、字节数并记录文件格式（EXE/MSIX/ZIP/ASAR/VSIX/TGZ 等）；不需要繁琐测试或功能验收。归档下载器请求的版本和实际解包识别出的版本；两者不同要记下。
4. **机械提取可读证据**（为后续分析准备，**不要求在本轮研究功能**）：若有 ASAR、ZIP、VSIX、TGZ、MSIX，尽可能解出原文件树；提供每个包的文件目录、入口文件清单、Source Map 可用性、内嵌 npm 包名及版本、主要可读 JS/TS/JSON 资源位置；对无法直接提交的大型解包树，上传归档并给出其 SHA-256 和确切内部路径。**不要重新构思功能、不要提前宣称抄到了某机制。**
5. **上传到 Atlas 私有仓库关联归档。** 所有原安装包、大体积 tarball、完整解包归档等，优先上传到**该私有仓库的 GitHub Release 资产**，按产品和版本命名并确保可重新下载；建议 release tag：`agent-client-packages-20261019`，关联目标分支。不要将数百 MB 的 EXE 直接 commit 进 Git 主历史。可读的 manifest、目录索引、精简版本数据、入口文件和小型必要文本资源放入本分支的 `docs/research/agent-clients/2026-10-19/`；保留能用来追溯所有 Release assets 的地址。无法用 Release 时可考虑仓库支持的 Git LFS，不能因上传失败就宣布完成。
6. **复核可访问性。** `gh release view` 能列出所有 Release asset，随机选一个 asset 完整重新下载并校验 SHA256。逐项检查 P0 的桌面端/引擎/CLI 是否已收集，确实不存在的形态标记 N/A。被封锁或无法获取的逐项记 BLOCKED，列明确原因和已经尝试过的官方路径，不要无依据写“已完成”。
7. **push 全部索引文档**，汇报 GitHub 分支、commit SHA、Release/tag 链接、资产总数/体积、P0/P1 实际完成情况，并给出后续分析人员应该先打开的文件路径。

## 3. 文件和交付约定

Git 分支路径：

`docs/research/agent-clients/2026-10-19/`

必须提供：

- `START-HERE.md`：汇总结果、分支/commit、Release 入口、总数量与未完成清单。
- `manifest.json`：**逐个**包的 machine-readable 元数据。每项至少包含 `product`, `component`, `publisher`, `upstream`, `version`, `releaseChannel`, `platform`, `arch`, `filename`, `format`, `sizeBytes`, `sha256`, `sourcePage`, `downloadUrl`, `capturedAt`, `releaseAssetUrl`, `sourceCommit`（适用时）, `status`, `notes`；确实未知的留 null，不能填猜测。
- `COLLECTION-STATUS.md`：按产品列桌面/CLI/Runtime/扩展/开源源码五类的完成、N/A、BLOCKED 明细，官方版与社区版分开。
- `PACKAGE-INDEX.md`：每个包的重要入口路径（程序目录、app.asar、runtime、web 资源、源码映射等）及对应原包 asset，适合作为下一轮逆向研究索引。
- `SHA256SUMS.txt`：每个资产名称与 checksum。
- `DOWNLOAD-LOG.md`：无法获取、动态分发、来源重定向、鉴别和版本差异的简洁说明。
- `CANDIDATES.md`：P1 之外发现了但未取得的潜在重要产品、官方地址与原因，**不能把“尚未检查”写成不存在**。

如果分支不能容纳核心代码索引，请将该索引打 ZIP 作为 Release 资产，并在 `PACKAGE-INDEX.md` 写出压缩包内部确切路径，后续可按文件请求提取。上传的原始包不要因为成功生成解包产物就删除。

## 4. 执行纪律

- **速度优先**，按照产品分配并发 worker（例如 Claude/Codex、OpenCode/ZCode、DSH、P1 各一路），并发数量由可用能力决定；不得人为限制为单线程。
- 默认自主调用终端、网络、浏览器、文件系统和 GitHub，**不为普通下载、解压、推送重复征求用户许可**。
- 不准修改 Atlas 正式前后端业务代码、不做功能移植、不写大规模测试、不做长篇功能分析；本轮只是为下一阶段提供充分原始证据。
- 不能为了达成“完整”而捏造下载成功或版本；遇到下载失败应继续处理其他产品，最后列具体阻塞。
- 程序包和源码资源可以归档；**不上传本机 AppData 中的用户会话、API key、cookie、账号授权文件、浏览器 Profile**。不破解签名、DRM 或访问限制。优先选择许可允许的归档方法并保留第三方声明。
- 分支与 Release 资产归档完成才算交付；不能只给 Codex 本地磁盘路径，也不能只给一篇调研报告。

## 5. 最终交接

向审查方报告：

`PACKAGE COLLECTION READY: <branch> @ <commit> | Release <url> | P0 x/y | P1 x/y | blocked ...`

并明确指出 **“当前只完成资料采集，后续拆包、源码追踪和 Atlas 对比尚未开始”**。

后续由 ChatGPT/GPT-6 以这个资料库为起点进行拆包分析。若当前聊天工具无法直接提取某个巨大二进制 Release asset，可再让本地 Codex **只执行指定的机械抽取和上传**，由 ChatGPT 负责决定抽取范围、阅读内容及分析结论，而不是让 Codex 凭印象替代研究。

---

## 执行启动指令

**Codex 立即开始下载并上传，不要停留在计划阶段。自动并行 P0；完成后补 P1；每批获取就入库并 push；所有归档与索引能在 GitHub 看见为止。**

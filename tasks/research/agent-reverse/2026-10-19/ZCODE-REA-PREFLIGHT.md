# ZCode 专用：REA 逆向前版本、原包、工具链全量核验与补采（2026-10-19）

**本任务是所有产品逆向研究的前置硬门槛。先做完本任务，再启动各产品深度拆解。**
执行人：ZCode（使用已配置的 DeepSeek V4.1 Flash）。用户本地 Windows 环境；只负责 **核对最新版、资产齐全度、真实性、补采和工具链可用性**，此阶段**不进行功能逆向、不创建 Atlas 功能代码、不制作竞品功能筛选表**。必须实做，不准仅写计划。

## 0. 输入和基准
- 仓库：`unicorn-Y/Atlas`
- 任务书分支：`research/agent-reverse-dispatch-20261019`
- 现有包采集分支：`research/agent-client-packages-20261019`
- Release：`https://github.com/unicorn-Y/Atlas/releases/tag/agent-client-packages-20261019`
- 旧采集资料：`docs/research/agent-clients/2026-10-19/manifest.json`、`PACKAGE-INDEX.md`、`COLLECTION-STATUS.md`、`SHA256SUMS.txt`、`DOWNLOAD-LOG.md`、`indexes/`
- 23 份产品任务书与清单：`tasks/research/agent-reverse/2026-10-19/START-HERE.md`、`sessions/`
- 此文件是先验门禁，之后依 `ZCODE-REA-MASTER.md` 和 `ZCODE-REA-LAUNCH.md` 执行单 Agent 解剖。
- 核验日期、上游发布日期、下载时间均记录为实际绝对时间，**不能把 2026-10-19 时收集的旧版本直接宣称为目前最新**。

## 1. 核对 REA 本身是否最新、能否在 ZCode 真正工作
1. 只从官方可核验来源定位 REA：`https://github.com/morluto/rea`、`https://rea.tools` 和 npm `rea-agents`；核对项目归属、官网链接、版本、release/npm dist-tag、发布时间与本机已安装包版本。
2. 用官方适用于当前版本的方式更新 REA，记录真实 CLI 版本和命令输出；更新后核对技能说明及 MCP tool list 是否和安装版本匹配。检查 Windows / Node 版本、所需系统依赖、适用的原生逆向引擎（如 Ghidra/IDA/Hopper 等）实际是否可用。
3. 检查 ZCode 是否支持 REA 的 MCP stdio 注册；能注册则真实调用一个小型合法样本完成 REA CLI 或 MCP 烟测：工具可用、可返回证据、输出可写入本地目录。不支持就使用实际可用的 CLI 调用流程并留下命令记录。
4. **禁止只凭安装成功推断逆向可用；必须写出实际跑通哪些类别的工具、哪些类别暂缺引擎。** 缺依赖能自动装的先装；确实需要付费许可证/手动操作的记真实阻塞。
5. REA 版本与能力会变，基于当前真实 CLI --help / MCP tool list 建立 `REA-CAPABILITY-MATRIX.md`，不引用过期教程代替实测。

## 2. 全产品最新版本复核（覆盖现有所有 23 份任务书和拆出的独立产品）
**先对所有目标完成这轮盘点，绝不拿旧 PACKAGE-INDEX 的 “COMPLETE” 当最新版证明。**

每个产品以及它的每个独立组件逐项核对：
- 官方网站、GitHub 官方仓库 releases/tags、官方更新日志、发行下载链接、npm package/registry、VS Code Marketplace、Microsoft Store、winget、官方应用更新源等相关权威渠道，确认具体目标产品和渠道，避免同名非官方项目、镜像和 fork。
- 当前最新稳定版 version + 发布日期 + 证据链接；如存在 beta/RC/nightly/企业版/渠道版本，单列 `latest-preview` 和 `channel`，不混为稳定版；对于滚动发布或无版本号的，记录 commit 与时间。
- 已收集版本、SHA256、文件大小、原始发布渠道，与上游当前版本逐项比较；标为 `CURRENT` / `OUTDATED` / `CHANNEL_DIFF` / `UNVERIFIED`，不能从某平台版本推断其他平台也相同。
- 各版本之间包含可能变化的 Agent runtime、前端资源、协议和工具，不能仅因主版本号一致就认为源码与发行包一一对应。

**必须检查的产品族：** Claude Desktop/Cowork、Claude Code、Codex Desktop、Codex CLI/Code Mode Host、OpenCode Desktop/CLI、ZCode Desktop/嵌入式 Runtime、DeepSeek Harness 官方 CLI/Core/Web、两个 DSH 社区桌面项目分别检查、Cursor、Windsurf/Devin、Cline、Roo Code、Kilo Code、Continue、Hermes Agent、Goose、Pi、Zed、OpenHands Agent Canvas、Squad、ccusage、Claude HUD、Agent Skills/MCP。新发现的关联官方发行物也须纳入，不能拘泥于清单。

## 3. 每个产品到底“齐不齐”
将 **产品体系拆成实际发布的交付形态和必要组件**，而不是只确认“有一个安装包”：
- Windows 桌面安装包（针对 Windows 优先）、独立 CLI/TUI、内嵌/独立 Agent runtime、宿主服务/后台守护进程、Worker/helper、Web UI 静态资源或独立服务、插件/扩展/Skills/MCP、对应版本源码或 source map、安装后拉取的关键依赖/引擎等。
- 同产品的 Windows 包 / Linux、macOS 包有哪些差异、与 Windows 用户目标是否相关。跨平台产物如有关键特有功能则纳入采样；未采集的平台必须公开登记，不能装作“全平台齐全”。
- 通过发行包内目录/文件头/元数据快速检查确实包含承诺组件（特别是嵌入式 Runtime、asar、native 模块）；**这个阶段只做范围确认和可解包性检查，不是深入逆向**。
- 源码与发行版本要确认精确关联：tag/commit/build metadata。不能把较旧源码当成新版本真实实现。
- 将每项分类为 `AVAILABLE_COLLECTED`、`AVAILABLE_MISSING`、`NOT_PUBLISHED`、`SERVER_ONLY`、`BLOCKED`、`UNKNOWN`。服务端或远程资源无法从本地安装包提取不应被虚报为已获得，也不必无限阻塞客户端逆向。
- 来源不可信、哈希不匹配、截断文件、无法读取关键压缩包，都不能算齐。

## 4. 立刻补采和校验（不是只把缺口列出来）
- 对确实存在的官方最新版文件，直接下载、核 SHA256 / 大小 / 签名（有则检验）、版本标识、是否能列出容器成员。
- 处理旧资源过期、最新未采、Web UI/Runtime/helper/源码快照缺失。新文件与旧文件**共存**，不要删掉旧版本，方便之后做版本差异比较。
- 本地保存：`D:\Atlas-Reverse-Lab\_preflight\downloads\`、`manifests\`、`logs\`。
- 同步至仓库指定的可追溯轻量索引、manifest-v2；二进制走适当的 Release assets，避免直接塞普通 Git 历史。不能在未上传之前说仓库已同步。
- 若下载因为地区限制/账号登录/官方停止发行而受阻，尝试官方其他合法发行渠道、准确记录 HTTP 状态和候选渠道；不要用第三方可疑安装器顶替官方，也不要声称已取得。
- 每种资产写明绝对 URL、渠道、检测日期、发布版本、SHA256、实际字节数、GitHub asset 路径、本地路径、验证状态。

## 5. 硬性产物
工作分支：`research/zcode-rea-preflight-20261019`，基于当前 `research/agent-reverse-dispatch-20261019`；**不修改 Atlas 正式业务代码、不 push main**。
GitHub 输出目录：`docs/research/agent-reverse/2026-10-19/preflight/`
本地目录：`D:\Atlas-Reverse-Lab\_preflight\`。

必须写出实际数据的文件（禁止空模板）：
- `START-HERE.md`：日期、执行范围、已核实产品数、未核实数、仓库 commit、目录入口；
- `VERSION-MATRIX.csv` 和 `VERSION-MATRIX.md`：**每产品每组件每渠道** 上游 latest/current + 时间 + 已有版本 + 证据链接 + 判定；
- `ARTIFACT-MATRIX.csv`：完整的目标交付形态、应有/实有/缺失/未发布/阻塞；
- `VERIFIED-MANIFEST.json`：实际得到的文件 + 下载 URL + 实测 hash/大小/版本/发布渠道；
- `REA-CAPABILITY-MATRIX.md`：ZCode+REA 真正可用的分析能力和实际烟测结果；
- `DOWNLOAD-LOG.md` 和 `BLOCKERS.md`：补采执行记录、失败链接/原因、可恢复方案；
- `READY-TO-REVERSE.md`：每个产品 `READY` / `NOT_READY` / `PARTIAL_SOURCE`，按是否已有其当前官方客户端主包、对应关键 Runtime/前端/可用解包工具来判定；若明确是厂商未发布/远端服务端不可获，列为已知边界，不假定存在下载包。
- 如资产需要二进制归档，附 `REMOTE-ASSETS.md` 链接与上传状态。

每个表里的状态必须带具体证据，不准“应该最新版”“大概齐全”。**全清单查完、补采可取得的缺口、生成 READY 表并 push 之后，才允许按 READY 顺序启动单产品 ZCode 深度拆解。** 对某些源头确实未发布/不可取得的产品保持 NOT_READY/PARTIAL_SOURCE，不因此停止其他已经 READY 的产品；未 READY 的产品不得冒充已经素材齐备。

## 6. 交付回执
`ZCODE REA PREFLIGHT | date: YYYY-MM-DD | branch: research/zcode-rea-preflight-20261019 | commit: SHA | verified products: N/total | READY: N | NOT_READY: N | version gaps: N | asset gaps: N | REA smoke: ... | local: D:\Atlas-Reverse-Lab\_preflight\ | report: .../START-HERE.md`

结束条件是**真实完成核验+补采+落盘+push**，而不是写一份建议清单。完成预检后另开新的产品会话开始拆；本会话不直接拆任何 Agent。

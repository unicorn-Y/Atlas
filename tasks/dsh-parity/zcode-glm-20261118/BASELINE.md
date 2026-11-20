# BASELINE — 官方 DSH 发行矩阵与 Atlas 快照(2026-11-18)

> 执行者:ZCode · GLM-5.3-Flash。查证时间:2026-11-18(当日)。复现命令见 §7。本文件随批次增量更新。

## 1. 官方发行矩阵

主对标版本:**GitHub tag `dsh-v0.2.2-rc.4`**(最新 release,2026-11-17 发布)= npm `next` `0.2.2-rc.4`(同日)。

| 渠道 | 版本 | 证据 | 获取时间 |
|---|---|---|---|
| GitHub release(最新) | `dsh-v0.2.2-rc.4`(pre-release) | releases 页;发行说明:improve handling of unexpected model responses;fix LiveShare failing to create shares in desktop app | 2026-11-18 |
| GitHub tag → commit | **`3f321d32bfe382212a8ed8785c1d47a5a300aa23`**(2026-11-17 21:30:09 +0800,merge PR #8666 `worktree-release-dsh-0.2.2-rc.4`) | 本地 fetch 后 `git rev-parse dsh-v0.2.2-rc.4^0` | 2026-11-18 |
| npm dist-tag `next` | `0.2.2-rc.4`(发布 2026-11-17) | registry dist-tags | 2026-11-18 |
| npm dist-tag `latest` | `0.2.2-rc.1`(发布 2026-11-04) | registry dist-tags | 2026-11-18 |
| npm dist-tag `alpha` | `0.2.2-alpha.3`(2026-11-03) | registry | 2026-11-18 |
| npm rc.4 tarball | 2,198,896 B;sha256 `5544f3d343131eb142f79a29c3f474c54fb8aa55e5389afe895d1e1c09730884`;sha512-base64 与 registry `integrity` 字段**逐字节一致**(`sha512-DRJaTWIk…`) | 本地计算 + registry JSON | 2026-11-18 |
| npm rc.4 包元数据 | fileCount 534,unpackedSize 6,221,766;`bin: dsh → lib/bin.js`;engines node ≥24.9.0 | registry JSON | 2026-11-18 |
| 官网 Windows | `https://download.deepseek.com/desktop/dsh-latest-windows-x64.exe`;实测下载 299,595,752 B,sha256 `786c9b26050c35b62c7be6a01dee2541dc1c2c5d9bd5f2dbe77beeeb8d50704e`,**FileVersion 0.2.2-rc.3** | 下载页 + 本地哈希 + exe VersionInfo | 2026-11-18 |
| 官网 macOS | `dsh-latest-macos-arm64.dmg`(macOS 13+);按计划口径只留静态证据,未下载 | 下载页 | 2026-11-18 |
| 本机桌面 | **0.2.2-rc.2**(FileVersion/ProductVersion;Electron 44.7.0);`%LOCALAPPDATA%\Programs\DeepSeek Harness`;内置 runtime `resources/runtime`:node 24.21.0 + pnpm 11.28.5(`versions.json`),含 `bin/ cli/ primary-runtime/` | exe VersionInfo + resources/runtime/versions.json | 2026-11-18 |
| 本机桌面更新通道 | `provider: generic`,`url: https://download.deepseek.com/dsh-desk/feeds/win-x64/`,channel: **nightly** | `resources/app-update.yml` | 2026-11-18 |
| 本机 CLI | 无全局安装、无 `dsh` PATH;CLI 证据走 npm 包与桌面内置 runtime | 本机探测 | 2026-11-18 |
| `~/.dsh` 用户数据 | `profiles/{desktop,headless,web}`、`sessions/`、`storages/`、`dsh-runtimes/`(只读盘点,不动) | 本机探测 | 2026-11-18 |

npm 近端版本时间线:0.2.1-rc.4(10-26)→ 0.2.2-alpha.2(10-27)→ 0.2.1-rc.5(10-29)→ 0.2.2-alpha.3(11-03)→ 0.2.2-rc.1(11-04)→ 0.2.2-rc.2(11-12)→ 0.2.2-rc.3(11-13)→ **0.2.2-rc.4(11-17)**。

**渠道偏差**:GitHub release 与 npm `next` 同为 rc.4;npm `latest` 停在 rc.1;官网 Windows 安装包实测为 **rc.3**(滚动 latest 滞后);本机桌面 rc.2。→ 主对标取 GitHub tag rc.4;各渠道差异行为(如 Windows 应用内更新修复只在 rc.3)按各自版本取证。

### 1.1 发行包成员登记(ZC-DSH-REVIEW-01)

| carrier | 成员数 | 获取方式 | 说明 |
|---|---:|---|---|
| source-git | 21,071 | `git ls-tree -r -z --name-only 3f321d32` | 原始 UTF-8 路径(NUL 分隔);与 TSV 集合逐项相等 |
| npm-dsh-cli | 534 | `tar -tzf downloads/dsh-cli-0.2.2-rc.4.tgz` | 与 registry `fileCount=534` 一致 |
| desktop-installer | 10 | `"C:\Program Files\7-Zip\7z.exe" l downloads/dsh-latest-windows-x64.exe` | NSIS/7zip 容器成员:4×brand.bmp、window-frame.dll、dsh-7za.exe、**app-64.7z(298,410,282 B,内部载荷)**、Uninstall、2×license;app-64.7z 内部成员需解包(约 300 MB),未展开,阻塞已记录 |
| desktop-runtime | 6,136 | `find resources/runtime -type f`(本机安装 0.2.2-rc.2) | `primary-runtime/runtime.json`:python 3.12.14、node 24.21.0、payloadDigest `0881fbf6…`;pythonPackages 含 numpy/pandas/python-docx/python-pptx/openpyxl/Pillow/lxml 等(office 文档族) |

SOURCE-INVENTORY.tsv 合计 **36,536 条目 = 35,631 个文件 + 905 个目录**(内包 7z 列表的 905 个目录条目含在内;文件口径 35,631 = git 21,071 + npm 534 + 外层 10 + 内包 7,880 + runtime 6,136)。五 carrier:source-git 21,071 / npm-dsh-cli 534 / desktop-installer 10 / desktop-installer-inner 8,785 / desktop-runtime 6,136;csv 往返断言通过(每行 8 列、source_id 唯一、Git 来源恰 21,071 条且与 NUL 集合相等);命令与实际计数存交付目录 `evidence\inventory-carrier-counts.txt`(与外部 evidence 同源)。安装包三层(外层/内包/已装 runtime)已按 carrier 分开;内包仅列未解包。

验收状态对账(ZC-DSH-EXEC-03 A):ATLAS-MAP 116 条「对齐已验」逐条重查——**36 条保留**(带本会话当前树锚点+真机/测试收据),**80 条降级**(待对照标记或无验收级收据,明细 `evidence/atlas-map-audit-20261118.txt`);source_ids 规范化 721 条接 source_id 外键+35 条目录锚点+0 悬空(`evidence/source-id-linking-20261118.txt`);全表自动复验(列宽/主键/外键/悬空/队列)**0 失败**(`evidence/table-audit-20261118.txt`)。

更新通道取证(ZC-DSH-EXEC-02):本机桌面 app-update.yml 指向 `https://download.deepseek.com/dsh-desk/feeds/win-x64/`(channel nightly);实测 `latest.yml`/`latest-nightly.yml`/`beta.yml`/`alpha.yml` 均返回 404+SPA 回退 HTML,`latest.yml` 首次请求返回完整 SPA 页——**更新 feed 公开面不可达**(尝试与错误已记录;可能需应用内请求头或路径变更),夜间通道现行版本未取证。

## 2. 旧基准 → 新标签差异

- 旧基准:`d743267388641bc76f17c45ce8b4c231aed1d32c`(0.2.1-alpha.2,2026-10-09,merge PR #5946)——本地参考库 `D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness` 的 HEAD,工作树干净
- 新基准:`3f321d32bfe382212a8ed8785c1d47a5a300aa23`(rc.4)
- diff 规模(rename 检测开启,`diff.renameLimit=0`):**11,777 行 = A 6,254 / M 5,242 / D 171 / R 109 / T 1**;树规模 14,988 → 21,071 文件
- 首轮 diff 曾因 >6,308 文件跳过改名检测(得 11,831 行),已重跑;以本节数字为准
- 全量行:`UPSTREAM-DELTA.tsv`(首批任务书 A 节列式);原始输出:`D:\ENGINE-V3-UPSTREAM-20261118\evidence\upstream-delta-name-status.tsv`

## 3. 差异分层统计(按 surface,产品面为"待核"工作面)

| surface | 合计 | 归属批次 | 备注(ZC-DSH-REVIEW-01 重分类) |
|---|---:|---|---|
| 客户端/UI(packages/client 等) | 2,406 | F03-web | 不变 |
| 实验组件(packages/experimental) | 1,813 | F05-host | 不变 |
| Host/Agent | 723 | F05-host | 不变 |
| SDK/协议 | 671 | F04-cli-sdk | **+48**:python/sdk(官方 Python SDK)与 python/sdk-runtime(运行时引导)实为产品代码,自"文档"移入 |
| 插件/扩展 | 624 | F09-extensions | **+33**:vendor/cordis 等为内联组合根本体,自"第三方"移入 |
| 执行环境 | 550 | F08-tools | 不变 |
| 会话/存储 | 529 | F07-session | 不变 |
| Web/渲染(apps/web) | 412 | F03-web | 不变 |
| 桌面(apps/desktop、desktop-host) | 401 | F02-desktop | 不变 |
| 构建发版 | 304 | 仅工程变更 | scripts/ 与 .github/:用途=构建/CI/发版与目录生成工具,不随产品分发 |
| 模型/账户(llm/credentials) | 283 | F06-model | 不变 |
| packages-待归类 | 262 | F05-host(逐个重归) | 不变 |
| CLI(apps/cli) | 101 | F04-cli-sdk | 不变 |
| 权限/审批 | 79 | F05-host | 不变 |
| 文档(docs/.agents/website、python 说明文件) | 1,530 | 仅工程变更 | **−48**:Python SDK 产品代码移出 |
| 测试/快照(snapshots/benchmarks) | 1,070 | 仅工程变更 | 不变 |
| 可观察性 | 12 | F10-cloud | 不变 |
| 第三方补丁(影响产品) | 7 | F09-extensions | **新列**:patches/ 的 pnpm 补丁(node-pty/lexical/fortune-sheet/exceljs/app-builder-lib 等),自"第三方"移入 |
| **产品面小计(待核)** | **8,873** | 阶段 2 起逐批映射 | 原 8,785 + 88 重分类 |

仓库结构要点(机械盘点产物):`packages/client` 3,369 文件、`packages/experimental` 2,470;`snapshots/`(1,944)= ACP/会话回放 fixtures;`.agents/`(4,135)= 内部开发笔记与技能文档;`python/` = Python 组件文档;`apps/` = desktop 697 / web 673 / cli 203 / plugin-market-generator 20 / desktop-host 17。

SOURCE-INVENTORY 角色分布(跨四 carrier,合计 27,751):code 9,165 / doc 7,261 / test 4,393 / other 3,723(多为 runtime 二进制 .dll/.pak/.bin)/ test-fixture 1,945 / build 677 / manifest 417 / vendor-inlined 69 / native-component 50(+1 native)/ i18n 19 / vendor-patch 12 / installer-member 10 / example 9。git 来源内剩余 `pending` 处置项:other 494 行、packages-待归类 262 行,阶段 1 人工复核。

发行说明层面的新行为(需源码取证后才进 BEHAVIORS.tsv):rc.2 Git Worktree review、命名多级 SubAgents/AgentTeam、桌面稳定/开发双更新通道;rc.3 实验性 DeepSeek chat import 插件、Windows 应用内更新修复;rc.4 模型异常响应处理改进、LiveShare 桌面创建修复。

## 4. Atlas 快照(执行时)

- 分支 `wave3` @ `060071ab2ecf86d41cab90e98160183ce126bc69`;141 项未提交(77 M + 64 ??);全量 status 存 `evidence/atlas-snapshot-20261118.txt`
- 在途主路径:`core/atlas/engine/kernel/*`、`core/atlas/api/*`、`core/tests`(13 个未跟踪新测试)、`frontend/src/renderer/services/runtimeEvents.ts`、`frontend/src/types/runtime.ts`、`backend-adapter/src/types.ts`、`sdk/python/atlas_sdk/*`
- worktree 景观:wave3-x4..x7、wave4(-z1..z7、merge)、wave5(-a..d、merge)、research/agent-reverse-*(dsh-core、dsh-desktop、codex-*、zcode、opencode、claude-desktop)、fix/interrupted-tool-recovery、fix/model-capabilities-20261018;`D:\Atlas\data\upstream\staging\atlas` 等内嵌 staging 树(detached HEAD)
- 在途改动归原批次作者,本批不整理、不提交、不 reset
- 历史口径:旧 **128/135**(2026-11-15,COVERAGE-FINAL:E36/36、D33/33、S30/33、X29/33,HARD 6 + NOT-DONE 1)保留为历史数字;原子账本 `atomic/completion.json` INCOMPLETE(413,732 obligations 全 unresolved,各分项 0)

## 5. 已读取的历史证据

| 材料 | 日期 | 用途 |
|---|---|---|
| `docs/parity/DSH-GAP-LEDGER.md` | 2026-11-13 | 135 条差距、DSH 证据锚点(packages 路径+行号),阶段 2 映射直接复用 |
| `tasks/dsh-parity/COVERAGE-FINAL.md` | 2026-11-15 | 128/135 历史口径;6 HARD(S26/S30/X5/X6/X7/X30)+ 1 NOT-DONE(S10) |
| `tasks/dsh-parity/BENCH-ANALYSIS.md`、`MULTITURN.md` | 2026-11-15 | 配对实测基线:单轮 prompt −48.8%、延迟 −5~8%,8 轮后 DSH 缓存反超 |
| `tasks/dsh-parity/atomic/*`(completion.json 等) | 2026-11-17 | 原子账本机制(source-index/atomic-capabilities/interaction-edges/batch-queue) |
| `docs/glm-hammer/plans/2026-11-17-atlas-dsh-atomic-parity-and-superiority.md` | 2026-11-17 | 9 Task 主计划:验证策略、比较协议、required_superiority_set 门槛 |
| 首批任务书 `2026-11-18-zcode-glm-first-dsh-batch.md` | 2026-11-18 | A 节版本对账格式(本文件 §2/§3 复用);B 节流式取消/重试/恢复命令(待执行) |

## 6. 证据限制

- macOS 安装包只留静态证据(官网命名、系统要求)。
- 官网安装包为滚动 latest(实测 rc.3),版本以下载物 FileVersion 为准;本机桌面 rc.2 落后主对标 rc.4,桌面运行时证据一律标注实际版本。
- npm `latest`(rc.1)与 `next`(rc.4)分裂:CLI 用户实际版本因安装渠道而异,行为取证标注包版本。
- LiveShare 服务端、DeepSeek 官方 API 会话上传等云端私有实现:只记录公开可观察契约(源码 + 发行说明),服务端内部为观察边界。
- UPSTREAM-DELTA.tsv 为机械首遍(ZC-DSH-REVIEW-01 已重分类 python/sdk、vendor、patches):`behavior_id/atlas_path` 空置、`atlas_state=待核`(产品面)待批次族逐批填充;文档/测试/构建行标 `仅工程变更`,scripts//.github 判纯工程的理由=构建/CI/发版与目录生成工具、不随产品分发。
- SOURCE-INVENTORY.tsv 多 carrier(27,751 行)已过 csv 往返断言;`disposition` 已按实际用途标注(python/sdk=product、patches/=product-affecting、vendor/=product 内联、native/=product 组件、scripts//.github=engineering);git 来源剩余 pending 待阶段 1 人工复核。
- 安装包内部载荷 `app-64.7z`(298,410,282 B)未展开:外层 10 成员已列出,展开需解包约 300 MB(磁盘/时间成本),列为后续可选项。

## 7. 来源与复现命令

- GitHub releases:`https://github.com/deepseek-ai/deepseek-harness/releases`(WebFetch,2026-11-18)
- npm registry:`curl -s https://registry.npmjs.org/@deepseek-ai/dsh`(存 `downloads/dsh-npm-registry.json`)
- 官网下载页:`curl -s https://www.deepseek.com/download/`(提取 exe/dmg/apk href)
- Windows 安装包:`curl -sL https://download.deepseek.com/desktop/dsh-latest-windows-x64.exe`(存 `downloads/dsh-latest-windows-x64.exe`)
- 官方源工作克隆:`git clone --no-checkout D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness D:\ENGINE-V3-UPSTREAM-20261118\deepseek-harness` → `git remote set-url origin https://github.com/deepseek-ai/deepseek-harness.git` → `git fetch --no-tags origin 'refs/tags/dsh-v0.2.2-rc.4:refs/tags/dsh-v0.2.2-rc.4'`
- 差异:`git -c diff.renameLimit=0 diff --name-status --find-renames d743267388641bc76f17c45ce8b4c231aed1d32c 3f321d32bfe382212a8ed8785c1d47a5a300aa23`
- 文件清单:`git ls-tree -r --name-only 3f321d32bfe382212a8ed8785c1d47a5a300aa23`
- 发行包成员:`tar -tzf downloads/dsh-cli-0.2.2-rc.4.tgz`;`"C:\Program Files\7-Zip\7z.exe" l downloads/dsh-latest-windows-x64.exe`;`find resources/runtime -type f`(本机安装)
- 生成与断言:`python -I D:\ENGINE-V3-UPSTREAM-20261118\scripts\build_delta_inventory.py`(可重生成两份 TSV,并自动断言 8 列/source_id 唯一/Git=21,071/与 NUL 集合相等)

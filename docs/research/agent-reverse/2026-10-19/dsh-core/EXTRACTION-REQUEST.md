# EXTRACTION-REQUEST — DSH 官方 CLI/Web 发行包精确机械提取

**机械提取状态：FULFILLED，三个指定发布资产均已下载、SHA-256/字节数核验并实际解包。** 后续还以已验证 CLI tarball 为 npm dependency install root（禁用 install scripts），检查实际解析出的部分 `0.2.0-rc.2` runtime/UI packages，并在 Node 上仅运行 CLI launcher `--version` / `--help`。没有 boot CLI profile/Web、Agent 或模型；也没有把 `0.2.1-rc.2` 源码快照冒充旧包精确源码。剩余完整 CLI 依赖审阅、旧 Web 对应源码以及动态 UI / RPC / 恢复行为仍为 U。详细差异见 [`extracted/version-diff.md`](extracted/version-diff.md)，机器证据见 [`extracted/`](extracted/)。不改 Atlas 业务代码/其他研究分支，不上传凭据和聊天内容。

## 提取执行记录

- 捕获时间和工具版本：`extracted/manifest-verified.json`（PowerShell 7.6.5，tar 可用）。
- 包校验：三项实际字节数及 SHA-256 均与下表一致；没有哈希失败。
- 树与内容：`extracted/cli-tree.txt`、`web-tree.txt`、`source-tree.txt`；三个包都在隔离 `work/dsh-unpacked/` 解包。报告目录仅保留 CLI `package.json`、launcher/profile-boot 关键 JS、LICENSE、及其他精简证据索引；Web 保留 `package.json`、LICENSE、`dist/index.html`、完整资源索引和 ten-symbol 有界上下文 JSONL；源码包逐文件树含 SHA，不复制 upstream 源码目录。
- 静态 JS 拆解：REA 对解包 CLI 目录给出完整应用容器覆盖（15 个 JS parsed，无 parse failure）；REA 对 Web 目录解析 25 个 JS / 3,448,159 text bytes，但主 entry 在语义阶段耗尽 analyzer heap，因此 Web 图为 partial，不能作为已穷尽证明。Evidence IDs: CLI `ev_4f652c791174bde9e4c3bf71a5f96e04d591c88d34c15af6e25db57e55c10011`; Web `ev_1e00377639a62d192bba484dd31eb34df1b6130601cb2e5089c400510a559c6c` (summary view `ev_bd7d883178159c01dc7444053b5fe17bfdbd1fdebbff34b9cca0b448c0bda030`).
- 完整 TypeScript 路由/命令/工具扫描：`extracted/command-endpoints.txt` 当前有 1,039 条匹配记录（不含 tests；匹配 defineTool、@Remote、ctx.on、slots.register 与 CLI command）。
- CLI launcher 实际执行 `--version` / `--help`，两者均成功；`npm ls --depth=0 --json` 校验已安装图无 missing/invalid package。没有启动 profile/Agent/Web 服务，亦没有 R 级引擎/UI 行为证据。REA 只解析原始 CLI/Web asset 静态文本，未执行 JS；runtime dependency install details 在 `extracted/published-runtime-packages.json`。

## 资产及 SHA256

| 文件 | 版本/大小 | SHA256 | Release URL |
|---|---|---|---|
| deepseek-harness-npm-cli-bd27847c44.tgz | npm CLI 0.2.0-rc.2；24,265 bytes | bd27847c445cd68a565ac1f91c06bbbcc7639ef93071f678bb59c5ebaff38859 | https://github.com/unicorn-Y/Atlas/releases/download/agent-client-packages-20261019/deepseek-harness-npm-cli-bd27847c44.tgz |
| deepseek-harness-source-dcc4cf8df9.zip | commit 687f282e8625c6b8d11ff58211a90524be2e4317；44,386,184 bytes | dcc4cf8df9c3cbb3d57726b7a1ad5a52c16a754dcdbc2c0a0836788976090d9f | https://github.com/unicorn-Y/Atlas/releases/download/agent-client-packages-20261019/deepseek-harness-source-dcc4cf8df9.zip |
| deepseek-harness-web-frontend-ccadad6dcb.tgz | Web 0.0.1-rc.5；1,428,754 bytes | ccadad6dcbb6f9a3c7a57802c3c2bb5958c2104ca33e9fb88135634b6d7b1516 | https://github.com/unicorn-Y/Atlas/releases/download/agent-client-packages-20261019/deepseek-harness-web-frontend-ccadad6dcb.tgz |

## 可直接执行步骤

1. 在 Windows 本地克隆/更新 unicorn-Y/Atlas，切换本会话分支 research/agent-reverse-20261019-dsh-core，核实当前远程 HEAD，**不操作 main**。使用 `gh release download agent-client-packages-20261019 -R unicorn-Y/Atlas -p <asset> -D <temporary dir>` 获取上述原包；逐一用 PowerShell `(Get-FileHash -Algorithm SHA256 <path>).Hash.ToLower()` 与表中完整 SHA 比对。Hash 不匹配立即报告该包失败，不继续解释内容。
2. 用 `tar -tzf` / `7z l` 列出所有 ZIP/TGZ 内容；再解压至临时文件夹。保存每个相对路径、原始大小、SHA256、可能的源码映射和版本。不要转存任何用户缓存、秘钥、会话或系统凭证。
3. 仅将必要机器可读文本写入 `docs/research/agent-reverse/2026-10-19/dsh-core/extracted/`：
   - `manifest-verified.json`：asset URL、实际字节、SHA256、version、成功/失败、工具版本、捕获时间；
   - `cli-tree.txt`、`web-tree.txt`、`source-tree.txt`：文件路径/大小/sha；
   - `cli/package.json`、CLI 入口 JS/命令注册、Profile 的 config 和差异文本；
   - `web/package.json`、`web-assets-map.json`：dist HTML/JS/CSS 资源路径、chunk hash、sourceMappingURL、主要入口和 sourcemap 是否存在；
   - `web-chunk-symbols.jsonl`：对每个真实 JS chunk 搜索 `remote.mux`、`subagent`、`prompt`、`interrupt`、`assistant`、`job`、`usage`、`team`、`trajectory`、`session`，每行保存路径、字节偏移、匹配字段及前后各150字节可打印片段；如果 minified 长文件过大，仅保留小片段及 hash；
   - `command-endpoints.txt`：源码遍历 TypeScript 的 CLI command、`@Remote`、`defineTool`、`ctx.on`、`slots.register`，输出 `path:line:symbol`，全面枚举而非只查任务书举例；
   - `source-versions.json`：root、apps/cli、apps/web 与涉及核心包 package versions、exports、依赖及 LICENSE；
   - `version-diff.md`：CLI 0.2.0 vs source 0.2.1，Web 0.0.1 vs source 0.2.1，标清能证明相同、发现不同、无法配对的文件。
4. 若能在无真实密钥的隔离测试 profile 运行 `dsh --help` 或 mock Web，可以单独记录准确命令/日志/截图与无敏感内容的网络消息，但**不能把未执行的动态步骤写成 R 证据**。
5. 只提交提取资料至本分支。返还 commit SHA + 三包实际哈希/提取路径/未取到的资产。此次步骤已完成；继续研究的版本边界和未配对事实记录在 `extracted/version-diff.md` 与主报告中。

## 特别强调

三个版本互不一致；若 tarball 内只有包装脚本不可据此推断 runtime。Github 仓库源码本轮已 S 验证，机械提取重点是**固定发行物和源码的一一对应**。社区 DSH Desktop 不得混入本任务。

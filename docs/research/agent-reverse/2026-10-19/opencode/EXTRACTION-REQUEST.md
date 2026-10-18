# 本地 Codex 机械提取任务（不代替本会话研究）

**目的：** 当前研究环境仅可访问仓库文本与 GitHub 公开 v2 tag 文件，无法下载/拆开数百 MB Windows 归档。请本地 Codex **只执行机械读取/导出与上传**，不要替本会话写功能总结、不要改 Atlas 正式代码，也不要上传任何个人 Cookie/Key/会话。

## 输入与匹配
来源固定 GitHub Release `agent-client-packages-20261019`，按下面 SHA256 验证：
- `opencode-desktop-v2.0.32-c6beba4a54.exe`: `c6beba4a54ce5daf2c7cc4017aee61c4af2bfb89b377a3a3f059917d263aea2e`；
- `opencode-cli-npm-windows-x64-2.0.32-bbc00de2c5.tgz`: `bbc00de2c5cdbb6c11649e7c6e2c094e8b55d16d4bfab41577d3cdbe5d36c90d`；
- `opencode-cli-npm-wrapper-2.0.32-3395134eec.tgz`: `3395134eec1cf24f91e8d2c660843a851e933794172a13c2507d9a9805ed5760`；
- `opencode-source-v2.0.32-0c4dfbc2f9.zip`: `0c4dfbc2f94c15e0e94bc1b2b4a8524c3474f5fb6c682d6f96c505ca58a55554`；
- 对照 v1 `opencode-source-v1.19.3-662ef890f5.zip`: `662ef890f51c49c364bc8e91ab04f25c8a3abf8833c86d42d9d0e5c31df34b0b`。
源码 tag commit 分别 843a6c514e606b436a7fe713422ace0a93ad3d61 与 60c9be092129745688bb3c3a752affc6cbd66ede。

## 机械工作
1. 用已归档 Release（可用本机 `D:\agent-client-staging\opencode-zcode` 缓存，但仍要 hash 校验）读取文件类型、PE metadata、安装包目录与大小。EXE 是安装包，不要当源码文本；优先 7-Zip/NSIS 工具展开，在非联网隔离目录操作。禁止加载个人 Profile/真实凭据。
2. 只从发行物导出 `file-list.tsv`：相对路径/大小/sha256/类型；`entrypoints.md`：主程序、Electron（如有）/Node、CLI、服务端资源实际路径及元数据；`package-json-index.tsv` 和 `route-command-register.tsv`（源码静态提取）；`module-map.tsv`（入口→代码包对应）。对所有发现的 *.asar/*.js/*.cjs/*.node/*.dll/exe 记录路径、size、sha256、符号和 strings 摘要。
3. 对 v2 `packages/{core,server,desktop,app,cli,plugin,protocol,schema,session-ui,codemode}` 静态扫描列出 `exports/routes/events/commands/shortcuts/features/env flags/experiments`，输出 `api-enum.tsv`、`events-enum.tsv`、`ui-commands.tsv`、`plugin-hooks.tsv`，每行 **源路径、行号、符号、引用片段（小于 200 字符）**；对 1.19.3 的对应符号做 rename/migration 表（保持 raw 证据）。
4. 可运行隔离 CLI 时仅在临时无凭据 HOME 中执行 `--version`, `--help`, `serve --help`, `service --help`, `plugin --help`, `mcp --help`, `run --help`，记录 stdout/stderr/退出码；不连账户、不建真实任务，不改用户配置。Desktop 若能隔离启动，记录窗口/侧车 PID、端口、进程命令行（隐藏任何 auth）、Network/IPC 的 schema 和用户入口截图，最好对空数据运行。
5. v1 → v2 精确差异：`git diff --find-renames v1.19.3 v2.0.32 -- packages/*` 生成有界摘要以及 `symbol-renames.tsv`；不导出全源码 ZIP 二次入库。
6. 所有文本须仅是软件结构信息；**严格避免**操作真实用户 chat/密钥/认证回执。小证据提交于同一独立分支 `docs/research/agent-reverse/2026-10-19/opencode/evidence-extracted/`；体积大放该专用 release asset，仅在 Git 提交索引 SHA 与 URL。
7. 输出 `EXTRACT-LOG.md`：工具版本、每步执行命令、哈希、失败情况、精确文件路径；提交并 push `research/agent-reverse-20261019-opencode`，回报 commit。Codex 不得改上述研究主报告，后续由本 ChatGPT 会话根据提取证据继续溯源。

**合格标准**：能从证据表反查到 *真实发行包文件* / *固定版本源码符号*，不接受自动生成概述、网页抄写或“支持XX”列表。

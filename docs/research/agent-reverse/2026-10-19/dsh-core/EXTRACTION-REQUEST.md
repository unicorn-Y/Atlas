# EXTRACTION-REQUEST — DSH 官方 CLI/Web 发行包精确机械提取

**当前状态：BLOCKED，源码 S 证据已读取，指定发布产物未在本会话直接解包。** 以下任务只让本地 Codex 做机械取证；绝不可代替本研究会话撰写机制结论，不改 Atlas 业务代码/其他研究分支，不上传凭据和聊天内容。

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
5. 只提交提取资料至本分支。返还 commit SHA + 三包实际哈希/提取路径/未取到的资产。后续由本会话继续逐包分析，不由 Codex自行宣布逆向完成。

## 特别强调

三个版本互不一致；若 tarball 内只有包装脚本不可据此推断 runtime。Github 仓库源码本轮已 S 验证，机械提取重点是**固定发行物和源码的一一对应**。社区 DSH Desktop 不得混入本任务。
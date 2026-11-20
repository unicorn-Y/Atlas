# T6-20 · Windows 插件升级与回滚回归

任一个已运行的工位到终态即领取。使用孤立候选树 `zcode-par10-plugin-install-windows`。从 T6-14 已验前端和后端候选接续，保留已通过的版本信息、取消、并发去重及构建批准。先核对三个旧失败是否在相同基线复现，再修实际安装事务。

- Codex 以 D 盘临时目录独立复跑 `core/tests/test_plugin_install_operations.py`，22 过 4 失败。报错记录在 `D:\Atlas\.worktrees\_codex-par10-probes\plugin-install-regression\pytest.log`。重点是 Git 同仓重装的 `PermissionError`、升级后读到旧内容 v1 的补丁携带回归、市场源批准后安装失败。第四项缺 `ATLAS_PNPM_ENTRY`，先提供真实本机 pnpm 入口复跑该夹具，再归因。
- 用真实临时仓、文件与正式安装执行器追踪 staging → 替换 → patch carry → revert。Windows 文件锁或重复请求时保持旧版本可读、终态可复验、可安全重试。保持源身份、构建脚本逐请求批准、取消和错误归因。校验现有同名插件配置和补丁会迁移。
- 多次复跑上述文件和真实回环安装链，记录退出码、首次与重复操作后的版本/内容/状态。子进程 TEMP/TMP、依赖与数据根均在 D 盘。写 `evidence/par10-t6-20.md`，末行 `PAR10_RECEIPT T6-20 READY|PARTIAL|BLOCKED` 后立即主动汇报，其他工位继续。

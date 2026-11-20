# T6-18 · Windows 桌面发行候选使用新后端

当有工位且返工队列已接续时领取。独占候选树 `zcode-par10-win-release-candidate`。从 T6-13 已实际通过 `package:backend` 的产物续做 T6-5 的 Windows 发行链。T6-13 构建仍在写入时只准备命令和检查，待其正式回执后取产物。继承原构建脚本的修复与验证范围。

- 在隔离树从正常桌面 `build`、Node 资源准备和 `stage-electron.mjs` 装配。使用 electron-builder 的解包目标生成实际 Windows 应用。把 T6-13 新后端输入、stage 内后端、最终 `resources` 中后端的 SHA-256 对上，检查内嵌清单与实际资源一致，留存退出码。禁止用 T6-5 的旧后端替代。
- 在临时数据目录、用户配置目录、回环端口启动解包后的实际 Atlas 桌面程序。通过 Electron 桌面入口确认 renderer 能连上其自带后端，收集 `/api/health`、有效版本和 Node 资源校验。附本次正在运行的可执行文件路径与进程退出证明。严禁运行安装器或现有卸载器，严禁改用户快捷方式、真实数据或注册表。无关系统进程保持原状。
- 交付 `evidence/par10-t6-18.md` 与可重跑命令，收尾行 `PAR10_RECEIPT T6-18 READY|PARTIAL|BLOCKED`。记录真实原地安装升级仍需独立 Windows 环境的验收边界。完成主动通知，其他代理继续。

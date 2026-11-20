# 固定 DSH 能力地图：插件与执行世界首批

日期：2026-11-16。上游固定 commit `d743267388641bc76f17c45ce8b4c231aed1d32c`，目录 `D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness`。Atlas 开工分支 wave3 / HEAD `060071ab2ecf86d41cab90e98160183ce126bc69`。

独立只读架构研究的首批结论，已通过 CDP 交给用户指定的 Codex Desktop GPT-6 Luna 高。没有生产实现、模型或 UI 验收证据，不能把本地图算 CLOSED。52 family / 331 package 是目录统计，不是功能条目数，也未完成逐包审计。

## X6：兼容准入可独立实施

旧账以需要 peer-range resolution 判 HARD，不构成外部不可实现条件。manifest/runtime 检查可独立于完整包安装实现。

DSH 实现与真实调用点（路径均相对上游根）：

- `packages/boot/app-boot/src/plugin-compatibility.ts:61`：manifest peer semver 判定。
- `packages/boot/app-boot/src/compatibility-preflight.ts:89`：嵌套 group/include 准入。
- `packages/boot/app-boot/src/index.ts:571`：导入前调用，不能导入后才阻止。
- `packages/boot/app-boot/src/profile-compatibility.ts:113`：精确 package version / runtime version 豁免。

Atlas 下一施工候选：现有 plugin runtime 安装、启用、启动入口共用兼容判定；精确豁免不因插件或 runtime 升级自动沿用。本地 fixture 应证明不兼容插件代码未执行、撤销豁免立即生效，并接管理 API/UI。尚未实现，不能因为模块名称存在算具备。

## X5 / X7：安装操作、审批与恢复闭环

主控此前已读 pnpm install / rollback / build approvals。独立研究进一步确认以下容易漏掉的生产语义：

- `packages/boot/plugin-manager/src/index.ts:612`：waitForInstall / cancelInstall，结果区分 not-running、cancelled、too-late。
- `packages/client/ui-plugin-manager/src/client/manager-store.ts:983`：前端丢回执后恢复等待，查不到活动操作只能算 unknown，不能反推成功或取消。
- `packages/boot/plugin-manager/src/registry.ts:54`：私有 registry 不向公共源兜底。
- `packages/boot/plugin-manager/src/index.ts:80,745`：回滚快照是 package.json / lockfile，不承诺撤销任意脚本副作用；审批政策文件有意保留。

这些属于可实现工程，旧 HARD(package-manager semantics / no package pipeline) 应改为明确待实现项，而不是删除需求。

Atlas `core/atlas/plugins/runtime.py` 现有 local / marketplace / git 安装可保留其现有契约；新增包管理事务需要 request identity、真实子进程取消、manifest/lockfile 回滚、逐包持久审批、过期审批拒绝和前端状态恢复。验证必须包含来源边界及失败路径，不能只 mock 包管理器成功。

## X30：同 authority 的远端执行世界

DSH 是可选生产组合，不是默认桌面必备：

- `scripts/product-package-policy.ts:24`：SSH package 归 optional。
- `packages/ssh/fs-ssh/src/index.ts:82`：文件版本守卫及写入。
- `packages/ssh/subprocess-ssh/src/index.ts:114`：远端 prepare/start/terminate。
- `packages/ssh/sandbox-ssh/src/index.ts:13`：远端 sandbox。
- 真实消费者：`packages/lsp/lsp-stdio/src/index.ts:146` 用 fs/subprocess；`packages/terminal/terminal-bash/src/index.ts:202` 用同世界 policy/process。

Atlas 不应按旧账判原语全无：已有 `core/atlas/engine/tools/environments/ssh.py:45` 的 SSHEnvironment，以及 `core/atlas/api/run_drive.py:3734` 附近的工具代理。候选实施是统一 fs/process/sandbox 接缝，确保同一 authority、cwd 与文件身份，再逐个接 PTY / LSP / child。现有 SSHEnvironment 能否覆盖全部消费者仍未核验。

所需验收包含版本拒写、沙箱拒绝、取消、断连后的结果未知；仅能远程 exec 不等于完整执行世界。

## 边界与推进次序

首选 X6 → X5/X7 → X30 各自可验证增量。生产实现保持由桌面 Luna 完成，主控只读审查、落证据和独立验证。当前 context 正确性批次仍在修，不以新地图冲掉未修 major。

以上三组未发现必须取得 DSH 私有授权的证据。功能等价不要求 DSH helper wire 原样兼容；如果选择另建 Node/Cordis 宿主，需要另行承担跨语言权限、所有权和打包工程，当前不默认采用。

置信度：首批 DSH 实现与调用链 high；Atlas 可复用范围 medium。未穷尽 Atlas 替代路径，未给新覆盖率。

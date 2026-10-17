# W6 启动、更新与部署兼容审查

## 范围与基线

- 只读审查 detached worktree `D:\atlas-luna-w6-20261017`，基于 `ui-redesign` / `0b1ba4114e25643369c95bfac85d37563788444f`。`D:\Atlas` 有未提交改动和未跟踪文件，未修改、未安装依赖、未执行 `start-atlas.bat`，未控制进程或数据。
- 实际运行观察（主执行者采集）：Electron PID 55644 命令行指向 `D:\Atlas\frontend`；Python PID 1800 / 53140 使用 `D:\Atlas\core\.venv\Scripts\python.exe -m atlas.desktop_entry`，8765 监听者为 53140；Electron PID 55644 持有 CDP 9335。`127.0.0.1:8765` 为 Atlas API。`engine/config.yaml` 仅有 `engine=auto / provider=auto / model=''`，这不能证明会话实际选择的模型；未读取或输出凭据。
- 进程命令行只能证明 Electron 加载 `D:\Atlas\frontend`、Python 运行 `atlas.desktop_entry`；父级 launcher 已退出或其命令行未在本次观察中提供，故无法确认本次进程是否经 `start-atlas.bat` 启动。不得把源码进程观察等同于 batch 更新路径已被实测。
- 跨分支：W0 确认 `boot-1-core`、`boot-1-int`、`boot-1-shell` 是当前基线祖先、branch-only 为 0；`track-upstream` 和 `fix-p1-audit` 也属已进入当前谱系的历史改动，不是待整合的独有功能。`codex/desktop-repair-20261013@b177a6a94a7f1a9adb2891955a37cd4d4490054d` 是本机 ahead 3 的分支，不在当前基线内。只读 diff 显示其 release-only 改动包括 `frontend/scripts/stage-electron.mjs:7-27`（按 Electron 版本 stage 并校验）、`frontend/scripts/package-sqlite.mjs:7-28`（校验归档后打包 SQLite runtime）、`frontend/scripts/write-release-manifest.mjs` 版本/散列校验，以及 desktop/backend tests/diagnostics；`frontend/package.json` 将这些步骤接入 `dist:win`。未改 `start-atlas.bat`、`scripts/atlas-update.mjs`、`backendProcess.ts`、`electron.ts`、`sourceUpdate.ts` 或 Python 锁文件。因此该分支没有改变 W6-001..004 的源码启动/更新结论，也没有修复这四项；它的安装包 staging 候选应单独评估，不能视作当前源码启动已使用。
- 额外只读检查 W0 指出的 dirty worktrees：`D:\atlas-boot-core`（HEAD `efcc0cb832799d07c2c952de9d4850062c4e1cba`）的 `agent/secret_scope.py:20,43-44` 改为按 Hermes profile-home override 判断 routed-profile；`engine_core/config.py:37-59,178-287` 扩展环境变量分类与终端配置读取；`hermes_constants.py:95-178` 增加进程/profile home 与 scratch-TMP 路由；`utils.py:42,114` 增加只读 YAML cache 和原子文本写入；并有 deadline/delegation/terminal-env/proxy-source 新模块。这批未提交源码不在 `0b1ba411`，不改变 W6 当前启动/更新证据。profile 环境密钥隔离可能是独立的安全/执行集成候选，应由相应模块审查，不能直接当作启动器修复。`D:\atlas-boot-int` 的 `engine/config.yaml` 仍为 dirty；未读取或输出配置值，未获得可确认的 W6 启动/更新差异。其未跟踪 `data/start-atlas-dev.bat:1-5` 直接启动 `uvicorn atlas.server:app`，`data/start-atlas-full.bat:1-3` 调用 `npm run dev`；这些不是当前仓库 `start-atlas.bat`，且未执行。它们提示本机存在其他入口，但已观察的 Python `-m atlas.desktop_entry` 不能归因给 `start-atlas-dev.bat`。`D:\atlas-p1fix-verify2`（HEAD `d029b6e5ad1e1cc7c71d9dac4c5a694dbc152dc1`）仅有 dirty `frontend/scripts/test-preload-bundle.mjs` 测试辅助器改为 esbuild transform；不改生产启动路径，也没有检查 main bundle，不能关闭 W6-004。三处 dirty 内容均保持原样，未复制或暂存。

## 已确认行为

- 源码启动：`start-atlas.bat:7-36` 检查 Node 22.12+、Python 3.14；缺少 venv 时创建 `core\.venv` 并 `pip install -e core`，缺少根 `node_modules` lock marker 时 `npm ci`，设置 `ATLAS_PYTHON` 后进入 updater 的 launch-only 路径。
- 普通开发启动是另一条路径：`frontend/package.json:12-13` 的 `npm run dev` 启动 loopback Vite，并由 `dev:electron` 直接运行 Electron；它不经 `start-atlas.bat` 或 `scripts/atlas-update.mjs`。`npm start` 也直接 `electron .`。Batch 源码启动路径则经 `node scripts/atlas-update.mjs --launch-only`，在 stamp 与 HEAD 相符时直接 launch，否则先尝试 rebuild 后 launch；UI 再通过 update banner 检查源码更新。以上均为源码链路核对，不足以证明本次实际进程采用哪条入口。
- 后端来源：`frontend/src/main/backendProcess.ts:140-159,550-565` 先由 `ATLAS_ROOT` 或 Electron 模块位置推导仓库根；Python 候选优先 `ATLAS_PYTHON`，其次仓库 `.venv`，再回退系统 `python` / Windows `py -3`；以 `cwd=core` 执行 `-m atlas.desktop_entry`。启动器也可附加 `ATLAS_DATA_DIR`、端口和打包 backend 环境变量。
- 前端构建：`frontend/package.json:13-16` 将主进程编译、preload 打包、renderer 类型检查与 Vite build 组合；默认源码启动走 `frontend/dist`，开发模式才设置 Vite dev URL。Electron 窗口禁用 nodeIntegration、启用 sandbox，拒绝新窗口；IPC 通过受限 preload API 暴露，主进程校验 sender/可信 URL（`electron.ts:283-289,325-337`）。
- 关闭路径：主窗口退出事件先清理计时器与快捷键，再等待 `stopManagedBackend()` 后退出（`electron.ts:793-805`）。托管后端通过带随机 shutdown token 的本机 API 请求优雅关闭，超时后 Windows 使用 `taskkill /T /F` 结束进程树；其他平台终止 child（`backendProcess.ts:285-312`）。更新应用前也先等待停止托管 backend（`electron.ts:692-703`）。
- Hermes：当前是 Atlas 源码内的移植实现，文件头记录上游 `hermes-agent@562ad75baec0c8360f6ce2d48b7d9de56506956c`（`ui-redesign@0b1ba4114e25643369c95bfac85d37563788444f:core/atlas/engine/hermes_runtime.py:1-4`），不是单独安装的 Hermes 包。`requirements.lock` 为 Atlas 第三方 Python 包的锁文件；上游同步由 `atlas.upstream` / updater 的 pending-merge 与 post-merge 路径处理。未发现需要额外安装独立 Hermes 发行包的代码证据。

## 问题

1. **W6-001 / P1 / 默认暴露 CDP 调试控制口。** updater `scripts/atlas-update.mjs:188-203` 在默认情况下以 `--remote-debugging-port=9335 --remote-allow-origins=*` 启动 Electron；只有显式 `ATLAS_DEBUG_PORT=0` 才关闭。实际运行中 9335 由 Atlas Electron PID 55644 持有。CDP 允许连接方控制/检查桌面网页会话；当前配置没有默认关闭或来源限制。证据确认代码和端口归属，未做外部可达性或攻击复现。最小处理：默认不启用 CDP，明确 opt-in；确需调试时限制回环和可信来源。
2. **W6-002 / P1 / 更新失败不是原子回滚，仍会重启。** `atlas-update.mjs:74-104` 对源代码执行 fast-forward；`136-175` 随后按变动安装 Python/npm 依赖并原地构建；失败处理只写错误状态，`258-259` 仍在 `--relaunch` / `--launch-only` 情况下启动 Electron。代码没有恢复旧 HEAD、依赖或旧 dist 的回滚路径。Vite 构建会清理/重写 dist，因此在 renderer 构建失败时“上一版 build 仍完整”的注释（258）不由代码保证。后果是更新失败后可能带着新源代码、半成品资源或已变依赖重新启动。最小处理：先构建到临时目录并校验成功，再切换构建产物；失败时保留旧 HEAD/依赖/产物且不要自动启动失败版本，至少应提示并保留可恢复状态。未执行故障注入。
3. **W6-003 / P2 / 首次源码安装没有使用 Python 锁文件。** `start-atlas.bat:19-24` 首次建立 venv 后只执行 `pip install -e core`；`core/pyproject.toml:5,9-33` 对大部分依赖使用 `>=` 范围。Updater `atlas-update.mjs:145-152` 仅在锁文件相对 build stamp 有变化时安装 `requirements.lock`；首次环境无 stamp 时 `changed=null`，该锁定分支不会运行。因而新建环境会按当时解析结果装包，而非仓库记录的完整第三方版本集。npm 路径使用 `npm ci`，相对明确。最小处理：初装和 venv 缺失时同步安装 `requirements.lock`，并让安装完成后 stamp 反映实际依赖状态。未在隔离环境实装验证。
4. **W6-004 / P2 / 快速启动与重建探测未覆盖 Electron 主进程 bundle。** updater 的 launch-only 快路径在 stamp 与 HEAD 相同即直接 `launch()`（`atlas-update.mjs:206-212`）；`rebuild()` 的 `built` 判定只要求 `frontend/dist/index.html` 和 `frontend/dist-electron/preload/index.cjs`（`169-173`），未检查实际启动所需的 `frontend/dist-electron/main/electron.js`。若主 bundle 被删掉或缺失但 stamp 保留，启动器会跳过重建；若 index/preload 仍在，常规重建判定也可能认为资源齐全。最小处理：快路径和完整构建探测均验证主进程入口及 preload/renderer 必需文件。

## 验证边界

- 做了源码和只读实际进程/端口核对；没有启动应用、修改配置、安装依赖、更新/回滚、运行测试或构建。
- 对 CDP 只确认了 Electron 进程持有端口；未确认跨主机可达性。更新失败、首次依赖安装和缺失 bundle 问题均由源码路径确认，未做故障注入。
- 结果仅覆盖 W6，不代表全项目通过。


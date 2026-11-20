# PAR-10-T2 发行清单接入打包链与 packaged 启动完整性

日期：2026-11-19（UTC 2026-11-18T21:46Z–21:58Z）
工作树：`D:\Atlas\.worktrees\zcode-par10-release-startup`
分支：`zcode/par10-release-startup`
基线 HEAD：`060071ab2ecf86d41cab90e98160183ce126bc69`
状态：完整性模块已接入真实 electron-builder 打包链与 packaged 启动入口，并在真实打包产物上验证正常启动、缺清单拒绝、篡改拒绝、开发态跳过和一次旧安装/升级兼容矩阵。未执行 NSIS 安装/卸载与完整 `dist:win` 端到端（§7）。
合入 / push / commit / stash：未做。主工作区未改（`git status --short` 仍 170 项）。

## 1. 基线与来源哈希

- 源树：`D:\Atlas\.worktrees\zcode-par09-release-integrity`，HEAD 同为 `060071ab`。
- 移入前源文件 sha256：
  - `releaseIntegrity.ts` `02db0ff1b194363f56fcd8a3bbca70c62ac57f213e1b67fd425c7b72669a72b8`（702 行）
  - `releaseIntegrity.test.ts` `2fa53025f5f9365cc43aac2c88ea019ab7b3fa113a717633e60098ca57ac783d`（449 行）
- 移入后本树最终 sha256：
  - `frontend/src/main/releaseIntegrity.ts` `02e79e3df135988f2031960e3b8d9ea50af22a1a4413d1ad01b88df0a7d4c261`（720 行）
  - `frontend/src/main/releaseIntegrity.test.ts` `5f526e1da2af767454b46dcb39e74365569845c383675c294fe06be4a908fadf`（616 行）
  - `frontend/scripts/after-pack-release-manifest.cjs` `401561e16ced169c1d0c291f7d1e83623b30c0c37a6c998c936d64a020a2c92f`（176 行，新）
  - `frontend/scripts/after-pack.cjs` `406e23ab2c55cb9393c6558189433e34ff57a0fea6af7bd70066b2f73345cf14`（10 行，新）
- 对已验模块的唯一语义改动：`installer` 改为可选。安装包在 payload 打包完成后才生成，无法把自身 SHA-256 嵌进自身；运行期清单省略该对象，发布侧清单仍带 `installer.file` + `installer.sha256`，模块在字段存在时仍按原规则完整校验（含纯文件名、与 `app_version` 命名一致、64 位哈希）。`installer` 存在但字段残缺时仍报 `manifest_invalid`，测试覆盖。
- 测试：原 26 例保留，新增 8 例（afterPack 生成器字段/常量契约、无 installer 运行期清单接受、残缺 installer 拒绝、旧 `resources/release-manifest.json` 路径、嵌入清单优先于陈旧 root 清单、升级陈旧 `app_version` 拒绝、旧 schema 清单拒绝、electron.ts 接线静态契约）。
- 工具链：Node `v24.18.1`、npm `12.0.2`、TypeScript `7.0.2`、vitest `5.0.4`、electron `44.7.0`、electron-builder `26.15.3`。
- 完整基线见 `evidence/par10-t2-baseline.txt`。

## 2. 打包链与时序

实际顺序（`frontend/package.json` 的 `dist:win`）：`clean:release → build → package:backend → package:node → stage-electron → electron-builder → write-release-manifest.mjs`。

清单拆分与落点：

1. **运行期清单**由 electron-builder `afterPack` 写入，路径 `win-unpacked/resources/atlas/release-manifest.json`。`afterPack` 链为先跑原图标钩子（重写 `Atlas.exe`），再算哈希，因此 `unpacked_executable_sha256` 覆盖最终可执行文件字节；此时 backend、sqlite、core、node runtime 均已就位，NSIS 尚未生成。
2. **发布侧清单**仍由 `write-release-manifest.mjs` 在 electron-builder 之后写 `windows-release/release-manifest.json`，额外记录 `installer.file` 与 `installer.sha256`。它现在必须读取 payload 内嵌清单，逐字段（`RUNTIME_MANIFEST_FIELDS`）比对；任何漂移直接退出 1，并复用内嵌清单的 `build.time_utc`，保证两份清单描述同一次构建。
3. 清单**不经** `files`/`extraResources` 进入安装树，而是在 payload 组装完成后由 `afterPack` 写入，避免“先生成后打包导致哈希/时序失真”；NSIS 从同一 `win-unpacked` 生成，因此安装包 payload 内实际带有该清单。

修改文件（候选树内）：

| 文件 | 类型 | 说明 |
|---|---|---|
| `frontend/src/main/releaseIntegrity.ts` | 移入+适配 | `installer?`；其余校验不变 |
| `frontend/src/main/releaseIntegrity.test.ts` | 移入+扩充 | 34 例 |
| `frontend/scripts/after-pack-release-manifest.cjs` | 新增 | 纯函数 `buildRuntimeManifest` + afterPack 写入 |
| `frontend/scripts/after-pack.cjs` | 新增 | 图标 → 清单钩子链 |
| `frontend/package.json` | 修改 | `afterPack` 指向 `scripts/after-pack.cjs` |
| `frontend/scripts/write-release-manifest.mjs` | 修改 | 内嵌清单对账、漂移失败、复用 build time |
| `frontend/src/main/electron.ts` | 修改 | 打包态启动前调用 `assertReleaseIntegrity` |

diff/内容审计见 `evidence/par10-t2-diff.txt`；3 个跟踪文件合计 +36/-1，4 个新文件未提交。

时序实证：

- `electron-builder --dir` 日志顺序为 `updating asar integrity executable resource` → `embedded Atlas icon into Atlas.exe (7 sizes)` → `wrote runtime release manifest`（`evidence/par10-t2-electron-builder-dir.txt`）。
- NSIS 从该 payload 生成 `Atlas-0.1.1-Setup.exe`（376,528,664 字节）；7-Zip 只读拆包显示 `$PLUGINSDIR/app-64.7z` 内含 `resources\atlas\release-manifest.json`（1091 字节），与 `win-unpacked` 内清单 sha256 完全相同：`228eecf83f8bf95539e8ef4ac3b55398c139938d506480c367b21958f0de164e`。`evidence/par10-t2-installer-payload.txt`。
- 漂移守卫：把内嵌清单 `app_version` 改成 `0.1.0` 后重跑生成器 → `Release manifest drift at app_version: runtime=0.1.0 release=0.1.1`，退出 1；恢复后退出 0。`evidence/par10-t2-drift-guard.txt`。

## 3. 启动接线

`frontend/src/main/electron.ts`：

- 顶部 `import { assertReleaseIntegrity } from './releaseIntegrity.js';`（NodeNext/tsc 输出 `dist-electron/main/releaseIntegrity.js`，已确认打进 `app.asar`）。
- `app.whenReady().then(async () => { ... })` 的 `if (app.isPackaged) { ... }` 块内，`ATLAS_NPM_PACKAGE_VERSIONS` 赋值之后、块结束之前调用：

```ts
assertReleaseIntegrity({
  installRoot: path.dirname(process.execPath),
  expected: {
    appVersion: packageJson.version,
    electronVersion: process.versions.electron,
    platform: process.platform,
    architecture: process.arch,
  },
});
```

- 调用点早于 `prepareSharedApiToken()`、`attachBackendToken()`、`createWindow()`、`startBackend()`；失败由既有 `app.whenReady(...).catch` 弹“Atlas 启动失败”并 `app.exit(1)`。
- 开发态（`app.isPackaged === false`）整段不进入，唯一调用点在打包块内，静态契约测试固定该顺序。

## 4. 验证记录

| # | 命令 / 场景 | 退出码 | 结果 | 证据 |
|---|---|---|---|---|
| 1 | `npx tsc -p tsconfig.electron.json --noEmit`（frontend） | 0 | 无诊断 | `par10-t2-tsc.txt` |
| 2 | `NO_COLOR=1 npx vitest run src/main/releaseIntegrity.test.ts` | 0 | 1 file / **34 tests passed** | `par10-t2-vitest.txt` |
| 3 | `npm run build`（tsc + preload + renderer tsc + vite） | 0 | 产物含 `dist-electron/main/releaseIntegrity.js` | `par10-t2-build.txt` |
| 4 | `npx electron-builder --win --x64 --dir --publish never` | 0 | 真实 win-unpacked + afterPack 清单 | `par10-t2-electron-builder-dir.txt` |
| 5 | `npx electron-builder --win nsis --x64 --prepackaged windows-release/win-unpacked` | 0 | 真实 NSIS Setup.exe + blockmap | `par10-t2-electron-builder-nsis.txt` |
| 6 | 真实 packaged 启动（win-unpacked\Atlas.exe，完整清单） | 进程存活 12s | 窗口 `新任务 — Atlas`，子进程含 `atlas_backend.exe` | `par10-t2-pkg-success.txt` |
| 7 | 复制 payload，删除 `resources/atlas/release-manifest.json`，启动 | 1 | 对话框正文 `manifest_missing`，无 backend 子进程 | `par10-t2-pkg-missing-manifest.txt` |
| 8 | 复制 payload，恢复清单，向 `atlas_backend.exe` 追加 22 字节，启动 | 1 | `hash_mismatch`（清单 `13d8511e…`，磁盘 `b391a203…`） | `par10-t2-pkg-tampered.txt` |
| 9 | 开发态 `electron.exe .`（无任何清单，`app.isPackaged=false`） | 进程存活 10s | 窗口 `新任务 — Atlas`，未出现完整性错误 | `par10-t2-dev-mode.txt` |
| 10 | 兼容矩阵 A/B/B2/C/D/E/F（下节） | 见 §6 | 5 通过、2 失败均按预期 fail-closed | `par10-t2-manifest-compat.txt` |
| 11 | 从 Setup.exe 拆 `app-64.7z`，提取清单与受检文件，跑编译模块 | 0 | 三份哈希与 win-unpacked 一致；`installer.sha256` 复算一致 | `par10-t2-installer-payload.txt` |
| 12 | 漂移守卫（篡改内嵌清单后生成器） | 1 → 恢复后 0 | 精确报 `app_version` 漂移 | `par10-t2-drift-guard.txt` |
| 13 | `npm run package:node` 首次 / 重试 | 1 / 0 | 首次环境 npmrc `allow-scripts` 冲突；绕过用户 npmrc + 本地官方归档后成功 | `par10-t2-package-node.txt` |

说明：第 7、8 项是**真实 packaged 进程**，从真实的 `win-unpacked\Atlas.exe`（含真实 `app.asar` 与官方 Electron 44.7.0）启动；对话框文本由 PowerShell UIAutomation 读出，正文包含打包后路径与 `app.asar` 内调用栈（`electron.js:2039` → `releaseIntegrity.js:539`）。关闭对话框后进程以 1 退出，未产生 backend 子进程。

## 5. 真实打包 vs 测试夹具边界

**真实（非夹具）部分：**

- electron-builder 26.15.3 真实产出 `windows-release/win-unpacked`；Electron 44.7.0 来自官方 npm dist（复制到 `electron-runtime`，与 `package.json` 一致）。
- backend 使用现有 **真实 0.1.0 PyInstaller 产物**副本（`D:\Atlas\frontend\backend-release\atlas_backend`，与工作树 `core/atlas/__init__.py` 的 0.1.0 一致），未在本树重跑 PyInstaller。
- bundled Node 由 `npm run package:node` 从 nodejs.org 官方 v24.21.0 归档真实打包（archive SHA-256 `158f7685…` 与 `node-runtime.json` 一致）。
- NSIS `Atlas-0.1.1-Setup.exe` 由 electron-builder 真实生成；只做了 7-Zip 只读拆包与哈希核对，**没有执行安装器**，因此没有注册表、开始菜单、桌面快捷方式或用户目录副作用。
- packaged 启动验证的是 `win-unpacked\Atlas.exe`（NSIS 将逐字节复制该 payload；拆包哈希已证明清单与受检文件在 Setup.exe 内一致）。

**夹具部分：**

- §4 表中缺清单/篡改两项基于 `win-unpacked` 的 robocopy 副本，复制后删除/追加字节；其余字节与真实产物一致。
- §6 的旧安装矩阵使用真实 0.1.0 产品文件（`Atlas.exe`、backend、sqlite、core、node runtime、旧 `release-manifest.json`）选择性复制到临时目录，再由编译后的模块验证；未运行旧版 Electron。
- 单元测试使用临时目录和合成字节，不触碰真实数据。

## 6. 已有安装 / 升级兼容验证

A–F 均使用编译后的 `dist-electron/main/releaseIntegrity.js`（与打包进 `app.asar` 的同一文件）：

| 场景 | 树 | 结果 |
|---|---|---|
| A | 本次真实 win-unpacked，内嵌清单 | 通过，3 份哈希全部验证，`installer` 缺失 |
| B | 同字节，当前 schema 清单放**安装根** `release-manifest.json`（旧清单路径） | 通过，按根路径读取 |
| B2 | 同字节，清单放 `resources/release-manifest.json` | 通过，按第三候选读取 |
| C | 真实 0.1.0 安装树 + 其原始发布侧清单（旧 schema，**无 `sqlite_runtime`**） | 拒绝：`manifest_invalid` ×4（sqlite 字段缺失），未做任何哈希 |
| D | 真实 0.1.0 字节 + 用当前 afterPack 钩子生成的新 schema 清单放内嵌路径（升级完成形态） | 通过，`app_version=0.1.0`、`electron=44.4.5` |
| E | 同 D，新 schema 清单放旧根路径 | 通过 |
| F | 用 D 的清单但 `app_version=0.0.9`（升级未替换清单） | 拒绝：`version_mismatch`（仅 app_version） |

结论与边界：

- 旧版生成器只把清单写到 `windows-release/release-manifest.json`，**从未把它装进 0.1.0 安装树**；真实 0.1.0 安装本身没有清单，其旧 Electron 也不做这项检查。升级到新版本后由新安装包写入内嵌清单，即 D 的形态。
- 模块仍接受旧清单候选路径（根目录、`resources/`），但不接受 0.1.0 的旧字段集：这类树若被新二进制直接接管会被 fail-closed 拒绝，不会静默放行。
- 升级未完成（清单仍是旧版本）会被 `version_mismatch` 拒绝；这一点对“旧清单或旧产物路径”的兼容要求是明确的 fail-closed 语义。

## 7. 未覆盖 / 风险

- **未跑完整 `npm run dist:win` 端到端。** 未执行本树 `package:backend`（PyInstaller；本机主树有 `core/.venv` + PyInstaller 6.22.3，但本工作树无 venv，重装 release extras 成本高），未执行 `stage-electron` 下载（改用官方 npm dist 复制）。manifest/启动链本身是在真实 electron-builder 与真实 NSIS 产物上验证的。
- **未执行 NSIS 安装/卸载，也未在已有 0.1.0 安装目录上原地升级。** 只验证了安装包 payload 与安装树等价性；真实安装器的注册表、快捷方式、覆盖/回滚行为未验。
- `node.exe` 字节没有哈希字段（继承 par09-f01 的 schema 缺口），只校验存在性与 `node-runtime.json` 元数据；`sqlite_runtime.version` 也只校验格式与 DLL 哈希。
- 启动期三份大文件（246MB + 87MB + 1.5MB）同步 SHA-256 的实际耗时未插桩测量；真实启动 12s 内完成窗口与 backend，未区分哈希耗时。
- 仅 Windows x64 验证；POSIX 分支未测。
- `tsconfig.electron.json` 的 `src/main/**/*.ts` 会把 `releaseIntegrity.test.ts` 编进 `dist-electron`，因此测试文件也会进入 `app.asar`（原有测试也有此行为）；不影响启动，但增加包体。
- 本次 packaged 启动只覆盖到窗口出现与 `atlas_backend.exe` 拉起，未逐项回归后端业务功能。
- `package:node` 首次失败是环境 npm 用户配置 `allow-scripts=` 与 npm 12 的冲突（`EALLOWSCRIPTS`），不是代码缺陷；绕过方式已记录。真实 `dist:win` 在同类 npm 配置机器上也会遇到同一步骤失败。

## 8. 可复现命令

```powershell
# typecheck / tests（frontend）
npx tsc -p tsconfig.electron.json --noEmit
NO_COLOR=1 npx vitest run src/main/releaseIntegrity.test.ts

# 构建（工作树 frontend 通过 junction 使用主树 node_modules；仅测试用，未提交）
npm run build

# 真实 unpacked 打包（需先准备 backend-release/atlas_backend、backend-release/runtime/node、
# backend-release/runtime/whatsapp-bridge、electron-runtime；本次为现有产物副本 + 官方 Node 归档）
npx electron-builder --win --x64 --dir --publish never

# 从 payload 生成真实 NSIS（本次为避免重跑 PyInstaller 使用 prepackaged；正式 dist:win 为同一 electron-builder 单次调用）
npx electron-builder --win nsis --x64 --prepackaged windows-release/win-unpacked --publish never

# 发布侧清单（必须在内嵌清单存在后运行）
node scripts/write-release-manifest.mjs

# 模块级验证夹具（脚本已保存到 evidence）
node evidence/par10-t2-harness-verify.mjs <compiled releaseIntegrity.js> <installRoot> "<expected JSON>"
powershell -File evidence/par10-t2-harness-run-packaged.ps1 -Exe <installRoot>\Atlas.exe -WaitSeconds 8 -ErrorDialogTitle Error
```

完整日志与哈希明细见本目录 `par10-t2-*.txt`。

PAR10_RECEIPT T2 READY

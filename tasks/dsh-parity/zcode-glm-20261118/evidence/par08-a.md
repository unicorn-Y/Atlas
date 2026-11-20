# PAR-08-A — CSV/TSV 空态返工收据

- 日期：2026-11-19（香港时间）
- 工作树：`D:/Atlas/.worktrees/zcode-exec06-csv-preview`
- 分支：`zcode/exec06-csv-preview`
- 基线 HEAD：`060071ab2ecf86d41cab90e98160183ce126bc69`（未变；未 commit/push/merge，未用 git stash）
- 范围：只改 `frontend/src/renderer/shell/panels/csvPreview.tsx` 与其测试；Electron 夹具只读本工作树；主工作区、`PROGRESS.md`、`QUEUE.tsv`、其他 worktree、`core/`、Electron 主进程产品代码均未触碰。

## 1. 缺陷与修复

验收缺口 A：内容为 `""` 的 CSV 在文件树中打开后仍显示「空文件，没有可显示的表格行」。原因是 `CsvFilePreview` 把「单行且所有单元格为空」也判成空文件，将解析器已经保留的那条记录又过滤掉了。

修复（`csvPreview.tsx:139-142`）：

```ts
const table = parseDelimited(file.content, file.path);
// Zero records is the only empty file. A record whose only field is empty
// (e.g. `""` or a blank line) is still a row and must render as a table.
if (table.totalRows === 0) {
```

语义边界现在明确区分：

| 输入 | `parseDelimited` | 界面 |
|---|---|---|
| 真正空文件（0 字节） | `totalRows=0`, `rows=[]` | 只显示「空文件，没有可显示的表格行。」，无 `<table>` |
| `""`（两个双引号） | `totalRows=1`, `rows=[['']]` | 1 行 1 列表格，空单元格用可见的 `&nbsp;` 占位，不显示空态 |
| `"\n"`（空行记录） | `totalRows=1`, `rows=[['']]` | 按 1 行记录渲染，不显示空态 |

PAR-07-A 的 `rowStarted` EOF flush 与 `firstLogicalRecord` 首逻辑记录定界符检测保持不变，相关旧用例全部继续通过。

## 2. 测试改动

`frontend/src/renderer/shell/panels/csvPreview.test.tsx`：

- 扩展 `keeps a lone empty quoted field as one row at EOF and renders it`：除解析断言外，断言静态渲染不含「空文件」、含 `<table>`/`<th>`/`1 行`，且空字段有可见 `\u00a0` 占位。
- 新增 `renders a blank-line record as a one-row table, not as an empty file`：`"\n"` 解析为 1 行 1 空字段，并渲染表格。
- 新增 `shows the empty note only when the file has zero records`：`""` 的零记录对照，空文件渲染「空文件，没有可显示的表格行」且没有 `<table>`。
- 原有普通 CSV、引号内换行/转义、首列跨引号换行的分号 CSV、TSV、截断、ragged 行、二进制/截断源等 7 个用例未改且通过。

`FilesPanel.test.tsx` 无需改动：该文件只有 `ancestorPaths` 和无 workspace/未加载根目录的静态渲染用例，不涉及文件点开后的预览；FilesPanel→DocumentPreview 的真实点开路径改由第 4 节 Electron 探针覆盖。

## 3. 命令、退出码与结果

所有命令的 cwd 均为工作树内对应目录。

### 3.1 Vitest（组件回归）

```
cd D:/Atlas/.worktrees/zcode-exec06-csv-preview/frontend
D:/Atlas/node_modules/.bin/vitest run --root . \
  src/renderer/shell/panels/csvPreview.test.tsx \
  src/renderer/shell/panels/documentPreviewRegistry.test.tsx \
  src/renderer/shell/panels/FilesPanel.test.tsx
```

- 实际二进制：`D:/Atlas/node_modules/.bin/vitest`（vitest 5.0.4，host Node v24.18.1，win32-x64）
- 退出码：**0**
- 结果：**3 files passed, 17 tests passed**
  - `csvPreview.test.tsx` 10
  - `documentPreviewRegistry.test.tsx` 3
  - `FilesPanel.test.tsx` 4
- 逐条日志：`evidence/par08-a-vitest-verbose.txt`；简版：`evidence/par08-a-vitest.txt`

### 3.2 renderer 类型检查

```
cd D:/Atlas/.worktrees/zcode-exec06-csv-preview/frontend
D:/Atlas/node_modules/.bin/tsc -p tsconfig.renderer.json --noEmit
```

- 实际二进制：`D:/Atlas/node_modules/.bin/tsc`（TypeScript 7.0.2）
- 退出码：**0**，无输出；日志：`evidence/par08-a-tsc.txt`

### 3.3 Electron 夹具构建

```
cd D:/Atlas/.worktrees/zcode-exec06-csv-preview/.tmp/par08-probe
node build.mjs
```

- 使用工作树内 `frontend/node_modules/.bin/esbuild`（0.28.2）打包 `entry.tsx` → `bundle.js`（1,143,517 bytes，IIFE）。
- 构建入口导入的是工作树 `frontend/src/renderer/shell/panels/FilesPanel.tsx`；`useAtlasStore` 被 esbuild resolve 插件替换为夹具 shim，bundle 中不含 `BackendAdapter`/主 checkout 产品代码。
- 退出码：**0**；日志：`evidence/par08-a-bundle-build.txt`

### 3.4 真实隔离 Electron 窗口

```
cd D:/Atlas/.worktrees/zcode-exec06-csv-preview/.tmp/par08-probe
PAR08_EVIDENCE_DIR="D:/Atlas/tasks/dsh-parity/zcode-glm-20261118/evidence" \
PAR08_USER_DATA_DIR="D:/Atlas/.worktrees/zcode-exec06-csv-preview/.tmp/par08-probe/user-data" \
"D:/Atlas/node_modules/electron/dist/electron.exe" \
  "--user-data-dir=D:/Atlas/.worktrees/zcode-exec06-csv-preview/.tmp/par08-probe/user-data" \
  "D:/Atlas/.worktrees/zcode-exec06-csv-preview/.tmp/par08-probe/electron-main.cjs"
```

- Electron：`D:/Atlas/node_modules/electron/dist/electron.exe` v44.7.0（Chromium 152.0.7977.130，Electron Node 24.21.0）。
- 独立 `--user-data-dir`：`D:/Atlas/.worktrees/zcode-exec06-csv-preview/.tmp/par08-probe/user-data`；主进程另执行 `app.setPath('userData', ...)`，日志确认实际使用该目录。
- 退出码：**0**，探针内部 `failures=0`，**19 项 PASS**。
- 日志：`evidence/par08-a-electron-log.txt`（主进程同步写盘）、`evidence/par08-a-electron-stdout.txt`（进程 stdout）。

夹具与服务器：

- 边界文件（`fixtures/`，经 `od -An -tx1` 核对）：
  - `empty.csv`：0 字节（真正空文件）
  - `quoted-empty.csv`：`22 22`，即恰好两个双引号 `""`
- 主进程起本机 HTTP server（随机 127.0.0.1 端口），提供 `/workspace/tree`、`/workspace/file`、`/workspace/raw` 与夹具页面 `/app`、`/bundle.js`；两个 CSV 内容只由该 HTTP 服务返回。
- 渲染的是工作树构建的 `FilesPanel`；文件树节点由 `webContents.sendInputEvent`（mouseMove/mouseDown/mouseUp）真实点击，非 `element.click()`。
- 每步用 `capturePage()` 截图并用 `executeJavaScript` 读取 DOM 快照。

关键 DOM 结果：

- `empty.csv`：
  - `marker="empty"`，`notes=["空文件，没有可显示的表格行。"]`，`tableHtml=null`，`thCount=0`。
  - 截图：`evidence/par08-a-electron-empty.png`（1184×755，17,880 bytes）。
- `quoted-empty.csv`：
  - `marker="quoted-empty.csv"`，`notes=["1 行 · 逗号分隔"]`，body text 不含「空文件」。
  - `tableHtml` 为 `<table aria-label="表格预览 quoted-empty.csv"><thead><tr><th ...>&nbsp;</th></tr></thead><tbody></tbody></table>`。
  - `thCount=1`、`trCount=1`、`tdCount=0`、`nbspCount=1`：1 行 1 列表格，空单元格以可见 `&nbsp;` 占位。
  - 截图：`evidence/par08-a-electron-quoted-empty.png`（1184×755，18,623 bytes）。

## 4. 产品入口（已走通）

`FilesPanel.tsx`：

1. 点文件树节点 → `selectFile(path)` → effect 调 `backend.getWorkspaceFile`；
2. `previewing = Boolean(shown && canPreview(shown.path) && mode === 'preview' && ...)`；
3. 渲染 `<DocumentPreview file={shown} ... />`；
4. `documentPreviewRegistry.tsx` 中 `renderers.set('csv', { id: 'csv', extensions: CSV_PREVIEW_EXTENSIONS, renderer: CsvFilePreview })`；
5. `DocumentPreview` 按扩展名选中 `CsvFilePreview`。

第 3.4 节的真实窗口正是从 `FilesPanel` 的文件树点开两个 HTTP 文件，命中上述整条链路。

## 5. 未验边界

- Electron 夹具使用 `useAtlasStore` 的测试 shim（只实现 FilesPanel 用到的 workspace tree/file/search/history 方法），不经过真实 `BackendAdapter`、Python 后端、真实工作区接口或真实用户数据；`/workspace/tree` 与 `/workspace/file` 是本地 HTTP 测试服务。这是任务要求的本机 HTTP 边界文件方案，不代表完整客户端启动。
- Electron 窗口只覆盖两个边界文件（真正空文件、`""`）；首列跨引号换行的分号 CSV、普通 CSV、TSV 三个场景由 Vitest 的静态渲染断言复验（`csvPreview.test.tsx` 全通过），未在本窗口内逐一点开。
- 未跑 Vite 生产构建、完整 `npm run dev`、Electron 主进程/preload 产品代码或完整桌面客户端；夹具 bundle 是 esbuild IIFE。
- 既有设计仍把第一行当表头：`""` 渲染为 1 行（`<th>`）1 列、0 条 tbody 记录，空单元格用 `&nbsp;` 可见占位；若期望明确出现一条 `<td>` 空行，需要另行改变「首行即表头」的既有语义，本次未改。
- `FilesPanel.test.tsx` 未扩展交互用例；其现有静态用例已通过，交互路径由上节真实窗口覆盖。

## 6. 基线、diff 与工作树状态

- HEAD 仍为 `060071ab2ecf86d41cab90e98160183ce126bc69`。
- `git status --short` 仅三项（均为 IMPL-3/PAR-07-A/PAR-08-A 的面板文件，未新增 tracked 文件）：
  - `A frontend/src/renderer/shell/panels/csvPreview.test.tsx`
  - `A frontend/src/renderer/shell/panels/csvPreview.tsx`
  - `M frontend/src/renderer/shell/panels/documentPreviewRegistry.tsx`
- `git diff --stat`（相对 HEAD，累计 IMPL-3 + PAR-07-A + PAR-08-A）：**3 files changed, 313 insertions(+), 0 deletions**：
  - `csvPreview.tsx` +182（基线 HEAD 中无此文件，IMPL-3 新增）
  - `csvPreview.test.tsx` +129（同上）
  - `documentPreviewRegistry.tsx` +2（本次返工未改，沿用 PAR-07-A 状态）
- PAR-08-A 本轮只改两个文件：`csvPreview.tsx` 空态条件由「单行全空也判空」改为 `totalRows === 0`（净 +1 行，含注释）；`csvPreview.test.tsx` 扩展 1 个旧用例、新增 2 个用例（相对本轮前净 +29 行）。
- `.tmp/par08-probe/` 被仓库 `.gitignore:130` 的 `.tmp/` 忽略，不影响 git 状态。
- 未执行 `git stash`；基线文件内容用 `git show HEAD:path`/`git diff` 对比。

## 7. 证据清单（`D:/Atlas/tasks/dsh-parity/zcode-glm-20261118/evidence/`）

| 文件 | 内容 |
|---|---|
| `par08-a.md` | 本收据 |
| `par08-a-vitest.txt` | 3 文件 17 用例通过，EXIT 0 |
| `par08-a-vitest-verbose.txt` | 逐用例名与结果，EXIT 0 |
| `par08-a-tsc.txt` | renderer 类型检查，空输出，EXIT 0 |
| `par08-a-bundle-build.txt` | esbuild 夹具构建，EXIT 0 |
| `par08-a-electron-log.txt` | Electron 主进程 19 PASS / 0 FAIL、DOM 快照、退出码 0 |
| `par08-a-electron-stdout.txt` | Electron 进程完整 stdout |
| `par08-a-electron-empty.png` | 真正空文件：空态提示、无表格 |
| `par08-a-electron-quoted-empty.png` | `""`：1 行 1 列表格、可见空单元格、无空态 |

夹具（未提交，`.tmp/` 内）：`D:/Atlas/.worktrees/zcode-exec06-csv-preview/.tmp/par08-probe/{entry.tsx,shim/useAtlasStore.ts,build.mjs,electron-main.cjs,fixtures/empty.csv,fixtures/quoted-empty.csv,bundle.js}`。
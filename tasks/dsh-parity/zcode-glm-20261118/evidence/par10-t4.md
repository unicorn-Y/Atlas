# PAR-10-T4 — 桌面与工作树集成候选（A/B/D 组合）

- 日期：2026-11-19（HKT）
- 工作树：`D:/Atlas/.worktrees/zcode-par10-desktop-recovery-candidate`
- 分支：`zcode/par10-desktop-recovery-candidate`
- 基线 HEAD：`060071ab2ecf86d41cab90e98160183ce126bc69`（四个树同基线；未 commit/push/merge/stash）
- 结果：**A、B、D 三个组件全部按任务要求复跑通过**；无基线冲突；候选树可供主控复审。

## 1. 工作树基线

四个工作树（候选 + 三个源）HEAD 均为 `060071ab2ecf86d41cab90e98160183ce126bc69`。源树写者已停止：

| 源树 | HEAD | `git status --short` |
|---|---|---|
| `zcode-exec06-csv-preview` (A) | `060071ab` | `A csvPreview.test.tsx`、`A csvPreview.tsx`、`M documentPreviewRegistry.tsx` |
| `zcode-exec06-keybindings-cas` (B) | `060071ab` | `M u6_router.py`、`A test_u6_keybindings.py`、`A ShortcutsPanel.test.tsx`、`M ShortcutsPanel.tsx`、`A keybindings.test.ts`、`A keybindings.ts`、`M shortcuts.test.ts` |
| `zcode-par07-worktree-api-fix` (D) | `060071ab` | `M workspace_router.py`、`M memory/__init__.py`、`M routes.json`、`A test_conversation_worktree_create.py` |
| `zcode-par10-desktop-recovery-candidate` | `060071ab` | 复制前 clean；复制后仅本包 14 个组件文件（见 §3） |

验证前后对 14 个源文件重新 sha256 比对：**14/14 未变**（`logs/01-source-hashes.txt` 与最终复算一致）。源树只读，未写入。

## 2. 源 sha256 与基线（逐文件）

`src_sha256` = 源树工作区字节哈希（CRLF）；`head_sha256` = `git show HEAD:path` 的 LF blob 哈希；`ABSENT` = 基线无此文件。全量 TSV 在候选树 `.tmp/par10-t4/logs/01-source-hashes.txt`。

```
A	frontend/src/renderer/shell/panels/csvPreview.tsx	6b405ed68cb00977c5b413e24f022c6c551a7778eefb84977ae1da34fb6ce406	ABSENT	181	0
A	frontend/src/renderer/shell/panels/csvPreview.test.tsx	42b886dddc2fd764c044d139de39c4a291c52b22766dda757a8af1ae10ff7f03	ABSENT	128	0
A	frontend/src/renderer/shell/panels/documentPreviewRegistry.tsx	483dc5e6919d5863809f080a6b9496e7d34ce59b3f988fbe6b6611137e22f0ad	a280100eed95872e2fab4fd80b27da73fc5c453e35cef288bea1f1a40ee2e005	65	63
B	frontend/src/renderer/services/keybindings.ts	78941bb80c7f4cd2fb93a928624d8da0cb0bc545e6f8a538ea744284939b5727	ABSENT	366	0
B	frontend/src/renderer/pages/ShortcutsPanel.tsx	d41c8a3594eb601554bc8391d7ba4b89ec338924bdeaf395f7d6c33d39455de6	16f05b224271994ea0d786963536fe38a0783c6b0c1c0651660d4597170978ce	391	226
B	frontend/src/renderer/services/keybindings.test.ts	5a315dbd59c62d2d047d1cab473d9626281bd3e822447197c5f25b759eb43a0c	ABSENT	522	0
B	frontend/src/renderer/pages/ShortcutsPanel.test.tsx	0b9a70c43aa7d26e9b79b13321223e1c9d36036be42fb2b0143a5c22bc29b918	ABSENT	272	0
B	frontend/src/renderer/services/shortcuts.test.ts	1876b04479a01ce8040c934f66b52f25150c804fdd5b374a740f70324536282a	99af733d08e0562758b55d4254c06b5dec6678f348f655ce6829e8e18f7c2c19	46	30
B	core/atlas/api/u6_router.py	59cb134b3bc8c70ce56a916e157b499e33bb6ddbe229d1774d80ea7e8dad4182	b5682287dd4fde459034171c50d8440fc52c8369e393a0a340f7c6f7e99d3076	391	312
B	core/tests/test_u6_keybindings.py	7e9953eb50215e4f192b72d5f56596923629f71d53474f94d9817f339d362d70	ABSENT	133	0
D	core/atlas/api/workspace_router.py	c8b6709db065ba8cdcfb189fd82d73a8c403bee8bd1ac4588fcfee67a0aafb41	96133b377d95d4db45cdb109d484ab2224ea7b78f5460386643701daf25ea61c	2996	2325
D	core/atlas/memory/__init__.py	13cfad394b67ae26c427fc1d76367661541962e7dff496610340c7057bd2b845	99074f25fff7776769886d6aac1abeb14a5975e0ffb2d92d938044cd1badc0d6	1024	964
D	core/tests/test_conversation_worktree_create.py	723ed518455b07863e5a6f1802283e7e080db1930bc1ea6224529cbc72bfde83	ABSENT	771	0
D	core/tests/snapshots/routes.json	aef47ce9b12e206a389d4d2430ff7cfc5a785ff9657b9a89b9aebb5c0ea3da70	9c1027bb6f7846d455704bda5c1defac291ff2a52eb2ff1539b45a8a42ed80b1	43119	41929
```

说明：候选树与源树同基线，tracked 文件的候选复制前工作区哈希与 `git show` blob 哈希不同仅因 CRLF/LF 转换；复制后 14 个文件与源树**逐字节相同**（`logs/02-pre-copy-candidate.txt` + 复制校验输出）。

## 3. 复制、基线冲突与最小 diff

一次性 `cp -p` 复制 14 个文件，逐文件 sha256 校验 `OK`。候选树复制前 clean，因此无覆盖风险。

**冲突检查**：三个组件路径集合两两交集为 0（`A∩B=0 A∩D=0 B∩D=0`，`logs/44-set-intersections.txt`）。**无同名文件冲突，无基线冲突**；无需要单独留证的冲突项。

候选树最终状态（`git status --short`）：7 个 `M` + 7 个 `??`，全部属于本包；`.tmp/` 被 `.gitignore` 忽略。tracked 部分 `git diff --stat` = **7 files changed, 2433 insertions(+), 250 deletions(-)**；加上 7 个新文件（2379 行），总计 **14 files, 4812 insertions(+), 250 deletions(-)**。

按组件分组的最小 diff（候选树 `.tmp/par10-t4/diffs/`，均已用 `git apply --check --reverse` 验证 EXIT 0）：

| 组件 | Patch | sha256 | 文件数 | numstat |
|---|---|---|---|---|
| A | `A-csv-preview.patch` (344 行) | `ac5f8979da6407405d9694d961016a30e79d925693138fba8e01197ca11840da` | 3 | `documentPreviewRegistry.tsx 2/0`；`csvPreview.tsx 182/0`；`csvPreview.test.tsx 129/0` |
| B | `B-keybindings.patch` (1752 行) | `febc60fa4eb4ca6f770afece2023505780d4672c852a61ace5dd068aaa2a3d25` | 7 | `u6_router.py 94/15`；`ShortcutsPanel.tsx 174/9`；`shortcuts.test.ts 17/1`；`keybindings.ts 367/0`；`keybindings.test.ts 523/0`；`ShortcutsPanel.test.tsx 273/0`；`test_u6_keybindings.py 134/0` |
| D | `D-worktree-recovery.patch` (3500 行) | `ffae388c591219686c1674100156c19b5db9860c0e9aa10e26dc53a6c60026ba` | 4 | `workspace_router.py 671/0`；`memory/__init__.py 60/0`；`routes.json 1415/225`；`test_conversation_worktree_create.py 771/0` |

D 的 `workspace_router.py` 671/0、`routes.json` 1415/225 是源树从 HEAD 起的累计 PAR-07-D/PAR-08-D/PAR-09-D2 状态；B 的 numstat 与 PAR-09-B2 回执完全一致；A 为 PAR-08-A 的 313 insertions 状态。

## 4. 复跑验证矩阵

所有前端命令 cwd = 候选树 `frontend/`，使用 `D:/Atlas/node_modules/.bin/vitest`（5.0.4）与 `tsc`；依赖通过工作树祖先目录解析到 `D:/Atlas/node_modules`（候选树不放 node_modules）。所有 Python 命令 cwd = 候选树 `core/`，`PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1`，`-p no:cacheprovider`，basetemp 均在候选树 `.tmp/` 下。

### 4.1 A — CSV/TSV 空态

功能入口：`FilesPanel` 点文件树 → `selectFile` → `DocumentPreview` → `documentPreviewRegistry` 按扩展名选 `CsvFilePreview`。

| 检查 | 命令 | 退出码 | 结果 | 日志 |
|---|---|---|---|---|
| 定向 vitest | `vitest run --root . src/renderer/shell/panels/csvPreview.test.tsx src/renderer/shell/panels/documentPreviewRegistry.test.tsx src/renderer/shell/panels/FilesPanel.test.tsx` | **0** | **3 files / 17 tests passed**（csv 10、registry 3、FilesPanel 4） | `logs/10-A-vitest.txt` |
| renderer tsc | `tsc -p tsconfig.renderer.json --noEmit` | **0** | 无输出 | `logs/11-A-tsc.txt` |
| 夹具构建 | `node build.mjs`（esbuild） | **0** | `bundle.js` 1,143,517 bytes，sha256 `f4f3bcbb43b03244560e24a710138ebcda6d2cbcd07b7291964b6deb5e2c507f`，与源 A 工作树 bundle **哈希相同** | `logs/12-A-bundle-build.txt` |
| 隔离 Electron | `electron.exe --user-data-dir=<候选>/.tmp/par08-probe-par10/user-data <候选>/.tmp/par08-probe-par10/electron-main.cjs` | **0** | **29 PASS / 0 FAIL**，`exit code 0 (failures=0)` | `logs/13-A-electron-stdout.txt`；`electron-a-evidence/par10-t4-A-electron-log.txt` |

Electron 44.7.0（Chromium 152.0.7977.130），独立 `--user-data-dir` + `app.setPath('userData')`，渲染候选树构建的 `FilesPanel`，真实鼠标事件点开三个夹具：

- `empty.csv`（0 字节，`od` 核对）：`marker=empty`，note=`空文件，没有可显示的表格行。`，`tableHtml=null`；截图 `electron-a-evidence/par08-a-electron-empty.png`（1184×755，18,927 bytes）。
- `quoted-empty.csv`（字节 `22 22` = `""`）：`marker=quoted-empty.csv`，note=`1 行 · 逗号分隔`，1 行 1 列表格（`thCount=1, trCount=1, tdCount=0`），空单元格 `&nbsp;` 可见占位（`nbspCount=1`），不含「空文件」；截图 `.../par08-a-electron-quoted-empty.png`（18,962 bytes）。
- `sample.tsv`（`name\tage\nAlice\t30\n`）：`marker=sample.tsv`，note=`2 行 · 制表符分隔`，`thCount=2, trCount=2, tdCount=2`，表格含 `name/age/Alice/30`，不含「空文件」；截图 `.../par10-t4-A-electron-sample-tsv.png`（21,854 bytes）。

本次在 A 原夹具基础上增加 TSV 用例（同一 harness，未改产品代码）；A 其余边界（引号内换行、分号首列跨引号、ragged/截断等）由 10 个 vitest 用例复验。

### 4.2 B — 快捷键首次保存与同 action 裁决

功能入口：`ShortcutsPanel` → `KeybindingsSync`（默认值基线 `effectiveKeybindings`）。

| 检查 | 命令 | 退出码 | 结果 | 日志 |
|---|---|---|---|---|
| 后端 pytest | `python -m pytest tests/test_u6_keybindings.py -q --basetemp=../.tmp/par10-t4/basetemp-b` | **0** | **7 passed**, 5 warnings | `logs/20-B-pytest.txt` |
| 定向 vitest | `vitest run --root . src/renderer/services/keybindings.test.ts src/renderer/services/shortcuts.test.ts src/renderer/pages/ShortcutsPanel.test.tsx` | **0** | **3 files / 33 tests passed**（23+4+6） | `logs/21-B-vitest.txt` |
| renderer tsc | 同 §4.1 最终全量 tsc | **0** | 无输出 | `logs/41-final-tsc.txt` |
| 真实双窗 Electron | `bash run_electron.sh`（临时 uvicorn 挂真实 `atlas.api.u6_router`；两窗各自 `--user-data-dir`） | **0** | **3/3 场景 PASS**，每场景两窗 exit 0，validate exit 0 | `logs/23-B-electron-run2.txt`；`electron-b-evidence/par10-t4-B-electron-summary.json` |

真实双窗结果（候选树 bundle 与源 B 完全一致：bundle sha256 `33b6d1e8062b71a36a512457c237ffaf375403d8a841789052e4bd78373c8dac`；panel `d41c8a3594eb…`；service `78941bb80c7f…`）：

| 初始状态 | PUT 序列 | 最终文件 | 结果 |
|---|---|---|---|
| 文件缺失（首次创建） | `200`（win1 创建）→ `409`（win2 newTask）→ `200`（win2 按最新 revision 重放） | `palette=["Ctrl+Alt+U"]`, `newTask=["Ctrl+Alt+N"]`, `settings=["Ctrl+,"]`，sha256 `17d2c1acd0777dff…` | PASS，无默认值假冲突；retry 后无 conflict/replayConflict/conflictRows |
| 文件存在（不同 action） | `200` → `409` → `200` | 同上，sha256 `17d2c1ac…` | PASS，win2 只重放本机 newTask，win1 palette 保留 |
| 同 action（palette） | `200`（win1 `Ctrl+Alt+U`）→ `409`（win2 `Ctrl+Alt+O`）→ 手工裁决后 `200` | `palette=["Ctrl+Alt+O"]`, `newTask=["Ctrl+N"]`，其余默认不变，sha256 `6467823c45e4159a…` | PASS；retry 先报 1 行逐项冲突（本机 `Ctrl+Alt+O` / 文件 `Ctrl+Alt+U`）、未选择前不写文件；点「保留本机」后写出 |

每场景 backend 日志均为 **2×200 + 1×409**；`par10-t4-B-electron-summary.json` 总结果 `PASS`，`problems: []`。证据含两窗 ready/saved/409/retry（或 replay-conflict/resolved）JSON 与 PNG。

第一次 harness 运行退出码 1（`logs/22-B-electron-run.txt`）：原因仅为我改名的证据前缀与 driver 内硬编码前缀不一致，validator 找不到快照；实际 driver 已产出正确 409/retry/replay/resolved 快照，后端序列也正确。修正 driver 前缀后重跑，**产品行为未变**。

### 4.3 D — 工作树回滚、恢复与路由快照

功能入口：`POST/GET/DELETE /api/conversations/{id}/worktree`、`/worktree/merge`、`/worktree/recovery`。

| 检查 | 命令 | 退出码 | 结果 | 日志 |
|---|---|---|---|---|
| 三文件套件 | `pytest -q -o addopts= --tb=short --basetemp=../.tmp/par10-t4/basetemp-d tests/test_conversation_worktree_create.py tests/test_engine_worktree_pinned_revision.py tests/test_route_snapshot.py` | **1** | **23 passed, 1 failed**；唯一失败为既有 `test_fastapi_lazy_includes_preserve_effective_paths_parameters_and_order`（`APIWebSocketRoute.original_route` AttributeError，与源 D 回执逐字相同） | `logs/30-D-pytest-suite.txt` |
| worktree 逐项 | `pytest -v ... tests/test_conversation_worktree_create.py` | **0** | **19/19 passed**（真实 `git init -b main` 临时仓库 + 真实 `MemoryStore` + `httpx.ASGITransport`） | `logs/32-D-worktree-v.txt` |
| 冻结路由快照 | `pytest ... tests/test_route_snapshot.py::test_routes_match_frozen_snapshot` | **0** | **1 passed** | `logs/31-D-snapshot-match.txt` |
| worktree 回归 | `pytest ... tests/test_backend_parity_wave2.py -k worktree` | **0** | **6 passed, 16 deselected** | `logs/33-D-regress-wave2.txt` |
| memory 回归 | `pytest ... tests/test_memory.py` | **0** | **16 passed** | `logs/34-D-regress-memory.txt` |

19 个 worktree 用例逐项覆盖任务要求：正常 `create/status/merge/delete`（`test_create_status_merge_delete_over_http`）；记录失败后回滚（`test_record_failure_with_successful_cleanup_reports_rolled_back`）；记录+清理都失败（`test_record_and_cleanup_failure_reports_rollback_failed`）；恢复重试（`test_retried_create_cleans_residue_clears_marker_and_succeeds`、`test_retry_clears_orphaned_directory_after_git_lost_registration`、`test_explicit_recovery_removes_residue_and_allows_create`）；并发唯一赢家；10 个边界拒绝用例（目录根/workspace/managed root/repo root/非托管目录/跨会话 path+branch/base/reparse link/create-retry 拒绝不安全记录）。清理失败为 monkeypatch `WorktreeService.remove` 注入（沿用源包方法）。

### 4.4 组件间互不影响

| 检查 | 退出码 | 结果 | 日志 |
|---|---|---|---|
| 文件集交集 | — | A∩B = A∩D = B∩D = **0** | `logs/44-set-intersections.txt` |
| 全量前端 vitest（A+B 同树） | **0** | **83 files / 408 tests passed**（= B 源 398 + A 新增 csv 10） | `logs/40-full-vitest.txt` |
| 组合 renderer tsc | **0** | 无输出 | `logs/41-final-tsc.txt` |
| 事件三真源契约 | **0** | **13 passed** | `logs/42-event-contract.txt` |
| 路由快照（B 的 u6 + D 的 workspace 同在） | **0** | 1 passed（见 §4.3） | `logs/31-D-snapshot-match.txt` |
| 交叉 import | — | A 面板只依赖 `csvPreview`/`documentPreviewRegistry`/backend-adapter；B 面板/服务不引用 A；D router import 与 A/B 前端无交集 | 本回执 §3 检查 |

A、B、D 路径互不重叠、无同名文件，组合后前端全量、后端契约、路由快照均通过。

## 5. 可重跑命令（汇总）

```bash
# 变量
CAND=D:/Atlas/.worktrees/zcode-par10-desktop-recovery-candidate
CORE=$CAND/core; FE=$CAND/frontend; EV=$CAND/.tmp/par10-t4

# A
cd $FE && D:/Atlas/node_modules/.bin/vitest run --root . \
  src/renderer/shell/panels/csvPreview.test.tsx \
  src/renderer/shell/panels/documentPreviewRegistry.test.tsx \
  src/renderer/shell/panels/FilesPanel.test.tsx
cd $FE && D:/Atlas/node_modules/.bin/tsc -p tsconfig.renderer.json --noEmit
cd $CAND/.tmp/par08-probe-par10 && node build.mjs
PAR08_EVIDENCE_DIR=$EV/electron-a-evidence PAR08_USER_DATA_DIR=$CAND/.tmp/par08-probe-par10/user-data \
  D:/Atlas/node_modules/electron/dist/electron.exe \
  --user-data-dir=$CAND/.tmp/par08-probe-par10/user-data \
  $CAND/.tmp/par08-probe-par10/electron-main.cjs

# B
cd $CORE && PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_u6_keybindings.py \
  -q -p no:cacheprovider --basetemp=$EV/basetemp-b
cd $FE && D:/Atlas/node_modules/.bin/vitest run --root . \
  src/renderer/services/keybindings.test.ts src/renderer/services/shortcuts.test.ts \
  src/renderer/pages/ShortcutsPanel.test.tsx
cd $CAND/.tmp/par09b2-harness && bash run_electron.sh

# D
cd $CORE && PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider \
  -o addopts= --tb=short --basetemp=$EV/basetemp-d \
  tests/test_conversation_worktree_create.py tests/test_engine_worktree_pinned_revision.py \
  tests/test_route_snapshot.py
cd $CORE && PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider \
  -o addopts= tests/test_route_snapshot.py::test_routes_match_frozen_snapshot \
  --basetemp=$EV/basetemp-d-snap
```

## 6. 未覆盖项 / 边界

- 未启动完整桌面产品（`npm run dev`/packaged Electron/完整 `atlas.server` lifespan）。A 使用 `useAtlasStore` 测试 shim + 本机 HTTP 夹具；B 使用临时 uvicorn 仅挂真实 `u6_router`；均非完整客户端启动。
- B 同 action 的真实 Electron 裁决只点了「保留本机」；「采用文件」由已有 panel/unit 用例覆盖。`missing` 场景两窗从空 localStorage 启动；机器已有本地缓存但无文件的组合未跑。
- D 未复现真实 OS 级 Windows `Permission denied` 文件锁；清理失败用 monkeypatch 注入。最终 link 检查与 `git worktree remove`/`rmtree` 之间仍有 check-then-act 窗口（源包已记录，非本次修复对象）。GET recovery 只读、不做所有权校验。
- D 的既有失败 `test_fastapi_lazy_includes_preserve_effective_paths_parameters_and_order` 与基线/源树逐字一致，不是本候选引入；`test_routes_match_frozen_snapshot` 通过。
- A 仍沿用「首行即表头」语义：`""` 渲染为 1 行 `<th>`、0 条 tbody 记录；若要求额外一条 `<td>` 空行需另改语义。
- 前端依赖从工作树祖先解析到 `D:/Atlas/node_modules`；候选树自身不含 `node_modules`，这是本机验证路径，不影响 14 个候选文件的转移。
- 工作区源文件为 CRLF，`git show` blob 为 LF；patch 由 git 归一化生成，`git apply --check --reverse` 三个 patch 均 EXIT 0。
- 未跑 `ruff`；未 commit/push/merge/stash；主工作区只新增本回执，候选树只新增组件文件与 `.tmp/par10-t4` 证据/夹具。

## 7. 证据路径

候选树内（`D:/Atlas/.worktrees/zcode-par10-desktop-recovery-candidate/.tmp/par10-t4/`）：

- `logs/01-source-hashes.txt`、`02-pre-copy-candidate.txt`、`03-candidate-status.txt`、`43-diff-numstat.txt`、`44-set-intersections.txt`
- `logs/10..13-A-*`、`20..23-B-*`、`30..34-D-*`、`40..42-*`
- `diffs/{A-csv-preview,B-keybindings,D-worktree-recovery}.patch`
- `electron-a-evidence/`（A 日志 + 3 PNG）、`electron-b-evidence/`（B 三场景 summary/run/backend/driver 日志 + JSON/PNG）
- A 夹具：`.tmp/par08-probe-par10/`；B 夹具：`.tmp/par09b2-harness/`

源树与基线：A `zcode-exec06-csv-preview`、B `zcode-exec06-keybindings-cas`、D `zcode-par07-worktree-api-fix`，均 HEAD `060071ab`，工作区状态见 §1。

PAR10_RECEIPT T4 READY
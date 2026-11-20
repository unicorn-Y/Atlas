# PAR-10 T6-23 回执：官方 DSH rc.4→rc.5 非搜索增量审计与实施

- 候选树：`D:\Atlas\.worktrees\zcode-par10-rc5-residual`
- 分支：`zcode/par10-rc5-residual`，基线 HEAD `060071ab`，作业前后 `git status --short` 均为 0 行。
- 官方源：`D:\Atlas\.worktrees\_codex-dsh-rc5-source.git`
  - `atlas-base-rc4` = `3f321d32bfe382212a8ed8785c1d47a5a300aa23`
  - `atlas-target-rc5` = `9c2670d3bce5275e0d1610272958121af87787bb`
- 临时目录：`D:\Atlas\.worktrees\_codex-par10-probes\t6-23-r2\{tmp,logs,scripts}`；所有子进程显式注入 `TEMP`/`TMP` 到该 `tmp`。
- 状态：**READY**。非搜索产品代码缺口 = 0，且不是"看着像清单"：433 个路径逐项落账，380 个 `package.json` 逐文件做 JSON 深层比对，53 个非清单文件做集合等值断言，Atlas 版本事实面用真实 rc.4/rc.5 清单只读回放。
- 边界：T6-19 搜索工位的工作树**未读取、未修改**；本包只读官方源码和 T6-19 已落盘回执。搜索相关文件全部判归 T6-19，本包不重复实现。

---

## 1. 变更全集与机器核对

命令（cwd `D:\Atlas`）：

```bash
git --git-dir=D:/Atlas/.worktrees/_codex-dsh-rc5-source.git diff --name-status \
  atlas-base-rc4 atlas-target-rc5
```

结果：**433 行**，退出码 0；`raw` 模式核对无 gitlink、无文件模式变化（`4 :000000 100644` = 新增，`429 :100644 100644` = 修改）；无删除。

| 类别 | 数量 | 核对方式 | 结果 |
|---|---:|---|---|
| 包清单 `package.json` | 380 | 逐文件解析 rc.4/rc.5 两个 blob，删除顶层 `version` 后 JSON 深层相等 | **380/380 仅版本变化**；旧版本全为 `0.2.2-rc.4`，新版本全为 `0.2.2-rc.5`，0 例外 |
| 文档 / 本地化 | 29 | 精确路径集合 + 逐文件 diff 审阅 | 29/29 均为网页搜索/获取主题（见 §3） |
| 代码 / 测试 | 17 | 精确路径集合 + 逐文件 hunk 审阅 | 17/17 均为搜索语义或其测试（见 §2） |
| 快照 | 5 | 精确路径集合 + 逐文件 diff 审阅 | 5/5 均为 `web-search-*` 会话快照（见 §3） |
| 配置 | 2 | 精确路径集合 + 逐文件 diff 审阅 | 2/2 均为搜索提供方默认值/搜索测试 overlay（见 §2） |
| **合计** | **433** | 433 = 380 + 29 + 17 + 5 + 2 | 与任务书分类完全一致 |

新增文件恰好 4 个，全部是搜索相关文档/测试夹具：

```
A apps/web/tests/search-api-provider.overlay.yml
A docs/upgrade-guide/v0.2.2-rc.4/web-search-deepseek-model-default/guide.i18n.yaml
A docs/upgrade-guide/v0.2.2-rc.4/web-search-deepseek-model-default/guide.md
A docs/upgrade-guide/v0.2.2-rc.4/web-search-deepseek-model-default/guide.zh.md
```

穷举台账：

- `evidence/par10-t6-23-pkg-manifest-audit.tsv`：380 行，逐包 `status/path/name/old_version/new_version/only_version_changed`。
- `evidence/par10-t6-23-nonpkg-ledger.tsv`：53 行，逐文件 `status/category/path/added/deleted/search_related`。
- `evidence/par10-t6-23-scope-audit.json`：集合断言的机器输出（433/4/429/380/29/5/17/2，`problems: []`）。

---

## 2. 17 个代码/测试 + 2 个配置逐项表

判断口径：只要 rc.5 的改动语义属于"搜索提供方选择、搜索请求路由、搜索摘要/去重、搜索设置页、搜索默认值、搜索测试/快照/文档"，即判为搜索相关并归 T6-19。Atlas 侧对照位置为当前候选树 HEAD `060071ab` 的既有实现；T6-19 新增文件仅引用其已落盘回执，不读取其工作树。

| # | 官方文件（rc.5） | 类 | rc.5 变化与目标标签锚点 | 搜索? | Atlas 对应 / 证据锚点 | 处置 |
|---:|---|---|---|---|---|---|
| 1 | `packages/web/web/src/index.ts` | 代码 | `DEEPSEEK_MODEL_ROUTES` :58；`selectSearchProvider(llmProvider)` :229-240；usable 首选 :318 | 是 | `core/atlas/websearch/service.py:81 chain()`；T6-19 §2 `websearch/routing.py` | 搜索；T6-19 专属，排除 |
| 2 | `packages/web/web/src/types.ts` | 代码 | `WebSearchRequest.llmProvider?` :46 | 是 | 同上；T6-19 §2 `route_kind()` | 搜索；T6-19 专属，排除 |
| 3 | `packages/web/tool-web/src/search.ts` | 代码 | `exec.agent?.session.requestContext()?.provider` :409；逐子查询携带 :272 | 是 | `core/atlas/tools/web.py:56 web_search()`；`core/atlas/agent/tool_node.py:1799`；T6-19 §2 | 搜索；T6-19 专属，排除 |
| 4 | `packages/web/web-search-deepseek/src/provider.ts` | 代码 | item 自带 `snippet` 优先、否则 `cited_text` :178；错误文案改 "DeepSeek server-side search" :410 | 是 | `core/atlas/websearch/providers/base.py:32`；T6-19 §2 `providers/deepseek.py map_messages_response()` | 搜索；T6-19 专属，排除 |
| 5 | `packages/web/web-search-deepseek/src/types.ts` | 代码 | `WebSearchResultItem.snippet?: string \| null` :16 | 是 | 同上；T6-19 §2 | 搜索；T6-19 专属，排除 |
| 6 | `packages/client/ui-settings-web-search/src/client/WebSearchCard.tsx` | 代码 | 自动选择时显示固定说明 :69, :77-78 | 是 | HEAD 无网页搜索设置页；T6-19 §2 `WebSearchSettingsPanel.tsx` | 搜索；T6-19 专属，排除 |
| 7 | `packages/client/ui-settings-web-search/src/client/locales.ts` | 代码 | `providerLegacy` 改名 :27/:75；新增 `searchAutoHint` :36/:84 | 是 | 同上；T6-19 §2 命名对齐 | 搜索；T6-19 专属，排除 |
| 8 | `packages/client/ui-settings-web-search/tests/card.client.spec.tsx` | 测试 | 自动选择说明与无提供方面板用例 :398 | 是 | T6-19 §3 设置页测试 | 搜索；T6-19 专属，排除 |
| 9 | `packages/extensions/tool-cordis/src/api-catalog.ts` | 代码（生成目录） | web 选择语义 :4554；`WebSearchRequest.llmProvider` :10605 | 是（生成物内容） | Atlas `core/atlas/introspect/registry.py` 是不同面；无 DSH 生成式插件 API 目录 | 搜索元数据；**N/A 生成物**，语义归 T6-19 |
| 10 | `apps/web/tests/plugin-config.e2e.ts` | 测试 | 自动选择菜单/说明 :171-175、保存/清空 :261-275 | 是 | DSH Web e2e 夹具，Atlas 无对应；T6-19 §3 真实 UI/回环 | 搜索；**N/A 夹具**，语义 T6-19 |
| 11 | `apps/web/tests/search-api-provider.overlay.yml` | 配置（测试） | 固定 `searchProvider: deepseek-search-api` :1-6 | 是 | DSH 测试 overlay，Atlas 无对应 | 搜索；**N/A 夹具** |
| 12 | `apps/web/tests/web-search-round.e2e.ts` | 测试 | 挂载新 overlay :157 | 是 | 同上 | 搜索；**N/A 夹具**，语义 T6-19 |
| 13 | `packages/bundle/base/tests/base.spec.ts` | 测试 | web 行期望仅 `fetchProvider: http` :44 | 是 | `core/atlas/websearch/settings.py:108` 默认顺序；T6-19 §2 自动默认 | 搜索；T6-19 语义 |
| 14 | `packages/web/tool-web/tests/integration.spec.ts` | 测试 | agent Session `requestContext` 夹具 :39 | 是 | T6-19 §3 工具入口测试 | 搜索；T6-19 专属，排除 |
| 15 | `packages/web/tool-web/tests/tool-web.spec.ts` | 测试 | 无配置按路由选择 Search API/Messages :787 | 是 | T6-19 §3 `test_websearch_route_routing.py` | 搜索；T6-19 专属，排除 |
| 16 | `packages/web/web-search-deepseek/tests/deepseek.spec.ts` | 测试 | snippet 自带/空/null 与 cited_text 回退 :104 | 是 | T6-19 §3 DeepSeek 映射测试 | 搜索；T6-19 专属，排除 |
| 17 | `packages/web/web-search-deepseek/tests/settings.spec.ts` | 测试 | 计费描述改 "No per-search charge" :73 | 是 | T6-19 §2 设置文案 | 搜索；T6-19 专属，排除 |
| 18 | `packages/web/web/tests/web.spec.ts` | 测试 | 路由首选套件 :201；readiness 按路由 :305 | 是 | T6-19 §3 路由测试 | 搜索；T6-19 专属，排除 |
| 19 | `packages/bundle/base/cordis.patch.yml` | 配置（组合） | 删除 `searchProvider: deepseek-search-api`，保留 `fetchProvider: http` :488-491 | 是 | `core/atlas/websearch/settings.py:108`；T6-19 §2 `search_provider` 自动 | 搜索；T6-19 语义 |

**逐项结论：17 个代码/测试 + 2 个配置全部与搜索相关；其中非搜索产品代码/配置 = 0。** 9/10/11/12 属于生成目录或 DSH 测试夹具，Atlas 无对应物，按"不适用"处理；其余 15 项的语义均已由 T6-19 回执声明覆盖（`evidence/par10-t6-19.md`，末行 `PAR10_RECEIPT T6-19 READY`）。本包不重复实现搜索功能。

---

## 3. 29 个文档/本地化 + 5 个快照穷举

29 个文档/本地化文件（全部为搜索主题，无产品代码）：

- `.agents/notes`（6）：`implemented/architecture/2026-10-29-web-provider-selection.{md,zh.md,i18n.yaml}`；`implemented/feature/2026-10-15-deepseek-search-fetch-api.{md,zh.md,i18n.yaml}`
- `docs/config-catalog.{md,zh.md}`（2）：仅 `@deepseek-ai/dsh-web` 的 `searchProvider` 注释与源码行号
- `docs/subsystems/web.{md,zh.md,i18n.yaml}`（3）：`llmProvider` 与按路由选择语义
- `docs/upgrade-guide/v0.2.2-rc.4/web-search-deepseek-model-default/guide.{md,zh.md,i18n.yaml}`（3，新增）：DeepSeek 模型默认改走服务端搜索的迁移说明
- `packages/client/ui-settings-web-search/README.{md,zh.md,i18n.yaml}`（3）：Automatic / DeepSeek server-side search 命名
- `packages/web/tool-web/README.{md,zh.md,i18n.yaml}`（3）：工具随模型路由搜索
- `packages/web/web-deepseek-api/README.{md,zh.md,i18n.yaml}`（3）：默认搜索由 Messages 搜索承接、Search API 显式选择
- `packages/web/web-search-deepseek/README.{md,zh.md,i18n.yaml}`（3）：snippet/计费/端点说明
- `packages/web/web/README.{md,zh.md,i18n.yaml}`（3）：seam 选择语义

5 个快照（全部是 `web-search-*` 会话回放）：

1. `snapshots/session/web-search-endpoint-guidance/cordis.snapshot.yml`
2. `snapshots/session/web-search-endpoint-guidance/cordis.yml`
3. `snapshots/session/web-search-legacy-endpoint-guidance/cordis.snapshot.yml`
4. `snapshots/session/web-search-legacy-endpoint-guidance/cordis.yml`
5. `snapshots/session/web-search-legacy-endpoint-guidance/session.v4.jsonl`（仅错误文案 `DeepSeek (legacy)` → `DeepSeek server-side search`）

Atlas 无 DSH 文档树/包 README/会话快照体系；这些文件不复刻。其语义已并入 T6-19 的 Atlas 设置页与测试（`evidence/par10-t6-19.md` §2、§3）。`docs/upgrade-guide/**` 是 DSH 用户迁移向导，Atlas 使用自己的设置路径与命名，不移植原文。

---

## 4. 为什么可以判定"无产品代码缺口"

不是靠文件名像清单，而是下面四个可复算的事实：

1. **集合等值**：`verify_scope.py` 把 433 个路径拆成 380 个 `package.json` 与 53 个非清单路径，并断言非清单路径集合**恰好等于** 29 文档 + 5 快照 + 17 代码/测试 + 2 配置的显式集合；任何多出/缺失路径都会 `problems` 非空并以退出码 1 失败。实际 `problems: []`，退出码 0。
2. **清单只动版本**：`verify_pkg_manifests.py` 对 380 个 `package.json` 分别解析 rc.4/rc.5 JSON，删除 `version` 后深层比较；结果 380/380 相等，旧/新版本集合分别只有 `0.2.2-rc.4`/`0.2.2-rc.5`。没有 `peerDependencies`、`deprecated`、`dsh`、`engines`、scripts 或依赖范围变化。
3. **文档/快照全为搜索主题**：§3 的 29+5 个路径逐项审阅；没有发布说明性质的泛化改动，也没有非搜索子系统文档。
4. **Atlas 不消费 DSH 包**：在 `core/`、`frontend/`、`backend-adapter/` 的 `package.json`/lock/`pyproject.toml` 中 grep `@deepseek-ai/dsh` 与 `deepseek-harness`，清单/锁文件 0 命中；全树 grep 仅命中 `core/atlas/engine/kernel/repair.py` 的源码移植注释和 `core/atlas/upstream/watch.py` 的 GitHub 监视清单，均与 npm 版本消费无关。因此 380 个 DSH 包版本号变化不可能影响 Atlas 运行时。

由此，**非搜索官方增量的适用实现项为 0**；唯一与"版本变化"有关的 Atlas 能力面是插件版本事实（T6-2/T6-6），按任务书做只读核对，见 §5。

---

## 5. Atlas 版本事实只读核对（T6-2 / T6-6）

### 5.1 被核对对象

- T6-2 纯函数：`D:\Atlas\.worktrees\zcode-par10-version-facts\core\atlas\plugins\version_facts.py`
  - sha256 = `ac58aa9b19d88ca31195a7b0621314dd0f524c19cb61a8fdf86f14c7a664a9ca`，与 `evidence/par10-t6-2.md` 记录一致。
- T6-6 接线副本：`...\zcode-par10-plugin-integration-candidate\core\atlas\plugins\version_facts.py`，同一 sha256。
- 主树 `D:\Atlas\core\atlas\plugins\version_facts.py` 不存在；`plugins_router.py` 无 `registry/versions` 路由。即版本事实面**尚未合入主树**；本包不复制、不改写、不冒充已合入。

### 5.2 真实 rc.4/rc.5 清单回放

探针 `verify_version_facts_rc5.py` 用官方两个标签的真实 `package.json` 构造 npm packument（含 `versions`/`dist-tags`），覆盖 374 个带 `peerDependencies` 或对象形 `dsh` 的包（rc.5 中 `peerDependencies` 374 个、对象形 `dsh` 118 个、`deprecated` 0 个），逐包断言：

- `newer_versions("0.2.2-rc.4", ...)` == `["0.2.2-rc.5"]`；
- `include_prerelease=False` 时为空（rc.5 是预发布）；
- 有 `dist-tags.latest=0.2.2-rc.5`、无 dist-tags、裸 rc.5 manifest 三种形状都选中 `0.2.2-rc.5`；
- `version_facts(...)` 对 rc.5 返回的 `peerDependencies`/`deprecated`/`dsh` 与真实 manifest 精确一致；rc.4 与 rc.5 的 facts 相同（因为字段未变）；
- `newer_versions("0.2.2-rc.5", ...)` 为空。

结果：**374/374 通过，`failures: []`，退出码 0**。明细 `evidence/par10-t6-23-version-facts-rc5.json`。

### 5.3 既有测试只读复跑

- T6-2 候选树：`pytest tests/test_plugin_version_facts.py` → **46 passed, 8 skipped**，退出码 0（8 skipped 是 HTTP 路由未接线的既有跳过，非本包引入）。
- T6-6 候选树：同一套件在接线态 → **54 passed**，退出码 0；`tests/test_plugin_registry_integration.py` → **15 passed**，退出码 0（真实回环 registry 的版本/依赖字段/预发布/回退矩阵）。
- 两个候选树在作业前后 `git status --short` 与既有预期一致（T6-2 仅 2 个未跟踪交付文件；T6-6 仍为 12 项在途改动），本包未写入其工作树；测试仅用 `PYTHONDONTWRITEBYTECODE=1`、`-p no:cacheprovider`、`--basetemp` 指向本包 probes。

结论：rc.5 的版本跃迁无需改动 Atlas 版本事实代码；T6-2/T6-6 已验实现可正确识别 rc.5 为 rc.4 的更新版本，并保持事实字段不变。

---

## 6. 命令、退出码与环境

解释器：`C:/Users/25011/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe`（Python 3.11.16）。所有 Python 探针与 pytest 子进程均显式设置 `TEMP`/`TMP` 到 `D:\Atlas\.worktrees\_codex-par10-probes\t6-23-r2\tmp`，pytest 另加 `--basetemp` 到同一 D 盘目录；日志在 `...\t6-23-r2\logs`。

| # | 命令（cwd） | 退出码 | 结果 |
|---:|---|---:|---|
| 1 | `git --git-dir=... diff --name-status atlas-base-rc4 atlas-target-rc5`（D:\Atlas） | 0 | 433 路径；4 A / 429 M |
| 2 | `python -I scripts/verify_scope.py`（probes/t6-23-r2） | 0 | 433 = 380 + 29 + 5 + 17 + 2；`problems: []` |
| 3 | `python -I scripts/verify_pkg_manifests.py`（probes/t6-23-r2） | 0 | 380/380 仅版本变化；0 失败 |
| 4 | `python -I scripts/verify_version_facts_rc5.py`（probes/t6-23-r2） | 0 | 374/374 packument 通过；0 失败 |
| 5 | `pytest -q -p no:cacheprovider tests/test_plugin_version_facts.py`（T6-2 候选 core） | 0 | 46 passed, 8 skipped |
| 6 | 同上（T6-6 候选 core） | 0 | 54 passed |
| 7 | `pytest -q -p no:cacheprovider tests/test_plugin_registry_integration.py`（T6-6 候选 core） | 0 | 15 passed |
| 8 | `git status --short`（候选树） | 0 | 0 行，干净 |

完整 pytest 调用（TEMP/TMP 均指向 `...\t6-23-r2\tmp`，解释器同上）：

```bash
# T6-2 候选
cd D:\Atlas\.worktrees\zcode-par10-version-facts\core
<python> -m pytest -q -p no:cacheprovider \
  --basetemp=D:\Atlas\.worktrees\_codex-par10-probes\t6-23-r2\tmp\t6-2-version-facts \
  tests/test_plugin_version_facts.py                       # exit 0: 46 passed, 8 skipped

# T6-6 候选（接线态）
cd D:\Atlas\.worktrees\zcode-par10-plugin-integration-candidate\core
<python> -m pytest -q -p no:cacheprovider \
  --basetemp=D:\Atlas\.worktrees\_codex-par10-probes\t6-23-r2\tmp\t6-6-version-facts \
  tests/test_plugin_version_facts.py                       # exit 0: 54 passed
<python> -m pytest -q -p no:cacheprovider \
  --basetemp=D:\Atlas\.worktrees\_codex-par10-probes\t6-23-r2\tmp\t6-6-integration \
  tests/test_plugin_registry_integration.py                # exit 0: 15 passed
```

探针完整调用（cwd `D:\Atlas\.worktrees\_codex-par10-probes\t6-23-r2`）：

```bash
<python> -I scripts/verify_scope.py              # exit 0
<python> -I scripts/verify_pkg_manifests.py      # exit 0
<python> -I scripts/verify_version_facts_rc5.py  # exit 0
```

工具性失败记录：第 4 项首次调用退出码 1，原因是探针用 `importlib` 动态加载 dataclass 模块时未先注册 `sys.modules`，`dataclasses` 报 `AttributeError: 'NoneType' object has no attribute '__dict__'`；在探针脚本内补 `sys.modules[spec.name] = module` 后重跑退出码 0。该失败只在探针装载层，未触及 Atlas 代码。

---

## 7. 改动范围

- **候选树产品代码：未改动。** 作业前后 `git status --short` 均 0 行；未 commit / push / merge / reset / stash。
- **本包证据（主树 `tasks/.../evidence/`，该目录本身为主树既有未跟踪目录）**：
  - `evidence/par10-t6-23-rc5-residual.md`（本文件）
  - `evidence/par10-t6-23-pkg-manifest-audit.tsv`（380 行）
  - `evidence/par10-t6-23-nonpkg-ledger.tsv`（53 行）
  - `evidence/par10-t6-23-version-facts-rc5.json`
  - `evidence/par10-t6-23-scope-audit.json`
- **探针脚本/日志（D 盘隔离区，不在仓库内）**：
  - `D:\Atlas\.worktrees\_codex-par10-probes\t6-23-r2\scripts\{verify_scope.py, verify_pkg_manifests.py, verify_version_facts_rc5.py}`
  - `...\t6-23-r2\logs\*`（含 `pkg-manifest-audit.json`、`version-facts-rc5.json`、两次 pytest 日志）
- 未改主工作树源码、未读取/修改 T6-19 工作树、未碰用户配置/数据/凭据；未调用真实模型/付费服务；未使用 8765 端口；不需要 18980–18989 回环（T6-6 测试使用 `127.0.0.1:0` 临时端口）。

---

## 8. 未验项与边界

1. 未访问 GitHub Release API/发布说明；审计宇宙严格限定为任务书给定的两个源码标签之间的 433 个文件。
2. 未构建或运行 DSH 自身测试（需要 pnpm/workspace，且非审计必需）；官方代码只做 blob 审阅和清单解析。
3. 未验证 npm registry 上 rc.5 的发布状态、dist-tags 或安装行为；源码标签不含 registry 状态。
4. 未独立复验 T6-19 搜索实现（明确排除，且禁止读取其未完成工作树）；只引用其已落盘 READY 回执。
5. 版本事实模块与 `/api/plugins/registry/versions` 路由仍在 T6-2/T6-6 候选树，未合入主树；本包的只读复跑不能替代合并后的主树验证。
6. 未做真实 DeepSeek/网络调用；未消耗任何付费配额。

---

## 9. 覆盖台账收口

| 处置 | 数量 | 说明 |
|---|---:|---|
| 仅版本与清单（Atlas 无需改产品代码） | 380 | 380/380 `package.json` 仅 `version` 行变化 |
| 搜索相关，归 T6-19（本包排除） | 53 | 17 代码/测试 + 2 配置 + 29 文档 + 5 快照 |
| 缺失且适用、本包需实现 | **0** | 非搜索产品代码/配置集合为空 |
| 不适用 Atlas（生成物/DSH 夹具/DSH 文档/快照） | 4 + 34 | `api-catalog.ts` + 3 个 e2e/overlay 夹具；29 文档 + 5 快照 |
| Atlas 版本事实只读核对 | 1 面 | T6-2/T6-6：374 真实清单 + 54 + 15 测试通过 |

PAR10_RECEIPT T6-23 READY

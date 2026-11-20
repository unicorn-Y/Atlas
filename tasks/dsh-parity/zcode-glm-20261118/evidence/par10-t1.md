# PAR-10-T1 · registry 策略接入实际插件安装 · 回执

日期：2026-11-19
状态：**策略与执行器已验证；接线补丁已对在途安装链 apply-check 通过并在隔离沙箱实际入口验证 35/35；因真实安装链不在候选树 HEAD、仍在他人未提交文件中，生产接线未硬改，标记 PARTIAL**
工作树：`D:\Atlas\.worktrees\zcode-par10-registry-runtime`，分支 `zcode/par10-registry-runtime`，HEAD `060071ab2ecf86d41cab90e98160183ce126bc69`
源树：`D:\Atlas\.worktrees\zcode-par09-plugin-registry`，分支 `zcode/par09-plugin-registry`，HEAD 同基
主工作区：只读；未合并、未 push、未 commit、未 stash；未触碰真实数据、账号或凭据；主树在途文件哈希在作业前后一致

---

## 1. 基线与源哈希

| 对象 | 值 |
|---|---|
| 候选树 HEAD | `060071ab2ecf86d41cab90e98160183ce126bc69`（`test(main): tolerate the port field D1 added to ensureBackendRunning`） |
| 候选候选树 `git status --short` | 仅 4 个新文件（见 §2/§3），无 M/删除 |
| 候选 HEAD `core/atlas/plugins/runtime.py` | sha256 `42750704dbc7f35a0d8812f8b138cbae52cf6c536eef84664bc9a19f5dbf430e`，1596 行，**无** `start_install_operation` / npm/pnpm/registry 安装链 |
| 候选 HEAD `core/atlas/api/plugins_router.py` | sha256 `1e6f85f1f372dc2bf9f81617ee861a4a8f65af98728892de2eae7bd71a108dd1`，471 行；`/api/plugins/install` 在 `:135-155` 同步调用 `install()` |
| 主树在途 `core/atlas/plugins/runtime.py` | sha256 `379cc28efba95779825a6ccb31fa5fc51907b159509978084a0dc6dde0936b4f`，2586 行，LF，mtime `2026-11-16 17:32`，`git diff --stat` +1044/-42；只读参考 |
| 主树在途 `core/atlas/api/plugins_router.py` | sha256 `1c553ca225738cb2619252c0d71f647745b501b0af8483c7bfcd987c9df6b206`，602 行，CRLF，mtime `2026-11-16 17:14`，+131 行；只读参考 |
| 主树未跟踪 `core/atlas/plugins/compatibility.py` | sha256 `450b6cef0c51da67acc22073b13b4fe23533b37cf0b15388faf03047d66f41a2`，62 行 |
| 主树未跟踪 `core/tests/test_plugin_install_operations.py` | sha256 `d649c57249dc2c997e4bc71e2c5610d02ce4103239fbf0ce3342e7f82064b332`，1046 行，23 tests |
| 解释器 | Python 3.11.16 (MSC v.1944 64 bit)，`sys.executable=C:\Users\25011\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe` |
| Node | v24.18.1（仅用于以假 npm/pnpm `.cjs` 驱动安装链，不访问网络） |

主树 `runtime.py` / `plugins_router.py` 作业前后 sha256 一致，未被本包修改。

---

## 2. 从 PAR-09 源树移入（字节一致）

| 文件 | 源 sha256 | 源 md5 | 行数 | 候选树 sha256 |
|---|---|---|---|---|
| `core/atlas/plugins/registry_plan.py` | `165c563c6a06e205b5d6bc61826379e25f1d32869bdcbda95bd7e0f26d367522` | `435c73b26d472e49ddd3201d15481c24` | 497 | 同源一致 |
| `core/tests/test_plugin_registry_plan.py` | `66fe200bd18eef019cd05ad882e9e7df8243bb14bc33d1dbcf339bebd5921ed5` | `5ced03c6689476f27bdf275a34a7da8d` | 378 | 同源一致 |

PAR-09 的 44 项纯函数测试在候选树原样通过。

---

## 3. 新增执行器与测试

### 3.1 `core/atlas/plugins/registry_install.py`

sha256 `06c6a9c7a552cf8b34cf7378feacefc9bc76fb9b3a0d839f0b990a68673f60fd`，388 行。补齐 PAR-09 明确未包含的“按 plan 执行/失败归因/脱敏”部分：

- `build_install_plan(source, registry=..., fallback_registries=...)`
  - 配置主源固定为公开 npm `OFFICIAL_NPM_REGISTRY`，fallback 为用户显式列表；
  - 请求 `registry` 在配置集内才允许后续 fallback；私有/自定义请求不在集合内 → **单源**，`requested-custom` + `requested-registry-not-configured`；
  - `registry=None`（pnpm 自身 registry，`resolved` 未知）→ 单源 `(None,)`，`pnpm-own-unknown`，**不**追加公共 fallback；
  - fallback 参数必须是 list/tuple，否则 `ValueError`（避免字符串被逐字符迭代）。
- `raw_registry_urls(...)`：plan 存归一化 URL（去 userinfo），实际调用 npm/pnpm 时映射回调用方原始 URL（含凭据）。凭据只进子进程参数，不进 plan/attempt/state。
- `run_registry_attempts(plan, attempt, ...)`：按 plan 顺序逐个 registry 执行；仅 `attribute_failure == "registry"` 且存在下一源时才推进；`spec-host`/`other`/单源不回落；支持取消检查、`succeeded` 扩展（pnpm `ERR_PNPM_IGNORED_BUILDS`）、逐次 `on_attempt` 上报。
- `classify_registry_failure(returncode, output)`：timeout / no-matching-version / not-found / network / other，其他类型不重试。
- `redact_output(text, sensitive_paths=...)`：去 URL userinfo、`_authToken=`/`NPM_TOKEN=`/`Authorization` 等赋值、query 密钥、`C:\Users\<user>`、`/home/<user>` 及调用方给出的私有根；幂等。
- `RegistryAttemptResult.to_dict()` 输出稳定字段 `ok/finalRegistry/failureKind/attribution/failureSummary/fallbackAttempted/fallbackRefused/attempts`，attempt 只存归一化 registry 与脱敏 output。

### 3.2 `core/tests/test_plugin_registry_install.py`

sha256 `aab9f33cb2df77cbc3f40bdb2d561dad137d26e7a0eb45fca5e9c231a3b4e125`，393 行，16 tests，`pytestmark = pytest.mark.unit`。覆盖：公共成功、公共失败→mirror、私有单源、pnpm-own 未知单源、spec host 不回落、other 不回落、timeout 回退、凭据“只下发不落状态”、路径脱敏/幂等、plan 形状与非法 fallback、ignored-build 成功语义、取消、URL 对齐、分类矩阵、失败摘要取错误行。

---

## 4. 真实安装链冲突与接线补丁（未硬改）

### 4.1 冲突事实

候选树 HEAD 的“实际安装入口”只有本地/git/marketplace，**没有 npm/pnpm 安装操作链**：

- `core/atlas/plugins/runtime.py:1063-1075` `install_local`、`:1179-1192` `install_git`、`:1194-1204` `install`，无 `registry`/`fallbackRegistries`/`start_install_operation`；
- `core/atlas/api/plugins_router.py:112-155` `install-local`/`install` 同步调用 `install()`；无请求任务、wait/cancel、`fallbackRegistries`。

真实 npm/pnpm 安装链只存在于主树**他人未提交**文件（mtime 2026-11-16，作业期间未变化）：

- 主树 `core/atlas/plugins/runtime.py:370-410` `start_install_operation`；`:504-532` `_run_package_manager`（pnpm `--registry`）；`:656-681` `_run_npm_pack`（npm `--registry`）；`:773+` `_run_install_operation_locked`；
- 主树 `core/atlas/api/plugins_router.py:136-160` 安装操作入口、`:165-187` wait/cancel；
- 另有未跟踪 `compatibility.py`（在途 runtime 导入）与 `test_plugin_install_operations.py`。

按派发“实际安装链与主树/其他作者在途文件冲突时报告文件/行号与替代测试范围，不硬改”，未把这些在途文件复制进候选树，也未修改主树。候选树保持仅本包新增 4 文件。

### 4.2 补丁

`D:\Atlas\tasks\dsh-parity\zcode-glm-20261118\evidence\par10-t1-wiring.patch`
sha256 `6fb780a69cbebb6adffb370db196f314ddc45cfdc75706700a47ffca14ea697e`，278 行。

对**主树在途版本**生成，`git -C D:\Atlas apply --check --verbose <patch>` **exit 0**（未应用）。内容：

1. `runtime.py` 导入 `registry_install` 执行器与 `registry_plan.attribute_failure`；
2. `start_install_operation(..., fallback_registries=None, ...)`：构建 plan/attempt URLs，`registryPlan` 写入 operation；非法 registry 配置返回不含原始 URL 的 `ValueError`；仅在 fallback 非空时把 fallbacks 加入 request digest（旧 requestId 摘要不变）；
3. npm pack：由 `run_registry_attempts` 逐源尝试，失败归因写入 `registryAttempts/registryOutcome/failureAttribution/failureKind/failureSummary`；
4. pnpm 依赖安装与审批后二次安装：同样按 plan 尝试；`ERR_PNPM_IGNORED_BUILDS` 保留为审批流，不当作 registry 失败换源；
5. git/marketplace clone 失败：记录 kind/attribution/summary（`spec-host` 不换源），输出脱敏；
6. `plugins_router.py`：`/api/plugins/install` 与 marketplace install 校验并转发 `fallbackRegistries`（list、≤8、元素为字符串；否则 422）。

补丁不包含：pnpm 自身 registry 的 `resolved` 读取（保持 `None` → 未知 → 单源，安全不回落）、前端 `registryPlan` 展示。

---

## 5. 真实入口的本地模拟验证（无真实 registry/账号/凭据）

- Harness：`D:\Atlas\tasks\dsh-parity\zcode-glm-20261118\evidence\par10-t1-harness.py`，sha256 `d3238ccd69640e1083de5ef9c141841c2f5e7146c5a782401c0469cde65e2156`，362 行。
- 沙箱：候选树 HEAD `atlas` 包 + **在途 runtime/router 的自包含副本**（候选树 `.tmp/par10-t1/sandbox`），补丁以 `git apply -p1` 应用后加载；主树未写。
- 包管理器：临时目录内生成 `.cjs` 假 npm / pnpm，由真实 `node` 执行；npm“成功”只把预置 `.tgz` 复制到 `--pack-destination`，失败输出/退出码由场景规则决定；pnpm 同法。全程无网络。
- 入口：`PluginRuntime.start_install_operation → _run_install_operation_locked`（真实安装任务），以及补丁后的 FastAPI `/api/plugins/install`。
- 命令（cwd 候选树）：
  `python -I D:/Atlas/tasks/dsh-parity/zcode-glm-20261118/evidence/par10-t1-harness.py --candidate-core D:/Atlas/.worktrees/zcode-par10-registry-runtime/core --sandbox D:/Atlas/.worktrees/zcode-par10-registry-runtime/.tmp/par10-t1/sandbox --tmp D:/Atlas/.worktrees/zcode-par10-registry-runtime/.tmp/par10-t1/integration-run-6`
- 退出码 **0**，`PAR10_T1_HARNESS PASS (35/35)`；日志 `evidence/par10-t1-harness.txt`。

| 场景 | 断言结果 |
|---|---|
| A 正常安装（registry=npmjs，fallback=mirror） | completed；1 次 npm pack；plan `[npmjs, mirror]`；无失败归因 |
| B 公共源失败→计划回退 | npm：npmjs ENOTFOUND → mirror 成功；pnpm 依赖：npmjs 失败 → mirror 成功；completed；`registryAttempts`/`dependencyAttempts` 均为 `[npmjs, mirror]` |
| C 私有/显式自定义源失败 | 仅问 private 一次；plan 单源、`requested-custom`、`requested-registry-not-configured`；failed；attribution=registry；mirror 从未调用 |
| D spec 自带 host（tarball URL） | 仅问首个 registry；plan `specKind=tarball`/`specHost=git.example.invalid`；attribution=**spec-host**；`fallbackRefused=true`；mirror 未调用 |
| E 凭据与路径脱敏 | npm 实际收到含 `build:par10-secret@` 的原始 URL（假脚本日志为证）；operation 快照无 `par10-secret`/`par10-token`/`alice`/完整工作区路径；attempt 出现 `<redacted>@`；plan 归一化 URL 无凭据 |
| F pnpm 自身 registry 未知 | 仅 1 次尝试（None）；`pnpm-own-unknown`；配置 mirror 未被调用 |
| G HTTP 安装入口 | `/api/plugins/install` 带 `fallbackRegistries` → 响应 `registryPlan.registries=[npmjs, mirror]`，安装 completed；`fallbackRegistries="not-a-list"` → 422 |

---

## 6. 单测、静态检查、既有回归

均在工作树 `core` 下执行，`--basetemp` 指向候选树 `.tmp/par10-t1/...`，`-p no:cacheprovider`。

| 命令 | 退出码 | 结果 |
|---|---|---|
| `python -m pytest tests/test_plugin_registry_plan.py tests/test_plugin_registry_install.py -q -p no:cacheprovider --basetemp=D:/Atlas/.worktrees/zcode-par10-registry-runtime/.tmp/par10-t1/final` | 0 | **60 passed**（44 plan + 16 engine），5 warnings，3.34s；日志 `evidence/par10-t1-pytest.txt` |
| `python -m pytest tests/test_plugins.py -q -p no:cacheprovider --basetemp=.../.tmp/par10-t1/existing` | 0 | **10 passed**，7.75s；日志 `evidence/par10-t1-pytest-plugins.txt` |
| `python -m ruff check atlas/plugins/registry_plan.py atlas/plugins/registry_install.py tests/test_plugin_registry_plan.py tests/test_plugin_registry_install.py` | 0 | All checks passed；日志 `evidence/par10-t1-ruff.txt` |
| `python -m py_compile` 同上 4 文件 | 0 | 无输出 |

补丁文件的 ruff 结果与在途 pristine 副本同为 10 条既有问题（I001/F401/PLR1704/TRY004/BLE001/S110 等），**无新增**；补丁与候选新文件 `py_compile` 通过。

### 6.1 在途安装操作测试对照（隔离 overlay，只读复制）

把候选 HEAD `atlas` 包叠加“在途 runtime/router 副本”，分别跑主树未跟踪的 23 项安装测试（未修改主树；测试文件复制到 `.tmp`）：

| overlay | 结果 | 失败特征 |
|---|---|---|
| 补丁后 | 20 passed / 6 failed（本次）；另一次 21 passed / 5 failed | 失败集合逐次漂移：`PermissionError`（Windows `.incoming`/temp rename 文件锁）、`real pnpm entry must be supplied`（本机无该 fixture）、patch-carry `upstream v1 vs v2` |
| 未打补丁 pristine | 21 passed / 5 failed | 同样包含 patch-carry 断言失败、`PermissionError`、real pnpm fixture 缺失；第五个失败项在两次运行间不同 |

日志：`evidence/par10-t1-regression.txt`（补丁后）、`evidence/par10-t1-regression-pristine.txt`（pristine）、`evidence/par10-t1-regression-detail.txt`（单个审批场景显示 `failureType=PermissionError` 且 `dependencyOutcome.ok=true`、`approvedBuildOutcome.ok=true`）。结论：未观察到补丁特有逻辑回归；失败来自 Windows 文件锁抖动与缺失真实 pnpm fixture，且 pristine 同样出现。安装审批/幂等/取消语义在通过的 20-21 项中保持。

---

## 7. 未覆盖与风险

- 补丁未应用到候选树或主树；候选树 HEAD 没有 npm/pnpm 链，无法在“本树代码”上直接接入。真实生产接线需等主树在途作者落盘后应用补丁（行号基于 sha256 `379cc28e...` / `1c553ca2...`；若在途文件继续变化需重做）。
- 未访问真实 npm/pnpm、私有 registry、账号或凭据；未验证 registry 认证失败（401/403）语义（按 `other` 不重试）。
- 未读取 pnpm 自身 registry 的 `resolved` URL：`registry=None` 始终按“未知 → 单源”处理，不隐式切到官方公共源。
- 未更新前端展示 `registryPlan`/失败归因；未走 Electron/桌面 E2E。
- 回退只在请求显式给出公开 `registry`（当前配置主源=官方 npm）且 `fallbackRegistries` 配置时启用；仅给 fallback 而不给 registry 时仍单源，这是有意的 DSH 安全语义。
- 回归对照使用 overlay 组合（候选 HEAD 其余模块 + 在途两文件 + 未跟踪 compatibility），不是主树完整 141 项在途状态；patch-carry 测试的失败在 pristine overlay 中也存在。

---

## 8. 可重跑命令

```bash
# 单测（候选树）
cd D:/Atlas/.worktrees/zcode-par10-registry-runtime/core
python -m pytest tests/test_plugin_registry_plan.py tests/test_plugin_registry_install.py -q -p no:cacheprovider \
  --basetemp=D:/Atlas/.worktrees/zcode-par10-registry-runtime/.tmp/par10-t1/final

# 既有插件测试
python -m pytest tests/test_plugins.py -q -p no:cacheprovider \
  --basetemp=D:/Atlas/.worktrees/zcode-par10-registry-runtime/.tmp/par10-t1/existing

# ruff
python -m ruff check atlas/plugins/registry_plan.py atlas/plugins/registry_install.py \
  tests/test_plugin_registry_plan.py tests/test_plugin_registry_install.py

# 接线补丁可应用性（只读，不写主树）
cd D:/Atlas
git apply --check --verbose D:/Atlas/tasks/dsh-parity/zcode-glm-20261118/evidence/par10-t1-wiring.patch

# 实际入口模拟（先准备候选树 .tmp/par10-t1/sandbox：候选 HEAD 在途两文件副本 + compatibility.py + 应用补丁）
cd D:/Atlas/.worktrees/zcode-par10-registry-runtime
python -I D:/Atlas/tasks/dsh-parity/zcode-glm-20261118/evidence/par10-t1-harness.py \
  --candidate-core D:/Atlas/.worktrees/zcode-par10-registry-runtime/core \
  --sandbox D:/Atlas/.worktrees/zcode-par10-registry-runtime/.tmp/par10-t1/sandbox \
  --tmp D:/Atlas/.worktrees/zcode-par10-registry-runtime/.tmp/par10-t1/integration-run-6
```

---

## 9. 结论

- 策略模块与测试已从 PAR-09 源树字节一致移入候选树；
- 新增的 plan 执行器补齐了 fallback 重试、失败归因、凭据安全与输出脱敏，并在假 npm/pnpm 的真实安装任务与 HTTP 入口上 **35/35** 验证通过；
- 候选树 HEAD 没有 npm/pnpm 安装链，真实链仍是主树他人未提交文件；按派发未硬改，交付可应用补丁（apply-check exit 0）与替代测试范围，状态 **链路待接**。

PAR10_RECEIPT T1 PARTIAL

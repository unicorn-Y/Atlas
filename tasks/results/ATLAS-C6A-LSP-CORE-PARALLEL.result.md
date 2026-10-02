# ATLAS-C6A-LSP-CORE-PARALLEL 结果

- 分支：`zcode/c6a-lsp-parallel`
- 执行：ZCode 第二施工线，6 个子代理并行（A 基础纯模块 / B 客户端 / C 工作区+注册表 / D 服务编排+门面 / E 假 LSP+协议客户端测试 / F 服务级+生命周期测试）
- 接口契约：`_tmp/c6a-lsp-contract.md`（施工前冻结，全程无破坏性变更；集成期零冲突）
- 日期：2026-10-02

## 一、选了 Hermes / OpenCode 哪些实现，为什么

**结论：以 Hermes `agent/lsp/**` 为移植基础（OpenCode 仅对照，未搬代码）。**

对比维度（先读两家最新上游实现：Hermes 本地 fork `D:\hermes-agent` @ `562ad75`；OpenCode 经 GitHub API 拉取 @ `1ddb0873aee50d209d1a8d7f91b89c5daf692d49`，存 `_tmp/ref/opencode-lsp/`）：

| 维度 | Hermes `agent/lsp/` | OpenCode `src/lsp/` | 取舍 |
| --- | --- | --- | --- |
| 语言/可移植性 | Python，可整文件移植 | TypeScript（vscode-jsonrpc/effect 栈），只能照逻辑重写 | Hermes |
| 诊断新鲜度 | 按文档版本标记 push/pull 结果，防"幽灵诊断"；TS 首推 seed 语义 | 同样有版本化 + debounce（其 client.ts 有 shouldSeedDiagnosticsOnFirstPush），两家同源思想 | Hermes（实现更完整） |
| before/after 差分 | 有：写前 snapshot_baseline + difflib 行位移（`range_shift.py`），只报本次新增 | 无跨编辑差分（`tool/lsp.ts` 是交互式查询工具面，无 delta） | Hermes（taskbook 验收 3/7 的硬需求） |
| Windows 进程管理 | `.cmd/.bat` 经 `cmd.exe /c` 包装、CREATE_NO_WINDOW、进程树 taskkill /T /F、优雅 shutdown→grace→kill 三段 | 有 Process 工具但树级清理与 .cmd 细节不如 Hermes 显式 | Hermes |
| 工作区门控/信任 | git worktree 门控 + 可信工作区白名单（服务可执行项目代码的才要求信任） | 有 instance 目录概念，无信任分级 | Hermes |
| 服务注册表 | 28 条整表（markers/root 排除/初始化选项/多根），有信任白名单 | 数十条但含 npm 自动安装路径 | Hermes（整表搬），OpenCode 表中额外 server 未来可按需增补 |
| 诊断格式化 | reporter（HTML 转义、字段长度钳制、severity 过滤） | diagnostic.ts（基本等价、无转义） | Hermes |
| 自动安装 | `install.py`（npm/go 自动装到 staging） | Npm 集成更深 | **两家都不搬**：taskbook 明确"不要自动下载安装"→ 新建 `availability.py` 纯探测 + 中文缺失提示 |

## 二、搬入/新增文件

全部为**新建**，零改动既有共享文件（`git diff --name-only` 为空；C4/C5/前端禁区一律未碰）：

| 文件 | 行数 | 说明 |
| --- | --- | --- |
| `core/atlas/lsp/protocol.py` | 139 | JSON-RPC 2.0 帧协议（Hermes 原样移植） |
| `core/atlas/lsp/range_shift.py` | 77 | difflib 行位移（原样移植） |
| `core/atlas/lsp/types.py` | 81 | Atlas 统一诊断类型 `Diagnostic(file,line,column,severity,code,message,source)` + `from_lsp` 转换 |
| `core/atlas/lsp/reporter.py` | 91 | `<diagnostics>` 格式化（转义/钳制/过滤），本地 elide |
| `core/atlas/lsp/_proc.py` | 85 | `windows_hide_flags` / `child_env` / `kill_process_tree`（taskkill /T /F） |
| `core/atlas/lsp/client.py` | 782 | 异步 LSP 客户端：版本化新鲜度、push debounce、ContentModified 退避、stderr 尾部、LRU 64 文档、多根文件夹增删 |
| `core/atlas/lsp/workspace.py` | 196 | git 工作区门控/信任/最近根；`operator_workspace_roots` 按 Atlas 简化（cwd + `ATLAS_WORKSPACE_ROOT` 锚点） |
| `core/atlas/lsp/servers.py` | 524 | **28 条注册表整表**（pyright/typescript/gopls/rust-analyzer/clangd/vue/…/powershell）+ 自定义 server 解析；全部安装分支删除 |
| `core/atlas/lsp/availability.py` | 72 | 纯探测（PATH/覆盖项，绝不安装）+ 12 个 server 的短中文缺失提示（含安装命令） |
| `core/atlas/lsp/manager.py` | 805 | LSPService：后台 asyncio 线程、按 (server,root) 复用客户端、broken 集合、delta 基线、idle reaper、release_workspace、缺失≠broken 的 5 分钟探测节流 |
| `core/atlas/lsp/eventlog.py` | 186 | 桶化去重结构化日志 |
| `core/atlas/lsp/__init__.py` | 166 | 门面：`get_service/shutdown_service/release_workspace/snapshot_baseline/diagnostics_for/missing_hint/edit_report` |
| `core/tests/fakes/fake_lsp_server.py` | 302 | 可执行假语言服务器（stdio/asyncio/帧协议，state 文件落 PID 供复用/退出断言，`--seed` 首推语义） |
| `core/tests/test_lsp_protocol.py` 等 6 个 | 1186 | 66 条测试，见下 |

共享热文件接线：**无**（本波按 taskbook 要求零接线；后续 C6 主线的接入面见第六节）。

## 三、Windows 进程生命周期

1. **启动**：`asyncio.create_subprocess_exec`；`.cmd/.bat` shim 先包 `cmd.exe /c`（CreateProcess 不能直接跑）；`start_new_session=True` 独立进程组 + `CREATE_NO_WINDOW`（无闪窗）；16MiB 流上限；stderr 常驻排流（防管道满塞死）+ 尾部 30 行留作失败报告。
2. **优雅停**：`shutdown` 请求 → `exit` 通知 → 等 `SHUTDOWN_GRACE=1s` 自退。
3. **强杀**：超时未退 → `kill_process_tree`：Windows 走 `taskkill /PID <pid> /T /F`（同步树杀，隔离到线程执行，最多 15s），杀不到再 `proc.kill()` 兜底；POSIX 走 `killpg`。
4. **清理**：reader/stderr 任务取消并 gather；`_cleanup_process` 用锁保证幂等；初始化中途失败也会执行（`asyncio.shield` 防 CancelledError 跳过清理→孤儿）。
5. **兜底**：atexit 钩子整树收摊；idle reaper 每 ≤60s 回收超时未用 server（默认 600s）；`release_workspace` 在 worktree 删除前主动停掉对应 server（多根只摘文件夹）。
6. **回归**：`test_lsp_lifecycle.py` 覆盖优雅退出、无视 shutdown 的强杀路径（≥2s 断言）、`_cleanup_process` 直杀、进程树孙进程全灭、门面幂等；套件跑完无残留进程。

## 四、diagnostics diff 语义

- **写前**：`snapshot_baseline(path)` 把当前诊断存为该文件基线（带 LRU 上限 256）。
- **写后**：`get_diagnostics_sync(delta=True, line_shift)`：
  1. 若给了 `pre/post` 文本，先 `build_line_shift`（difflib opcodes）把基线诊断**重映射进编辑后坐标**；落在被删行的基线条目丢弃——纯位移/整段删除的旧错误不误报为"新增"；
  2. 以内容键（severity+code+source+message+range）做差集，只留本次新增；
  3. **基线前滚**到当前状态（下一次编辑的 delta 以本次结果为基准）；修复后服务端推空 → 前滚基线为空 → 报告空（验收 8"修后清空"）。
- **无新鲜数据 ≠ 干净**：预算内没等到 verdict 返回 `[]` 并按"无数据"记录，绝不拿陈旧缓存充数（防幽灵诊断）；`fresh_only` 确保推送/拉取任一store 版本没追上文档版本就不计。
- **缺失≠故障**：二进制探测不到 → 不标 broken，记入 `_missing`（5 分钟探测节流），`missing_hint`/`describe_missing` 返回中文安装提示；装好即用。

## 五、测试结果

```
core/.venv (Python 3.14.7, Windows)
pytest tests/test_lsp_{protocol,range_shift,types_reporter,client,service,lifecycle}.py
  → 66 passed in ~11s（两种顺序各跑一遍均 66/66；无孤儿进程）
```

taskbook 最小验收逐条映射：

| 验收 | 结果 | 位置 |
| --- | --- | --- |
| 1 fake LSP 打开文件→类型错误 | ✅ | test_lsp_client.py（T999 断言到 range/message/severity/source） |
| 2 修文件→同一错误消失 | ✅ | test_lsp_client.py（fresh 空） |
| 3 before/after 只返回新增 | ✅ | test_lsp_service.py（delta/行位移/edit_report 三用例） |
| 4 同 workspace 两次复用同一 server | ✅ | test_lsp_service.py（state 文件 PID 不变 + 单客户端） |
| 5 workspace 关闭后 server 退出 | ✅ | test_lsp_lifecycle.py（release→PID 轮询至死→幂等） |
| 6 server 缺失→中文"未安装/如何安装" | ✅ | test_lsp_service.py（提示非空且含"安装"，含具体安装命令） |
| 7 Windows lifecycle 回归（terminate/kill/cleanup） | ✅ | test_lsp_lifecycle.py（5 用例） |
| 8 Python 与 TS/JS 代表文件 | ✅ | 注册表映射断言（.py→pyright/python；.ts/.tsx→typescript/typescriptreact；.mjs→javascript）+ 客户端集成测试用 .py |

真实 server smoke：本机 PATH 无 pyright / typescript-language-server（node/npm 有）；按 taskbook"没有就不装、不阻塞"跳过。缺失路径的真实行为已由中文提示测试覆盖。

**门面手工冒烟**（fake server 端到端）：干净基线→写入错误→`diagnostics_for(delta=True)` 恰 1 条 line=2 error T999；`edit_report` 输出 `本次编辑引入的诊断: ERROR [2:5] … [T999]`；修复后报告为空。

## 六、是否触碰共享热文件

**零触碰。** 未改 `server.py`、`plugins/**`、`skills/**`、`models/**`、`runtime/hooks.py`、前端任何文件、C4/C5 任何文件；全部产出在新目录 `core/atlas/lsp/`、`core/tests/fakes/fake_lsp_server.py` 与 `core/tests/test_lsp_*.py`。唯一仓库内新依赖是既有的 stdlib/pytest 设施，`core/pyproject.toml` 无需改动。

## 七、后续 main C6 只需要补的接线（每处 ≤10 行）

1. **写文件/patch 工具结果追加诊断**（对应 Hermes `file_operations_lint._maybe_lsp_diagnostics`）：
   - 写前：`from atlas.lsp import snapshot_baseline; snapshot_baseline(path)`
   - 写后：`from atlas.lsp import edit_report; block = edit_report(path, pre_content, post_content)`；`block` 非空则拼到工具结果尾部。
2. **改动面板/时间线"发现 N 个新问题"**：`from atlas.lsp import diagnostics_for; n = len(diagnostics_for(path, delta=True))` 发一条 runtime 事件即可（前端事件表登记 + 渲染属 C6 主体）。
3. **设置页缺失提示**：`from atlas.lsp import missing_hint` 按语言展示（文案已带安装命令）。
4. **会话/worktree 清理**：删除工作区前调 `release_workspace(root)`（幂等）。
5. **配置暴露**（可选）：`config/atlas.toml` 的 `[lsp]` 表：`enabled/wait_mode/wait_timeout/idle_timeout/trusted_workspaces/exclude_roots/servers.*`，`create_from_config` 已按点路径读取，无需改 `atlas.config`。
6. **测试环境开关**（建议）：CI 无 server 时任务书行为已安全（缺失→提示，不 spawn），无需开关。

## 八、已知边界与后续建议

- 本波未做 `/init`、`/review`、UI、长会话性能（taskbook"不做"清单全部未越界）。
- `test_computer_use.py` 类全量测试未跑（taskbook 禁止跑全量）；如需在 C6 合入前回归，`core` 全量 pytest 由主线自跑。
- vue/powershell 两个 bespoke builder 按"表不缩水"保留，但安装 staging（Hermes `lsp/bin`）不存在，两者只能用 PATH/手动安装——已在 availability 提示中说明。
- OpenCode `src/tool/lsp.ts` 的交互式查询工具面（goToDefinition/findReferences 等）留待后续波次按需引入，本波无消费者。

---

## R1 附注（ATLAS-C6A-R1-BASEDPYRIGHT，2026-10-02）

最小修复：Python LSP 兼容 basedpyright，不重做 C6A、不动共享文件。

- **改动 1 — `core/atlas/lsp/servers.py::_spawn_pyright`**：探测顺序扩为 `pyright-langserver → pyright → basedpyright-langserver → basedpyright`；CLI→langserver 兄弟解析泛化为 `pyright`/`basedpyright` 两个词干（同一后缀规则，Windows 下裸兄弟是 npm 不可运行的 POSIX shim）。server_id 保持 `"pyright"`——信任白名单、binary_overrides、缺失提示仍键在同一适配器上，无第二个 manager/运行时。
- **改动 2 — `core/atlas/lsp/availability.py`**：`pyright` 缺失提示改为「未找到 Python 语言服务：安装 pyright 或 basedpyright 均可（如 npm install -g pyright 或 pip install basedpyright），重启 Atlas 即可自动启用。」
- **新增测试 — `core/tests/test_lsp_pyright_fallback.py`**（7 条，monkeypatch `shutil.which`，不起真进程）：basedpyright-langserver 直接可用；basedpyright CLI 无兄弟时本身即为合法 spec；有兄弟时解析到兄弟；两族并存时 pyright 优先（langserver 与 CLI 两形态各一条）；全部缺失→无 spec；提示含"安装…均可"。
- **测试结果**：`pytest tests/test_lsp_service.py tests/test_lsp_pyright_fallback.py` → 13 passed（6 条既有服务级用例无回归 + 7 条新增）。按任务书只跑直接受影响文件，未重跑 66 条全套。
- 本轮改动文件：`servers.py`、`availability.py`、新增 `test_lsp_pyright_fallback.py`、本 result、`ZCODE-CURRENT`。其余一律未动。

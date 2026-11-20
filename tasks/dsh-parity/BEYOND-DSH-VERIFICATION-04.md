# X5/X7 安装事务与审批：独立验证截点

日期：2026-11-16。生产实施：用户指定 Codex Desktop GPT-6 Luna 高；主控只读审查、独立验证及证据记录。不代表全目标验收。

## 首批安装任务测试

工作目录 D:/Atlas/core，既有 hermes-agent venv Python；唯一 --basetemp，60秒外层期限。

```text
python -m pytest tests/test_plugin_install_operations.py -q -p no:cacheprovider --basetemp=<唯一 atlas-install-first-supervisor>
4 passed, 5 warnings in 2.45s
INDEPENDENT_EXIT_CODE=0
```

子进程自然退出。5 warnings 为已有 FastAPI on_event / Pydantic Config 弃用。

这一截点覆盖未知 requestId、排队后取消及 too_late、替身包管理器失败后的 staging 清理与源文件不变、按包审批持久化/时间过期、显式 registry 参数传递。失败和成功包管理器均为 monkeypatch；不证明真实 pnpm 下载/安装、私有源网络边界、脚本未批准不执行/批准后执行、实际进程树取消、同 profile 并发、已有 target 的 commit/refresh 失败回滚或真实 API/UI。

实施仍在进行，不能将施工稿静态观察当最终缺陷，也不能将这4项当X5/X7完成。

## 传递依赖审批截点

仅新增场景独立复跑，唯一 --basetemp，45秒外层期限：

```text
python -m pytest tests/test_plugin_install_operations.py::test_install_waits_only_for_pnpm_reported_transitive_build_and_resumes_on_approval -q -p no:cacheprovider --basetemp=<唯一 atlas-install-transitive-supervisor>
1 passed, 5 warnings in 2.35s
INDEPENDENT_EXIT_CODE=0
```

进程自然退出。替身包管理器报告 @transitive/native-build@2.0.0，生产状态机只等待这一构建包的审批，不要求direct-dep授权；批准后发起rebuild并完成。此测试仍不证明真实pnpm ignored-builds输出、真实脚本执行或传递依赖的实际rebuild语义。

## HTTP 接线截点

```text
python -m pytest tests/test_plugin_install_operations.py::test_install_api_exposes_request_wait_unknown_cancel_and_script_approval -q -p no:cacheprovider --basetemp=<唯一 atlas-install-api-supervisor>
1 passed, 5 warnings in 2.39s
INDEPENDENT_EXIT_CODE=0
```

进程自然退出。FastAPI TestClient 使用AppServices注入真实PluginRuntime；验证创建返回requestId/queued、等待完成、未知取消为unknown、按包审批落盘。扩展刷新为替身，fixture无依赖，因此没有真实pnpm、完整lifespan或浏览器证据。

## 安装关停 drain 截点

```text
python -m pytest tests/test_plugin_install_operations.py::test_shutdown_drain_cancels_install_waiting_for_build_approval -q -p no:cacheprovider --basetemp=<唯一 atlas-install-drain-supervisor>
1 passed, 5 warnings in 2.38s
INDEPENDENT_EXIT_CODE=0
```

进程自然退出。使用替身包管理器到达awaiting_approval，然后调用真实close_install_operations，确认取消及staging清理。这不是实际运行中pnpm进程树取消或完整后端自然退出证据。

## 目录交换失败与 stale approval 修复截点

```text
python -m pytest tests/test_plugin_install_operations.py::test_failed_second_install_rename_restores_previous_target_bytes tests/test_plugin_install_operations.py::test_script_approval_api_rejects_stale_request_and_resumes_current_request -q -p no:cacheprovider --basetemp=<唯一 atlas-install-swapapproval-supervisor>
2 passed, 5 warnings in 4.59s
INDEPENDENT_EXIT_CODE=0
```

进程自然退出。主控静态指出target移到backup之后prepared.replace失败会丢旧目录；实施端补恢复逻辑并新增rename故障注入，旧target字节保留。审批API补当前requestId与pending包校验，失效请求不留下授权，当前任务可恢复。仍非真实pnpm/完整后端/浏览器验收。前述首批测试是历史截点，审批契约已随本次更新，不能把旧任意包授权路径视作最终设计。

## 真实 pnpm 首次独立尝试：失败

```text
ATLAS_PNPM_ENTRY=<已确认本机pnpm.mjs>
python -m pytest tests/test_plugin_install_operations.py::test_real_pnpm_blocks_transitive_script_until_scoped_approval -q -p no:cacheprovider --basetemp=<唯一 atlas-install-realpnpm-supervisor>
1 failed, 5 warnings in 93.23s
INDEPENDENT_EXIT_CODE=1
```

90秒观察截止时status=running，pnpm_output=[]，未到awaiting_approval。失败位于首次审批状态断言，没有任何审批后marker成功证据。pytest自然退出1；外层Python wrapper未传播退出码而返回0，真实测试结论以上述pytest和INDEPENDENT_EXIT_CODE=1为准，不能按工具外层exit0记通过。真实卡点待定位，不能靠延长期限/削弱断言关闭。

## 受影响生命周期回归

新增安装清理动作后独立跑四项：test_lifespan_resource_shutdown_uses_reverse_dependency_order、test_shutdown_actions_run_unknown_names_with_an_empty_registry、test_lifespan_shutdown_orders_gateway_before_its_channel_manager、test_lifespan_shutdown_stops_blocked_mcp_child_and_startup_tasks。

```text
4 passed, 5 warnings in 15.09s
INDEPENDENT_EXIT_CODE=0
```

唯一basetemp、60秒外层期限，进程自然退出。覆盖既有依赖清理/unknown fallback/channel顺序及真实fixture MCP阻塞子进程的lifespan测试；不证明本次完整live后端自然退出。

## 安装面板组件截点

```text
node node_modules/vitest/vitest.mjs run --root D:/Atlas/frontend src/renderer/pages/ConsolePage.compatibility.test.tsx -t "polls a request id"
Test Files 1 passed; Tests 1 passed | 1 skipped; Duration 274ms
```

只执行新增安装轮询/逐包审批/完成提示测试；另一个X6测试按名称过滤跳过，不能计作本次执行。React renderer + stub fetch，非浏览器/真实HTTP/真实pnpm。该截点fixture的状态响应requestId硬编码install-123，与创建时动态ID不同；当前测试未覆盖身份一致性。响应丢失、重挂载、取消、跨后端恢复尚未由此测试证明。

## 临时 registry + 真实 pnpm 第二截点：失败

修订fixture使用loopback临时registry/真实tarball、真实PluginRuntime和TestClient API，30秒用例期限、60秒外层期限：

```text
1 failed, 5 warnings in 3.96s
INDEPENDENT_EXIT_CODE=1
```

首次install真实返回1并报告：`ERR_PNPM_IGNORED_BUILDS` / `Ignored build scripts: @fixture/native-build@1.0.0`；两层依赖已进入stage。当前runtime非零立即failed，未进入awaiting_approval；这是实际pnpm语义缺口。未证明批准后执行，未关闭X5/X7。进程自然退出1，外层正确传播1。

## unknown 新组件回归：夹具失败截点

```text
vitest ... ConsolePage.compatibility.test.tsx -t "does not re-POST"
1 failed | 2 skipped; Duration 337ms; exit1
ReferenceError: localStorage is not defined (:71)
```

未到生产行为断言，不作为unknown重提路径的执行复现，已反馈Luna补stub storage及timer清理。同时静态反馈taskkill测试原pytest.raises包外层wait_for会让旧无界实现同样“通过”，需区分内部deadline与外层测试保护期限；尚未将该测试计为验证。

## 四根因修复后定向复验截点

```text
pytest test_process_tree_termination_shares_the_install_deadline test_legacy_uninstall_holds_mutation_claim_against_new_install
2 passed, 5 warnings in 2.58s
INDEPENDENT_EXIT_CODE=0

vitest ConsolePage.compatibility.test.tsx -t "does not re-POST"
1 passed | 2 skipped; Duration 281ms; exit0
```

Python唯一basetemp/45秒外层期限、自然退出；taskkill测试已改为被测task在外层保护期限内自行done，不能靠外层wait_for伪绿。反向旧卸载先占用时新安装拒绝。组件补显式存储stub，unknown不自动POST；其它两项按名称跳过不计执行。仍不覆盖同runtime首次丢回执恢复或真实进程树消失证明。

## 真实审批链第三次独立截点：批准后失败

实施端经CDP报告真实链已绿后，主控独立运行同名真实用例：

```text
1 failed, 5 warnings in 3.91s
INDEPENDENT_EXIT_CODE=1
```

已通过awaiting_approval、精确批准HTTP200及审批前marker不存在的断言，但最终status=failed（用例:434，预期completed）。pytest自然退出1；摘要未展开具体approved输出/异常，不推断根因。该结果与实施端先前成功报告不同，已反馈定位，未采信完整通过结论。

## 带诊断第四次独立截点：Windows lifecycle spawn 失败

```text
pytest test_real_pnpm_blocks_transitive_script_until_scoped_approval test_install_request_id_survives_runtime_restart_without_replaying_install -q -s --tb=short ...
1 failed, 1 passed, 5 warnings in 4.61s
INDEPENDENT_EXIT_CODE=1
```

新诊断确认：首轮install退出1并正确进入精确审批；第二次install退出1，`ERR_PNPM_EXECUTOR_SPAWN_LIFECYCLE`，获批@fixture/native-build的`postinstall: node write-marker.js`无法创建进程，`目录名称无效。(os error 267)`。operation error=approved_build_failed / failureType=RuntimeError，postinstall marker=false/pnpmfile marker=false。不是认证或首次审批问题。深层Windows cwd/路径长度是待核查候选，未证明；不能仅缩短测试目录冒充生产路径修复。

重启requestId tombstone用例通过；完整真实审批链仍失败。进程自然退出1。

## Windows 物理工作区修复后的真实审批链：独立通过

```text
pytest test_real_pnpm_blocks_transitive_script_until_scoped_approval -q -s --tb=short ...
1 passed, 5 warnings in 3.10s
INDEPENDENT_EXIT_CODE=0
```

真实pnpm v12.4.1、loopback registry + 实际tarball、TestClient API、真实runtime；60秒外层期限、唯一长basetemp，进程自然退出。生产stage改为短临时物理路径；两次pnpm cwd长度均47，最终安装目标仍为深目录，测试确认虚拟store深层路径超过260字符。首轮exit1/ERR_PNPM_IGNORED_BUILDS，精确批准后第二轮exit0并实际postinstall Done；postinstall marker=True/pnpmfile marker=False，安装提交completed。

此结果关闭前述fixture下Windows error267，不抹去历史失败。不是全部pnpm版本、完整后端lifespan或浏览器证明。host workspace其他自批字段与首次POST轮询竞争还有限定审查残留，npm spec/Git/marketplace统一任务入口尚未完成，不能关闭X5/X7总能力。

## 危险自批与首次创建竞争：独立通过

```text
pytest test_real_pnpm_blocks_transitive_script_until_scoped_approval ...
1 passed, 5 warnings in 3.69s
INDEPENDENT_EXIT_CODE=0

vitest ... -t "keeps the request id pollable"
1 passed | 3 skipped; Duration 276ms; exit0
```

真实pnpm fixture同时在workspace和package配置dangerouslyAllowAllBuilds/allowBuilds，生产执行前强制false/空白名单；批准后仅精确获批包进入allowBuilds。marker、深目标提交及pnpmfile不执行断言均通过。组件deferred POST/先unknown场景保持poll/cancel句柄；其它三项名称过滤跳过，不计执行。两进程自然退出。至此只关闭上述两个限定bug，不把所有安装来源/完整live计通过。

## 统一来源改造的中间态交叉回归

主控在来源改造已开始写入时运行install_operations + compatibility两个文件，退出1；多项安装入口报`AttributeError: PluginRuntime has no attribute _infer_install_source_type`。这是新调用已写入、helper未完成的施工截点，不当最终回归或新增独立根因。输出被工具截断，未取得完整汇总，不推算通过/失败总数。停止复跑，待实施端稳定接线后再验证。

## 统一来源入口稳定截点

```text
pytest tests/test_plugin_install_operations.py -k "source_classifier or git_fixture or marketplace_api or scoped_npm_tarball" ...
4 passed, 13 deselected, 5 warnings in 4.76s
INDEPENDENT_EXIT_CODE=0
```

唯一basetemp/60秒外层期限，进程自然退出。真实scoped npm经loopback registry/npm pack、临时Git真实clone及checkout持久化、市场TestClient返回可wait request、来源classifier通过；13项名称过滤未执行，不计通过。新来源fixture无build依赖，不能据此认定各来源审批、取消、升级patch保留、失败回滚均已验证。后续限定审查发现三项需修见REVIEW-02。

三项身份/patch/首次rollback新回归首次独立尝试未收集：runtime.py:980的_copy_replace语句IndentationError unexpected indent，pytest1 collection error/exit4，0测试执行。已反馈实施端修语法/AST，施工截点不算通过或最终回归结论，待稳定后复验。

## 来源身份、patch、首次回滚与取消：独立通过

```text
pytest ... -k "git_manifest_identity or upgrade_preserves_old_patch or first_install_refresh_failure or remote_source_fetch_cancellation"
6 passed, 17 deselected, 5 warnings in 3.44s
INDEPENDENT_EXIT_CODE=0
```

唯一basetemp/60秒外层期限，自然退出。三项review修复回归通过；remote_source_fetch_cancellation按git/npm/marketplace参数化3项，下载方法为受控替身，证明共同状态机取消后无提交且清理workspace，不证明真实进程树取消。17项未执行不计通过。

## scoped npm 来源到真实依赖审批链

同名真实marker用例已改从loopback registry的scoped npm包发起，经npm pack/解包进入共同事务，再做真实pnpm依赖阻断、精确审批及第二次install。主控独立：

```text
1 passed, 5 warnings in 4.63s
INDEPENDENT_EXIT_CODE=0
```

唯一basetemp/60秒外层期限，自然退出。保留审批前后marker、host构建策略及深目标提交断言；不把替身取消当真实子进程树取消，也不将本例扩为全来源组合验收。

## 稳定联合回归截点

```text
pytest tests/test_plugin_install_operations.py tests/test_plugin_compatibility.py -q --tb=short -p no:cacheprovider --basetemp=<唯一 atlas-plugins-stable-supervisor>
45 passed, 5 warnings in 14.33s
INDEPENDENT_EXIT_CODE=0

vitest ConsolePage.compatibility.test.tsx
Test Files 1 passed; Tests 6 passed; Duration 311ms; exit0
```

后端唯一basetemp/90秒外层期限，真实pnpm入口显式设置；两进程自然退出。包含当前完整安装/兼容性两文件和插件组件文件，不把历史逐次测试数量累加。真实下载子进程取消、完整后端/桌面验收及相关introspection仍待验证，未关闭DSH总目标。

## 真实受管进程取消：断言缺口，暂不采信 child 清除结论

```text
pytest tests/test_plugin_install_operations.py::test_git_source_cancel_terminates_real_managed_process_tree ...
1 passed, 5 warnings in 4.26s
INDEPENDENT_EXIT_CODE=0
```

唯一basetemp/45秒外层期限，进程自然退出。source-fetch 方法为确定性 fixture，内部执行真实 Python 父子进程并调用生产 managed command/cancel。静态复核发现 child 存活检查使用 `os.kill(child_pid, 0)`：Windows 下这可能终止目标，并非 POSIX 只读存在性检查，故此 PASS 不能证明取消实现已经清除 child。另仅等 process 登记即取消，未先确认 child 创建/就绪，存在时序不稳定。已反馈 Luna 改为 child ready 握手、只读 Windows 进程句柄查询、持有同一句柄确认退出；失败兜底清理不能计入断言成功。当前只采信请求终态/受管 parent 退出与 tracking 清理的有限证据。

安装面板最新 renderer 类型检查：第一次误用不存在的 `frontend/tsconfig.json`，TS5058/exit1，未执行类型检查；定位真实配置后 `node node_modules/typescript/bin/tsc --noEmit -p frontend/tsconfig.renderer.json` exit0。不是浏览器或完整桌面证明。

## 只读 Windows 句柄握手后的真实进程取消：独立通过

```text
pytest tests/test_plugin_install_operations.py::test_git_source_cancel_terminates_real_managed_process_tree ...
1 passed, 5 warnings in 4.82s
INDEPENDENT_EXIT_CODE=0
```

唯一basetemp/45秒外层期限，自然退出。fixture 的真实 Python child 写 ready marker；测试通过 OpenProcess 取得 query/synchronize 句柄，取消前 GetExitCodeProcess=STILL_ACTIVE 且 WaitForSingleObject=WAIT_TIMEOUT。调用生产 request cancel 后，parent returncode 已设置、request terminal=cancelled、tracking 无残留；同一句柄变 signaled，child exitcode 非 STILL_ACTIVE。检查不再调用 os.kill(pid,0)，故可采信当前 Windows 环境下真实受管父子进程取消结果。source-fetch 替换为确定性 helper，不冒充真实 Git 网络取消、全平台进程回收或完整后端/桌面验收。

## Git/市场审批路径与目录交换 AST

```text
pytest tests/test_plugin_install_operations.py::test_git_and_marketplace_sources_share_dependency_approval_request_lifecycle ...
2 passed, 5 warnings in 5.93s
INDEPENDENT_EXIT_CODE=0
```

唯一basetemp/45秒外层期限，自然退出。临时 Git fixture 真实 clone 与市场来源解析，共享审批状态机；pnpm 为受控替身，首轮精确 blocked package、批准后第二轮完成，不能扩大为两个来源都跑过真实构建脚本。真实 npm/pnpm marker 证据仍以上述 scoped npm 用例为准。

独立 AST 检查：runtime.py:986 `await asyncio.to_thread(self._copy_replace, stage, prepared, previous=target)` 的父链为 `Await → Expr → Try → AsyncFunctionDef:_run_install_operation_locked → ClassDef → Module`，不在额外 If 分支内。首次核对脚本错误地把 `_copy_replace` 当直接被调函数（实际为 to_thread 的首参数），得到[]/AssertionError；改按真实调用结构定位后确认唯一匹配。脚本错误不记作生产错误。

## 既有插件安装、刷新与 patch 契约

```text
pytest tests/test_plugins.py tests/test_plugin_patch_layer.py tests/test_plugin_patches_http.py tests/test_plugin_reload_idempotent.py tests/test_plugin_validation.py ...
58 passed, 5 warnings in 15.67s
INDEPENDENT_EXIT_CODE=0
```

唯一basetemp/55秒外层期限，自然退出。覆盖既有插件/patch HTTP/重复reload/validation 契约；不与前述45+6等截点累加宣称总覆盖，不扩大为完整lifespan或桌面验收。

已核对 PROGRESS:158 的自省记录：显式构造临时 AppServices(plugin_runtime=PluginRuntime(...))，detail.bound=True；工具注册表无插件 tool。本次没有新增 model-callable tool，空列表不能证明生产接线，完整运行中 lifespan 的 services.unbound/tools.hidden/handlers.shadowed 仍待实测。此限定记录可保留，不作生产自省通过。

## 真实隔离后端 HTTP 安装与文件提交

证据：`artifacts/plugin-live-20261116-234b6abd/supervisor.py` / `receipt.json`。沿用 IsolatedAtlasBackend 完整生产 lifespan、私有数据/DB/state/hook 覆盖和动态空闲端口，不碰8765，无模型/外网/补充API状态查询。可信测试自建本地插件，无npm依赖；POST真实 `/api/plugins/install`，GET同ID wait至终态，on_complete 使用生产 `_reload_extensions`。

第一次端口38975：POST200、completed、正常exit0，但主控按manifest名推导安装目录，未找到文件导致脚本AssertionError/exit1。生产本地来源保留source目录名（runtime.py:896），故这是验收脚本路径假设错误，不作产品文件丢失结论。临时数据随close清理，未宣称第一次文件校验成功。

修订按operation.result.path读取，并额外确认name与路径均合法；第二次新隔离端口13704：

```text
post_http=200; request_id_matches=true
terminal_status=completed; phase=complete; error=null
installed_in_private_root=true
hooks_effective=true; on_complete_is_production_reload=true
graceful_exit=true; forced_termination=false; exit_code=0
startup=complete; shutdown=complete; errors=0
supervisor exit0
```

此结果补足本地无依赖fixture的真实HTTP/完整lifespan/reload/文件提交/自然关停证据；不扩大为浏览器/桌面、真实依赖脚本审批、npm/Git/市场全来源live验收或运行中自省通过。

## 完整后端真实 npm/pnpm 精确审批链

证据：`artifacts/plugin-live-approval-20261116-7c7bad7d/supervisor.py` / `receipt.json`。完整生产lifespan/真实HTTP/production reload；新临时registry只服务可信fixture包，真实npm pack及pnpm执行，无模型/外网/补充API状态读取。fixture在package/workspace自带dangerouslyAllowAllBuilds/allowBuilds及pnpmfile marker，宿主策略须阻断自批。

```text
post_http=200
before_status=awaiting_approval
approval_required=[@fixture/live-native]
marker_before=false; hook_marker_before=false
approval_http=200
terminal_status=completed; error=null; failure_type=null
marker_after=true; hook_marker_after=false
executed_build_packages=[@fixture/live-native]
production_reload=true; installed_in_private_root=true
graceful_exit=true; forced_termination=false; exit_code=0
startup=complete; shutdown=complete; errors=0
supervisor exit0
```

registry请求仅观察到本地fixture路径：/@fixture/live-plugin、/@fixture/live-native及其两tarball。批准前确无postinstall/pnpmfile文件，批准后postinstall内容executed，pnpmfile仍不存在，target在临时数据根且plugin.json存在。本次已补真实后端依赖审批/提交接线证据，不再仅为TestClient；仍不证明桌面UI、远程Git/市场所有来源组合、MCP调用或真模型对测。

## Git/市场真实 HTTP：市场通过、通用 Git 失败

独立验证证据 `artifacts/x30-independent-git-http-20261116-55c904b8ab8b/verify.py` / `receipt.json`，完整生产lifespan/private data与HOME/临时Git fixture，无依赖/外网/真实认证；动态端口34185，不碰8765。仅创建/等待自己的安装任务及注册市场，没有补充API状态读取。

通用 `/api/plugins/install` sourceType=git：POST200、同requestId wait200，queued→failed，failureType=PermissionError；无目标marker、无reload report，未通过。具体失败阶段待诊断，不凭市场成功推定原因。

市场HTTP注册/安装：均200，同requestId queued→completed，result.path在backend.data_dir，marker内容一致、manifest落盘、production reload loaded包含该fixture且无错误。关闭graceful=true/forced=false/code0，私有数据根已清理；双路径8.703秒。整体脚本按通用Git失败记失败，不以市场成功覆盖。

该验证脚本另设监督进程最终os._exit兜底；本次未触发（watchdog_forced=false），不把兜底当生产关停方案或成功依据。已安排一次限定诊断定位PermissionError，生产修复仍由原桌面Luna承担。

后续仅一次新隔离Git诊断（同证据目录diagnose_git.py及git-diagnostic-events-ca4a72ea.jsonl）：12.218秒，端口2259，queued→completed，marker/production reload通过，checkout含.git复制、.sources提交、目标交换与stage/source清理均返回成功；未复现PermissionError，没有失败调用/errno/winerror根因证据。诊断wrapper/tracing可能影响时序，不将成功归因修复。关闭graceful=true/forced=false/code0，监督强杀/os._exit均未触发。上轮失败receipt保存在receipt-prior-f8422f90.json；仍记间歇失败未定位，不反复盲跑。

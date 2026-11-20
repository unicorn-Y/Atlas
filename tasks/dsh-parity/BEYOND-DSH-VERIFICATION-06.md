# X30 SSH 共享执行环境：独立验证截点

2026-11-16。生产实施：用户指定原 Codex Desktop GPT-6 Luna 高。主控只读审查、独立测试及证据记录。各截点不累加，也不代表全 X30 或 DSH 目标完成。

## 改造前既有 SSH 基线

```text
pytest tests/test_atlas_ssh_routing.py tests/test_ssh_execution_world.py -q --tb=short -p no:cacheprovider --basetemp=<唯一 atlas-ssh-baseline-supervisor>
6 passed, 5 warnings in 14.65s
INDEPENDENT_EXIT_CODE=0
```

唯一basetemp/55秒外层期限，自然退出。原有 loopback harness 覆写 manager._connect 且 known_hosts=None，证明已有工具SSH通道，不证明生产 alias/host-key/连接池或统一 process/LSP/PTY。

## 首批 authority 与 URI 边界：合法 alias 解析失败

```text
pytest tests/test_ssh_execution_world.py::test_real_connect_uses_configured_authority_and_known_hosts tests/test_ssh_execution_world.py::test_ssh_workspace_identity_rejects_uri_credentials_and_overrides ...
1 failed, 4 passed, 5 warnings in 8.45s
INDEPENDENT_EXIT_CODE=1
```

唯一basetemp/45秒外层期限，自然退出。四项 URI credentials/port/query/fragment 拒绝通过；合法配置解析在测试:139失败：first_authority.hostname 实际 loopback-atlas，预期127.0.0.1。尚未到真实 _connect/SSH命令断言，不能计为真实连接通过。已反馈 Luna 修实际解析与连接options同源，独立只读review另行核对。此为施工截点，不推定最终根因。

## 双阶段/冻结修订中的独立失败

```text
pytest tests/test_ssh_execution_world.py::test_real_connect_uses_configured_authority_and_known_hosts ...
1 failed, 5 warnings in 8.58s
INDEPENDENT_EXIT_CODE=1
```

唯一basetemp/45秒外层期限，自然退出。hostname127.0.0.1断言通过，但测试:147 authority.port=22，预期loopback监听35464；未到真实连接成功断言。当前施工稿普通/final/freeze参数保值仍未稳定，已反馈Luna，不将先前设计探针当生产通过。后续实施端定位本例的`Match final host <alias>`夹具语义也有误：host在Hostname重写后匹配127.0.0.1，原alias应使用originalhost。改为匹配实际hostname后待复验；该次失败本身不能单独证明生产冻结丢端口。独立review另以6组纯内存配置确认：initial reload=True/False结果相同；host alias final/freeze=22，originalhost alias或host127.0.0.1均正确保留final指定端口。

## 身份首批稳定联合回归

```text
pytest tests/test_ssh_execution_world.py tests/test_atlas_ssh_routing.py ...
11 passed, 5 warnings in 19.50s
INDEPENDENT_EXIT_CODE=0
```

唯一basetemp/55秒外层期限，自然退出。合法alias仅在Include文件中，HostName127.0.0.1，Match final匹配有效主机后指定动态监听端口；真实manager._connect/key/known_hosts连接及命令回包成功。known_hosts内容变化、Include IdentitiesOnly变化、identity路径轮换分别生成新authority且实际_connect返回不同连接，未知alias拒绝；既有SFTP/edit/exec/routing用例也通过。

边界：trust内容变化fixture追加注释，证明版本变化/重连，不证明撤销host key时拒绝；没有穷尽GlobalKnownHostsFile、配置prepare→connect间文件替换、DNS canonicalization或Match exec；当前显式拒绝CanonicalizeHostname，不算该功能完成。此为身份首批，受管process/LSP/PTY/sandbox/child尚未接线，不关闭X30。

## 同路径 host-key 信任替换：真实拒绝

独立脚本 `artifacts/ssh-trust-20261116-1a9cb663/probe.py` / `receipt.json`，临时data/home与生成key、loopback真实SSH服务，20秒内层/30秒外层期限。首次manager._connect成功；同一路径known_hosts改为另一生成host key后，再_connect报HostKeyNotVerifiable，未返回旧池项。脚本自然exit0，manager/listener已await关闭；无模型/外网/实际SSH配置或认证读取。

该结果补足上述注释变化测试之外的真实错误key拒绝边界；不证明prepare→connect间材料替换、GlobalKnownHostsFile或全部信任配置。

## 单独改变身份/全局信任策略的离线 probe

`artifacts/ssh-trust-20261116-1a9cb663/policy_probe.py` / `policy-receipt.json`，仅可信临时配置与生成key，无连接/网络/实际用户配置。固定IdentityFile和known_hosts字节，只改变Include的IdentitiesOnly yes→no，authority id变化；恢复后id与原基线相同。再只改变GlobalKnownHostsFile路径，id变化。15秒内层/25秒外层，脚本自然exit0。

这一限定probe消除现有联合用例同时改两个变量的归因歧义，证明实际resolve_authority身份版本对两个单项策略变化敏感；没有调用_connect，不能单独作为真实缓存重连或global host-key拒绝的运行证据。

## 受管进程改造前 ExecManager 基线

```text
pytest tests/test_kernel_exec_jobs.py ...
11 passed, 5 warnings in 3.02s
INDEPENDENT_EXIT_CODE=0
```

唯一basetemp/50秒外层期限，自然退出。既有owner job/list/output/kill等契约基线，不是新SSH managed process验证。

后续LSP接线前基线：`pytest tests/test_lsp_client.py tests/test_lsp_lifecycle.py tests/test_c6_lsp_wiring.py ...`，`8 passed, 20 deselected, 5 warnings in 7.26s`，exit0，唯一basetemp/50秒外层期限，自然退出。20项被默认unit筛选未执行，不计通过；不是SSH LSP验收。

## 首个 managed process 用例：45秒超时

`test_managed_ssh_process_streams_stdin_checks_owner_and_cancels` 主控独立单项唯一basetemp，45秒外层subprocess期限；TimeoutExpired/外层exit1，无pytest最终结果，不能计通过。subprocess.run已终止并wait直接子进程；后续按唯一basetemp搜索未发现存活pytest根。没有事前保存全部后代PID/创建时间，因此不能由此声称所有fixture后代清零。第一次清理探针因Windows反斜线unicodeescape语法错误未执行，修正后matched_test_roots=0。

已反馈Luna按阶段/task栈定位，不延长期限或反复盲跑；另三项owner/cancel/lease/unknown施工review见REVIEW-04。

## 三项进程修复定向复验与真实接口失败

新有界监督脚本`artifacts/ssh-process-check-20261116-c8a073c2/run_check.py`，记录并轮询自有PID+创建时间/后代，40秒测试期限，超时或测试后残留仅清理已确认自有进程。

取消迟到handle两参数、活动lease保留、ExecManager unknown终态三条回归：`4 passed, 5 warnings in 3.59s`，exit0，自有观察2个，测试后残留0/cleanup后alive=[]。fake连接/进程，不冒充真实SSH链。

真实managed单项随后：`1 failed, 6 warnings in 6.55s`，exit1，未超时，观察2自有进程、测试后残留0。:212 start结果state=unknown而预期running；生产ssh.py:1096 RuntimeWarning `coroutine SSHClientConnection.create_process was never awaited`。已反馈Luna核实create_process实际awaitable与create_task契约，尚未定位最终根因/修复；不能因4fake绿而认真实API通过。日志pytest-b5e558ea.log保留。

AsyncSSH2.24.1的create_process经@async_context_manager返回_ACMWrapper（awaitable非coroutine）；直接create_task会TypeError。Luna改为async wrapper里await真实create_process，保留shield/启动超时/迟到回收。独立真实managed单项再跑：`1 passed, 5 warnings in 6.24s`，exit0，无未await警告。监督观察7个自有进程、测试后残留0、cleanup后alive=[]，日志pytest-9ba00715.log。覆盖真实loopback命令/输入输出/owner拒绝/取消/lease释放；_connect在此fixture覆写，不等于完整生产kernel/真实authority连接的组合验收。

当前三文件稳定联合回归：`test_ssh_execution_world.py + test_atlas_ssh_routing.py + test_kernel_exec_jobs.py`，`27 passed, 5 warnings in 20.56s`，exit0，40秒监督期限，未超时。观察14自有进程、测试后残留0、cleanup后alive=[]，日志pytest-0f312534.log。不与前述截点累加；真实kernel SSH派发/断连no-retry新增用例尚待补，不把既有job dispatch测试当远端组合证明。

本地受影响回归：`test_c1_local_workspace_cwd.py + test_c1_process_notifications.py + test_atlas_execution_flags.py`，`81 passed, 3 skipped, 5 warnings in 11.62s`，exit0，40秒监督期限；观察12自有进程、测试后残留0、cleanup后alive=[]，日志pytest-25f33cd9.log。3项skip不计通过，不与27项累加宣称覆盖率。

## 新 kernel 派发组合用例：施工失败

真实tool_node/ExecManager派发与断连替身两项主控独立：`2 failed, 5 warnings in 16.66s`，exit1，未超时，观察8自有进程、测试后残留0，pytest-361dc752.log。远端用例:487首次dispatch返回running/尚无输出即断言marker文本；断连用例:560在remote.close遇DroppedTransport缺close的AttributeError。已反馈Luna补有界poll与fake清理契约；暂不能据此判生产派发失败，也不能将未过组合用例计通过。

等待/清理修订后两项独立：`1 failed, 1 passed, 5 warnings in 14.14s`，exit1，无超时，观察6自有进程、测试后残留0，pytest-3f073a75.log。断连unknown/no retry用例通过（transport为ConnectionResetError替身，不是真实网络丢包）；远端输出用例在失败diagnostic读取不存在的record.stdout报AttributeError，真实记录使用streams，遮住原断言上下文。已反馈修诊断并定位实际输出/offset，未采信通过。

两新组合用例稳定后独立：`2 passed, 5 warnings in 8.39s`，exit0，无超时，观察7自有进程、测试后残留0，pytest-01e3dad7.log。真实kernel._dispatch→AgentOrchestrator/tool_node→ExecManager→SSH manager读到SSH_KERNEL_REMOTE_ONLY且stdout offset推进；local runtime trap未触发。当前测试未断言自然completed，finally经ExecManager取消收尾；主控先前“且completed”的描述过强，已更正。一次性命令keep_stdin=False仍未证明自然退出，交互行为由前述managed用例另验。断连项使用ConnectionResetError transport替身，最终unknown且create一次，不冒充真实网络断连。_connect在此组合fixture覆写，实际身份/host-key组合见下段。

## 真实 authority + managed process 组合

独立probe证据`artifacts/ssh-joint-independent-20261116-8f3c19a4/receipt-4.json`，6.328秒，worker exit0/30秒内层/50秒外层，无强制清理或残留。manager._connect未覆写，exact alias及实际key/host-key握手通过，known_hosts包含user/global两文件且manager未禁验证；harness辅助预连接known_hosts=None单列，不作manager认证证据。实际启动一次、ready及stdin应答；跨run status/read/write/cancel均拒绝。活动lease保护、显式cancel确认SSH退出/fixture消失、lease1→0、随后可回收，manager/listener/handlers await清理。

此前三个验证脚本施工失败保留：首次隔离用户名环境遗漏且现场异常未精确记录，不推断ModuleNotFoundError已证实；第二次known_hosts期望遗漏global文件而AssertionError，未到_connect；第三次receipt写入错误，recovery-3.json有记录。最终脚本修复不改生产/tests/docs。此组合仍不是kernel/桌面验收，不能以脚本失败当产品缺陷或抹掉历史记录。

## one-shot 自然完成：修正测试等待竞态后独立通过

加严版本曾在 marker 到达时提前跳出 poll，随后立即断言 completed，不能由其间歇红断定已完整等待5秒仍不退出。原 Luna 改为同5秒 deadline内等待 outcome非running，保持 marker、stdout byte offset、completed和exit_code=0断言；fixture转发EOF后另有2秒有界stdin pipe wait_closed。未延长自然退出预算。

主控独立两项：`2 passed, 5 warnings in 9.52s`，exit0，无超时，观察7个自有进程、测试后残留0、cleanup后alive=[]，日志`pytest-2faf2838.log`。该次真实kernel/tool_node/ExecManager→SSH loopback的一次性命令在finally清理前已自然completed且exit0，不再用cancel作为自然退出证据；断连项仍是ConnectionResetError替身/no retry。只跑本次定向两项，不将历史27/81重复累加。真实外部SSH平台、生产lifespan、网络断连及LSP尚未由此证明。

独立窄审另见REVIEW-04：AsyncSSH wait→communicate可能与独立reader争用剩余输出；属于待处理输出消费候选，不能因本次自然退出通过而宣称尾部输出安全或所有平台稳定。

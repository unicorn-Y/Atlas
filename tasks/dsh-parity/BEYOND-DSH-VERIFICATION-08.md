# X30 SSH LSP：独立验证截点

2026-11-16。生产实施仍由用户指定原 Codex Desktop GPT-6 Luna 高；主控只读审查、隔离验证与证据记录。本文各截点不累加，不代表完整 X30 或 DSH 目标完成。

## 首批改造前定向本地 fake 基线

通过既有有界监督器 `artifacts/ssh-process-check-20261116-c8a073c2/run_check.py` 执行5节点，显式 `-o addopts= -m ""`，避免默认unit筛选静默跳过。唯一basetemp、40秒pytest外层期限；自然退出，无超时。

```text
test_lsp_client.py::test_open_buggy_file_reports_t999_then_fix_clears_it
test_lsp_client.py::test_seed_baseline_push_never_counts_as_fresh
test_lsp_lifecycle.py::test_graceful_service_shutdown_terminates_server
test_lsp_lifecycle.py::test_release_workspace_stops_server_and_is_idempotent
test_c6_lsp_wiring.py::test_introduced_error_reports_and_emits_then_fix_is_silent
1 failed, 4 passed, 5 warnings in 8.95s
INDEPENDENT_EXIT_CODE=1
```

日志 `pytest-6ba5d5a4.log`，观察17个自有进程，测试后残留0，cleanup后alive=[]。前4节点通过，证明既有本地fake的诊断更新、stale seed隔离、正常shutdown及幂等release基线。第5节点在 `test_c6_lsp_wiring.py:189 import agent.lsp as hermes_lsp` 报 `ModuleNotFoundError: No module named 'agent'`；此前 introduced diagnostic/report/event断言已走过，但后续修复清空尚未执行，整项不能计通过。仅凭此失败不能判本轮SSH实现回归，也不能把环境依赖缺失隐去。只读搜索当前 `D:/hermes-agent` 未找到 `lsp.py`，不猜另一路径或修改测试伪造模块。

这是本地回归基线，不是SSH raw transport、远端FS/URI、authority缓存或双loop验收。SSH LSP首批代码尚在原Luna施工，稳定后追加真实证据。

## 首块 raw bridge / client injection 独立回归

原Luna提交首块 `ssh.py` raw bytes跨loop桥、`lsp/client.py`进程/FS/URI注入及 `test_lsp_ssh_transport.py`。主控经同监督器执行 `-o addopts= tests/test_lsp_ssh_transport.py tests/test_lsp_client.py`：`10 passed, 5 warnings in 11.88s`，exit0，无超时，观察23个自有进程、测试后残留0、cleanup后alive=[]，日志`pytest-1671157e.log`。

两个新节点标unit：一个真实双loop、内存底层process/StreamReader，验证原始bytes、分片、drain背压及同步write_eof；另一个注入fake process验证target URI、远端read_document和processId=null。既有8客户端节点显式覆盖默认unit筛选。不是实际AsyncSSH握手或真实远端FS，尚未覆盖manager缓存/准入及kernel组合。原Luna本地10项7.45s另记，不合并时间或次数。

## 独立观察器准备与局部自检

`artifacts/ssh-lsp-independent-20261116-6f28c9a1/support.py`复用可信仓库fake和stdlib-only protocol，打包到新support目录后隔离加载；观察rootUri/processId、didOpen/didChange内容与目标磁盘摘要、原fake shutdown state，并分片输出含Unicode的协议帧。`selfcheck.py`只用本机pipe直接驱动该观察器，不替代生产LSP客户端。

pack成功；首次selfcheck在快速退出后的PID枚举报NoSuchProcess，原receipt另存，修正监督器容忍已消失PID。随后局部自检1.078秒exit0：buggy→T999→clean→空诊断，两次同步与磁盘摘要一致，Unicode收到且stderr分离，shutdown/exit0，观察2自有进程无强制清理/残留。这只是验收材料有效性，不是SSH网络、query_lsp、authority或双loop生产接线证明。包装器保留原fake专用os._exit避免daemon stdin线程解释器退出问题；不作生产退出策略。

首块取消与清理失败两条确定性纯内存major见`BEYOND-DSH-REVIEW-05.md`，已交原Luna修复，不能用正常路径10项PASS代替异常窗口验证。

## 首块异常窗口回归修订后截点

原Luna在 `test_lsp_ssh_transport.py` 增加交接取消与终止确认失败的确定时序回归后，主控独立执行该文件（显式 `-o addopts=`）：`4 passed, 5 warnings in 4.36s`，exit0；观察2个自有进程，测试后残留0、cleanup后alive=[]，日志`pytest-bef099a4.log`。该命令覆盖raw bridge正常双loop、spawn交接取消和cleanup失败重试窗口；尚未因此证明真实AsyncSSH网络、manager/workspace/kernel或桌面链路。随后原两项窄审复核确认cleanup失败引用/manager关闭收敛已修，但spawn测试只覆盖同loop、create未返回时取消；真实双loop已登记未交付窗口仍有跨线程create_task错误，见REVIEW-05，已交Luna续修，不能以4项绿关闭。

## 二层 query/root 接线：替身边界

主控独立 `test_lsp_ssh_world.py`：`2 passed, 5 warnings in 4.42s`，exit0；观察2自有进程，无超时/测试后残留，cleanup后alive=[]，日志`pytest-ab65e7d9.log`。实际query_lsp→LSPService→LSPClient链使用_RemoteWorld和内存_LspProcess，验证authority cache key、nested root注入、远端read_document和null processId；另条SSHLspWorkspace root marker验证覆写_exists。不是AsyncSSH loopback或SFTP，未触发kernel两入口。真实网络组合由独立probe另验，不将替身写成远端真机。

后续跨loop交付修订与新增world节点同跑：`8 passed, 5 warnings in 9.82s`，exit0，观察2自有进程，无超时/测试后残留，日志`pytest-10425bd2.log`。该版本5条transport+3条world，第3条当时kernel两消费者仍stub query，不能由8项数字推真整链。REVIEW-05原两项最终已修，限定原发现窗口。

## kernel 双消费者提升至真实 query/service/client

原Luna将kernel两消费者测试提升为实际 `AtlasKernel._dispatch→query_lsp→LSPService→LSPClient`，底层仍是_RemoteWorld/协议fixture，read_file本体也为execute_tools替身结果。主控独立单项 `test_kernel_lsp_tool_and_read_file_diagnostics_forward_ssh_workspace`：`1 passed, 5 warnings in 7.20s`，exit0；观察2自有进程，无超时/残留，日志`pytest-1f780408.log`。覆盖LSP hover工具结果、read_file后附加诊断及两次同world构建；不等于真实SSH文件读取或网络LSP。真实authority/SFTP/raw通道独立probe另行记录，不重复累加通过数。

## 真实 SSH LSP 首次组合：查询未启动 server

独立probe目录`artifacts/ssh-lsp-joint-independent-20261116-b2e6a091`，`worker-receipt-1.json`：真实未覆写manager._connect，生成client key、host key及user/global known_hosts校验通过；SFTP部署可信support成功。目标为本机Windows loopback模拟，不是外部机器；harness明确encoding=None且只转发bytes，不用旧text decode/encode夹具，无辅助禁host-key连接。

首次production query_lsp diagnostics在0.234秒返回available=false，owner heartbeat推进146次，handler_records=[]，尚未spawn语言服务器。验证脚本没有保存query reason，故确切产品异常类和根因尚未知，不能仅凭静态resolve_root/_exists跨loop疑点定性。主链未通过。服务shutdown在线程完成且LSP线程停止；随后脚本读取不存在audit.json报SFTPNoSuchFile，阻断后续显式manager/listener/handler清理，不能宣称全部正常回收。外层另遇已退出PID的NoSuchProcess监督竞态；原receipt保留，正在按事前PID+creation补自有进程核查和一次限定诊断。缺失审计、自然退出或无handler不能当完整PASS。

## 新快照真实 SSH LSP 主链通过

唯一一次限定诊断运行 `receipt-2.json` / `worker-receipt-2.json`：10.703秒，worker exit0，40秒内层/60秒监督，无超时、强制清理或观测自有进程残留，private材料已删。五生产文件运行前后hash一致，ssh.py为3c1065f414a8f76b7df3b1db8ca3f4d10336932119ba879d1f26ee2c7a65a4ec。该新快照通过不倒推首轮available=false根因；原receipt-1及receipt-1-final保留。原launcher/worker按事前PID+creation核查均已消失，不能补作首轮显式清理已执行的证据。

真实未覆写_connect、公钥/hostkey/user+global known_hosts校验、SFTP部署，经production remote_world→query_lsp→LSPService/LSPClient→原始SSH process factory，在同world/client/process完成buggy T999→同world写clean→空诊断。观察器两次文档摘要均等目标磁盘，rootUri匹配、processId=null、shutdown/exit_seen。harness全程encoding=None/bytes，7帧、29次support写入、13个stdout片段，实际Unicode多字节内切分1次且成功接收；stderr ready独立、不在stdout。单次查询耗时4.469秒及0.485秒。

owner/LSP/query线程区分，resolve_root在LSP loop，实际_exists_on_owner均在SSH owner loop；heartbeat持续，最大间隔0.516秒。service.shutdown经worker thread先await（其间owner推进34ticks），然后manager/listener/handlers全await，SSH及LSP exit0，lease1→0；9个观测自有PID+creation无强制清理/残留。observer本身authority_verified/dual_loop_verified=false是其局部范围，身份/loop证明来自外层真实握手与线程观测。fixture保留原fake专用os._exit，不作生产退出方案。

范围仅本机Windows/Hermes Python loopback模拟；一条可信authority与未绑定authority负向通过。未验双连接authority隔离/轮换、kernel/桌面、外部平台、真实断连、全部LSP查询或spawn/cancel窗口；这些不能由主链PASS扩大。A→B身份漂移与release问题在此真实主链截点尚未验证，后续限定回归见下。

## 身份轮换、缓存隔离与 release/reaper 定向收口

- `_connect(expected_authority_id=...)`在缓存/握手前拒绝旧world身份漂移，expected穿透stat/read/binary/remote_os/process_command/spawn。主控独立身份漂移与remote release/reaper两项：`2 passed, 5 warnings in 6.56s`，exit0，日志`pytest-2ca2db32.log`，观察2自有进程无残留。
- remote authority间cache/missing/broken隔离单项：`1 passed, 5 warnings in 4.70s`，exit0，日志`pytest-a750ef00.log`，观察2自有进程无残留。这是内存world状态机，不是双真实SSH连接。
- 独立窄复核确认身份漂移已修；公开SSH release定向B且保留A，B的client/last_used/missing/broken/probe清除。另纯内存验证pending B spawn落地后释放，A pending保留；不把新unit的done futures等同pending验收。
- 原本地裸路径_release_async仍可能误关同路径A/B remote，已交Luna补skip_remote=True。修订后主控独立 `test_local_release_does_not_detach_remote_clients_with_same_posix_root`：`1 passed, 5 warnings in 4.79s`，exit0，日志`pytest-451e599b.log`，观察2自有进程无残留。测试明确只关同路径local，两个remote client及其last_used/broken/missing/probe均保留；源码调用已同reaper排除remote。限原释放身份残留，不扩大任意transport/外部平台结论。

同名root-owner测试重复定义已由原Luna去重，不能按源文件函数出现次数计执行数；以上都是各次实际collected/executed截点，不累加报覆盖率。

## 受影响本地 LSP 回归与单项修复

主控经40秒监督，显式-o addopts=执行test_lsp_service.py、test_lsp_provider_registry.py、test_lsp_pyright_fallback.py、test_lsp_lifecycle.py：1 failed, 27 passed, 5 warnings in 25.10s，exit1，观察40自有进程无残留，日志pytest-c637da2d.log。唯一失败为test_workspace_lsp_implementation_uses_implementation_request：新增remote_world=None关键字不兼容旧单参_get_or_spawn替身，随后替身缺_uri_for_path属性；不能直接据此判真实用户本地查询失败。

原Luna保留本地_get_or_spawn旧调用形式，远端才传remote_world；测试fake Client补真实file_uri映射属性，implementation method/params/schema断言不变。主控仅复验失败节点：1 passed, 5 warnings in 6.99s，exit0，观察2自有进程无残留，日志pytest-39e09a48.log。不将此前27pass加该单项宣称28同跑全绿。早先test_c6_lsp_wiring对已不存在agent.lsp的依赖失败仍单列保留，未造模块或删除断言。

下一批terminal改造前本地EOF基线：test_terminal_pty_eof_emits_exit_without_background_task_error显式-o addopts=，1 passed, 5 warnings in 6.74s，exit0，观察2自有进程无残留，pytest-78281e4a.log。该项底层winpty替身，不是SSH或桌面终端验收。


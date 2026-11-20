# X30 SSH 终端：独立验证截点

2026-11-16。生产实施仍由原Codex Desktop GPT-6 Luna高，主控独立只读审查/隔离验证/证据记录。各截点不累加，不代表X30/DSH全部目标完成。

## 本地终端改造前基线

显式-o addopts=执行test_terminal_pty_eof_emits_exit_without_background_task_error：1 passed, 5 warnings in 6.74s，exit0，观察2自有进程无残留，pytest-78281e4a.log。底层winpty替身，只证明原EOF/exit事件契约。

## 首个真实SSH terminal管理接口：回执竞态失败

主控唯一basetemp/40秒监督：test_ssh_terminal_uses_real_authority_pty_input_resize_exit_and_disconnect，1 failed, 5 warnings in 13.28s，exit1，观察6自有进程无超时/残留，pytest-af6deaa4.log。失败于全局_LAST_LOOPBACK_CHILD.term_type=None预期xterm-256color，尚未执行input/resize断言。不能由该旧全局记录先判生产没发PTY。

原Luna核对AsyncSSH真实API并将fixture改为等待本次terminal handler回执，不放宽PTY/input/resize/exit断言。主控修订后独立单项：1 passed, 5 warnings in 8.45s，exit0，观察8自有进程无残留，pytest-5dbd8369.log。实际manager未覆写_connect，临时生成key/known_hosts走真实SSH authority；PTY request/term_type/size、stdin、resize、自然exit0/lease0及显式close后本地回收通过。底层loopback执行器是pipe，不是实际OS PTY；该测试不是ASGI WebSocket/桌面UI验收，close=True不单独证明远端终止确认。

## 施工窄审：两条异常路径待修

只读ssh.py、api/tools_router.py及terminal测试，纯内存实际函数固定时序复现，无网络/服务/模型/子进程/生产修改。快照ssh.py前缀27128c982cf6743a，router3d0a905743874ae1。

1. create_process永不回执，cancel open_terminal后_recover_terminal_start无期限await；manager.close先等session.close后无限gather recovery，未到transport.close。3.25秒观察transport_close_calls0、lease1、session1、recovery1；主动放行后才完成。需有界恢复与关停顺序，迟到handle仍清理，远端未确认保持unknown。
2. output_task未与receive loop联合监督。session.read确定抛OSError，output task已失败而handler仍等receive，session.close_calls0。需任一端结束/失败收敛并cancel/gather另一端后有界cleanup；不能依赖客户端再发消息。正常exit后实际ASGI是否必挂未证，不以fake推全部平台结论。

session.close返回True且exit_status=None时仅证明本地channel回收，不能称远端进程确认退出；作为准确性边界，不加第三major。原Luna已收到并将同批修复，当前正常路径PASS不覆盖这些异常窗口。

## 实际 ASGI WebSocket→SSH 单次运行

`artifacts/ssh-terminal-independent-20261116-49ad1e6b/{receipt.json,worker-receipt.json,postflight.json}`：单worker运行7.187秒、exit0，未超时/重跑。实际FastAPI router最小app（不含完整lifespan）与真实ASGI WebSocket→原始open_terminal/_connect→生成key/hostkey/known_hosts；仅注入独立manager服务对象，未替换生产协议实现。PTY xterm-256color/80×24、input/回显、resize113×37通过。自然fixture exit0→output EOF→WS exit0；未发送显式stdin EOF。disconnect收到TERM后harness清理保存PID+creation的自有fixture树、exit15、lease/session0，不外推任意远端后代。pipe后端只证明SSH PTY协议，不是OS PTY/ConPTY。

源码版本限制：ssh.py前后一致f59b7c9221d5cb899811d778ebe238714b746660455fed922ca912faace0e622；tools_router.py运行前489b3df4e5822796c3e7d7f8ae2157cb40d97e35ef354fbda773df47d9f94917、后582d4a58df31810d7a8859870b773f705c72ed0f1d16de86d682ec8bc12f2cea；未保存加载code hash，确切加载版本unknown，source_hashes_stable_during_run=false。后读新版本为双任务联合监督，但本次不算最终新异常路径验收，postflight.latest_router_snapshot_accepted=false。

最终pool/session/cleanup tasks/handlers/backend均0，监督器forced_cleanup=[]、remaining=[]，8个观测自有PID+creation记录，private材料删除。没有生产/tests/docs或用户真实config/data/凭据改动，不碰8765/外网/模型。

## 异常回收修订后独立四项

原Luna补有界启动恢复/manager关停顺序、input/output FIRST_COMPLETED监督和定向回归后，主控独立4节点：`4 passed, 5 warnings in 9.71s`，exit0，无超时，观察7自有进程、测试后残留0、cleanup后alive=[]，日志pytest-dc898f01.log。节点含永不回执关停/迟到handle、read OSError自动收敛、WS协议替身、真实authority terminal管理接口。两异常及WS为纯内存fake，不冒称ASGI；真实manager节点不等于真实OS PTY。

## 原两major最终限定复核

原两项均已修。实际manager.close在故意让create回执于transport关闭后仍不返回的情况下3.015秒返回，lease0/session0；close返回后再放行迟到handle，实际recovery调用close一次，最终cleanup_tasks0。回执永不来时manager返回后仍留1个recovery等待task，不再阻塞manager或持lease，不能宣称该异常下所有task清空。exit_status始终None，不当远端终止成功。

实际router FIRST_COMPLETED监督read OSError与永久receive，1秒边界内返回，receive取消、session关闭、脱敏error/WS1011；无需新客户端输入。复核仅指定片段+纯内存确定性实验，无网络/服务/模型/文件修改，快照ssh587475f561c9c21d/router4ec88de74c2e1f0c。原两项结束，不扩审正常路径/其他模块，继续child/sandbox。

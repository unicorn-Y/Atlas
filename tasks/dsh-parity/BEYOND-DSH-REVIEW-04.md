# X30 受管 SSH process：施工截点有界审查

2026-11-16。生产原桌面GPT-6 Luna高；独立只读5文件，AST/纯内存fake复现，无文件/服务/网络/模型/真实配置data。不把施工稿当终稿验收，最多三项已复现major。

1. **启动确认前取消丢失**：ssh.py:1000/:1047附近create_process未返回时process=None，cancel只置unknown，不保留待处理取消意图；晚回handle安装后再cancel_run仅筛running，跳过活进程。直接取消start task又因CancelledError未捕获留下process=None/watcher=None/lease1。Event复现返回unknown但remote_still_running=True、signals=[]、lease1。需取消意图跨启动窗口保留、迟到handle终止、本地资源有界回收；两定向回归分别卡create后cancel_run再放行、直接cancel启动task。
2. **活动lease未保护_connect缓存替换**：ssh.py:317/:325只按300秒检查复用，未看active_leases，下一请求会close仍持活动进程的旧client；reaper单点检查不足。fake复现old_lease1、old_client_closed=True、connection_replaced=True。健康活动连接不能仅因闲置计时关闭。
3. **unknown未同步上层**：ExecManager._poll_locked:619在is_error提前return，SSH有效execution_id/data.state=unknown未改handle.outcome，watcher继续轮询，无显式timeout可永久running占配额。AST提取真实方法fake连续3次仍running。需一次poll收敛unknown/watcher退出、不自动重启。

owner跨run拒绝负向检查通过；纯内存exit0→completed/17→failed/无exit→unknown及lease重复释放保护通过。不扩大为真机SSH/完整kernel/模型证据。

已通过原会话反馈Luna。行号为施工快照，需以关键词定位。后续修复与实测另记VERIFICATION-06，不先记通过。

## 首个真实fixture超时的限定静态定位

test_ssh_execution_world.py:90将_forward_input与两个output任务一并gather，:91才process.exit。子进程已退出但SSH stdin未EOF时，输入task仍等:50下一块，SSH exit不能发出，客户端wait又不能结束；甚至remote_os的echo探测可先落此等待链。等待链静态high，本次45秒实际落点仍需阶段/task证据，未冒充现场栈。

同用例detached=True却调用cancel_run，生产明确跳过detached，预期冲突。前台owner取消应non-detached，detached另验显式取消/生命周期。已反馈Luna以单点2秒task诊断定位并修fixture清理，禁止延长期限或弱化断言。此fixture问题不覆盖上述三个生产不变量。

## 原三项定向修复复核

当前静态复核三项均已修，限原触发路径；主控4fake/真实managed/三文件27项通过另见VERIFICATION-06。启动取消保留cancel_requested、迟到handle接入后终止，cancel_run覆盖starting；_connect健康active lease连接不因300秒替换；ExecManager先同步unknown再返回，watcher可收敛。

明确边界：句柄始终不返回的恢复超时分支未由该测试覆盖；它关闭共享连接且依赖wait_closed返回，不能据此宣称任意异常transport有严格总时限或远端一定停止。同authority健康cache复用不等于断连恢复；真实kernel/断连传播仍待补测。这些未验证范围保留，不把原三项继续记未修。

## one-shot 终态与输出消费者窄审

安装版 AsyncSSH `process.wait(check=False)` 调用 `communicate()`，后者等待 channel/cleanup 关闭再 `collect_output()`；没有 input 时不主动发送 stdin EOF，也不直接等待 stdin EOF。生产 `_watch_process` 同时有独立 stdout/stderr readers，存在 `collect_output()` 收走剩余缓冲、返回的 stdout/stderr 未写入 record 的输出消费重叠候选；不是已证实的自然退出死锁。最小建议是单一 reader 消费输出，watcher 等 `wait_closed()`、drain readers 后读取 exit_status/exit_signal。此为指定 ssh.py 与安装版 process.py 的静态结论，未确认现场卡点。

主控随后读取加严版本测试发现确定的测试竞态：`while` 在 marker 到达或 outcome 非 running 时退出，紧接着断言 completed；marker 先到会提前结束，并未用满 5 秒自然完成等待预算。因此该版本间歇红不能单独证明远端 5 秒未退出。已反馈原 Luna 将退出条件改为等待非 running，保留 marker/offset/exit0 与 no-local 断言且不延长期限；独立复验另记 VERIFICATION-06。

输出消费候选后续确定时序纯内存实验未复现：安装版AsyncSSH2.24.1真实process/readers，提取当前生产watcher/reader/attach，内存channel在readers启动、watcher等close后同tick交付stdout/stderr各4124字节与不同尾标记、EOF及close。record两流逐字节/SHA256一致，communicate各收走0字节，completed/exit0/lease0/readers结束/pending tasks0。0.015秒，无子进程/网络/文件/生产修改；首次内存channel缺接口纠正后执行有效实验。不是实际transport证明，不列确定bug；也不要求仅凭该候选修改生产。此前静态单消费者建议仍是可选设计理由，不能记为已复现丢字修复。

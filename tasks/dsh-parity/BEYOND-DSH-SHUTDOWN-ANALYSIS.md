# 隔离后端 shutdown complete 后挂活：静态诊断建议

2026-11-16。只读8文件核对，未启动/停止服务，未发HTTP，未读取实际配置/认证，无模型调用。不是现场根因证明。生产诊断与修复仍由原桌面 Luna 执行。

## 现场已知

VERIFICATION-03:70-75：8918隔离后端观察startup/shutdown complete，但30秒后forced termination，code1；MCP fixture未ping、撤销后进程0。不能以application shutdown complete证明server.serve、asyncio.run或解释器退出。omni_bench.py:530日志摘要只看末200行ERROR/CRITICAL，DBOS warning不计errors。

## 候选排序（全部需现场栈验证）

1. core/atlas/capabilities/durable/dbos_backend.py:163：stop把DBOS.destroy放daemon线程atlas-dbos-shutdown，默认仅等1.5秒，超时warning后返回；destroy会join scheduler/worker。daemon本身不足以解释挂活，需找到其等待的non-daemon/SDK executor。:187有恢复默认executor说明，不能据此推定本次SDK已泄漏。
2. core/atlas/api/deferred_startup.py:457/517/539：startup-engine-warmup以to_thread执行_warm_engine，包装task取消不终止真实线程；导入/token prefetch可能仍在跑。需栈证明此次残留，不能把用过to_thread等同泄漏。
3. 新安装任务最终取消的进程回收：runtime.py:330/383/454。Windows taskkill.wait及kill后wait存在无显式期限路径，当前清理表未见统一drain_install_tasks；此次X6没有已知安装操作，故不作为本次首选归因，但新X5/X7必须接生命周期。
4. core/atlas/tools/mcp_client.py:925/1028：owner/session/transport清理与shield等待无显式期限。正常lifespan/disposer会await MCP stop，若直接卡这里通常看不到shutdown complete；只有漏收owner/SDK任务更符合本次现象，暂无现场证据。

其他条件候选：deferred_startup.py:294 shield的DBOS启动线程、dbos_backend.py:137取消后destroy、server.py:898/968 PR/IMAP to_thread。只有此次真实触发且残留才提高优先级。

## 下一次既定隔离验证的一次取证

保持原30秒退出期限，不重复整套UI，不触碰8765，不用os._exit或延长timeout掩盖问题。

- 阶段时间线：私有shutdown文件、lifespan返回、serve_task返回、_serve返回、asyncio.run返回、进程退出；记录单调时间/PID，DBOS destroy开始/完成/timeout。
- shutdown complete后约2秒、15秒仍活着时两次全线程栈：name/ident/native_id/daemon/alive及frame位置；不用locals。
- serve_task返回及最终取消前异步task：name/coro/done/cancelling/stack，特别是DBOS、warmup、MCP owner/monitor、install/subprocess。
- 对应自有PID进程树：PID/PPID/创建时间/可执行basename/存活/退出码，以及自有端口。不得输出完整命令行、env、配置或请求内容。
- 保存Python/uvicorn/DBOS/MCP版本与受检代码身份；退出前将诊断证据复制到独立证据目录，避免TemporaryDirectory清理丢失。

判读：主线程executor shutdown+worker warmup/DBOS→修真实工作终止；asyncio.run返回仍non-daemon→找owner stop/join；最终任务取消卡MCP/subprocess→查对应清理；仅daemon destroy线程join栈仍不够，要找到被等线程。

结论置信度medium；退出阶段语义与代码候选high，实际根因未定。

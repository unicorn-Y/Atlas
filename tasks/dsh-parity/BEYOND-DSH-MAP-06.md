# X30 后续 LSP：现有调用链与双 loop 接线

2026-11-16。有界只读5生产文件+fake顶部元数据，不读当前施工ssh.py，无实现/测试/网络/模型/服务/实际配置data。供原桌面Luna在managed process稳定后接线，不打断当前取消修复，不构成CLOSED。

## 保留现有链

kernel loop.py:3684经to_thread(query_lsp)→tools/workspace_lsp.py:61→LSPService（实现在lsp/manager.py，不存在service.py）→LSPClient→目标world。读取文件后附诊断是第二个消费者，loop.py:4412当前排除SSH。仅替换spawn不足：workspace_lsp.py:12仍本机Path.resolve/is_file，返回Location也需authority URI转换。

LSPClient依赖：client.py:252本机process argv/cwd/env/三PIPE；:202/:452二进制stdin write/drain/is_closing，stdout给read_message，stderr.readline；:584本机读文件与文档缓存；:80桌面OS路径/URI；:420本机PID tree cleanup。initialize :380当前桌面processId，remote应null或有效远端client PID，不传宿主PID。必须同world fs/process/URI/platform/lifecycle，不拿文本截断命令输出仿造JSON-RPC流。

manager.py:609 root/trust/provider/spawn先于client，:676 ServerContext/build_spawn为注入处。:734 reaper本机isdir、:748release本机abspath也需world。缓存key(server_id,root)及trusted multi-root空root需authority参与；spawning/broken/missing/baseline一并隔离。

## 双 loop 边界

manager.py:103后台loop.run以run_coroutine_threadsafe.result同步阻塞。保留kernel.to_thread，不能在SSH owner/main loop同步query_lsp，否则LSP等待SSH而主loop等LSP死锁。LSP pending futures/locks/readers归LSP loop，AsyncSSH连接/process/stream归创建loop；桥只传bytes/结果/异常，I/O投递owner loop后await线程安全future，不跨loop直接await原生stream。

同步stdin.write若保留只缓冲本地，实际SSH写与背压由async drain完成，或沿client._write改异步managed接口。to_thread取消不停止线程，manager.py:130超时取消及client.py:240 shield清理需定义确认。manager.py:526关闭顺序必须cleanup完成→停LSP loop→关SSH owner loop。

## 最小改动图与前置契约

必触及loop.py两消费者、workspace_lsp.py路径/authority service/URI、manager.py root/provider/状态身份、client.py process/fs/URI/lifecycle。types.py的Diagnostic.file可保持目标绝对路径，authority放外层，不必无依据加transport字段。root/build_spawn内部helper本轮未展开，实施时若写死本机需补现有seam，不另建SSH LSP旁路。

managed process前置：稳定authority/owner loop/目标平台；argv/cwd/env/binary探测；非PTY二进制独立stdout/stderr、分片/EOF/背压；wait退出码/信号/断连区分；spawn前取消与迟到回收；handle幂等终止/清理确认。当前模型进程ring buffer截断输出不是LSP协议reader。

## 五项验收建议（未执行）

1. 同root/server跨authority的client/trust/missing/broken/baseline隔离，远端失败不回本机。
2. 真实双loop fake bridge的spawn/read/write/wait线程归属与主loop活性。
3. Content-Length分片/中文/长stderr/慢reader与背压，不解码丢帧或合并流。
4. Windows桌面→POSIX目标FS/URI往返，读取远端内容、rootUri/didOpen/Location一致，processId合法。
5. 初始化取消/查询超时/断连/shutdown，pending结束、无迟到spawn泄漏、清理先于loop停止且保留版本新鲜度。

现有fake_lsp_server有LSP_BUG/延迟push/stale seed/shutdown元数据，但依赖目标Atlas protocol import并写state；不能直接把本机argv路径当远端fixture。置信度medium：当前链证据充分，最终bridge接口依赖正在施工managed契约。

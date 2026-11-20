# 隔离后端退出阶段：一次独立诊断

2026-11-16。主控诊断脚本仅位于 artifacts，未改生产实现。使用当前 dirty 工作树，HEAD=060071ab2ecf86d41cab90e98160183ce126bc69；该提交身份不代表未提交内容已固定。生产实施继续由原 Codex Desktop GPT-6 Luna 高承担。

## 条件与边界

沿用 IsolatedAtlasBackend：全新临时数据根/配置副本/DB/日志与私有 hook 覆盖，动态空闲 loopback 端口5541；不碰8765，不发模型请求，不安装MCP或插件，不读取补充API状态。只执行既有启动 ready/hook-isolation 校验，然后写私有 shutdown 文件。没有重新执行之前 context-mode 拒绝的状态读取。

诊断脚本在子进程内包装 uvicorn.Server.serve，记录 serve/_serve/asyncio.run 阶段；线程只保存 name/ident/native_id/daemon/alive 和 frame 文件/行号/函数，不保存 locals、环境、配置、完整命令或请求。watchdog 计划在 shutdown 请求后2秒、15秒仍存活时采线程栈；本次更早退出，未获得这两份挂活栈。关停期限保留原30秒，没有延长或 os._exit。

证据目录：`artifacts/shutdown-probe-20261116-3b6e5c83/`，包含 supervisor.py、child-events.jsonl、result.json。

## 实际结果

```text
ready: hooks_effective=true; port=5541
shutdown_file_observed elapsed=7.469s
serve_return elapsed=8.078s
_serve_return elapsed=8.078s
asyncio_run_return elapsed=8.078s
graceful_exit=true
forced_termination=false
exit_code=0
startup=complete; shutdown=complete; errors=0; last_error_type=unknown
```

shutdown 文件观测到 asyncio.run 返回约0.609秒。返回时线程只有 MainThread 与本诊断新增 daemon watchdog，没有观察到残留非daemon工作线程。serve 返回时异步 task 快照只含当前 serve wrapper 与主协程。诊断进程及当时两个自有Python PID已按 PID+创建时间另行核实均不存在；没有仅用父进程消失推断全部子进程退出。

运行版本：Python3.11.16 / uvicorn0.41.0 / DBOS3.0.0 / MCP2.0.0。命令退出0。

## 结论

本次轻量隔离启动/关停自然退出，未复现 VERIFICATION-03 的8918 UI/MCP场景30秒后forced退出。不能由本次成功关闭旧挂活问题，也没有现场栈可归因DBOS/warmup/MCP。后续须在真实触发旧UI/MCP或模型路径的隔离进程保留相同阶段/线程/task取证，再决定生产修复。本次没有模型成功、完整插件桌面安装或公平DSH对测结论。

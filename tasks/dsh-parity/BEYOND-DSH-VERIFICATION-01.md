# 首批生产依赖/生命周期：独立验证回执

日期：2026-11-15。实施：Codex 桌面 6 Luna High，经主控本机 CDP 派工与非中断 steer。主控仅观察、审查和独立验证，未代写生产实现。

## 独立定向回归

工作目录：D:/Atlas/core。独立测试子进程自然退出，返回码 0。

```text
python -m pytest tests/test_service_registry.py tests/test_startup_failure_resilience.py::test_preyield_constructor_failure_closes_initialized_memory_store -q -p no:cacheprovider --basetemp=C:/Users/25011/AppData/Local/Temp/atlas-cdp-supervisor-3bba1f9ed0064920ae0a5b6e946b8b72
...........................                                              [100%]
27 passed, 5 warnings in 7.31s
INDEPENDENT_EXIT_CODE=0
```

Python：C:/Users/25011/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe。测试的 pytestmark = pytest.mark.unit 已核实，不是全 deselect。5 个 warning 为已有 FastAPI on_event 与 Pydantic Config 弃用提示，不是 0 warning。首次主控外层命令因 shell 引号 SyntaxError 未启动测试，纠正后才得到上述真实运行结果；不得把失败命令记为测试通过。

覆盖：服务注册/依赖/owner、未知 action、真实 pre-yield 构造失败下 MemoryStore 关闭、同名 provider 冲突、跨 owner 异步 disposer 在 memory.close 前、异常后继续清理、channel stop/drain 与 sessions/channel DB 释放顺序。覆盖边界以测试实现为准，不代替真实同批消息/真实进程压测。

## 独立只读定点复核

同一审查者复核原三项及未知 action，结论 PASS：
- channel 先 await stop/drain，再 sessions.close，最后 channel DB close。
- 同名 provider 预检 owner、实例身份、依赖与 disposer 配置，不再吞错制造分裂图。
- 跨 owner await disposer 与 core close 通过依赖闭包排序，普通失败后继续清理，最终汇总异常。
- 未注册 action 与 pre-yield 空 registry 仍有真实关闭兜底。

此为限定范围静态复核，不是整库安全或所有并发路径证明。原审查见 BEYOND-DSH-REVIEW-01.md；其中未决快照已由本次复核更新，不能把旧 findings 继续当当前未修。

## 仍未完成

- 真实进程启动/退出、用户入口与真实模型验收。
- 安全基准脚本与公平整轮计量修复。
- 多轮 volatile 上下文当前态投影与隔离真实复测。
- 固定 DSH 完整差距地图、余下工程及可重复超越。

当前仅可表述：首批服务依赖/生命周期代码的定向回归及原问题静态复核通过。不可宣称 Atlas 全面对齐/全面超越 DSH。

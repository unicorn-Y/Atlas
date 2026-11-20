# 首批服务依赖/生命周期独立只读审查

日期：2026-11-15。这是施工中快照审查，不是全目标最终验收。实施仍由 Codex 桌面 6 Luna High 进行；审查者只读，未运行测试、真实模型或操作用户进程。所有发现已由主控通过 CDP steer 转交实施端。

## 当前判定：待修复复核

1. **major：channel 关停竞态。** 新排序把 gateway.sessions.close 置于 channel_manager.stop 之前。真实链路：channels/__init__.py 中 _drain 同批多条 await dispatcher；gateway_service.py 的当前 run 取消被捕获后正常返回，drain 可能继续下一条并访问已关 sessions。需拆分 quiesce/stop 与 dispose/close，保持 channel.stop → bridge.sessions.close → channel.close，增加同批两条、首条等待 run 时关停的对象级验证。不能以只断言新调用顺序的测试自证。
2. **major：同名插件实例身份分裂。** server.py 新注册 helper 遇同名 provider 吞 ValueError，但 AppServices 及已构造对象可能仍持 core 实例，依赖图却连接 plugin 实例。卸载 plugin 会级联撤销 core 登记而字段保留。需显式拒绝不一致实例/owner 冲突，或使用统一权威对象，并验证 registry、实际持有对象、AppServices 一致。此为既有同名吞错机制与新增依赖边的新交互。
3. **major：跨 owner disposer 晚于依赖实际关闭。** 新 finally 在真实 memory 等 close 后才 unregister_owner(core)，依赖 memory 的 plugin disposer 执行过晚；异步 disposer 返回的协程也不能被丢弃。需让依赖闭包的 disposer/真实 close 统一排序并 await，验证 plugin flush 先于 memory.close、异步 disposer 确实完成、失败不阻断其余必需清理。

## 已撤销的先前发现

曾发现拓扑排序丢弃未注册 action，造成 manager/automation/x2 等漏关，空 registry 时 pre-yield 失败资源也漏关。审查者最后读取时已见未知 action 保留修复，因此不再列为当前未决，但仍需定向回归验证；不能以静态已改冒充测试已过。

## 复核规则

实施端修复并提供具体测试命令/输出后，复用同一审查者只针对以上问题与直接回归复核，不扩展成持续移靶的整库审计。真实 lifespan/模型入口尚需另行验证。当前不存在全面完成声明，也不能把修复中缺项判为虚假完成。

# ATLAS-C1R-FINISH 独立验收

日期：2026-10-02  
结论：**通过，可以进入 C2。**

## 验收依据

核对了 Atlas 提交 `df16b12cc7a4062e1e442a3474ba6bb890276476`、结果提交 `255ba547a4fc395ecd025d7e6085c6bb70bc1f49`、Hermes 提交 `b275599798fb89040a5a53981a5a409001af8774`，以及本波改动的运行时、工具桥接、C1 WebSocket 验收和 C1 对标状态。

关键结果：
- C1 WebSocket 验收：24 项通过；
- C1 聚焦回归：35 项通过；
- Hermes Windows 文件读取回归：18 项通过；
- MCP checkpoint 修复后的定向回归：2 项通过；
- 前端四项检查全部通过；
- CORE-PARITY 的 C1 行已收口为 ✔。

暂停修复的位置正确：Atlas 在 provider 请求前挂单一 gate，Hermes 只在每次真正发起模型请求前调用，不额外复制循环或增加第二套状态机。暂停、继续、取消由原运行上下文控制，符合本波“只修真实问题”的要求。

## 全量 pytest 的 6 个失败判断

施工阶段按任务书只跑了一次全量：`1056 passed, 9 skipped, 6 failed, 3 warnings`。之后没有为追求数字重复跑全量，符合“禁止过度验收”的要求。

其中 2 个 MCP checkpoint 失败来自“没有 pause_event 时仍走异步等待”的本波新问题，已修复并定向 `2 passed`。剩余 4 个不作为 C1 阻塞项：

1. **legacy Agent 流式模型名期望**  
   旧 LangGraph 测试仍钉死旧 metadata 中的 LiteLLM 名称；当前用户可见模型语义使用 Atlas 模型 ID。C2 第一节会删除 legacy 循环和对应旧契约，不为即将删除的路径改生产代码。

2. **terminal 默认 shell 期望**  
   旧测试仍期望无 `shell` 参数时固定 PowerShell；当前工具 schema 已明确“优先 Git Bash，找不到再 PowerShell”，`_translate` 默认进入 bash 路由。C2 本来就要核实 Git Bash 识别与回退，这属于陈旧测试契约。

3. **新旧内核事件完全相等**  
   旧测试把 Hermes 的 `read_file` 与 legacy 的 `local_file(action=read)` 等内部工具名、参数也要求逐字段完全相同。对外稳定事件顺序与结果已经由 C1 WebSocket 验收覆盖；内部实现不同不应作为兼容失败。C2 删除 legacy 后移除这类“两个内核必须内部相同”的断言。

4. **并行子 Agent 假服务重复委派**  
   测试 responder 用“消息中出现 `delegate both summaries`”作为每轮再次返回 `delegate_task` 的条件；后续父模型请求仍包含原始用户消息，因此 fake 自己会再次委派。这不是生产代码在收到子任务结果后主动重复派发。C1 的子 Agent 生命周期/权限/清理及 WebSocket 路径已有独立聚焦覆盖。

## 非阻塞清理

上述 4 个测试契约在 C2 第一节随 legacy 删除/测试清理一起处理。原则是：
- 陈旧 legacy 测试直接删或改成 Hermes 等价测试；
- fake responder 自身错误只修 fixture；
- 不为了让旧断言变绿而回退生产行为。

## 结论

C1 的生产主链路、Hermes 内核桥接、暂停/继续/取消、工具/终端、会话、子 Agent 和 C1 对标项没有发现新的真实阻塞缺口。

**ATLAS-C1R-FINISH：PASS。进入 ATLAS-C2-TOOLS-CONTEXT。**

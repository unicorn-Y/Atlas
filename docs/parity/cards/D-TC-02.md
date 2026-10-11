# D-TC-02：Agent 委派、计划与任务生命周期

基线：`origin/memory-v1`（`e0bbfcf0587fc41ad6bb90f54f7362bfb2b0b0d6`）
分支：`card-d-tc-02`

## 逐项结果

- **D013 计划模式入口/退出 — 已完成。** 新增 `EnterPlanMode` / `ExitPlanMode` 模型工具及动态计划模式状态转换；计划模式限制为只读工具。退出时沿用现有计划提案和用户审批流程。
- **D014 询问用户 / 结构化问题 — 已完成。** `AskUserQuestion` 接收问题标题、选项描述和多选设置；多选答案以结构化列表回传，前端问题卡展示相应信息。
- **D016 代理创建和委派 — 已完成。** 单项和并行委派支持调用级模型、reasoning effort 和最大深度；最大深度受 Atlas 配置上限约束，reasoning effort 会传入子代理运行参数。
- **D017 子代理消息、恢复、等待、中断、关闭 — 部分完成。** 当前运行中的委派任务新增等待、恢复、取消、中止升级和关闭工具，并复用现有委派任务记录与事件。跨会话 Agent registry、跨会话消息路由和相应权限校验未完成：现有注册与任务记录只覆盖当前运行，代码中没有可复用的持久跨会话 Agent 身份及授权合同；在缺少该基础时不能安全地把这些控制扩展到其他会话。
- **D018 会话上下文读取/工具历史 — 已完成。** 新增当前运行工具历史读取；`new_context` 可在 Atlas Kernel 中执行上下文压缩并发出窗口切换事件，保留 Hermes handoff callback 兼容路径。
- **D042 工具审批范围/理由 — 已完成。** 审批请求向界面传递理由与资源范围；PreToolUse / PermissionRequest 分支保留原因和 scope/resource，审批 UI 显示这些内容。
- **D115 本地定时任务管理 — 已完成。** 新增 Cron 创建、列表、更新、删除模型工具，并通过现有 AutomationStore 持久化。需要本地持久调度器处于运行状态；调度器未运行时写操作明确失败，不返回虚假的已调度成功。
- **D118 会话唤醒调度 — 已完成。** 新增 `ScheduleWakeup`，通过持久 Automation 计划在指定时间向原会话投递唤醒任务；调度器未运行或日期无效时不会伪报成功。
- **D122 结束会话 — 已完成。** 新增 `EndConversation`，取消当前 Agent 运行并把结束原因写入可见的取消事件及时间线。
- **D125 结构化审查发现 — 已完成。** 新增结构化 `ReportFindings` 接收入口，包含 finding、severity、location 和 evidence，并接入现有审查发现解析与持久化路径。

## 验证

- `python -m uvicorn atlas.server:app --port 28798`：在 Python 3.14 隔离环境并关闭 upstream 自动连接后启动成功；`/api/health` 返回 `status: ok`，所有列出的组件为 ready。服务随后已停止。
- `npm --prefix frontend run build`：通过（TypeScript 检查及 Vite 生产构建）。未写入或运行测试。

## 提交

- 实现提交：`9bae1f6f1cdff51650ffddd87f81e1859a55d329`。
- 卡片结果文档提交：本文件随结果文档提交；该提交号由 Git 记录。

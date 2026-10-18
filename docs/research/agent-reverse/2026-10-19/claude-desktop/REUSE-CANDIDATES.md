# Reuse candidates / 合法实现边界

此处是**机制及开源接口候选**，不是从 Claude 专有发行包复制代码的许可。Claude Desktop / cowork-svc 属于闭源商业发行物；静态分析供理解互操作与比较，原始 JS/EXE 不作为 Atlas 可直接复制资产。

| Atlas 需要的机制 | 可吸收方向 | 研究/授权边界 |
|---|---|---|
| 任务与 GUI 生命周期解耦 | 复用已在 Atlas 的 `core/atlas/runtime/hub.py` 和 `core/atlas/runtime/hub_control.py` 作为稳定服务，再将交互式 run 身份与事件持久化桥接 | 自有代码，无需重写整个 agent |
| 持续事件流、游标、可恢复订阅 | 在现有 `core/atlas/api/runtime.py` + `run_drive.py` 基础上增加持久 event journal / replay，令 UI 复用 `backend-adapter/src/client.ts` 的 cursor 机制 | 自有代码；不要照抄未经授权的 Claude 协议内核 |
| GUI 原生动态消息/任务卡 | `frontend/src/renderer/services/runtimeEvents.ts` 与 `ConversationActivity.tsx` 建立 schema-driven component registry，按注册的 event action 打开视图 | 自有代码；Claude UI 行为只供对照 |
| 后台多设备 broker | 界定 `remote session`/Desktop agent 与 cloud transport 的生命周期，结合已有 Atlas device manager 模块 | 不从 Cloud API 文档猜私有 RPC 字段；采用公开协议或自定义合法协议 |
| 工具与插件 | Model Context Protocol 开放规范和公开许可证的 MCP SDK/servers；Atlas 已有 `core/atlas/tools/mcp_client.py` 与插件 registry | 逐仓核查具体依赖 LICENSE，扩展不能等同桌面宿主原生 |
| 浏览器/Computer Use | 复用 Atlas 已有 `core/atlas/tools/x2/browser.py`、`computer.py`，先证明 Browser / UIA / CUA 场景，再补能力优先级 | Claude Desktop 具体闭源实现不可拷贝；官方 D 仅验证产品层设计 |
| 交互式文档/可编辑工件 | 在已有 artifact 事件上引入有版本的文档对象及局部 patch（可用公开编辑器生态评估） | Claude Docs/Slides 内部数据模型未见，不声称兼容 |

实施前提：先拿到包内真实组件/IPC 清单和对照证据，确认真正值得移植的机制。此文件不把概念性差异写成已经存在的成熟开源代码。
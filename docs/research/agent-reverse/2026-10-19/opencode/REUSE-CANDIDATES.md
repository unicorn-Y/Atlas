# 复用评估（v2.0.32 固定源码）

[OpenCode 根 LICENSE](https://github.com/anomalyco/opencode/blob/v2.0.32/LICENSE) 为 MIT（Copyright 2025 opencode）；若复制代码需保留许可及 copyright，且第三方依赖、素材、子项目还需逐个确认，不以根 MIT 推断全部资产开放同样许可。下述“移植”是技术适配建议，不是已执行改造。

| 优先 | 机制、入口 | 适配 Atlas 方法 | 依赖与许可注意 |
|---|---|---|---|
| P0 | `core/src/session/{inbox.ts,execution.ts,execution/restart.ts,sql.ts}` | 抄数据状态转换、claim/write-ahead、terminal/recovery 规则，用 Python + Atlas SessionDB 的侧表/事务接入 | 源码 TypeScript Effect+Drizzle；直接复制无法独立运行。和 Hermes 已有 SessionDB 所有权统一 |
| P0 | `core/src/session/subagent-job.ts`, `subagent-completion.ts` | child Session durable Job + 父会话 synthetic 结果，在 Atlas 当前 subtask scheduler 上做适配 | 可重用语义和测试思路；不引入 Effect runtime |
| P1 | `core/src/session/runner/{step.ts,retry.ts}` | 拆 provider/tool terminal，按 ProviderError 分类决定重试，确保取消结算状态不误报成功 | 事件/回调模型与 Hermes 不同，优先适配 |
| P1 | `app/src/session/composer/queue.ts`, `server/client.tsx` | React composer 由后端 inbox 真相派生，重连触发 reconcile；避免本地 queue 丢失 | 源 SolidJS；只抽状态机而非组件直拷 |
| P1 | `core/src/plugin/{module.ts,supervisor.ts}` | Python plugin supervisor 基于 generation、状态、来源、错误、热更排序统一管理 | npm/Node 热加载仅适合 JS 插件；Python 需新 adapter |
| P2 | `core/src/codemode/tool.ts` + `packages/codemode` | 若要 Code Mode，作为显式可选 tool execution 路径与 Atlas 宿主工具、permission 合并 | 独立沙箱能力与 Atlas 高权限操作不是一回事；不可直接把 JS sandbox 变成 unrestricted host |
| P2 | `app/src/session/timeline/virtualizer.tsx`, `session-ui` | 借虚拟化/锚点/逐组展开设计重写 React 时间线 | Solid 虚拟列表和 UI 库、许可证需单查；直接搬组件成本大 |

**不建议**用 OpenCode v2 的整个 Agent Host 或 DB 覆盖 Atlas Hermes：用户已要求 Atlas 自己作为独立 Agent/记忆主体，外部引擎可随时切换。复用应以可替换模块为单位、始终保持 Atlas 单一任务与会话真相。

# 主动发现机制账本（v2.0.32；除特别说明皆 S / 静态源码）

证据评级：S = 对应标签源码具体逻辑；D = 文档声明；I = 有根据的推断；U = 未核；R = 真实运行验证（本轮没有）。每条记录同时给出 UI/服务归属与生命周期，详见 IMPLEMENTATION-TRACE。

| ID | 机制／发现 | 归属与最短源码证据 | 生命周期／结论 |
|---|---|---|---|
| OPENCODE-001 | v2 **拆分运行时包**，不是旧版原路径的小改动 | v1 `packages/opencode/src/session/prompt.ts`; v2 `packages/core/src/session/session.ts:39-48`, `packages/server/src/handlers/session.ts:35` | S；v1 原 `packages/opencode` 路径在 v2 树中不再存在；行为差异需逐项比较 |
| OPENCODE-002 | **持久化待处理输入**，用户消息 admission 与 execution 解耦，`steer`/ `queue` 可修改或取消 | `core/src/session/session.ts:118-185`, `core/src/session/inbox.ts:240-415`, `core/src/session/sql.ts:119-149` | S；先 admission 到 SQLite，再 wake；队列不是前端数组 |
| OPENCODE-003 | **持久化执行 claim** 与 terminal 同事件提交；shutdown 留 claim，主动取消释放 | `core/src/session/execution.ts:65-149`, `core/src/session/store.ts:62-72` | S；孤儿 turn 被重启 sweep 识别 |
| OPENCODE-004 | **重启恢复有界重试**；恢复子 Agent、后台 shell 也分类处理 | `core/src/session/execution/restart.ts:17-57,70-219` | S；默认每 turn 10 次 resume；at-least-once 并非外部副作用 exactly-once |
| OPENCODE-005 | **后台子代理并非只开线程**：Child Session、Job、关联父会话通知可恢复 | `core/src/tool/plugin/subagent.ts:110-260`, `core/src/session/subagent-job.ts:12-71`, `subagent-completion.ts:21-45` | S；background 立即返回 child ID，完成时 synthetic 入父会话 |
| OPENCODE-006 | **子代理继续同一 child Session**、agent/model 切换、父子归属验证、深度限制 | `core/src/tool/plugin/subagent.ts:29-46,110-209` | S；不是每次 spawn 都必须丢上下文；默认配置深度约 1 可调 |
| OPENCODE-007 | **模型输出流与并行工具 fiber**，事件在开始/结束上维护顺序；工具执行前确保持久发布 Tool.Called | `core/src/session/runner/step.ts:67-192` | S；provider streaming 与本地工具相互编排，取消时等待/清理工具 fiber |
| OPENCODE-008 | **可解释的重试策略**：退避、上游 Retry-After、timeout 子预算、插件 hook 可调整 | `core/src/session/runner/retry.ts:31-116` | S；10 次通用重试序列、单次间隔上限逻辑，超时最多 3 次 |
| OPENCODE-009 | **按阶段选定上下文**：agent/permissions→tools/skills/MCP/instructions→model/history | `core/src/session/context.ts:83-185` | S；cache 友好前缀顺序，禁用工具不应仍注入其技能说明 |
| OPENCODE-010 | **自动/手动/overflow 压缩** 和错误状态 | `core/src/session/compaction.ts:41-63`, `runner/step.ts:135-159` | S；provider 还未输出就 overflow 可紧接压缩；细节策略见压缩源码 |
| OPENCODE-011 | **事件投影与 token/cache/费用账目**：消息和成本合并投影 | `core/src/session/projector.ts:49-92`, `core/src/session/sql.ts:22-96`, `core/src/session/usage.ts:11-53` | S；usage 字段 input/output/reasoning/cache read/write 与 cost |
| OPENCODE-012 | **动态插件生命周期监督**（本地目录/npm、安装、失败/阻止、热变更、版本更新） | `core/src/config/plugin/source.ts:20-160`, `core/src/plugin/module.ts:73-150`, `supervisor.ts:150-245` | S；加载后由 registry 重新激活，配置源/文件变更触发 |
| OPENCODE-013 | **插件可跨能力扩展**：agent/command/tool/provider/MCP/skill/permission/event/RPC/worktree 等 Effect/Preset Promise API | `packages/plugin/src/effect/*`, `packages/plugin/src/promise/*`, `core/src/plugin/host.ts:99-130` | S 仅接口存在；特定扩展实际可用还要逐插件验证 |
| OPENCODE-014 | **Desktop 管理独立 CLI server**：选择随包 CLI、service ensure、复用早期探测连接 | `desktop/src/main/service/desktop-cli.ts:20-110`, `background-service.ts:24-102` | S；Electron 主进程不是 Agent 主引擎 |
| OPENCODE-015 | **Electron MessagePort / Effect RPC**，连接及渲染器销毁时解绑；HTTP server另有事件流 | `desktop/src/main/ipc-transport.ts:1-122`, `server/src/event-feed.ts:1-91` | S；不要混淆本地窗口 IPC 与 Agent API |
| OPENCODE-016 | **按 server / location 订阅与重连同步**；独立 request queue / 状态实例 | `app/src/runtime/server/client.tsx:1-124`, `server-sync/connection.ts:1-30` | S；UI 支持 sidecar/extension 等不同 server连接；具体同步冲突策略部分未追到底 |
| OPENCODE-017 | **服务端会话输入队列 UI**：编辑/撤回/重排带服务器回执，避免原条目先被删 | `app/src/session/composer/queue.ts:30-109` | S；优先 admit replacement，再 cancel original；并发变化能报冲突 |
| OPENCODE-018 | **Code Mode JS 工具编排**：多工具并行 JS、进度、文件输出 | `core/src/codemode/tool.ts:1-126`; `packages/codemode/*` | S；Code Mode 是独立受控运行时，不是普通 shell 工具；权限和依赖独立 |
| OPENCODE-019 | **时间线虚拟化与进程任务定位**，远距定位指定 tool/shell，交互展开并确保尺寸测量 | `app/src/session/timeline/virtualizer.tsx:93-426`, `message-timeline.tsx:30-70` | S；性能/交互工程实际在 UI 代码，真实帧率 U |

## 不能因源码路径或注释直接认定
- Windows EXE 内真正装入这些模块/使用 v2 服务、完整内置 CLI 版本是否和 npm 2.0.32 字节一致：U。
- 真实 UI 菜单、所有隐藏命令/实验路由遍历覆盖率和快捷键的平台差异：U（本次仅抽样）。
- 服务在突然断电、强杀、数据库锁竞争、断网恢复下的动态效果：U。特别是重启恢复为 **at-least-once**，不能许诺副作用不重放。
- 各 provider 真实 retry/error 场景、所有社区插件兼容性：U。不能把扩展 API 存在等同插件功能完成。

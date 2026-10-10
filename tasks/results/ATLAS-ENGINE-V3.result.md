# Atlas ENGINE-V3 交付结果

日期：2026-10-11（Asia/Hong_Kong）

分支：`engine-v3`
实现提交 SHA：`ef4ca1f6c105c149772559abe1918ffeb90fdb6f`

## 上游固定版本

| 上游 | 固定 HEAD |
|---|---|
| OpenAI Codex | `6c0c6759d0617d7670826b61aca0a931bbb6db1f` |
| ZCode | `aac4755666d09fdcd70272fcf063c077a639015f` |
| DeepSeek Harness | `d743267388641bc76f17c45ce8b4c231aed1d32c` |
| OpenHands SDK | `c4b93299cf2b31c8b5d0b2c5a89965ccc5ff24f9` |
| OpenCode | `7b3d4ce3a7dbd2a6d3637722a0d5f22a7d086937` |
| Aider | `5dc9490bb35f9729ef2c95d00a19ccd30c26339c` |
| Claude Code 文档行为 | v2.1.296 文档快照（闭源，无源码 SHA） |

逐目录对照结果、Atlas 原行为、已补差异与有意不移植项见 [`docs/engine/GAPS.md`](../../docs/engine/GAPS.md)。

## 各部件完成情况

1. **Turn loop / state**：补充明确的模型等待、工具排队和结果聚合状态；收集按 attempt/index 区分的文本、推理、拒答和工具调用分片；完善中断、插话、工具审批、部分结果修复、Stop/PreCompact/PostToolBatch hook 和一次性上下文超限压缩闭环。保持原有公开事件字典。未把内部推理/工具分片变成 wire 事件；`defer` 因 Atlas 没有持久化挂起/恢复接口而返回 denied。详见 GAPS §1。
2. **Model calls**：补全错误类别、Retry-After/复位时间、一般和 529 退避、断流/连接重试、Claude retry/watchdog 环境配置、attempt telemetry 与 reasoning/refusal/tool delta。保留 Chat Completions 路由，不移植 Codex Responses/WebSocket 与 credential refresh。详见 GAPS §2。
3. **Tool orchestration**：标准化错误/畸形调用结果，取消时为每个调用保留结果，避免开始未排队调用，并只并行调度经核实的只读工具。保留现有 dispatch、审批、重试和输出契约。详见 GAPS §3。
4. **Process execution**：补充 ZCode 默认 120 秒/600 秒上限、显式 timeout、detached 与取消结果语义，以及进程交互锁。未增加跨 run 的持久后台任务接管，也未改变 Windows 原生进程管理边界。详见 GAPS §4。
5. **Context compaction**：调整默认预算公式，补充 microcompact、摘要保留规则及兼容的 `force` 参数；Atlas copy-on-success 和连续失败熔断保留。未移植 provider 专属缓存、远端历史截断或 ZCode 非流式 fallback。详见 GAPS §5。
6. **Prompt construction**：补充祖先/项目 AGENTS 与 Claude memory 文件发现、大小上限、override 合并及可选动态环境段。未引入 Claude imports/managed policy、子 agent 动态加载或 ZCode 日期段。详见 GAPS §6。
7. **Edit / patch**：补充 patch 错误提示、目标替换的快照校验及 OpenCode 标点/空格匹配；保留 Atlas 的唯一匹配、编码/BOM/换行保护、路径授权和原子写入。详见 GAPS §7。
8. **Plan mode**：无显式规划设置时继承活动模型并使用 Medium reasoning；保留当前只读白名单。Terminal 参数级安全守卫未接通前不放宽执行权限。详见 GAPS §8。
9. **Subagents / workflow**：工作流节点 metadata 和 changed-files 进入快照/事件/结果，取消和提前退出会 drain 活动节点；重试缺省交给 model-call 的环境/默认策略。未添加需要共享 loop task-control port 的 Codex 后台 spawn/send/wait/interrupt API。详见 GAPS §9。
10. **Repair / stuck / hooks**：按“是否已开始”区分 dangling tool call 安全重试与未知副作用；重复错误需 action 和 observation 都相同。补充 Claude/Codex hook decision、改写、反馈、审批及 kernel/legacy alias 去重接线。没有 Atlas 生命周期调用点的 hook 事件仍只有声明，不会伪造触发。详见 GAPS §10。
11. **Rewind / repomap**：保留 Atlas byte-snapshot rewind 契约；为运行时支持的 8 种语言补 Aider legacy query，并保留无语法查询文件的路径可见性。未移植 OpenCode Git-only snapshot/event stages；不支持的 Julia、QL、csharp 命名查询不加载。详见 GAPS §11。

## 验证

- **后端启动：通过。** 从 `D:\atlas-engine4` 启动隔离后端，显式设 `ATLAS_UPSTREAM_AUTO=0`，`GET /openapi.json` 返回 HTTP 200。隔离 `ATLAS_DATA_DIR`、`MEMORYOS_DATA_ROOT`、`MEMORYOS_DB_PATH`、`HERMES_HOME`；完成后停止进程并删除临时数据根。
- **真实模型消息：通过。** 使用真实 Atlas `run.start` → `/ws/chat` 流程，型号 `deepseek-v4.1-flash`，普通输入“你好，请用一句简短中文回复。”收到 `run.completed` 及完整 assistant 回复：“你好，我是 Atlas，有什么可以帮你？”为匹配用户现有网关与型号，本次只在可删除的 smoke 数据根中登记该自定义 catalog alias；没有修改 `D:\Atlas` 配置或代码。预检发现内置 `deepseek-v3` 型号被网关账号拒绝（404 model_not_found），最终请求使用原设置选定的型号 alias 成功。
- **前端构建：通过。** `npm --prefix frontend run build` 退出码 0；TypeScript、preload 和 Vite production build 均成功。
- **测试：未编写或运行测试，也未运行测试套件。** `git diff --check` 通过。
- **工作目录：** 实现只在 `D:\atlas-engine4` 工作树内；`D:\Atlas` 中原有文件保持未修改。

## SHA 说明

最终代码实现 SHA 为 `ef4ca1f6c105c149772559abe1918ffeb90fdb6f`。该 SHA 含 11 个部件改动、GAPS 清单和来源通知；本结果文件随后作为单独的交付记录提交。推送后的 `engine-v3` 分支 tip 由总控在最终回报中另行给出。未推送 `memory-v1` 或 `track-upstream`。

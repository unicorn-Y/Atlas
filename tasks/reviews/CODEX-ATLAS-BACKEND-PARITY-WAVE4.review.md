# CODEX-ATLAS-BACKEND-PARITY-WAVE4 — Review

VERDICT: ACCEPTED（有修复，见下）
REVIEWER: Claude（前端接入 + 实测）

## 验证

- 后端全量：笔记本上 626 passed, 6 skipped（Codex 那边没跑完是环境问题，不是代码问题）。修复后重跑见提交说明。
- 实机（开发版 + 无头 Edge）：Word/Excel/PPT 生成与预览 ✅；文件历史版本 ✅；`run_checks` 测试结果卡片 ✅；运行方式菜单 ✅。
- 未实测：Docker（本机 Docker 服务未运行）；外部 Agent 与并行 Worker（用户决定先跳过，见下）。

## 审阅中修掉的问题

1. **外部 Agent 回复事件名不对**：发 `reply.delta` / `reply.completed`，前端只认 `message.delta` / `message.completed`，回复不显示。任务书写错的名字，已统一为 Atlas 自己的事件。
2. **外部 Agent 的回复没写进会话记录**，刷新后消失。已保存（metadata 带 `executor`）。
3. **`ask_writes` 可以启动外部 Agent**：ACP 权限请求在 `runtime/backends.py` 自动批准，等于绕过「改前问我」。现在只有 `full_access` 能启动外部 Agent；补测试 `test_external_agent_refused_unless_full_access`。
4. **`ask_writes` 漏了几类会动文件的工具**：`run_checks`（跑项目脚本）、`execute_code`、`delegate_task`、`delegate_parallel` 加入先问名单。（`read_only` 是白名单，本来就拦住了。）
5. **历史版本的 `checkpoint_id` 直接拼进路径**：加格式校验（uuid hex）。
6. **委派固定选 Hermes，不看有没有装**：没装时 Worker 报 `WinError 2`。现在按已安装的外部 Agent 选（优先 Hermes），一个都没有时整组直接给中文说明。

## 已知问题 / 下一波

- **外部 Agent 认证**（用户决定先跳过）：Claude Code 走 `@agentclientprotocol/claude-agent-acp` 时返回 `Authentication required`；ACP 的 `authenticate` 没处理，错误也是英文。另外可用性检查查的是 `claude` / `codex` 命令，实际执行却是 `npx` 拉 ACP 适配器（需要网络），两者不一致。
- **子任务 Worker 应该默认用 Atlas 自己**（同模型、同工具、受同样的权限模式约束），外部 Agent 作为可选项。现在没装外部 Agent 的机器上 `delegate_task` / `delegate_parallel` 完全不可用。
- Docker 命令超时只杀掉了 `docker exec` 客户端，容器里的进程还在跑（run 结束删容器时才停）。
- 二进制 Office 文件的改动统计显示为几百行增加，没意义；二进制文件应只计文件数。

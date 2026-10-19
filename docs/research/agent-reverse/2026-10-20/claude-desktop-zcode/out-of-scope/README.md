# OUT-OF-SCOPE — 运行时取证（已按 2026-10-20 任务书修订降级）

> 任务书修订（commit `3e2b27b9`）明确：**禁止启动软件、截图、点 UI、尝试登录、连接 API、使用账号**。
> P7 由“真实运行时取证”改为“纯静态运行机制还原”。
> 本目录内容是在收到该修订前采集的运行证据，**不计入完成率**，仅作归档留痕。

## 归档内容

| 文件 | 说明 |
|---|---|
| `main.log` | 首次启动的 main 进程日志（21,792 B） |
| `cowork_vm_node.log` | VM bundle 支持性检查 |
| `mcp.log` | 空（未初始化用户 MCP） |
| `ssh.log` | SSH 管理器初始化 |
| `claude.ai-web.log` | 主 webview 远程资源加载 |
| `config.json` / `claude_desktop_config.json` | 首次启动写出的配置 |
| `proctree.json` | 6 进程树 |
| `run03/` | 第三次取证的全部同名文件 |

## 为什么保留而不是删除

1. 任务书要求“发现什么就登记什么，不能删除、隐匿”。
2. 它们可以作为静态结论的**旁证**（例如主 UI 由 claude.ai 加载，这在 `main_window/index.html` 的源码注释里已有静态证据，日志只是补充）。
3. 但**它们不能作为验收分子**，也不能被写成 R 级完成度。

## 对报告正文的影响

- `P7-STATIC-LIFECYCLE.md` 取代 `P7-RUNTIME-EVIDENCE.md` 成为正式 P7 交付物。
- `P7-RUNTIME-EVIDENCE.md` 已移入本目录，其结论在正文中若被引用，一律标注为“旁证（OUT-OF-SCOPE）”。
- `P4-AGENT-RUNTIME.md` 中凡标注 `R` 的条目已复核：其结论均有静态锚点（S），运行日志只是同一事实的另一表现形式，不改变证据等级归属。

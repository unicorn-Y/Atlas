# WAVE 2：给 PARTIAL 补最后一公里

## 上一轮的真实教训

**W5 原话**：「三行所需的生产接入点分别位于 kernel loop、agent 图片输入和 local execution 工具。
只增加 state 层孤立 API 无法形成端到端行为，因此**没有添加无调用方实现**。」

这是**正确判断**，但代价是那 3 条只能标 PARTIAL。
**WAVE 2 的核心改变：一个 worker 拥有「能力跨的所有目录」，而不是只拥有一个目录。**

## 模型通道（上一轮失败的主因，必须修）

上一轮 worker 用 `-m gpt-6-luna`，真实模型回合普遍失败。本轮**统一用 Atlas 自己的通道**：

- 模型：`deepseek-v4.1-flash`
- base_url：`https://d1api.xin/v1`
- 代理：Clash `http://127.0.0.1:7897`（**必须在启动后端的 shell 里设 `http_proxy`**）
- key：已在 Windows 凭据库，无需环境变量

验证命令（每个 worker 必须跑通这条才算有证据）：
```bash
cd core
http_proxy=http://127.0.0.1:7897 https_proxy=http://127.0.0.1:7897 \
  python -m uvicorn atlas.server:app --port <你的端口>
python scripts/dsh_live_ws_check.py <你的端口> "Reply with exactly the word: OK"
```
**期望输出**：`[terminal] run.completed` + `[reply] 'OK'`

上一轮我已亲自验证这条通道可用（`MERGED`、带工具回合都成功）。

## PARTIAL 清单与补法

按「缺什么」分类，不按目录：

### P1 — 缺真实模型证据（代码可能已够）
| row | 批次 | 缺什么 | 补法 |
|---|---|---|---|
| E2 | W1 | 真实模型回合 | 用上述通道跑通即可，代码已在 |
| E19 | W1 | 同上 | 同上 |
| E25 | W1 | 生产运行时没有 maintenance 调用点 | 在 `run_drive` 的 run 结束后接一次 |
| E14 | W7 | Docker Engine 不可用；Windows host 无 per-call 隔离 | Docker 部分用假设测试证明；host 部分如实标 HARD |
| E18 | W7 | 真实模型未到达 approval | 用上述通道跑一次触发审批的回合 |

### P2 — 缺跨目录接线（需要跨目录所有权）
| row | 缺什么 | 要改的文件 |
|---|---|---|
| S4 | reader-side repair closer | `engine/state/` + `engine/kernel/loop.py` |
| S19 | durable image attachment | `engine/state/` + `agent/__init__.py` + `api/run_drive.py` |
| S21 | session-scoped fs observation | `engine/state/` + `tools/local_execution.py` |
| E3 | post_execute 三瀑布接线 | `engine/kernel/tools.py` + `engine/kernel/loop.py` |
| E4 | 逐工具 output schema + UI 消费 | `engine/tools/registry.py` + `agent/tool_catalog.py` |
| E8 | step 边界压缩 | `engine/kernel/loop.py` + `context.py` |
| S9 | 遮蔽替换 resume 重放 | `engine/kernel/context.py` + `engine/state/` |
| S25 | token 计价生产接线 | `engine/agent/token_meter.py` + `engine/kernel/loop.py` |
| X2 | async MCP lifecycle disposer | `plugins/runtime.py` + `tools/mcp_client.py` |
| X4 | profile/bundle 持久化 + dump CLI | `plugins/` + `cli.py` |
| X8 | preset isolate realm 接入 run setup | `plugins/` + `agent/` |
| X9 | ACP 入口接 preset | `tools/app_server.py` + `automation/` |
| X22 | MCP liveness 真实服务器验证 | `tools/mcp_client.py` |
| D13 | `present` 工具注册 | `engine/tools/registry.py` + `agent/tool_catalog.py` + `frontend/` |

### P3 — 前端（换验收方式，不用真实模型）
| row | 缺什么 | 验收方式 |
|---|---|---|
| D1 | OS 分配端口 + boot injection | vitest + 主进程单元测试 |
| D2 | typed host IPC lifecycle | 同上 |
| D3 | 压缩重连重放 | vitest |
| D4 | 扩展注册卸载 | vitest（已有 2 项） |
| D5 | 附件发送端到端 | vitest + IndexedDB mock |
| D6 | 草稿 UI 重载 | vitest |
| D7 | 首帧 baseline + page() | vitest + adapter 测试 |
| D8 | 递归 split tree + 拖动浮动 | vitest + 组件测试 |
| D10 | 强制版本策略 | vitest |
| D17 | 7.7k 全局串迁移 | 分批迁移 + vitest |

**P3 的 CLOSED 标准改为**：vitest 全通过 + TypeScript 检查 0 错误 + 组件测试覆盖该行为。**不要求真实模型。**

## 硬规则（同前，全部适用）

- 不重写 `messages` 表语义
- 不在 `_execute_write` 回调里再调 `_execute_write`（死锁）
- 事件名三处真源同步
- 新 router 进 `application.py` tuple；新 service 进 `AppServices` + lifespan
- 测试需 `@pytest.mark.unit` / `integration`
- 不许写「已实现」而不贴输出
- **一个 worker 拥有该能力跨的所有目录**（这是本轮与上轮的核心区别）

## 批次划分（按能力，不按目录）

- **V1**: E2, E19, E25 —— kernel 生命周期收尾
- **V2**: E3, E4 —— 工具契约接线
- **V3**: E8, S9, S25 —— 上下文与 token
- **V4**: S4, S19, S21 —— 状态层跨目录接线
- **V5**: X2, X4, X8, X9 —— 插件与外部入口
- **V6**: X22, D13 —— MCP 实测 + present 工具
- **V7**: E14, E18 —— 沙箱（Docker 可测部分）
- **V8**: D1, D2, D3, D7 —— 桌面连接与端口
- **V9**: D4, D5, D6 —— 渲染与输入
- **V10**: D8, D10, D17 —— 布局、更新、i18n

## 端口分配
V1=8841 V2=8842 V3=8843 V4=8844 V5=8845 V6=8846 V7=8847
（V8-V10 是前端，不需要端口）

# FEATURE-F1 D 区交付记录：工具

日期：2026-10-11 · 分支：`f1-d`（基于 `origin/memory-v1` `ce71ee9`）

## 经过
Codex（GPT-6 Luna）做了清单和大部分实现后额度用完；用户的 Hermes 接手继续，后因并发限制停在未提交状态；Claude 收尾：把工作树成果原样提交、自动修复简单 lint、核对清单、启动验证、写本记录并推送。

## 交付内容
- 清单：`docs/parity/F1-D.md`（116 行，对照 Codex `codex-rs/core/src/tools/handlers/`、Claude Code 官方工具文档、ZCode `apps/zcode-cli/packages/core/src/tool/` 与 `packages/zcode-cua`、OpenCode `packages/core/src/tool/plugin/`，以及四家功能矩阵 V5 的 D1–D5 与附录 VIII-C/K/L）；跨区条目在 `docs/parity/F1-unassigned.md`。
- 新增工具模块（`core/atlas/tools/`）：`app_server.py`（无头 JSON-RPC 入口，对应 codex exec / claude -p / app-server）、`browser_use_compat.py`（标签页与导航）、`claude_tasks.py`（TaskCreate/Get/List/Update）、`git_platform.py`（PR 创建与评论）、`local_image.py`、`media_generation_search.py`（图片生成/编辑、X 搜索、视频生成/分析、TTS、音乐、安全扫描——均走真实提供商接口，缺凭据时明确报错）、`mobile_simulator.py`（Android 模拟器全套）、`notebook_edit.py`、`plugin_marketplace.py`、`workspace_lsp.py`、`workspace_queries.py`、`workspace_workflows.py`。
- 修改：`kernel/tools.py`（注册上述工具，新内核共 81 个内置工具 schema）、`kernel/loop.py`、`kernel/plan.py`、`tools/mcp_client.py`（新增 Streamable HTTP 传输与可展开环境变量的请求头）、`tools/web.py`、`cli.py`、`server.py`。

## 有意未做（详见清单）
- 浏览器：桌面面板内预览与「停止加载」；网络/trace/CPU/heap/Lighthouse 不另做内置工具，网络与性能 trace 走默认启用的 chrome-devtools MCP。
- MCP：OAuth 授权/刷新流程（目前支持 header 与环境变量 Bearer token）。
- Workflow：命名工作流脚本保存（Atlas 没有命名 workflow 定义注册表）。
- iOS 模拟器（Windows 主机不适用）。

## 验证
- `compileall` 通过；新增/修改文件的可自动修复 lint 已修。
- 后端：主机测试环境检出本分支，`ATLAS_UPSTREAM_AUTO=0` 启动，9 秒 `/api/health` = ok，全部组件 ready，启动日志无错误；`kernel_tool_schemas(include_workflow=True)` 返回 81 个工具。
- 前端：本区未改前端，构建沿用 memory-v1。
- 未编写、未运行测试套件（用户要求）。

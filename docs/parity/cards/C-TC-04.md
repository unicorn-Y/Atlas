# C-TC-04｜MCP、插件宿主、Hooks 与命令注册

## 逐项结果

- **C016｜部分完成。** MCP 设置 API/UI 增加 SSE 与 Streamable HTTP 请求头、脱敏凭据状态、重连、启停和连接认证诊断。MCP server 可配置逐工具 allowlist，并在工具暴露和调用时双重检查。未实现 OAuth/PKCE、回调、token 持久化和续签：Atlas 当前没有授权窗口及完整授权生命周期；OAuth 留在 HTTP 401/403 的诊断提示中，不显示假授权按钮。
- **C017｜部分完成。** MCP server 的 enabled 状态、`auto_start`、工具 allowlist 已形成配置到运行时的闭环；已有 Agent `tool_allow/tool_deny` 规则继续叠加。未实现 MCP server 的 User/Workspace/Project/Agent scope 选择：MCP 配置当前由共享连接客户端读取，运行时没有请求级 workspace/project/agent 身份解析链路。
- **C019｜部分完成。** 插件 Marketplace 支持来源增删改查、catalog JSON 只读校验、插件引用保护、安装/更新和错误诊断。校验读取已注册本地 catalog，不下载远端插件源码或验证签名。未实现任意插件配置表单：PluginRuntime 没有 `userConfig` schema 的消费和配置值注入接口，面板说明了这一能力缺口。
- **C020｜部分完成。** 插件 User 级启停覆盖及恢复 manifest 默认值可用；扩展来源 API/UI 对 workspace/project 显示能力边界并拒绝保存。未实现 Workspace/Project 扩展覆盖：设置 API 没有活动工作区身份，插件运行时是进程共享，不能按会话安全隔离或覆盖。
- **C022｜已完成（声明式宿主范围）。** 新增 enabled plugin `atlasHost` 注册 API，支持声明式 settings pages、menu items、slash aliases、palette entries 和 keybinds；Slash 与 palette 读取同一 Atlas 命令集合。宿主只渲染内建受限控件，不执行插件 JavaScript。
- **C023｜部分完成。** 插件设置页支持受限 widgets 及本机持久状态；声明式按钮可在确认后调用 manifest 明确列出的 MCP tool，后端重新核验插件启用状态和声明，MCP server allowlist 再做运行时授权，调用结果回到界面。未支持任意插件 React UI、任意 Atlas service API 或插件自定义脚本，以免把插件目录 metadata 扩成无隔离的代码执行面。
- **C027｜部分完成。** Hook 新增/编辑/试跑支持 command、HTTP JSON handler 和已连接 MCP tool handler；提供 `atlas.hooks/v1` 导入导出，新建/导入默认为 disabled。生命周期仍只有 Atlas 既有五种事件；HTTP/MCP `tool.before` 失败会阻止工具。未新增 prompt/agent handler 或更多实际生命周期触发点。
- **C028｜已完成（当前 Hook 范围）。** Hook review 按 User/Workspace 分开记录，审查与准确的 Hook 配置指纹绑定；未审查或配置变更后的 Hook 在执行与试跑时失败关闭。UI 显示策略来源并允许逐条审查/撤销。策略只覆盖 Atlas 当前可运行的 Hook 来源和事件。
- **C031｜部分完成。** Slash 命令、命令面板、插件声明式 palette/menu/keybind 共享已注册 Atlas 命令。Atlas palette 现展示同一命令集合，插件快捷键只可调度已注册命令。任意插件代码型命令执行仍不开放。
- **C068｜已完成。** 工具设置中增加 Computer Use 授权状态和撤销入口；重新授权需用户确认，后端持久化为现有 `computer_use.permission_mode`（`full_access`/`deny`），继续使用实际执行器已有权限判断。

## 上游与声明

本次依据 Atlas 实际 runtime/API 补齐行为，以声明式数据契约实现宿主，不复制上游源文件；因此没有新增 `// Ported from ...` 文件头，也没有修改 `THIRD_PARTY_NOTICES.md`。开源与闭源参考边界按本文件各条列出的实际未实现能力保留。

## 验收

- `npm --prefix frontend run build`：通过。Vite 输出既有的大 chunk/deprecation 警告。
- 后端使用 Python 3.14、`ATLAS_UPSTREAM_AUTO=0` 启动，且所有 `/api/health` 组件为 `ready`、`status=ok`：通过；关闭服务后确认工作树服务器已停止。该机器的 Hermes bootstrap 会试图在导入时重启整个 Uvicorn 命令，因此本地验收另设 `HERMES_DISABLE_LAZY_INSTALLS=1`，避免依赖自动安装副作用；`PYTHONPATH` 指向本机 Hermes 源目录。
- 按要求未写或运行测试。

## 提交

- 实现提交号：`8046c93d722cbf67d43b3dcc40924a589967e733`。

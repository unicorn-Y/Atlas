# B-TC-04：Changes：Diff、评注与审批

基线：`origin/memory-v1`（`e9be4b4b176eae332c82cd124ec669b4b7612969`）  
分支：`card-b-tc-04`

## 上游核查

- ZCode：`aac4755666d09fdcd70272fcf063c077a639015c`，核对 `PermissionDialog.tsx`、`WorkflowPermissionBlock.tsx` 与 `diff-viewer.tsx`（Apache-2.0）。
- OpenCode：`7d2618637fc37c9fe157f66939d3fcaf8c6023d8`，核对 `session-review-v2.tsx`、`session-review-file-preview-v2.tsx`（MIT）。
- Codex：核对权限、Code Review、Auto Review 和 changelog 文档；Auto Review 是独立审批 reviewer。
- Claude Code：核对 permission modes 与 Desktop 文档，参考权限模式、多行评注和 finding 处理交互。

## 逐项结果

- **B025 Approval 权限范围、一次/始终允许、拒绝理由 — 已完成（范围严格限定）。** 审批卡展示操作和服务端提供的权限范围，支持允许一次、条件允许时始终允许、填写拒绝理由；Alt+1/2/3 快捷键避开输入框和中文输入法组合输入。后端把“始终允许”存入独立 `approval-permissions.json`，按规范化工作区、工具、资源和请求参数指纹精确匹配；临时运行或没有稳定工作区时不提供该选择。拒绝理由写入审批响应事件和工具结果；旧 `allow` 协议仍兼容。
- **B055 Diff 逐文件查看与行级 review — 已完成。** Changes 面板提供当前文件/总数、待审 hunk 数、逐文件预览与前后导航，可在默认编辑器打开工作区文件；行评注仍可集中提交，hunk 接受/拒绝沿用既有接口。
- **B076 OpenCode V2 Review 会话概览和文件预览 — 部分完成。** 增加改动概览、选中文件预览和文件导航；Review findings 卡增加严重级汇总及逐条导航。Atlas 当前 Review 仍属于运行/对话内的审查结果，没有可独立承载 OpenCode V2 Review 会话的持久会话模型，因此未伪造独立会话布局或会话数据。
- **B093 Codex 合并审查提示与快捷导航 — 已完成。** 现有 branch review 以 merge-base 计算差异；审查发现卡显示严重级计数、逐条位置和导航状态，支持 Alt+↑/↓。Diff 评论提交和导航快捷键忽略 IME composing / keyCode 229，避免中文输入法确认键误触。
- **B102 Claude Desktop 多行 Diff 评论一次提交 — 已完成。** 跨文件行级评注保留在同一草稿列表，一次性提交为一条对话消息；提交成功后清空草稿，失败时保留草稿并显示错误。评论输入支持 Ctrl/Meta+Enter、Escape，并恢复评论行焦点；IME composing 时不触发快捷键。
- **B103 Claude Desktop Code Review Fix/Dismiss/Apply fixes — 部分完成。** 每条 finding 支持 Fix（将该条修复请求发给 Atlas）、Dismiss/恢复查看，Apply fixes 将所有未忽略 finding 一次发回；仅在消息提交成功后标记已提交，失败显示错误并允许重试。Dismiss 状态是当前卡片会话内的 UI 状态，不持久化为独立审查决定。
- **B123 Codex Desktop Auto Review 审查结果/权限 UI — 部分完成。** `/auto-review` 入口明确标为 `/review` 兼容入口；没有添加假策略、假授权或伪造结果。Codex Auto Review 对沙箱边界审批使用独立 reviewer，并返回决策/理由；Atlas 当前仅有代码审查 reviewer，没有独立 Auto Review 策略、触发与授权配置，不能安全地把代码审查结果当作审批授权结果。

实现仅采用上游公开交互行为并使用 Atlas 现有组件实现，未复制 ZCode/OpenCode 源码；因此没有新增移植源码头或第三方声明。

## 验证

- `npm --prefix frontend run build`：通过（TypeScript、Electron/Preload 检查及 Vite 生产构建）。构建输出包含既有弃用提示和 chunk size 警告。
- 后端在 Python 3.14 下可启动并响应 `/api/health`，但状态为 `starting` 而非要求的 `ok`：当前验证环境缺少 `hermes_constants`，使 `engine_registrations` 失败；`/review` 扩展注册随之失败。默认 `python` 指向 Python 3.11，启动时另缺 `tomli_w`。服务已停止；未更改健康状态或绕过启动失败。
- 未编写或运行测试套件。

## 提交

- 实现提交：`f418810dfbea28d1a5d0439ed9525b2d0c8ff15b`。
- 本结果文档与推送提交号：以随卡分支提交记录为准。

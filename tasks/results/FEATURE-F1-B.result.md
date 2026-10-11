# FEATURE-F1 B 区交付记录：对话界面

日期：2026-10-11
工作树：`D:\atlas-f1-b`
分支：`f1-b`（基于 `origin/memory-v1`，不会推送 `memory-v1`）
最终提交 SHA：由交付回复提供。

## 实现

- 在 `docs/parity/F1-B.md` 记录 B 区功能、来源、Atlas 现状和本次处理；依据 V5 主表及附录 VI–IX 修正主表误标，并补入矩阵漏项。ZCode 固定提交为 `aac4755666d09fdcd70272fcf063c077a639015f`，OpenCode 固定提交为 `7b3d4ce3a7dbd2a6d3637722a0d5f22a7d086937`。可移植实现标注来源文件头并更新 `THIRD_PARTY_NOTICES.md`。
- 对话交互包含会话内搜索和命中导航、消息复制/编辑重发/重试/分叉、生成停止、文件外部打开、提示词增强、`/goal` `/recap` `/raw` `/ide` `/auto-review` 对应操作、屏幕阅读开关及键盘帮助。
- 对话辅助面板包含浏览器多标签、文件搜索/预览及多文件标签、每会话独立多终端、diff 搜索、PR 信息呈现和活动/推理事件展示；另外增加白板 PNG 附件、Markdown 表格 CSV 导出、时间线显示控制和失败工具事件的真实字段复制。
- 后端为提示词增强、Dashboard 和 diff hunk review 增加接口。`/auto-review` 明确映射到 Atlas `/review`；不伪称拥有 Codex Auto Review 策略 UI。

## 验证

- `npm --prefix frontend run build`：通过，退出码 0。构建有既存的 npm 配置、Vite 选项弃用及大 chunk 警告。
- 后端：在隔离数据目录、隔离 `HERMES_HOME` 且 `ATLAS_UPSTREAM_AUTO=0` 的环境中启动；`/api/health` 返回 `status=ok`，全部组件 ready，`component_errors={}`。
- 后端启动日志另有 `startup.engine_warmup_failed`：`ModuleNotFoundError: No module named 'agent.agent_hooks'`。服务仍启动并通过上述健康检查；该引擎模块缺失未在 B 区范围内修改。
- 网页 UI 冒烟：Vite + 隔离 headless Chrome 可打开；未观察到页面异常或控制台错误。实际打开了快捷键帮助、屏幕阅读开关、白板、会话搜索、Inspector 及 slash-command 建议。网页版的浏览器面板正确显示“需 Atlas 桌面应用”。
- 单独的 Electron 开发态冒烟启动出现标题为 `Error` 的窗口，CDP 未能连接；因此不将桌面 BrowserPanel 多标签的 Electron 运行态标记为已验证。
- 按要求未编写或运行任何测试，也未运行测试套件。

## 尚未闭合的 B 区能力

以下项在清单中按部分支持/未实现标注，不能作为完成能力宣称：

- Browser 站点/设备权限卡片：Electron IPC 尚无权限请求与决策结果接口。
- 原生 kernel 的完整模型请求/响应轨迹：目前没有持久化并发送到 UI 的对应事件；只呈现实际收到的 `run.status` 推理文本及现有调用事件。
- OpenCode `session.background` 专属挂起/重新接回 UI：Atlas 暂无同等会话状态/重连接口；集成终端和后台 Shell 不等同。
- PR 评论变更、推送范围选择、GenUI/插件自定义面板、CI 自动修复等：缺少相应授权 API 或属于其他区域依赖，界面没有伪造操作。
- PPTX 当前只有静态 HTML 预览，不含页码/缩略图/缩放/元素选择/导出。
- Claude 官方 settings-reference 的全部键未能逐键列举；B 区文档及 2026-07-11 至 2026-10-11 的公开 changelog 已核对，细节见清单的来源范围说明。

## 推送

提交和 `origin/f1-b` 推送完成后，由最终交付回复列出远端 SHA。不会推送 `memory-v1`。`D:\Atlas` 活跃工作树及其原有未跟踪内容保持不变。

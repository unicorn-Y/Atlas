# B-TC-05｜Composer：模型、附件与上下文

结果：按代码现状逐项核对；可复用的 Atlas API 能力继续由真实能力驱动，缺少服务端能力的选项不做空壳。

- **B027｜部分完成。** `Composer` 已有真实模型选择、act/plan 模式、按所选模型 `supports_reasoning_effort` 显示的推理档位；运行事件提供上下文 token 与窗口上限时显示用量。各 Provider 暴露的模型参数并不相同，未暴露的上游切换项没有伪造。模型 API 扩展后才能逐 Provider 补齐。
- **B028｜已实现本卡缺口。** 图片/文件选择、剪贴板粘贴、操作系统文件拖放、DrawingPad、预览/移除已有。新增文件读取进度、保留读取失败的 `File` 并提供重试。Atlas 当前没有独立附件上传 API：读取后的 base64 随 `run.start` 传输，所以进度准确表示本地读取，不显示虚假的网络上传百分比。
- **B030｜部分完成。** `@` 工作区文件和 `#` 其他会话候选按当前 Atlas 会话查询，引用由 `context_files` / `context_conversations` 随 run 请求发送；会话引用最多三条。当前文件树没有向 Composer 投递路径引用的拖放数据协议，因此未将文件拖放误报成已支持的引用。
- **B031｜已实现。** 选择器中的 `$skill` 仍显示消息文本 token；发送时按 Atlas 已登记技能名解析为独立 `message_skills` 字段，后端仅在该次 run 合并并通过既有 Skill 授权/解析流程，不写入全局 active Skills。单次运行技能数超限由后端明确拒绝。
- **B034｜未实现，原因明确。** Atlas 当前模型/Provider API 没有声明 Codex fast mode 的能力字段、请求参数或可验证映射。仅加 `/fast` 开关不能改变模型执行速度，故未添加假入口。
- **B036｜部分完成。** `/model`、`/reasoning`、Composer 模型菜单及已支持模型的推理档位均可用；推理请求只在当前模型声明支持时发送。未公开 reasoning 选项的 Provider 无法安全映射到 Atlas 档位枚举。
- **B043｜部分完成。** 新增 Composer 添加菜单的 Enter 发送偏好，持久化于本机 localStorage；关闭时 Enter 换行、Ctrl+Enter 发送。Steer / Redirect / Queue 继续使用既有持久化选择，并修复启动时只恢复 queue、丢失 redirect 的问题。该偏好仍是本机设置，没有跨设备同步。
- **B049｜部分完成。** 添加菜单提供附件入口和真实 `/goal` 命令草稿快捷项。当前 Composer slash command registry 没有可调用的 `/workflow` 入口；为避免假按钮，没有放入 Workflow 菜单项。
- **B070｜未实现，原因明确。** Atlas 插件/扩展目前没有可由 Composer 选择的资源目录、稳定资源 ID、消息级引用结构或 run 请求字段。通用插件管理/MCP 资源接口不等价于插件上下文 mention；缺少协议和可调用入口前不添加仅展示的候选项。

## 变更与验证

- 实现提交：`40cb16321f76067ddb2a24c3cfee4bf82a573063`（在刷新后的 `origin/memory-v1` 上重放）。
- `npm --prefix frontend run build`：通过。
- 隔离数据目录下启动 `python -m uvicorn atlas.server:app --port 28795`，`GET /api/health` 返回 `status: ok`；检查后已停止服务。
- 未写入或运行测试。
- ZCode 移植来源及 Apache-2.0 许可追加在 `THIRD_PARTY_NOTICES.md`。

# 主执行者补充：语音、视觉与API边界

基准：`ui-redesign@0b1ba4114e25643369c95bfac85d37563788444f`，主目录相关 tracked dirty 另行标注。仅做静态核查和只读运行信息获取；未开麦克风、发送消息或请求真实模型。

## 语音与视觉现状及后续规划

| 能力 | 入口与调用证据 | 本轮可确认范围 | 后续最小步骤（计划，不施工） |
|---|---|---|---|
| 桌面语音对话 | `frontend/src/renderer/App.tsx:63` lazy 引入 VoiceOverlay；`:530` 检查 SpeechRecognition；`components/VoiceOverlay.tsx:63` 识别，`:93` onSend；`:109` speechSynthesis | 浏览器识别与朗读的UI调用链存在；没有在当前 Electron 验证浏览器识别服务可用或实际语音识别成功 | 先在隔离窗口确认 Electron SpeechRecognition 是否可用；用现有发送链验证一次识别→请求→朗读及停止，确认需要替换的具体组件后再选本地语音引擎 |
| 独立语音演示 | `voice-demo/README.md:19` 单独启动服务，`:26` 使用 8780；`:39` 文件架构 | 独立演示存在，不等于接入 Atlas 的会话/审批/工具/记忆生命周期；README 宣称性能未本轮实测 | 若复用，先验证服务取消和音频队列行为，再决定是否接入 Atlas 的同一会话与模型选择；演示模型不得成为第二个长期记忆主体 |
| 用户图像输入 | `core/atlas/agent/__init__.py:876` 构造 image_url；`models/models_dev.py:839` 能力覆盖；`frontend/src/renderer/pages/models/ModelForm.tsx:188` 视觉能力配置 | 图像消息和能力配置路径存在；不同模型真实识图能力未验证 | 在隔离数据和显式视觉模型下验证一张本地图片输入，再验证非视觉模型的明确提示；不引入自动故障切模型 |
| 工具截图反馈 | `core/atlas/kernel/loop.py` 的 screenshot/image_url 注入路径（当前磁盘文件约1471–1479行）；`tools/x2/computer.py:219` 解读截图块 | 截图内容可构造为模型输入；当前 dirty 行号不是提交基线的稳定引用，W4 负责完整工具链证据 | 优先验证已有截图→图像消息→下一轮模型请求的可用性；屏幕持续视觉/摄像头为后续需求，未实施 |

## ROOT-001：关闭语音界面后晚到的麦克风请求未清理

- 优先级：P2；分类：代码确认；本机复现：未执行。
- 证据：`ui-redesign@0b1ba4114e25643369c95bfac85d37563788444f`，`frontend/src/renderer/components/VoiceOverlay.tsx:153–159` 在 getUserMedia 的异步 then 中赋值 stream 并新建 AudioContext；`:179–188` 的 effect 清理函数只停止当时存在的 stream/context。
- 用户症状与触发：麦克风权限/设备请求未完成时关闭语音界面；清理函数先执行，之后 Promise 成功返回，then 没有检查 effect 已卸载，新的 MediaStream/AudioContext 没有后续清理机会。
- 影响：当前分支和实际磁盘代码存在该路径；没有声称本机已观察到麦克风保持工作。
- 最小处理：effect 内维护已卸载标记；若 getUserMedia 晚返回，立即停止返回流的 tracks；只在组件仍挂载时建立 AudioContext。无需新服务或通用资源管理层。
- 复用：现有 effect cleanup、MediaStreamTrack.stop 即可；复杂度 S；本轮不施工。

## API配置边界复核

- `core/atlas/api/config_editor_router.py:61–80` 明确是主体配置文本编辑器，返回 config_text/settings_text/effective_text。源码证明它传出配置文本；本轮不读取该接口，未将旧报告“当前真的传出密钥”当成已重新复现。
- `core/atlas/origin_guard.py:42–66` 校验 token、loopback、开发 origin；文档与实现表明 `Origin:null` 本身不获信任；`api/application.py` 挂载 OriginGuard。不能仅见 CORS 列表包含 null 就断言绕过该 guard。
- 当前默认模型采用 `/api/settings/configuration`，主执行者只保留模型/来源/密钥已配置布尔值；不导出网关地址或凭据。该读取不涉及用户会话内容。
- 是否应为配置编辑器增加受控显示密钥，属于后续最小权限与用户可编辑性的产品选择；现有静态证据不足以把“本地配置编辑器会返回配置”独立判为已复现的外部泄漏。

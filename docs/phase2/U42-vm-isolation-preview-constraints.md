# U42: VM 隔离文件预览的主机约束

## 决定

U42 期间没有把现有本机 Office/PDF 预览包装成“隔离预览”。仓库当前没有可复用的 guest renderer、只读帧传输通道或 VM 生命周期管理器；当前主机又不能由本进程创建、枚举或控制 guest。缺少两端基础设施时，加入 UI 开关会让文件仍在宿主打开，形成虚假的安全边界。

## 本机复核记录

- Atlas 现有 PDF/Office 预览位于 `frontend/src/renderer/shell/panels/FilesPanel.tsx`，文档内容在宿主 Electron/renderer 内解析。
- Hyper-V `vmms` 与 `vmcompute` 服务正在运行，但 `Get-VM` 返回授权策略拒绝，当前进程无权枚举 VM。
- Windows Sandbox 可执行文件 `C:\Windows\System32\WindowsSandbox.exe` 不存在。
- Docker CLI 已安装，但 Docker Desktop Linux engine named pipe 不存在，`docker info` 无法连接 daemon。
- 因为不能枚举/启动 guest，无法验证 guest 的 Office/PDF 工具、宿主回传链路、断开行为或 VM 清理。

## 完成实现需要的组件

1. 可由 Atlas 控制的 guest provider：检查宿主功能和权限，创建一次性隔离 VM，指定只读输入卷/文件映射、网络策略、资源上限与超时，并能在关闭时销毁。
2. Guest renderer：在 guest 内解析 PDF、DOCX、XLSX；把页/缩放等只读视图状态映射给宿主。宿主只接收图像帧和导航元数据，不接收文档活动内容的可执行 DOM。
3. IPC/帧传输：鉴别请求窗口、限制帧尺寸和速率、支持 park/show/close、guest 崩溃和超时状态；关闭窗口或会话时终止 guest 并删除临时副本。
4. 明确降级矩阵：列出支持格式；不支持的格式返回原因并保留宿主原有预览作为显式用户选择，不能静默称为隔离渲染。
5. 验收：使用真实 VM 验证无网络/受限网络、只读文档、多个格式、崩溃恢复和关闭清理；检查宿主进程没有文档解析负载。

## 当前可做的安全结论

当前阻塞不是前端缺一个按钮：缺少 guest 控制权限和可以运行的隔离后端。要开始实现，需要在具备 VM 管理权限且提供可启动 Windows guest/renderer 的环境中开发和验收。现在只保留既有本机预览，且不把它标记为 VM 安全预览。

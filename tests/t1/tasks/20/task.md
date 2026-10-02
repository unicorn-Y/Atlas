# provider 故障后的恢复记录

当前 provider 请求会遇到本地测试代理注入的短暂故障，然后恢复。请正常完成当前请求；恢复后，根据只读的 `release.json`，在工作区根目录创建 `recovery.json`。

文件必须是 UTF-8 JSON，字段为：`incident_id`、`recovered`、`attempts`、`faults`、`response`。`recovered` 为 true，其余字段按发布配置记录受控故障计划；`response` 是配置中的固定恢复标记，不能填模型回复正文，`attempts` 表示注入计划达到首次成功所需的请求数。实际请求和恢复状态由代理独立验证。不要修改 `release.json`，不要用工具访问外部网络服务。

# 已搬进 Atlas 的外部代码登记

每搬一个文件（或一段逻辑）就加一行。第 12 波会用这张表自动对照上游更新。

| Atlas 文件 | 来源仓库 | 来源路径 | 来源提交 | 许可证 | 方式（依赖 / 拷贝改 / 逻辑移植） | 改了什么 | 搬入日期 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `core/atlas/tools/ssrf_transport.py` | `NousResearch/hermes-agent` | `tools/url_safety.py` | `663362680b6ffa4fbffeb58f6682564239a1953b` | MIT | 拷贝改 | 保留连接时 DNS 校验并按校验 IP 拨号，使用 Atlas 的公网地址策略 | 2026-10-01 |
| `core/atlas/agent/prompt_caching.py` | `NousResearch/hermes-agent` | `agent/prompt_caching.py` | `663362680b6ffa4fbffeb58f6682564239a1953b` | MIT | 拷贝改 | 保留缓存断点布局、TTL 和消息标记规则；按 Atlas 路由判定工具消息标记 | 2026-10-01 |
| `core/atlas/agent/prompt_cache_boundary.py` | `NousResearch/hermes-agent` | `agent/prompt_cache_boundary.py` | `663362680b6ffa4fbffeb58f6682564239a1953b` | MIT | 拷贝改 | 保留稳定前缀 LRU 注册和查找 | 2026-10-01 |
| `core/tests/test_prompt_caching.py` | `NousResearch/hermes-agent` | `tests/agent/test_prompt_caching.py` | `663362680b6ffa4fbffeb58f6682564239a1953b` | MIT | 拷贝改 | 移植缓存边界、复制语义、TTL 与代理布局测试；Atlas 专属代理规划器测试另写 | 2026-10-01 |
| `core/tests/test_prompt_cache_boundary.py` | `NousResearch/hermes-agent` | `tests/agent/test_prompt_cache_boundary.py` | `663362680b6ffa4fbffeb58f6682564239a1953b` | MIT | 拷贝改 | 移植稳定前缀查找与请求级拆分测试；未移植 Hermes 专属技能/定时任务构造器测试 | 2026-10-01 |
| `core/atlas/tools/output_limits.py` | `NousResearch/hermes-agent` | `tools/tool_output_limits.py` | `663362680b6ffa4fbffeb58f6682564239a1953b` | MIT | 拷贝改 | 使用 Atlas TOML 配置读取字节、行数和行长上限 | 2026-10-01 |
| `core/atlas/tools/output_truncate.py` | `NousResearch/hermes-agent` | `tools/tool_output_truncate.py` | `663362680b6ffa4fbffeb58f6682564239a1953b` | MIT | 拷贝改 | 保留 40/60 头尾裁剪与统一截断标记 | 2026-10-01 |
| `core/atlas/agent/results.py` | `NousResearch/hermes-agent` | `tools/tool_result_storage.py` | `663362680b6ffa4fbffeb58f6682564239a1953b` | MIT | 逻辑移植 | 复用 Atlas run 目录持久化全量结果并返回头尾预览；无 run ID/写入失败时按配置截断 | 2026-10-01 |
| `core/atlas/usage_pricing.py` | `NousResearch/hermes-agent` | `agent/usage_pricing.py` | `663362680b6ffa4fbffeb58f6682564239a1953b` | MIT | 拷贝改 | 只保留静态价格计算和自定义价格覆盖；无 Hermes 账户/积分逻辑，表内为当前明确列出的模型 | 2026-10-01 |
| `core/atlas/usage.py` | `NousResearch/hermes-agent` | `agent/usage_pricing.py` | `663362680b6ffa4fbffeb58f6682564239a1953b` | MIT | 逻辑移植 | Atlas SQLite 用量记录、分组汇总；以模型+子任务聚合运行数 | 2026-10-01 |
| `core/atlas/agent/error_classifier.py` | `NousResearch/hermes-agent` | `agent/error_classifier.py` | `663362680b6ffa4fbffeb58f6682564239a1953b` | MIT | 逻辑移植 | 移植限流、额度、上下文、过载、网络、认证和格式错误的 provider-neutral 分类；未移植 Hermes 账户/供应商专属规则 | 2026-10-01 |
| `core/atlas/agent/retry_utils.py` | `NousResearch/hermes-agent` | `agent/retry_utils.py` | `663362680b6ffa4fbffeb58f6682564239a1953b` | MIT | 逻辑移植 | 采用有上限的抖动指数退避 | 2026-10-01 |
| `core/atlas/agent/fallback_cooldown.py` | `NousResearch/hermes-agent` | `agent/fallback_cooldown.py` | `663362680b6ffa4fbffeb58f6682564239a1953b` | MIT | 逻辑移植 | 当前进程内按模型设置临时冷却，剔除凭据池耦合 | 2026-10-01 |
| `core/tests/test_error_recovery.py` | `NousResearch/hermes-agent` | `tests/agent/test_error_classifier.py`, `tests/agent/test_retry_utils.py` | `663362680b6ffa4fbffeb58f6682564239a1953b` | MIT | 拷贝改 | 移植状态分类、重试退避和冷却核心测试；省略 Hermes 专属规则断言 | 2026-10-01 |
| `core/atlas/safety/detection.py` | `NousResearch/hermes-agent` | `tools/approval_detection.py` | `663362680b6ffa4fbffeb58f6682564239a1953b` | MIT | 逻辑移植 | 保留风险分类思路，另补 PowerShell/Windows 危险操作；未搬 Hermes 完整 shell 归一化器 | 2026-10-01 |
| `core/atlas/safety/floors.py` | `NousResearch/hermes-agent` | `tools/approval_floors.py` | `663362680b6ffa4fbffeb58f6682564239a1953b` | MIT | 逻辑移植 | 加入格式化系统卷、系统注册表删除和块设备写入的硬拦截 | 2026-10-01 |
| `core/atlas/safety/smart.py` | `NousResearch/hermes-agent` | `tools/approval_smart.py` | `663362680b6ffa4fbffeb58f6682564239a1953b` | MIT | 逻辑移植 | 15 秒辅助模型审查，仅传工具名和参数，输入按不可信数据包裹 | 2026-10-01 |
| `core/atlas/safety/threats.py` | `NousResearch/hermes-agent` | `tools/threat_patterns.py` | `663362680b6ffa4fbffeb58f6682564239a1953b` | MIT | 逻辑移植 | 移植有界文本扫描与提示注入识别；Atlas 当前模式表为子集 | 2026-10-01 |
| `core/atlas/safety/policy.py` | `NousResearch/hermes-agent` | `tools/approval.py` | `663362680b6ffa4fbffeb58f6682564239a1953b` | MIT | 逻辑移植 | Atlas 本地安全设置、永久规则匹配与近期审查日志 | 2026-10-01 |
| `core/tests/test_safety_foundation.py` | `NousResearch/hermes-agent` | `tests/tools/test_approval_detection.py`, `tests/tools/test_approval_smart.py`, `tests/tools/test_threat_patterns.py` | `663362680b6ffa4fbffeb58f6682564239a1953b` | MIT | 拷贝改 | 覆盖 Windows 危险命令、注入检测和审查输入边界 | 2026-10-01 |
| `core/atlas/agent/verification_stop.py` | `NousResearch/hermes-agent` | `agent/verification_stop.py` | `663362680b6ffa4fbffeb58f6682564239a1953b` | MIT | 逻辑移植 | 用 Atlas 工具执行记录判断代码编辑后是否有验证命令，文档路径不触发提醒 | 2026-10-01 |

参考提交号（2026-09-30 调研时）：
- `NousResearch/hermes-agent`：`12e4d3e2dd5281adf289f70e5d6c7f33427d6982`

# 已搬进 Atlas 的外部代码登记

每搬一个文件（或一段逻辑）就加一行。第 12 波会用这张表自动对照上游更新。

| Atlas 文件 | 来源仓库 | 来源路径 | 来源提交 | 许可证 | 方式（依赖 / 拷贝改 / 逻辑移植） | 改了什么 | 搬入日期 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `core/atlas/tools/ssrf_transport.py` | `NousResearch/hermes-agent` | `tools/url_safety.py` | `663362680b6ffa4fbffeb58f6682564239a1953b` | MIT | 拷贝改 | 保留连接时 DNS 校验并按校验 IP 拨号，使用 Atlas 的公网地址策略 | 2026-10-01 |
| `core/atlas/agent/prompt_caching.py` | `NousResearch/hermes-agent` | `agent/prompt_caching.py` | `663362680b6ffa4fbffeb58f6682564239a1953b` | MIT | 拷贝改 | 保留缓存断点布局、TTL 和消息标记规则；按 Atlas 路由判定工具消息标记 | 2026-10-01 |
| `core/atlas/agent/prompt_cache_boundary.py` | `NousResearch/hermes-agent` | `agent/prompt_cache_boundary.py` | `663362680b6ffa4fbffeb58f6682564239a1953b` | MIT | 拷贝改 | 保留稳定前缀 LRU 注册和查找 | 2026-10-01 |
| `core/tests/test_prompt_caching.py` | `NousResearch/hermes-agent` | `tests/agent/test_prompt_caching.py` | `663362680b6ffa4fbffeb58f6682564239a1953b` | MIT | 拷贝改 | 移植缓存边界、复制语义、TTL 与代理布局测试；Atlas 专属代理规划器测试另写 | 2026-10-01 |
| `core/tests/test_prompt_cache_boundary.py` | `NousResearch/hermes-agent` | `tests/agent/test_prompt_cache_boundary.py` | `663362680b6ffa4fbffeb58f6682564239a1953b` | MIT | 拷贝改 | 移植稳定前缀查找与请求级拆分测试；未移植 Hermes 专属技能/定时任务构造器测试 | 2026-10-01 |

参考提交号（2026-09-30 调研时）：
- `NousResearch/hermes-agent`：`12e4d3e2dd5281adf289f70e5d6c7f33427d6982`

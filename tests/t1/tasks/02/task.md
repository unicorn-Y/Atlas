# 任务 02：修复 TTL 缓存过期边界

请修复 `TTLCache` 的过期判断。条目有效区间是写入时刻起、严格早于 `expires_at` 的时刻；到达过期时刻就必须重新计算。保留构造和 `get_or_load` 的公开接口。不要改动已有测试，并补充一个回归测试。

使用 `python -m unittest discover -s tests -v` 验证。

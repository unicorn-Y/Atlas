# 任务 08：查明 Hermes MCP 连接并发配置

请阅读仓库 `source/upstream/hermes-agent` 的源码，回答 `tools/mcp_tool_discovery.py` 中 MCP discovery 连接并发限制的实现：默认并发是多少、配置键是什么、设为 0 有什么含义、负数或布尔值怎么处理、读取配置抛异常时怎么处理？

将答案写为仓库根目录的 `answer.json`，JSON 顶层字段为 `repository`、`commit`、`source_path`、`facts`、`evidence`。`repository` 固定为 `NousResearch/hermes-agent`；`commit` 填下面的 pinned commit；`source_path` 填 `tools/mcp_tool_discovery.py`。`facts` 必须包含整数 `default_concurrency`、字符串 `config_key` 和 `zero_means`，以及整数 `negative_falls_back_to`、`boolean_falls_back_to`、`config_load_error_falls_back_to`。`evidence` 是对象数组，每项含 `path`、整数 `start_line`、整数 `end_line`。

所有事实都要引用真实源文件路径和行号。提交结构化事实，不能只写一段没有依据的总结。仓库固定在 NousResearch/hermes-agent commit `9a71d5a8b59b37d1795ab7065fbbe3b647ba5249`。若完整仓库暂不可用，可先用 `source/snapshot` 内标记过的离线源码摘录完成；真实 benchmark setup 会准备完整 pinned checkout。

# 任务 05：增加 Catalog 名称前缀搜索

为小型 Catalog 增加 `search_prefix(prefix, limit=None)`：大小写不敏感地匹配名称前缀，按名称大小写折叠后的字母顺序返回；同名时按 `id` 排序。`limit` 省略时返回全部匹配项，传入非负整数时最多返回该数量，传 0 返回空列表，负数抛 `ValueError`。不得改变现有 `get`、`all`、`add` 行为。请在新的测试文件中补充功能测试，并保留原有测试。

使用 `python -m unittest discover -s tests -v` 验证。

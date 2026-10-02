# 任务 06：增加按标签查询笔记

给笔记增加标签查询。`Note` 添加默认空标签列表；`NoteService.search_tags(tags, match="all")` 对标签做大小写不敏感比较，支持所有标签均匹配（`all`）和任意标签匹配（`any`）。空查询返回空列表；空白标签在构造或查询时忽略；未知的 `match` 值抛 `ValueError`。结果保持存储顺序。不得破坏原有创建和列表行为。新增独立测试文件覆盖新旧行为。

使用 `python -m unittest discover -s tests -v` 验证。

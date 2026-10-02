# 任务 10：重构用户展示格式化模块

把当前多个模块依赖的私有 `_format_user` 整理为 `src/presentation.py` 中的公开 `render_user`，并更新所有调用处。旧 helper 所在的 `src/formatting.py` 可保留兼容转发，但整个源码和测试中不能再有 `_format_user` 这个旧私有符号。`contact_card`、`directory_entry`、`export_row`、`profile_label` 的公开导入路径、返回值和格式必须保持稳定。

这是一个跨文件重构：请更新所有引用并新增测试。运行 `python -m unittest discover -s tests -v` 验证。

# 评分要点

- 展示逻辑移入 `src/presentation.py`，新公开 API 为 `render_user`。
- 所有生产调用点已迁移；仓库代码及测试不残留 `_format_user`。
- 四个既有公开 helper 的导入位置、格式和行为均稳定。
- 至少跨五个源码文件，并新增测试覆盖迁移后的 API。

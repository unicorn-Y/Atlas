# 任务 07：增加安全的库存调整

为库存服务增加 `adjust_stock(sku, delta)`。只有库存中存在的 SKU 可调整；调整后数量不得小于 0。成功时返回调整后的 `Product`，未知 SKU 抛 `KeyError`，负库存抛 `ValueError`，失败时库存保持原值。`delta` 可以是正数、负数或 0。保留原有新增、查询行为，并在新的测试文件中补充测试。

使用 `python -m unittest discover -s tests -v` 验证。

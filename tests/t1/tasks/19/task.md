# 执行中途的新要求

开始时按 `transactions.json` 只汇总 `paid` 交易，金额都用整数分。执行过程中我会用 steer 补充要求：最终改为统计 `paid` 与 `pending`、排除 `refunded`，并在输出中写明“已应用中途更新”。请以 steer 之后的要求为准；原始交易数据不能改。

# 任务 03：修正 TypeScript 区间判断

修复 `isBetween`。该函数表示闭区间判断：`min` 和 `max` 都算区间内；当 `min > max` 时返回 `false`。保留导出的函数名和参数类型，不要改动已有测试。

请用 `tsc` 编译 TypeScript，再用 Node 运行测试：`tsc -p tsconfig.json && node tests/run.cjs`。

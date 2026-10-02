# 任务 04：修复 Unicode 安全的中间截断

修复 `truncateMiddle(text, maxLength)`。当文本超过最大长度时，在中间插入一个 `…`；最大长度按 Unicode 码点计算，不得拆开代理对。长度为 0 返回空串，长度为 1 返回 `…`，长度为 2 返回首个码点和 `…`。较短文本原样返回。保留公开函数名和类型，不改已有测试。

请用 `tsc` 编译再用 Node 运行：`tsc -p tsconfig.json && node tests/run.cjs`。

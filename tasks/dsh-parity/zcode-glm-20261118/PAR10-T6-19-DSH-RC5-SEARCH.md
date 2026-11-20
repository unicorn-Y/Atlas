# T6-19 · 补齐官方 DSH rc.5 的搜索路由差异

可立即领取空余工位，独占 `zcode-par10-rc5-search`。官方 rc.4 `3f321d32bfe382212a8ed8785c1d47a5a300aa23` 至 rc.5 `9c2670d3bce5275e0d1610272958121af87787bb` 已隔离拉取到 `D:\Atlas\.worktrees\_codex-dsh-rc5-source.git`，标签 `atlas-base-rc4`、`atlas-target-rc5`。完整 diff 是 433 个文件，其中 380 是包清单、29 文档与本地化、17 代码或测试、5 快照、2 配置。官方变化集中在网页搜索。核对 `packages/web/web/src/index.ts`、`packages/web/tool-web/src/search.ts`、`packages/web/web-search-deepseek/src/provider.ts`、网页搜索设置组件、升级说明及它们的测试和快照。 [官方发布说明](https://github.com/deepseek-ai/deepseek-harness/releases/tag/dsh-v0.2.2-rc.5)

- 在 Atlas 正常搜索工具中接实际调用该工具的模型路由。明确设置的合法 provider 保持优先；只有自动模式才按模型路由首选。官方 DeepSeek 与账户路由首选服务端搜索，其它或未知路由首选支持的独立 Search API。用本地夹具验证回退规则、零/多候选错误以及默认配置与旧用户兼容。任意中转和相似模型别名不得被误认为官方账户路由。
- 沿 `core/atlas/websearch/service.py`、`core/atlas/websearch/providers/`、`core/atlas/tools/web.py` 复用现有证书、密钥管理、限流、域名过滤、引用输出与取消处理。保持网页抓取独立。核对 rc.5 摘要从结果与引文回退的规则、重复 URL 处理和设置用语。说明服务端搜索仍消耗模型 tokens；遇到不支持的 endpoint 要显示可操作的配置提示。采用 Atlas 自己的设置界面和命名。
- 真实回环 HTTP 与正常工具入口覆盖官方路由、非官方路由、手动覆盖、不支持端点和取消。无须付费调用；报告真实 DeepSeek 验证边界。写 `evidence/par10-t6-19.md`，末行 `PAR10_RECEIPT T6-19 READY|PARTIAL|BLOCKED`，完成主动回报。
- 当前搜索缓存键只包含语言、查询、过滤和数量。接入路由自动选择后，补上选路所需的身份信息，验证同一查询在两条路由上不会互用结果。既有 `tests/test_web_tools.py` 在 D 盘临时环境独立跑过 6 项；共享 venv 缺声明的 `semantic-version` 时可用该探针的本地依赖目录 `D:\Atlas\.worktrees\_codex-par10-probes\rc5-web-baseline\deps`，无需修改共享 venv。
- C 盘目前可用空间为 0。为当前任务子进程设 `TEMP` 和 `TMP` 到该工作树下新建的 D 盘临时目录，并把 Vite、测试和运行输出留在 D 盘。不改全局环境、不清理用户目录。T6-17 如有可核验的 rc.4 样本应保存并清楚标注，rc.5 样本继续遵守既定配对预算。

# START-HERE

本分支收集原始发行材料并作机械提取。后续 GPT-6 负责拆包分析、源码追踪和 Atlas 对照；本轮尚未开始这些工作。

- Branch: research/agent-client-packages-20261019
- Commit: 该文档即本分支 HEAD；本次精确 SHA 由交付说明提供。
- Release: https://github.com/unicorn-Y/Atlas/releases/tag/agent-client-packages-20261019
- Machine manifest: manifest.json（62 条包/组件记录，未知字段保留 null）
- Release assets: 54 个文件，共 4,908,552,923 bytes
- Hash list: SHA256SUMS.txt
- Package index: PACKAGE-INDEX.md
- Status and limits: COLLECTION-STATUS.md、DOWNLOAD-LOG.md、CANDIDATES.md

P0：5 个产品族中 4 个完整覆盖；OpenAI Codex Desktop 受阻，因为 Store 安装程序文件无法经普通复制读取。Claude consumer Setup 返回 HTTP 403，但 enterprise MSIX 已收集。ZCode 独立 CLI 为 N/A。

P1：任务书列出的 9 个产品族均已取得适用 Windows 包或源码；两个 Windsurf 插件/catalog 形态仍未检查。另收 Zed、OpenHands Agent Canvas、Squad、ccusage 和 Claude HUD。

2026-10-19 recovery pass: Claude Consumer Setup still returns HTTP 403. Codex Desktop’s official Microsoft Store download did not proceed because package agreements were not accepted; the installed package remains Application Protected. No new asset was acquired or uploaded; the Release still contains 54 assets / 4,908,552,923 bytes. See DOWNLOAD-LOG.md for official URLs and evidence.

原安装器、VSIX、npm tarball、CLI ZIP 和源码快照均为独立 GitHub Release assets。索引列出包内路径和入口文件，原归档保持可下载。


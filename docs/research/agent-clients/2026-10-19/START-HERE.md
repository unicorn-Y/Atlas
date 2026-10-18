# START-HERE

本分支收集原始发行材料并作机械提取。后续 GPT-6 负责拆包分析、源码追踪和 Atlas 对照；本轮尚未开始这些工作。

- Branch: research/agent-client-packages-20261019
- Commit: 该文档即本分支 HEAD；本次精确 SHA 由交付说明提供。
- Release: https://github.com/unicorn-Y/Atlas/releases/tag/agent-client-packages-20261019
- Machine manifest: manifest.json（62 条包/组件记录，未知字段保留 null）
- Release assets: 55 个文件，共 5,857,546,738 bytes
- Hash list: SHA256SUMS.txt
- Package index: PACKAGE-INDEX.md
- Status and limits: COLLECTION-STATUS.md、DOWNLOAD-LOG.md、CANDIDATES.md

P0：5 个产品族中 4 个完整覆盖；OpenAI Codex Desktop x64 MSIX 26.1013.4894.0 已从官方 CDN 收集并验证。Claude Consumer Setup 和直连 consumer MSIX 返回 `region_unavailable`；enterprise MSIX 已收集，但内容等价性未知。ZCode 独立 CLI 为 N/A。

P1：任务书列出的 9 个产品族均已取得适用 Windows 包或源码；两个 Windsurf 插件/catalog 形态仍未检查。另收 Zed、OpenHands Agent Canvas、Squad、ccusage 和 Claude HUD。

2026-10-19 recovery: added `ChatGPT-x64.msix`; Release now has 55 assets / 5,857,546,738 bytes. Full Release round-trip download matched local size and SHA-256. See RECOVERY-CODEX-CLAUDE.md for signatures, Package Identity, entry points, links, and the remaining Claude block.

原安装器、VSIX、npm tarball、CLI ZIP 和源码快照均为独立 GitHub Release assets。索引列出包内路径和入口文件，原归档保持可下载。


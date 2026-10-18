# COLLECTION-STATUS

本轮仅负责原始资料采集和机械提取；功能研究、源码追踪和 Atlas 对照留给后续 GPT-6。

## P0

| 产品 | Desktop | CLI / Runtime | 源码 / Web UI | 结果 |
|---|---|---|---|---|
| Claude | PARTIAL：官方 Windows x64 enterprise MSIX 2.42304.0 已收集；consumer Setup 的普通 GET/HEAD 于 2026-10-19 仍返回 HTTP 403 | COMPLETE：Claude Code npm core + Windows x64 包 2.1.302 | 包树和元数据已索引 | consumer installer BLOCKED：无重定向目标、版本或安装包 |
| OpenAI Codex | BLOCKED：Store 产品 ID 9PLM9XGG6VKS 的官方 WinGet 下载因未接受 package agreements 而取消；已安装 Store-signed 26.1013.4894.0 的 3,650 个程序文件仍受保护，普通复制全部失败 | COMPLETE：CLI 0.163.0 ZIP、code-mode host ZIP | COMPLETE：源码 ZIP 0.163.0，GitHub 发布摘要匹配 | Desktop 安装包仍受阻；未接受协议或绕过保护 |
| OpenCode | COMPLETE：官网当前稳定 Windows x64 v2.0.32；另保留 v1.19.3 | COMPLETE：npm wrapper + Windows x64 CLI 包 v2.0.32 | COMPLETE：固定源码提交 843a6c514e606b436a7fe713422ace0a93ad3d61 | 当前官网版本已核验 |
| ZCode | COMPLETE：Z.ai 官方 Windows x64 3.15.3 | N/A：未找到独立官方 CLI；排除无关同名 npm 包 | COMPLETE：提交 aac4755666d09fdcd70272fcf063c077a639015f（源码 v3.15.1） | 桌面/源码版本差异已记录；runtime 在桌面包内 |
| DeepSeek Harness | 未发现官方 Windows desktop；两个社区桌面/源码封装已分别标注 | COMPLETE：官方 npm latest 0.2.0-rc.2 | COMPLETE：官方源码提交 687f282e8625c6b8d11ff58211a90524be2e4317 和 Web UI 构建包 0.0.1-rc.5 | 官方和社区材料分开标记 |

P0 产品族：4/5 完全覆盖；Codex Desktop 受阻。Claude consumer Setup 受阻，但官方 enterprise MSIX 已取得。ZCode 独立 CLI 为 N/A。2026-10-19 补采未新增可上传资产。

## P1

- Cursor：Windows x64 system 和 user 安装器 3.24.18。
- Windsurf：官网当前下载跳转 Devin Desktop 3.10.67；已收集官方 Visual Studio 插件源码。VS Code/JetBrains 插件和独立 Windsurf MCP catalog 尚未检查。
- Cline：官方 VSIX、npm wrapper、Windows x64 CLI runtime。
- Roo Code：可取得的最后官方 Marketplace VSIX；上游标注于 2026-05-15 停运。
- Kilo Code：官方 VSIX、npm wrapper、Windows x64 CLI runtime。
- Continue：官方 VSIX 和 CLI npm 包。
- Hermes Agent：main 和 v0.22.2 源码；v0.22.2 Release API 无上传资产。
- Goose、Pi：Windows x64 ZIP、固定版本和 main 源码；本轮未取其他平台安装包。
- 其他项目：Zed、OpenHands Agent Canvas、Squad、ccusage、Claude HUD。
- 扩展样本：Anthropic Skills、Model Context Protocol servers、Windsurf Visual Studio plugin，均标为扩展/项目。

P1 任务书列出的 9 个产品族均已取得适用 Windows 包或源码；两个 Windsurf 插件/catalog 形态仍是 unchecked candidate。

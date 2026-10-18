# DOWNLOAD-LOG

采集时间为 2026-10-18 UTC（香港日期 2026-10-19）。来源为公开官方/上游发行地址及任务书点名的社区仓库。未收集 Atlas 业务代码、本机用户会话、凭据、Cookie、浏览器 Profile 或授权状态。

## 阻塞、重定向和版本差异
- Claude consumer Windows Setup 返回 HTTP 403；已获取并标注官方 enterprise x64 MSIX 2.42304.0。
- OpenAI Codex Desktop Store 包 OpenAI.Codex_26.1013.4894.0_x64__2p2nqsd0c76g0 通过只读包清单发现。WinGet 仅解析到 Codex CLI。逐一普通复制 3,650 个已安装程序文件，全部因 Encrypted 属性而以 System.IO.IOException: 无法加密指定的文件 失败。未解密、修改 ACL/ownership、提权、登录 Store、访问替代 CDN 或绕过 DRM。只读目录索引和失败清单保留在 Claude/Codex index。
- OpenCode 官网当前下载指向 desktop v2.0.32；GitHub v1.19.3 文件另标为旧版本。
- ZCode desktop 是 3.15.3，最新公开源码快照是 3.15.1。未找到独立官方 CLI；排除无关同名 npm 包。
- DeepSeek Harness npm latest 是 prerelease 0.2.0-rc.2。两个社区桌面封装明确标为社区项目。DSH 重定向链未采集。
- Goose、Pi Windows x64 ZIP 来自官方 Releases，摘要与上游 API digest 相符；其他平台只记录未下载。
- Hermes Agent v0.22.2 Release API 显示没有上传资产；源码快照已取得。
- Windsurf 官方下载跳转 Devin Desktop 3.10.67。独立 VS Code/JetBrains 包和 Windsurf MCP catalog 尚未检查。
- Roo Code 官方 Marketplace 标注 2026-05-15 停运；收录仍可获取的最后版本 3.54.0。

每条包的 URL、抓取时间、源码 commit、哈希、提取文件数、入口文件和 source map 清点见 indexes/。

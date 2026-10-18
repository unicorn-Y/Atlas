# DOWNLOAD-LOG

采集时间为 2026-10-18 UTC（香港日期 2026-10-19）。来源为公开官方/上游发行地址及任务书点名的社区仓库。未收集 Atlas 业务代码、本机用户会话、凭据、Cookie、浏览器 Profile 或授权状态。

## 阻塞、重定向和版本差异
- Claude Consumer Setup 官方 Windows x64 直链 `https://claude.ai/api/desktop/win32/x64/setup/latest/redirect` 与官方直连 MSIX `https://claude.ai/api/desktop/win32/x64/msix/latest/redirect` 在 2026-10-19 的普通 GET 均返回 HTTP 403、0 次重定向、0 字节，响应头 `X-Claude-Error-Code: region_unavailable`（Cloudflare edge LHR）。未取得 consumer 包、版本或最终 URL。已取得 enterprise x64 MSIX 2.42304.0，不据此推断 consumer 等价性。
- OpenAI Codex Desktop x64 MSIX 由 OpenAI 官方部署文档 `https://learn.chatgpt.com/docs/enterprise/windows-deployment` 指向官方 CDN `https://persistent.oaistatic.com/codex-app-prod/ChatGPT-x64.msix` 直接下载，HTTP 200。版本 JSON `https://persistent.oaistatic.com/codex-app-prod/windows-store-update.json` 给出 buildVersion 26.1013.4894.0、releaseVersion 26.1013.40934、identity OpenAI.Codex、Store ProductId 9PLM9XGG6VKS。包大小 948993815 bytes，SHA256 `e2d892e6c22310e4b1a2928b0d3a29a066e0863d3a333754d6585c77cdafbe7f`；Microsoft Authenticode 签名有效。AppxManifest 为 x64 / Windows.Desktop，主入口 `app/ChatGPT.exe`，辅助入口 `app/resources/codex-command-runner.exe`；版本与本机安装包相同。版本化 URL 同样 HTTP 200、相同 Content-Length 但 ETag 不同；仅 latest alias 实际下载。Release 完整回下载大小和 SHA256 与本地匹配。此前 Store/WinGet 路线因未接受协议而取消，随后由官方 CDN 成功取得，不需该备用路线。
- OpenCode 官网当前下载指向 desktop v2.0.32；GitHub v1.19.3 文件另标为旧版本。
- ZCode desktop 是 3.15.3，最新公开源码快照是 3.15.1。未找到独立官方 CLI；排除无关同名 npm 包。
- DeepSeek Harness npm latest 是 prerelease 0.2.0-rc.2。两个社区桌面封装明确标为社区项目。DSH 重定向链未采集。
- Goose、Pi Windows x64 ZIP 来自官方 Releases，摘要与上游 API digest 相符；其他平台只记录未下载。
- Hermes Agent v0.22.2 Release API 显示没有上传资产；源码快照已取得。
- Windsurf 官方下载跳转 Devin Desktop 3.10.67。独立 VS Code/JetBrains 包和 Windsurf MCP catalog 尚未检查。
- Roo Code 官方 Marketplace 标注 2026-05-15 停运；收录仍可获取的最后版本 3.54.0。

每条包的 URL、抓取时间、源码 commit、哈希、提取文件数、入口文件和 source map 清点见 indexes/。

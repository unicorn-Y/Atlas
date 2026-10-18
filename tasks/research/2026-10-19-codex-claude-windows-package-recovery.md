# Codex 补采任务书：Codex Desktop + Claude Windows Consumer Setup (2026-10-19)

执行：Codex / Luna High，可并行两个 worker；直接执行下载、核验、上传，不要再出规划稿。
仓库：unicorn-Y/Atlas
基线及交付分支：research/agent-client-packages-20261019
Release：https://github.com/unicorn-Y/Atlas/releases/tag/agent-client-packages-20261019
性质：**只补两个缺失原包，不做逆向研究、不改 Atlas 代码。**

## 当前基线

先读 docs/research/agent-clients/2026-10-19/ 中 START-HERE.md、COLLECTION-STATUS.md、DOWNLOAD-LOG.md、PACKAGE-INDEX.md、manifest.json。

- Codex Desktop 已发现本机 Store 安装 OpenAI.Codex_26.1013.4894.0_x64__2p2nqsd0c76g0，但 WindowsApps 中 3650 个文件均无法普通复制。**别再重复复制受保护安装目录，改用官方 MSIX 下载。**
- Claude Desktop 已成功获取官方 Windows x64 MSIX 2.42304.0；只缺 Consumer Setup.exe，引导器下载曾返回 403。**先确认消费者 Setup 最终安装内容是否已经由 MSIX 覆盖。**
- 2026 年 Codex 和 ChatGPT 桌面端合并：新客户端显示 ChatGPT，但程序包身份仍可能是 OpenAI.Codex。不要拿旧 ChatGPT Classic 或 Codex CLI 冒充当前 Codex Desktop。

## A. Codex Desktop：已定位官方 CDN 的直接下载办法

优先通过 OpenAI 自己的 CDN，不依赖 Microsoft Store、WindowsApps 导出或第三方镜像。

1. 官方最新版 x64 MSIX：https://persistent.oaistatic.com/codex-app-prod/ChatGPT-x64.msix
2. 官方版本 JSON：https://persistent.oaistatic.com/codex-app-prod/windows-store-update.json
3. 官方企业部署文档（网页内“x64 MSIX”直接链接）：https://learn.chatgpt.com/docs/enterprise/windows-deployment
4. 若清单显示版本 X，还可检查：https://persistent.oaistatic.com/codex-app-prod/releases/X/ChatGPT-x64.msix 。X 必须读取当天的实际 JSON。历史上有清单指向暂时 404 的情况；版本化路径失败就先试 latest alias，并明确记录区别。

Windows PowerShell 推荐直接执行（下载不安装）：

    $ErrorActionPreference = 'Stop'
    $dir = 'D:\Atlas-Agent-Package-Recovery'
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    Invoke-RestMethod 'https://persistent.oaistatic.com/codex-app-prod/windows-store-update.json' | ConvertTo-Json -Depth 10 | Set-Content -Encoding UTF8 (Join-Path $dir 'codex-update.json')
    curl.exe -fL --retry 3 --connect-timeout 20 'https://persistent.oaistatic.com/codex-app-prod/ChatGPT-x64.msix' -o (Join-Path $dir 'ChatGPT-x64.msix')
    Get-Item (Join-Path $dir 'ChatGPT-x64.msix') | Select-Object FullName,Length
    Get-FileHash (Join-Path $dir 'ChatGPT-x64.msix') -Algorithm SHA256
    Get-AuthenticodeSignature (Join-Path $dir 'ChatGPT-x64.msix') | Format-List Status,SignerCertificate

再用 7-Zip 查看 MSIX 压缩包树及 AppxManifest.xml：确认 x64、Package Identity、Package Version、实际桌面程序入口和程序内容，校验官方签名。记录与本机旧版 26.1013.4894.0 是否相同或更新，**别假定官网 latest 一定等于本机 Store 版本**。不要把 800MB 级 MSIX 文件直接 git commit。

如果官方 CDN 暂时失败，备用：
- 官方 Microsoft Store ProductId：9PLM9XGG6VKS；微软官方 WinGet 命令尝试下载（如支持）：winget download --id 9PLM9XGG6VKS --source msstore --skip-license --accept-source-agreements --accept-package-agreements --download-directory "D:\Atlas-Agent-Package-Recovery"；权限/Entra 阻塞则记录，不要反复空转。
- 官方部署文档的 x64 MSIX 直链。
- 最后才考虑来源注明为非官方的原版镜像，例如 https://github.com/Wangnov/codex-app-mirror ；仅在验证微软/OpenAI 官方 Authenticode 签名、AppxManifest identity 与版本等证据一致后才能作为可信原包归档。严禁采用破解/改包版本。

注意官方部署文档说没有独立 MSI / 非 Store EXE，因此不要耗费时间寻找不存在的“官方独立 setup.exe”；**目标是原装、可解包的官方 x64 MSIX**。

## B. Claude Desktop Consumer Setup：两个官方下载入口

1. 消费者 Setup 重定向：https://claude.ai/api/desktop/win32/x64/setup/latest/redirect
2. 官方直接 MSIX 重定向：https://claude.ai/api/desktop/win32/x64/msix/latest/redirect
3. 官方页面：https://claude.com/download
4. 官方企业部署：https://support.claude.com/en/articles/12622703-deploy-claude-desktop-for-windows
5. 官方 Microsoft Store：https://apps.microsoft.com/detail/9P6K58THS811

具体步骤：
- 在本机浏览器通过 claude.com/download Windows 下载按钮实际获取 Setup EXE；记录 URL 跳转和版本。浏览器成功、CLI 403 时直接从浏览器下载目录保留原件。
- 浏览器不成功再试 curl.exe -fL -L 跟踪消费者 Setup 重定向，记录 HTTP 状态和实际目标 URL。403 时核对浏览器与 CLI 使用的正常网络、系统代理、DNS/TUN 出口等（仅使用授权的正常网络，不绕过账号/DRM）。
- 使用已有 x64 MSIX 2.42304.0 的 Package Identity、Version、入口和主要程序资源，与最新官方 MSIX 比较。消费者 Setup 如果只是下载/安装相同 MSIX，不需要将它当成第二套不同程序。若程序内容已覆盖，明确结论：“consumer setup 引导器仍缺，但桌面程序本体已齐”及支持依据；若不能确认则标未知，不能猜测。
- 成功获取 Setup.exe 则保存原件、SHA256、签名、大小、厂商、下载时间及最终重定向 URL；不要保存任何用户凭据、登录状态或个人数据。

**A 与 B 并行处理，某一路失败也不要影响另一路。只做机械归档、内容等价性核查，不开始逆向功能。**

## C. 上传与验收

- 在已有私有 GitHub Release agent-client-packages-20261019 **新增**原始包资产，保留已归档的 54 个资产不删除。MSIX、EXE 等大文件只上传 Release Assets，不进 Git 主历史。
- 更新 docs/research/agent-clients/2026-10-19/ 下的 manifest.json、COLLECTION-STATUS.md、DOWNLOAD-LOG.md、PACKAGE-INDEX.md、SHA256SUMS.txt、START-HERE.md。manifest 中 Codex Desktop blocked / Claude consumer setup blocked 不能笼统直接改 COMPLETE：必须注明 fetched / verified-equivalent / still-blocked 的真实状态，准确更新数量、体积、版本和 URL。
- 新建 RECOVERY-CODEX-CLAUDE.md，记录下载成功或失败的原始 HTTP/路径证据、签名及包身份检查、Setup 与 MSIX 等价性、Release 资产和解包入口路径。包内文件目录只需机械列索引，不需要写功能总结。
- git commit + push 至 research/agent-client-packages-20261019。回传 commit SHA、Release URL、新资产文件名/大小/SHA256、两处缺口终态和未解决问题。上传后由 GPT-6 分会话逆向研究，不要在本任务里宣称已完成拆包分析。

## 查询来源（仅为下载路线的依据，不代表原包已验证）

- OpenAI 官方 Windows 部署：https://learn.chatgpt.com/docs/enterprise/windows-deployment
- OpenAI 新桌面应用迁移：https://help.openai.com/en/articles/20001276-moving-to-the-new-chatgpt-desktop-app
- Codex CLI GitHub 官方仓库讨论（官方 CDN 端点）：https://github.com/openai/codex/issues/13993
- Anthropic 官方下载：https://claude.com/download
- Anthropic Windows 部署：https://support.claude.com/en/articles/12622703-deploy-claude-desktop-for-windows

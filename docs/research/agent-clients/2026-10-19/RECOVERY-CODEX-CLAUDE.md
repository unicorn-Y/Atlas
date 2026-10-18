# Codex Desktop and Claude Consumer Setup recovery

Checked 2026-10-19 (Asia/Hong_Kong), following the recovery taskbook. Scope was package acquisition and mechanical verification only; no application was installed or run and no functional analysis was performed.

## OpenAI Codex Desktop

- Official deployment documentation: https://learn.chatgpt.com/docs/enterprise/windows-deployment
- Official version metadata: https://persistent.oaistatic.com/codex-app-prod/windows-store-update.json
- Official x64 MSIX: https://persistent.oaistatic.com/codex-app-prod/ChatGPT-x64.msix
- Download result: HTTP 200; 948,993,815 bytes; SHA-256 `e2d892e6c22310e4b1a2928b0d3a29a066e0863d3a333754d6585c77cdafbe7f`.
- Version metadata: buildVersion `26.1013.4894.0`, releaseVersion `26.1013.40934`, Store ProductId `9PLM9XGG6VKS`.
- Authenticode: Valid / Signature verified. Signer subject `CN=50BDFD77-8903-4850-9FFE-6E8522F64D5B`; issuer Microsoft Marketplace CA G 024; thumbprint `1DA78AFE445125E845477BB30EB0E7B703270FEF`.
- `AppxManifest.xml`: identity `OpenAI.Codex`, publisher matches the signing certificate, version `26.1013.4894.0`, architecture x64, target `Windows.Desktop`.
- Package tree: 3,651 archive entries / 2,346,419,207 uncompressed bytes. Main app entry `app/ChatGPT.exe`; second entry `app/resources/codex-command-runner.exe`. Signature block `AppxSignature.p7x`; catalog `AppxMetadata/CodeIntegrity.cat`.
- The downloaded version matches the existing Store installation `OpenAI.Codex_26.1013.4894.0_x64__2p2nqsd0c76g0`. The versioned URL `https://persistent.oaistatic.com/codex-app-prod/releases/26.1013.4894.0/ChatGPT-x64.msix` also returned HTTP 200 and the same Content-Length, but had a different ETag and was not downloaded; only the official latest alias is archived.
- Release asset: [ChatGPT-x64.msix](https://github.com/unicorn-Y/Atlas/releases/download/agent-client-packages-20261019/ChatGPT-x64.msix). GitHub reports `uploaded`; a full Release download was 948,993,815 bytes and its SHA-256 matched the local original.

## Claude Consumer Setup

- Official download page: https://claude.com/download
- Consumer Setup redirect: https://claude.ai/api/desktop/win32/x64/setup/latest/redirect
- Direct consumer MSIX redirect: https://claude.ai/api/desktop/win32/x64/msix/latest/redirect
- Both official endpoints returned HTTP 403 on 2026-10-19, with zero redirects, zero bytes, and `X-Claude-Error-Code: region_unavailable` (Cloudflare edge LHR). No current consumer payload, version, or final URL was obtained.
- Consumer Setup-to-MSIX equivalence is **unknown**. The separately collected enterprise x64 MSIX is signed and identified, but it does not prove the unavailable consumer package has the same content.
- Existing enterprise reference: `Claude-2.42304.0-x64.msix`, 297,191,037 bytes, SHA-256 `2bf309665f0de4eaa76a7e64033594e6f73ceb6413c60080f72f3ce640fa24ee`; Authenticode Valid, signer Anthropic, PBC; Package Identity `Claude`, version `2.42304.0.0`, x64. Entries: `app/Claude.exe`, `app/resources/claude-ssh-askpass.exe`, and `app/resources/claude-ssh-proxy.exe`. Existing tree has 4,443 files; notable resources include `app/resources/app.asar` and `app/resources/cowork-svc.exe`.

## Delivery

- Release: https://github.com/unicorn-Y/Atlas/releases/tag/agent-client-packages-20261019
- Added asset: `ChatGPT-x64.msix` (948,993,815 bytes; SHA-256 above). The previous 54 assets were retained. The Release now contains 55 assets / 5,857,546,738 bytes.
- No Claude consumer asset was uploaded because neither official endpoint yielded bytes.
- This recovery completed package collection only. Further unpacking, source tracing, and Atlas comparison remain for a later task.

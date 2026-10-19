# P4 — Chat / Cowork / Agent 主运行机制

> 版本：Claude Desktop Windows x64 enterprise 2.42304.0  
> 证据：静态（S）+ 少量推断（I）。本机未安装运行，故 **R = 0**（见 `RUNTIME-BLOCKERS`）。

---

## 1. 结论先行

Claude Desktop 的 Agent Runtime 是**三层分离**结构，不是单一"本地 agent loop"：

| 层 | 执行所有者 | 证据 |
|---|---|---|
| **Chat（主对话 UI）** | **云端**（claude.ai 渲染 + Anthropic API） | `main_window/index.html` 首行注释："everything else gets loaded from claude.ai"；本地只有标题栏与错误页 |
| **Code / LocalSessions** | **本地**（spawn CLI 子进程） | `spawn(i,a,"claude",e,void 0,f,u,!1,t.allowedDomains,!0)`；`LocalSessions` 329 个方法 |
| **Cowork** | **两者皆有**：VM 内（`ClaudeVM`）或云端 | `ClaudeVM.download/startVM/restartVM` + `downloads.claude.ai/vms/linux/` + `cowork-svc.exe` 提供 Hyper-V 宿主 |

"客户端里有 `cowork-svc.exe`"**不等于**所有 Cowork 都在本地执行：`LocalAgentModeSessions` 与云会话是两套并行路径，且受 `coworkLocalTasksOff` / `codeLocalPolicy` / `thirdParty()` 三个 policy 门控。

---

## 2. 三套会话模型

### 2.1 `LocalSessions`（本地 Code 会话，329 个方法）

真实方法签名（来自 `EIPC-METHODS.tsv`，参数名是打包器保留的原始名）：

| 方法 | 参数 | 说明 |
|---|---|---|
| `start` | `info` | 创建本地会话 |
| `sendMessage` | `sessionId, message, images, toolStates, attachments, priority, steeringGates, messageUuid, seededSummon, typedText, sessionMentions, paneHolds, seededKind, pastes, marks` | 17 个参数，说明输入侧有丰富的结构化能力 |
| `forkSession` | `parentSessionId, sessionId, forkAtMessageUuid, targetCwd` | 从某条消息分叉 |
| `detachFromParent` | `sessionId` | 分离 |
| `setModel` / `setEffort` / `setFastMode` / `setExtendedThinking` | — | 模型与推理强度控制 |
| `setPermissionMode` | `sessionId, mode, _chromeAllowedDomains, options` | 权限模式（含 Chrome 域白名单） |
| `getContextUsage` / `getContextUsageSummary` | `sessionId` | 上下文用量 |
| `warmSession` / `personOpenedSession` | `sessionId` | 预热与会话归属 |
| `canAutoResume` / `restartRemoteSession` / `retryStart` / `confirmImportedSessionResume` | — | **恢复语义** |
| `startSideChat` / `sendSideChatMessage` / `stopSideChat` / `interruptSideChat` | `sessionId, text` | **侧对话（不打断主线）** |
| `toggleRemoteControl` / `getRemoteControlStartState` / `shareSession` | `sessionId, enable` | **远程控制/共享会话** |
| `createOutputStyle` / `refreshOutputStyles` / `revealOutputStyle` | — | 输出风格（system prompt 变体） |
| `reviewRepository` | `sessionId, generation` | 仓库审阅 |
| `getClaudeCodeRestartVersions` / `applyModelByRestart` / `reinstallRemoteClaudeCode` / `restartRemoteHelper` | — | Claude Code 版本管理与重启 |

**执行所有权（S）**：`LocalSessions` 通过 `spawn(..., "claude", ...)` 拉起一个名为 `claude` 的子进程，并把 `t.allowedDomains` 传入 —— 即 **Claude Code CLI 作为子进程执行**，Desktop 是它的前端宿主，不是它自己实现 agent loop。

### 2.2 `LocalAgentModeSessions`（115 个方法）

与 `LocalSessions` 平行的另一套会话，参数更偏"模式"：

| 方法 | 参数 |
|---|---|
| `start` | `info` |
| `sendMessage` | `sessionId, message, images, userSelectedFiles, messageUuid, toolStates, fileAttachments, contentBlocks, syntheticMessage, documentFunnelEnabled, seededSummon, extendedThinking, docxEditingCarveout, trailingContentBlocks, seededKind` |
| `setPermissionMode` | `sessionId, mode, _chromeAllowedDomains, options` |
| `setEffort` | `sessionId, effortLevel` |
| `setSpSectionPrompts` | `push` |

`docxEditingCarveout`、`documentFunnelEnabled` 说明有**文档类任务的专门通路**。

### 2.3 `Cowork` 家族（8 个服务）

| 服务 | 方法数 | 职责（由方法名判定，S） |
|---|---:|---|
| `CoworkSpaces` | 33 | 工作空间 CRUD |
| `CoworkArtifacts` | 24 | Artifact 全生命周期（见 §4） |
| `CoworkScheduledTasks` | 16 | 定时任务 |
| `CCDScheduledTasks` | 12 | Claude Code 定时任务 |
| `CoworkArtifactBridge` | — | 渲染侧桥接（`callMcpTool` / `askClaude` / `runScheduledTask` / `navigateHost` / `openExternalUrl`） |
| `CoworkStorage` / `CoworkUserFiles` / `CoworkMemory` / `CoworkFilePreview` / `CoworkFeedback` | — | 存储、用户文件、记忆、预览、反馈 |

---

## 3. ClaudeVM：真正的本地 VM 生命周期

`ClaudeVM` 服务方法（全部为 S）：

```
download                 startVM(options)           restartVM
getDownloadStatus        getRunningStatus           checkVirtualMachinePlatform
enableVirtualMachinePlatform                        restartAfterVMPInstall
isHostLoopModeEnabled    isHostLoopDevOverrideActive
setForceDisableHostLoop(value)                     setYukonSilverConfig(config)
```

配套证据：
- 镜像下载源 `https://downloads.claude.ai/vms/linux/`（字符串 S）。
- `checkVirtualMachinePlatform` / `enableVirtualMachinePlatform` / `restartAfterVMPInstall` → 需要 **Windows Hyper-V / Virtual Machine Platform** 才能在本地跑 Cowork。
- `AppxManifest` 注册 `CoworkVMService`（`localSystem`、`auto`），服务二进制 `cowork-svc.exe` 13.7 MB Go 程序，命名管道 `\\.\pipe\cowork-vm-service`。
- `isHostLoopModeEnabled` / `setForceDisableHostLoop` → 存在 "host loop" 模式开关（推断：让 VM 内的 loop 跑在 host 侧；**I 级**，P5 会验证）。

**分界规则（S）**：`surfaces:["cowork","coworkRoutines"]` 的 deny 规则 `cowork-local-tasks-off` 在 `!e.thirdParty() && e.coworkLocalTasksOff()` 时生效 → 说明 **1P 与 3P 的 Cowork 行为不同**；3P 走 `executionTarget:"desktop"` 的不同路径。

---

## 4. Artifact 机制（24 个方法，完整生命周期）

```
创建/导入            渲染/显示              版本               共享/发布
importArtifact       showArtifact           restoreArtifactVersion   shareArtifact
refreshImported…     hideArtifact           setArtifactLastModified… unshareArtifact
                     parkAndCapture…        getArtifactThumbnail     isSharingEnabled
                     reloadArtifactView     getArtifactHtml          setArtifactAutoPublish
                     printArtifactToPdf     getArtifactRepublish…    isAutoPublishEnabled
                     setArtifactName        getArtifactMetadata      isSharedContentCurrent
                     setArtifactStarred     deleteArtifact           deleteArtifact(removeFiles)
                     setArtifactMcpTools
```

关键洞察：
- `parkAndCaptureArtifact(bounds, targetWindowId)` → artifact 在**独立 BrowserWindow** 中渲染后截图，用于缩略图。
- `setArtifactMcpTools(artifactId, tools, toolServers)` → artifact 能绑定 MCP 工具。
- `printArtifactToPdf` + `DesignPdf.printFrameToPdf` → 有专门的 PDF 打印通道。
- `isAutoPublishEnabled` / `setArtifactAutoPublish` → artifact 可自动发布到云端。

---

## 5. 持久化映射（真实路径与文件名）

| 数据 | 位置/文件名 | 证据 |
|---|---|---|
| 会话记录 | `.claude/projects/` | 字符串 S |
| 设置 | `.claude/settings.json`、`.claude/settings.local.json` | S |
| 插件 | `.claude/plugins/`、`installed_plugins.json`、`known_marketplaces.json`、`plugin.json`、`marketplace.json` | S |
| 第三方配置 | `.claude.json`、`.mcp.json` | S |
| Cowork | `cowork/`（81 处引用）、`cowork_settings.json`、`spaces.json`、`scheduled-tasks.json`、`artifacts.json` | S |
| 窗口状态 | `window-state.json` | S |
| MSAL | `msal-cache.json` | S |
| 认证 | `auth.json` | S |
| 日志 | `logs/`（56 处）；MSIX 把 1P 日志重定向到 `%LOCALAPPDATA%\Claude\logs` | Manifest + S |
| 用户数据根 | `%LOCALAPPDATA%\Claude-Data`（1P）、`%LOCALAPPDATA%\Claude-3p`（3P） | AppxManifest 虚拟化排除注释 |
| 缓存 | `cache/`、`cached/`、`cache_fallback` | S |

`electron-store` 出现在代码中（3 处），但主配置仍是明文 JSON + 目录树。

---

## 6. 恢复语义（区分四种，避免混淆）

| 类型 | 证据 | 说明 |
|---|---|---|
| UI 恢复历史 | `confirmImportedSessionResume`、`CliSessionImport`、`HistoryImport`、`ClaudeAiImport` | 把历史导入/显示 |
| 进程内任务续跑 | `canAutoResume`、`retryStart`、`warmSession` | 同进程 |
| 跨进程冷恢复 | `restartRemoteSession`、`restartRemoteHelper`、`reinstallRemoteClaudeCode` | 重启远端 helper |
| 云端后台执行 | `RemoteControlServing`、`CloudMove`、`egressProxy*` | 云端执行、客户端只订阅 |

**重要**：`UI 恢复历史 ≠ Agent 真正恢复执行`。本轮没有任何 R 级证据能证明重启后 agent 从中断点继续跑，只能证明**存在用于恢复的 RPC 与状态文件**（S）。

---

## 7. 推理后端（企业版特有，重大发现）

380 条 feature flag 中，`inference*` 前缀共 40+ 条，表明企业版支持**多路推理后端**：

| 后端 | 相关 flag |
|---|---|
| Anthropic 官方 | `inferenceAnthropicApiKey`、`inferenceModels`、`inferenceMaxTokensPerWindow` |
| **AWS Bedrock** | `inferenceBedrockProfile`、`Region`、`BaseUrl`、`BearerToken`、`ServiceTier`、`SsoAccountId`、`SsoRegion`、`SsoRoleName`、`SsoStartUrl`、`WebIdentityRoleArn`、`AwsCliPath`、`AwsDir` |
| **Azure AI Foundry** | `inferenceFoundryApiKey`、`AuthFlow`、`BaseUrl`、`ClientId`、`Resource`、`TenantId` |
| **自建 Gateway** | `inferenceGatewayApiKey`、`AuthScheme`、`BaseUrl`、`ManagedClaudeCode`、`Oidc`、`OidcAuthFlow` |
| **IdP 直连** | `inferenceIdpAuthFlow`、`inferenceIdpOidc` |
| 凭据助手 | `inferenceCredentialHelper`、`Args`、`SilentRefreshEnabled`、`TtlSec`、`TimeoutSec`、`Windows`、`inferenceCredentialKind` |
| 成本核算 | `inferenceModelPricing`、`inferenceModelPricingEnabled`、`inferenceModelPricingMultiplier` |

这说明企业部署**可以完全不经过 claude.ai 后端**，这与"UI 从 claude.ai 加载"结合，形成两种部署形态：托管模式 vs 自建网关模式（后者需要 `bootstrapUrl`/`bootstrapOidc`/`bootstrapHeaders`）。

---

## 8. 管理面（MDM/策略）

186 个唯一 flag 中，大量是企业策略键，按类别：

| 类别 | 代表 flag |
|---|---|
| 功能开关 | `coworkTabEnabled`、`chatTabEnabled`、`codeTabEnabled`(推断)、`dictationEnabled`、`hardwareBuddyEnabled`、`claudeInChromeEnabled`、`autoModeEnabled`、`keepAwakeEnabled` |
| 安全/权限 | `disableBypassPermissionsMode`、`blockReadsOutsideWorkingDirectories`、`coworkEgressAllowedHosts`、`builtinBrowserBlockedDomains`、`claudeInChromePasswordManagersEnabled`、`coworkEDRIntegration`(+`Vendor`)、`coworkFileReadCheck`、`mcpPersistentAlwaysAllowEnabled` |
| 插件治理 | `allowedPluginMarketplaces`、`allowedPluginMcpServers`、`deniedPluginMcpServers`、`managedMcpServers`、`isDesktopExtensionSignatureRequired` |
| 数据保留 | `coworkSessionRetentionDays`、`chatSessionRetentionDays`、`codeSessionRetentionDays` |
| 网络 | `egressProxyUrl`、`egressProxyPacUrl`、`bootstrapUrl`、`bootstrapHeaders`、`bootstrapOidc` |
| 身份 | `loginSsoOrgDomain`、`forceLoginOrgUUID`、`entraClientId`、`entraScope`、`entraAzureCloud`、`disableMultiAccount` |
| 更新 | `disableAutoUpdates`、`autoUpdaterEnforcementHours`、`dangerousMaxVersion` |
| 遥测 | `disableEssentialTelemetry`、`disableNonessentialTelemetry`、`disableNonessentialServices` |

这些 flag 的 scope 分布：`3p` 304 条、`1p` 22 条、`3p,1p` 38 条、未知 14 条 —— **绝大多数是企业（3P）配置项**。

---

## 9. 未解 / 待验证

| 项 | 级别 | 说明 |
|---|---|---|
| Fast Mode 的具体实现 | U | `setFastMode` 存在，但"fast"指模型路由还是并行请求，静态无法断定 |
| `seededSummon` / `seededKind` 语义 | U | 出现在 sendMessage 参数，疑似"预置触发"，未找到定义 |
| `violinFret` / `gorse` / `baku` / `sable-otter` 代号 | U | 内部代号服务名，功能需进一步追踪 |
| Host loop 模式的真实行为 | I | 由 `isHostLoopModeEnabled`/`setForceDisableHostLoop` 推断，P5 验证 |
| 云端 agent loop 内部实现 | CLOUD-UNKNOWN | 不可得 |
| 恢复是否真能续跑 | U | 需 R 级实验（P7 阻塞） |

## 10. 产物

`index/EIPC-METHODS.tsv`(1,170)、`EIPC-EVENTS.tsv`(162)、`EIPC-SERVICES.tsv`(97)、`FEATURE-FLAGS.tsv`(380 行 / 186 唯一键)、`STRING-ENUMS.tsv`(1,179)。

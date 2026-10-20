# P4D — `LocalSessions` 329 个方法的完整能力分类

> 解决 `U-021`。此前只给了方法签名清单，这里按**能力域**归类并解释每组的语义。
> 这是一张"本地 Code 会话到底能做什么"的完整地图。

---

## 1. 会话生命周期（约 22 个）

```
start(info)                 创建（cwd + message 必填，可选 worktree/branch）
forkSession                 从某条消息分叉
detachFromParent            分离
clearSession                清空
archive / unarchive         归档
delete                      删除
updateSession               更新元数据
setCustomGroups             自定义分组
getSession / getAll / getSessionList / loadArchivedSessions
getLocalSessionIdForBridgeId    桥接 id ↔ 本地 id 映射
resumePreClearSession       清空后恢复
prewarmFolderless / prewarmLocal / discardPrewarm / changeCwd   预热与切换目录
```

## 2. 消息发送与队列（约 14 个）

```
sendMessage(17 参数)         主发送路径（见 P4C）
cancelQueuedMessage          取消排队
reorderQueuedMessage         调整排队顺序
promoteQueuedMessage         提升排队消息为立即发送
sendSteeredNow               **立即转向**（跳过排队，插入当前轮）
interrupt                    中断
stop                         停止
stopTask                     停止子任务
getTaskOutput                取任务输出
backgroundTasks / setBackgroundTasksShortcutArmed    后台任务视图
```

`sendSteeredNow` + `promoteQueuedMessage` + `reorderQueuedMessage` 三者并存，说明**输入队列是可编排的**：用户可以排队多条、调整顺序、或直接插队。

## 3. 回退与撤销（约 11 个）

```
rewind / rewindV2            回退到某个点
rewindToRefusedPrompt        回退到被拒绝的提示
rewindFiles                  回退文件改动
undoRewind                   撤销回退
switchRewindMark             切换回退标记
discardPendingTurn           丢弃待处理轮次
getUncommittedChanges / getUncommittedChangesByFolder
discardKeptWorktree          丢弃保留的 worktree
```

这组是本次最重要的发现之一：**会话有完整的"时间旅行"能力** —— 不仅回退对话，还能**回退文件改动**（`rewindFiles`），并区分"未提交改动"（`getUncommittedChanges`）。

## 4. 侧对话（约 6 个）

```
startSideChat / sendSideChatMessage / stopSideChat / interruptSideChat
startBtwChild / closeBtwChild
```

`Btw` = "by the way"，即**旁支追问**：不打断主线，开一个临时对话问问题，然后回到主线。

## 5. Git 与代码状态（约 20 个）

```
getGitInfo / getGitDiff / getGitDiffStats / getDiffFileContent / getDiffFileImage
getGitDiffFilePatch / getGitCommits / getCommitDiff / refreshGitState / invalidateGitDiffCache
getLocalBranches / getUncommittedChanges(ByFolder)
getCodeStats / getDetectedProjects
getInstalledEditors / openInEditor
```

**注意 `getDiffFileImage`** —— 能取二进制/图片文件的 diff 展示，说明 diff 视图不只处理文本。

## 6. 转写（transcript）（约 9 个）

```
getTranscript / getTranscriptTail / getTranscriptPage / readTranscript
requestTranscriptPort        请求一个端口用于流式读
searchSessions               跨会话搜索
reportTranscriptLoadEarlier / reportTranscriptWindowBackfill   埋点
```

`requestTranscriptPort` 说明**转写通过端口流式读取**，不是整块返回 —— 与 `transcript-search-worker` 配合。

## 7. 会话文件与目录（约 30 个）

```
pickSessionFile / pickFileAtCwd / readFileAtCwd / listDirectoryAtCwd
readSessionFile / readSessionFileWithStatus / writeSessionFile / createSessionFile
listSessionDirectory / watchSessionDirectories
showSessionFileInFolder / showSessionFilePreview / openSessionFileInDefaultApp
resolveSessionFile / isSessionPathGone / getSessionFilePlacement
readSessionImageAsDataUrl / readSessionMediaAsDataUrl / readSessionPanelMediaAsDataUrl
getSessionImageStreamUrl / getSessionMediaStreamUrl / getSessionPanelMediaStreamUrl
readSessionPanelDocumentAsDataUrl
suggestFolderForSessionFile / addSuggestedFolderForSessionFile
revealRemotePath
```

三种读取形态并存（S）：`AsDataUrl`（内联）、`StreamUrl`（流式）、`PanelDocument`（面板文档）。说明会话产物可以是图片、媒体、文档三类。

## 8. Shell / PTY（约 12 个）

```
startShellPty / stopShellPty / resizeShellPty / writeShellPty
getBusyShellPtyKeys / setShellPtyTitle / getTerminalShells
runBashCommand / interruptBashCommand
```

与 `pty-host` worker（ConPTY + scrollback）对应。`getBusyShellPtyKeys` 说明能查询哪些终端忙碌。

## 9. 权限与信任（约 12 个）

```
respondToToolPermission             工具权限应答
respondToRefusalFallbackPrompt      拒绝后的回退提示
respondToAutoModeServerFallbackPrompt
respondToLanyardConsent             Lanyard 同意（代号）
respondToViolinBowPrompt            ViolinBow 提示（代号，与 ViolinFret 同族）
checkTrust / checkStoredTrust / saveTrust
answerPendingCwdTrust               目录信任
getDefaultPermissionMode / setPermissionMode
```

**五个不同的"应答"入口**，说明权限交互有多种触发源（工具、拒绝回退、自动模式回退、Lanyard、ViolinBow）。

## 10. MCP（约 15 个）

```
getAgents / createAgent
getMcpServers / setMcpServers / replaceRemoteMcpServers / replaceEnabledMcpTools
getLocalMcpServers / getSessionCliMcpServers
mcpAuthenticate / mcpReconnect / mcpRetryConnection / mcpSubmitOAuthCallbackUrl
mcpAuthenticateConfigServer / mcpClearAuth / mcpEnableServer
mcpCallTool / mcpReadResource / mcpListResources
sessionConnectorToggleStarted / respondSessionConnectorToggle
remoteStartMcpConfigStarted / respondRemoteStartMcpConfig
getProxiedConnectorCall
```

**MCP 是会话级可配的**：每个会话可以有自己的 MCP 服务器集合与启用的工具集（`replaceEnabledMcpTools`），并且 MCP 的 OAuth 流程由会话 RPC 驱动（`mcpSubmitOAuthCallbackUrl`）。

## 11. 会话内 Agent 与设置（约 20 个）

```
getAgents / createAgent              子代理
setModel / setEffort / setFastMode / setExtendedThinking
setPermissionMode / setChipLevel(+Preference)
getSupportedCommands                 CLI 支持的命令列表
getSSHDraftCommandNames
writeAutoModeProposalFile / cleanupAutoModeProposalFile    自动模式提案文件
launchUltrareview                    **Ultrareview**（代号，深度评审）
submitFeedback
```

`getSupportedCommands` 是关键：**Desktop 会向 CLI 查询它支持哪些斜杠命令**，说明命令集是运行期协商的，不是硬编码。

## 12. 埋点与诊断（约 20 个，方法名以 report 开头）

```
logCliEvent
reportSwitchTiming / reportSwitchInitiated / reportSwitchAbandoned
reportSessionListHint / reportComposerInp / reportStreamRender
reportRunFollowUp / reportSessionDeadEnd / reportArtifactsReset
reportSessionListLoad / reportTranscriptLoadEarlier / reportTranscriptWindowBackfill
getPersisted…
```

这批是**纯遥测上报**，揭示了产品关注的性能/体验指标：切换耗时、会话列表加载、输入框交互、流式渲染、后续追问率、会话死胡同率、artifact 重置。

## 13. 待办与提示（约 6 个）

```
setAvailableNextActions       设置可用下一步动作
markPeerMessagesRead          标记对端消息已读
setSessionPaneMenuState       面板菜单状态
completeSessionViewRequest / completeCodeSettingRequest / completeStartTargetsRequest
```

`complete*Request` 三个是**"完成某个请求"的应答通道**，与 `requestXxx` 成对。

## 14. 其他

| 方法 | 语义 |
|---|---|
| `dropsHostReplyStamp()` | 探测宿主是否会丢弃回复时间戳 |
| `checkGitAvailable`（在 `ClaudeCode` 服务） | Git 可用性 |
| `createScratchWorkspace` | 创建临时工作区 |
| `switchRewindMark` | 切换回退标记 |

## 15. 统计与结论

| 能力域 | 方法数（约） |
|---|---:|
| 会话生命周期 | 22 |
| 消息发送与队列 | 14 |
| 回退与撤销 | 11 |
| 侧对话 | 6 |
| Git 与代码状态 | 20 |
| 转写 | 9 |
| 会话文件与目录 | 30 |
| Shell/PTY | 12 |
| 权限与信任 | 12 |
| MCP | 15 |
| Agent 与设置 | 20 |
| 埋点与诊断 | 20 |
| 待办与提示 | 6 |
| 其他 | 约 132（含大量 `getXxx` 查询与内部状态方法） |
| **合计** | **329** |

**结论**：`LocalSessions` 不是一个"发消息的接口"，而是**一个完整的 IDE 级会话运行时**：它管理代码状态、文件、终端、MCP、权限、回退、埋点。这也解释了为什么 Desktop 要 spawn 一个 `claude` CLI 而不是自己实现 agent loop —— 它把 CLI 当作执行引擎，自己提供这一整套宿主能力。

## 16. 证据

`ledgers/EIPC-METHODS.tsv` 中 `LocalSessions` 的 329 行（含每行参数表）。
字段级语义见 `P4C-SENDMESSAGE-SCHEMA.md`（`sendMessage` 17 参数已完整还原）。

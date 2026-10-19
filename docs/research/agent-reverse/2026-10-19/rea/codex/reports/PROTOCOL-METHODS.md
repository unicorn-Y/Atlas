# Codex app-server RPC 方法全表（172 项）

来源：`codex app-server generate-json-schema --experimental` 生成的真实协议定义（`decompiled/app-server-schema/ClientRequest.json`）。
证据等级：**S**（官方二进制自生成的协议 schema）。

## account (15)
- `account/bedrock/checkGovCloudRequirements`
- `account/bedrock/discover`
- `account/bedrock/setup`
- `account/gatewayOAuth/cancel`
- `account/gatewayOAuth/login`
- `account/gatewayOAuth/read`
- `account/login/cancel`
- `account/login/start`
- `account/logout`
- `account/rateLimitResetCredit/consume`
- `account/rateLimits/read`
- `account/read`
- `account/sendAddCreditsNudgeEmail`
- `account/usage/read`
- `account/workspaceMessages/read`

## app (3)
- `app/installed`
- `app/list`
- `app/read`

## collaborationMode (1)
- `collaborationMode/list`

## command (4)
- `command/exec`
- `command/exec/resize`
- `command/exec/terminate`
- `command/exec/write`

## config (4)
- `config/batchWrite`
- `config/mcpServer/reload`
- `config/read`
- `config/value/write`

## configRequirements (1)
- `configRequirements/read`

## environment (3)
- `environment/add`
- `environment/info`
- `environment/status`

## experimentalFeature (2)
- `experimentalFeature/enablement/set`
- `experimentalFeature/list`

## externalAgentConfig (4)
- `externalAgentConfig/detect`
- `externalAgentConfig/import`
- `externalAgentConfig/import/readHistories`
- `externalAgentConfig/import/recordHistory`

## feedback (1)
- `feedback/upload`

## fs (9)
- `fs/copy`
- `fs/createDirectory`
- `fs/getMetadata`
- `fs/readDirectory`
- `fs/readFile`
- `fs/remove`
- `fs/unwatch`
- `fs/watch`
- `fs/writeFile`

## fuzzyFileSearch (4)
- `fuzzyFileSearch`
- `fuzzyFileSearch/sessionStart`
- `fuzzyFileSearch/sessionStop`
- `fuzzyFileSearch/sessionUpdate`

## hooks (1)
- `hooks/list`

## initialize (1)
- `initialize`

## marketplace (3)
- `marketplace/add`
- `marketplace/remove`
- `marketplace/upgrade`

## mcpServer (5)
- `mcpServer/event/stream/start`
- `mcpServer/event/stream/stop`
- `mcpServer/oauth/login`
- `mcpServer/resource/read`
- `mcpServer/tool/call`

## mcpServerStatus (1)
- `mcpServerStatus/list`

## memory (2)
- `memory/reset`
- `memory/status`

## mock (1)
- `mock/experimentalMethod`

## model (1)
- `model/list`

## modelProvider (1)
- `modelProvider/capabilities/read`

## permissionProfile (1)
- `permissionProfile/list`

## plugin (13)
- `plugin/install`
- `plugin/installed`
- `plugin/list`
- `plugin/read`
- `plugin/reconcile`
- `plugin/search`
- `plugin/share/checkout`
- `plugin/share/delete`
- `plugin/share/list`
- `plugin/share/save`
- `plugin/share/updateTargets`
- `plugin/skill/read`
- `plugin/uninstall`

## process (4)
- `process/kill`
- `process/resizePty`
- `process/spawn`
- `process/writeStdin`

## project (7)
- `project/create`
- `project/delete`
- `project/import`
- `project/list`
- `project/move`
- `project/read`
- `project/update`

## remoteControl (7)
- `remoteControl/client/list`
- `remoteControl/client/revoke`
- `remoteControl/disable`
- `remoteControl/enable`
- `remoteControl/pairing/start`
- `remoteControl/pairing/status`
- `remoteControl/status/read`

## review (1)
- `review/start`

## rollout (1)
- `rollout/compress`

## server (1)
- `server/diagnostics`

## skills (3)
- `skills/config/write`
- `skills/extraRoots/set`
- `skills/list`

## thread (52)
- `thread/approveGuardianDeniedAction`
- `thread/archive`
- `thread/attachment/add`
- `thread/attachment/list`
- `thread/attachment/remove`
- `thread/attachmentOwner/list`
- `thread/backgroundTerminals/clean`
- `thread/backgroundTerminals/list`
- `thread/backgroundTerminals/terminate`
- `thread/compact/start`
- `thread/decrement_elicitation`
- `thread/delete`
- `thread/fork`
- `thread/goal/clear`
- `thread/goal/get`
- `thread/goal/set`
- `thread/increment_elicitation`
- `thread/inject_items`
- `thread/items/list`
- `thread/items/read`
- `thread/list`
- `thread/loaded/list`
- `thread/memoryMode/set`
- `thread/metadata/update`
- `thread/name/set`
- `thread/prediction/request`
- `thread/queue/add`
- `thread/queue/delete`
- `thread/queue/list`
- `thread/queue/reorder`
- `thread/queue/start`
- `thread/queue/update`
- `thread/read`
- `thread/readState/update`
- `thread/realtime/appendAudio`
- `thread/realtime/appendSpeech`
- `thread/realtime/appendText`
- `thread/realtime/listVoices`
- `thread/realtime/start`
- `thread/realtime/stop`
- `thread/resume`
- `thread/revert`
- `thread/search`
- `thread/searchOccurrences`
- `thread/section/move`
- `thread/settings/update`
- `thread/shellCommand`
- `thread/start`
- `thread/timeline/list`
- `thread/turns/list`
- `thread/unarchive`
- `thread/unsubscribe`

## threadSection (4)
- `threadSection/create`
- `threadSection/delete`
- `threadSection/list`
- `threadSection/update`

## turn (4)
- `turn/interrupt`
- `turn/settings/update`
- `turn/start`
- `turn/steer`

## userVerification (5)
- `userVerification/cancel`
- `userVerification/delete`
- `userVerification/enroll`
- `userVerification/status`
- `userVerification/verify`

## windowsSandbox (2)
- `windowsSandbox/readiness`
- `windowsSandbox/setupStart`

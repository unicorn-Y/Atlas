# P4C — `LocalSessions.sendMessage` 的参数语义（由校验函数反推）

> 解决 `U-021` 的主要部分。方法有 17 个参数，压缩后名字仍保留，但字段结构要靠**校验函数体**还原。
> 下面是逐个参数的真实字段集（来自 `DMt` / `MOt` / `jOt` / `Djt` / `Tjt` 等 validator 函数体）。

---

## 1. `sendMessage(sessionId, message, ...)` 17 个参数

| # | 参数 | 类型/结构 | 语义 |
|---|---|---|---|
| 1 | `sessionId` | string | 会话 id |
| 2 | `message` | string | 用户文本 |
| 3 | `images` | `Image[]` | 图片附件 |
| 4 | `toolStates` | `ToolState[]` | 工具的当前状态（用于续跑/回放） |
| 5 | `attachments` | `Attachment[]` | 文件附件 |
| 6 | `priority` | string? | 消息优先级 |
| 7 | **`steeringGates`** | object | 见 §2 |
| 8 | `messageUuid` | string? | 幂等键 |
| 9 | **`seededSummon`** | boolean? | 见 §3 |
| 10 | `typedText` | string? | 用户手打的原始文本（与 `message` 区分） |
| 11 | **`sessionMentions`** | `{sessionId,title}[]` | 见 §4 |
| 12 | **`paneHolds`** | `{uuids[],earlierCursor?}` | 见 §5 |
| 13 | `seededKind` | string? | 预置类型 |
| 14 | `pastes` | string[] | 粘贴记录 |
| 15 | **`marks`** | object[] | 见 §6 |

## 2. `steeringGates`（validator `DMt`）

字段（全部可选布尔）：

```
ccdSteering          — 是否启用 Claude Code 的"舵"（steering）机制
queuedMessageBar     — 排队消息栏
sessionPresets       — 会话预设
steerDetach          — 转向时是否脱离
asides               — 侧对话（side chat）
```

**语义**：这不是"内容"，而是**本次发送时启用的交互能力开关集合**。即在提交一条消息时，同时声明"这条消息是否允许被中途转向、是否走排队、是否开侧对话"等。
`ccdSteering` 直接对应 Claude Code 的 steering（用户可在模型执行中插话改向）。

## 3. `seededSummon` / `seededKind`

- `seededSummon`: boolean
- `seededKind`: string

**语义（I，依据命名与同组字段）**：用于**程序化预置一次触发** —— 不是用户输入的，而是由 UI 动作（按钮、菜单、深链）"召唤"出来的消息。`seededKind` 标明这种预置的类型（如某个快捷动作的标识）。

它们是布尔+字符串的组合，典型形态是"`seededSummon=true` 且 `seededKind='some-action'`"，让后端知道这条消息来自预置动作而非自由输入。

## 4. `sessionMentions`（validator `Tjt`）

```
{ sessionId: string, title: string, ... }
```

**语义**：消息里 `@` 提到的**其它会话**。字段只有 `sessionId` + `title`（标题用于渲染 chip）。
相邻的 validator 还接受 `atMessageUuid`、`attachesThroughArchived` —— 说明 @ 可以精确指到某条消息，且允许跨归档会话引用。

## 5. `paneHolds`（validator `MOt`）

```js
function MOt(e){
  return !(!e || typeof e !== "object"
    || !(Array.isArray(e.uuids) && e.uuids.every(x => typeof x === "string"))
    || (e.earlierCursor !== undefined && typeof e.earlierCursor !== "string"));
}
```

**语义**：`uuids[]` 是**被"握住"（hold）的消息 id 列表**，`earlierCursor` 是可选的游标（指向更早位置）。
结合同文件的枚举 `new Set(["sent","gone","unreadable","unsent"])`（相邻代码），`paneHolds` 用于**分栏/多窗格场景下，声明某个窗格当前锚定在哪批消息上**——避免多窗格滚动静默同步。

## 6. `marks`（validator `jOt`）

```js
function jOt(e){
  return !(!e || typeof e !== "object"
    || (e.modelAuthored !== undefined && typeof e.modelAuthored !== "boolean")
    || (e.editedDraftText !== undefined && typeof e.editedDraftText !== "string")
    || (e.personSent !== undefined && typeof e.personSent !== "boolean"));
}
```

字段：

| 字段 | 类型 | 语义 |
|---|---|---|
| `modelAuthored` | boolean | 该 mark 由模型产生（vs 用户） |
| `editedDraftText` | string | 用户编辑过的草稿文本 |
| `personSent` | boolean | 是否由人发送 |

**语义**：`marks` 是**消息的归因/来源标记**，用于事后区分"模型写的 / 人改过的 / 人发的"。
相邻 validator 还有 `at:number`、`state:string`、`respondedAt?:number` —— 说明 mark 也记录时间点与响应状态。

## 7. `start(info)` 的参数（validator `Djt`）

| 字段 | 类型 | 语义 |
|---|---|---|
| `cwd` | string | **必填**工作目录 |
| `message` | string | **必填**首条消息 |
| `sessionId` | string? | 可指定（用于恢复） |
| `model` | string? | 模型 |
| `useWorktree` | boolean? | **是否用 git worktree** |
| `sourceBranch` | string? | worktree 的源分支 |
| `branchHint` | string? | 分支名提示 |

相邻 validator（`Ejt`）还接受：`path`（必填）、`useWorktree`、`sourceBranch`。
以及 `sendMessage` 的另一个变体接受：`systemPromptAppend`、`sessionMentions`、`messageUuid`、`agent`、`effort`、`effortSource`、`fastMode`、`remoteControlAtStart`。

**这条直接证实了 Code 会话的两种工作目录模式**：直接在 `cwd` 干，或 `useWorktree + sourceBranch` 开一个隔离 worktree。后者与 Atlas 自己的 worktree 工作流同构。

## 8. 其余特殊方法

| 方法 | 语义 |
|---|---|
| `dropsHostReplyStamp()` | 返回 boolean，**查询服务端是否丢弃"宿主回复戳"**（一个能力探测：宿主是否在回复里加时间戳/签名标记） |
| `getAdvisorSetting(sessionId)` | 读取该会话的 advisor 设置（`_Ot` 结构） |
| `setAvailableNextActions(sessionId, actions[])` | 设置"下一步可执行动作"列表，供 UI 渲染建议按钮 |
| `applyFlagSettings(sessionId, settings)` | 把 flag 设置为会话级 |
| `createOutputStyle(sessionId, description, name, cancelToken)` | 创建输出风格（**system prompt 变体**），带取消令牌 |
| `reviewRepository(sessionId, generation)` | 仓库审阅，`generation` 用于防过期 |

## 9. 证据

| 断言 | 锚点 |
|---|---|
| 17 参数完整列表 | `EIPC-METHODS.tsv` 中 `LocalSessions.sendMessage` 行 |
| steeringGates 字段 | `index.chunk-lzaSYO3Q.js` 函数 `DMt` |
| paneHolds 字段 | 同文件 `MOt` |
| marks 字段 | 同文件 `jOt` |
| start 字段 | 同文件 `Djt` |
| sessionMentions 字段 | 同文件 `Tjt` |
| 消息状态枚举 | 同文件 `new Set(["sent","gone","unreadable","unsent"])` |

# 06 · MCP、Skills 与企业集成

> 证据等级：**S**=源码直接可见，**R**=运行时观测，**D**=官方文档，**I**=推断，**U**=不可获得

---

## 1. MCP 的三层结构

Claude Desktop 里的 MCP 不是单一实现，是**三条独立通道**：

| 层 | 宿主 | 证据 | 用途 |
|---|---|---|---|
| 内置引擎 MCP | 引擎子进程 | `--mcp-config <json>` 内联参数（S） | 会话级 MCP server |
| 独立 MCP 宿主 | `mcp-runtime/directMcpHost.js`（613,700 B） | `serviceName: "Custom 3P MCP Host"`（S） | 第三方 MCP，**跨桌面与 CLI 共用** |
| 插件 MCP | `PluginBridgeMcp`（2 方法） | `plugin:${cliName}:${toolName}` 策略键（S） | 企业插件市场 |

`directMcpHost.js` 有注释明确写着它**不是桌面专属**：

```
// Desktop and CLI share the same MCP host process.
```

这一点从 IPC 面能反证：`PluginBridgeMcp` 只有 **2 个方法**，是三层里最薄的——因为大部分工作在独立进程里。

---

## 2. MCP 传输类型（S，Zod schema）

从 `index.chunk-DNyequwM.js` @823817 的 schema 定义可读出**完整的 MCP 配置模型**：

```js
// 标准 I/O
$ge = H(() => L({
  type: V("ws-ide"),
  url: M(),
  ideName: M(),
  authToken: M().optional(),
  ideRunningInWindows: P().optional(),
  timeout: M2().optional(),
  alwaysLoad: P().optional(),
  role: j2()
}))

// HTTP
R2 = H(() => L({
  type: B(["http", "streamable-http"]).transform(() => "http"),
  url: M(),
  headers: z(M(), M()).optional(),        // header 名 → 值
  headersHelper: M().optional(),          // 动态 header 生成器
  oauth: F2().optional(),
  timeout: M2().optional(),
  request_timeout_ms: N2(),
  tools: I(I2()).optional(),
  alwaysLoad: P().optional(),
  bareElicitationCapability: P().optional(),
  discoveryCache: P().optional(),
  role: j2(),
  toolPermissions: ...
}))
```

要点：

1. **`type` 归一化**：`"streamable-http"` 被 `transform` 成 `"http"` —— 对外兼容两种写法，内部只有一种。
2. **`headersHelper`** —— header 不是静态的，可以是**可执行助手**（用于动态 token）。
3. **`oauth`** —— 支持 OAuth 流程，含 `F2()` 的完整 OAuth 配置。
4. **`request_timeout_ms`** 与 `timeout` 两个超时字段并存 —— 一个是单请求，一个是整体。
5. **`discoveryCache`** —— 工具发现结果有缓存，说明 `tools/list` 是昂贵操作。
6. **`bareElicitationCapability`** —— **elicitation**（向用户追问）能力是可选协商的。
7. **`role`** —— MCP server 有角色概念（`j2()` 枚举）。
8. **`alwaysLoad`** —— 可以强制常驻加载，不按需启动。

`ws-ide` 这个类型名说明有一类 MCP server 是 **IDE 集成**（VS Code / Cursor 之类），且带 `ideRunningInWindows` 标志——WSL 场景下需要区分。

---

## 3. MCP 相关 IPC 面

| IPC 类 | 方法数 | 代表方法 |
|---|---|---|
| `PluginBridgeMcp` | 2 | — |
| `Launch` 中的 MCP 子集 | — | `callRemoteBrowserTool`、`listRemoteBrowserTools` |

`LocalSessions` 的 339 个方法里有大量 MCP 生命周期方法（S）。

MCP 工具在权限系统里的键格式（S）：

```
plugin:${cliName}:${toolName}
```

即 **MCP 工具的授权粒度是"插件 × CLI 名 × 工具名"三元组**，不是工具名本身。

MCP 策略失败时的行为（S）：

```
"${d} Plugin MCP scan failed while an MCP policy is active;
 refusing to start session with unenforced plugin"
```

fail-closed：扫描失败就拒绝启动会话，而不是放行未策略化的插件。

---

## 4. 内置 Skills（S）

`app.asar/resources/bundled-skills/` 下有 6 个内置技能，`manifest.json` 结构：

```json
{
  "agentSkillsRef": "1792020044",
  "skills": [
    { "name": "docx",        "tier": "always", "description": "…" },
    { "name": "pdf",         "tier": "always", "description": "…" },
    { "name": "pdf-reading", "tier": "always", "description": "…" },
    { "name": "pptx",        "tier": "always", "description": "…" },
    { "name": "xlsx",        "tier": "always", "description": "…" },
    { "name": "frontend-design", "tier": "…" }
  ]
}
```

关键字段：

- **`agentSkillsRef: "1792020044"`** —— 版本引用，用于判断是否需要重新拉取
- **`tier: "always"`** —— 技能分档。`always` 表示**常驻在上下文里**，不按需加载

### 4.1 描述文本本身的信息量

`docx` 的描述里有一句非常能说明设计的东西：

> "However, if they ask for a document, page, report, memo, or notes WITHOUT naming a file format and the session offers Claude's own dedicated document or page skill or connector, use that instead, even if they will email or print it."

这是**技能优先级裁决规则**：没有明确文件格式时，优先用 Claude 自己的文档能力，而不是 docx 技能。这种规则写进描述文本，说明技能的触发是**纯语义匹配**，没有硬编码路由。

`pdf` vs `pdf-reading` 的分工也是写死在描述里的：

- `pdf` → 创建、合并、拆分、水印、表单、加密、OCR
- `pdf-reading` → 读、检查、抽取、光栅化、选读取策略

两者明确互斥，描述里各写了 "Do NOT use … use the … skill instead"。

### 4.2 技能授权机制

回到 `02-agent-loop.md` §2 的 argv 构造：

```js
skills: "all"        → --allowedTools 追加 "Skill"
skills: ["docx","pdf"] → --allowedTools 追加 "Skill(docx)","Skill(pdf)"
```

即技能在引擎侧是**一个叫 `Skill` 的工具**，具体技能是它的参数。授权粒度是 `Skill(<name>)`。

---

## 5. Office 集成

`app.asar/resources/office365-mcp/` 是 Office 365 的 MCP 实现，含 `pdfExtractorProcess.mjs`（独立 PDF 抽取进程）。

`AppxManifest.xml` 里有：

```xml
<uap:Extension Category="windows.office.trustedCatalog">
```

即**注册为 Office 可信加载项目录**。

对应 IPC 类 `OfficeAddinFiles`（17 方法，S）—— 桌面端负责把 Office 加载项文件写到正确位置。

推断（**I**）：Claude 能以 Office 加载项形式出现在 Word/Excel/PowerPoint 里，桌面端是安装器与文件提供者。

---

## 6. 插件体系

### 6.1 插件在 CLI 上的表示（S）

```js
// 本地插件
plugins: [{ type: "local", path: "…", skipMcpDiscovery: false }]
  → --plugin-dir <path>
  → 或 --plugin-dir-no-mcp <path>

// 非本地插件
else throw Error(`Unsupported plugin type: ${e.type}`)
```

**只支持 `type: "local"`**。远程插件在 CLI 层不支持，只能通过其他通道。

### 6.2 插件相关 feature flag（S）

```
ccdPlugins                 ccdPluginSourceRouting
ccdSshStartsWithoutBlockedPlugins
```

`ccdPlugins` 是总开关，`ccdPluginSourceRouting` 控制插件来源路由。

### 6.3 插件策略（S）

- 策展来源仓库：`anthropics/knowledge-work-plugins`
- 策略键：`plugin:${cliName}:${toolName}`
- 门控函数：`s()` / `c()`，检查 `isMcpb`、`signatureRequired`、`directoryEnabled`、`allowedPluginServers`

**`isMcpb`** —— `.mcpb` 是 MCP Bundle 格式（MCP server 的打包分发格式）。
**`signatureRequired`** —— 插件可要求签名验证。

---

## 7. 第三方历史导入

`index.chunk-BPjIr-mn.js`（50,076 B）是一个**独立的导入子系统**，功能是把竞品的历史会话搬进 Claude。

### 7.1 可确认的事实（S）

| 项 | 值 |
|---|---|
| Sentry debug id | `sentry-dbid-9cf4e251-4f17-48c2-88cd-201ac3410330` |
| 遥测事件名 | `desktop_third_party_history_import` |
| 环境变量 | `CLAUDE_DESKTOP_SIBLING_IMPORT_ORG` |
| 导入对象 | ChatGPT / Codex 等同级应用的会话历史 |

### 7.2 导入的错误处理（S，原文）

```
a scheduled-task store is not loaded
could not be written
MCP servers found: ${r}, left to Settings › Import
deferred: plugins: the organization-policy gate holds them
```

最后一条说明：**插件导入受组织策略门控**，策略不放行就延后（deferred），不失败。

### 7.3 组织策略判定结果（S）

```
allowed (managed configuration)
allowed (organization setting)
key present but not honoured: names another organization
not enabled for this organization
```

四种结果，其中 `key present but not honoured: names another organization` 特别有意思 —— 配置里带了组织标识但**不是当前组织**，会被忽略。这是防跨组织配置串用的检查。

### 7.4 对应的 IPC 面

`HistoryImport` 类，**15 个方法**（S）：

```
enumerateSessionSources      getAutoImportStatus
getImportCapabilities        getImportHistory
getRemovePreview             importSessionSources
importSourceExtras           instructionTextAdded
listInstructionTexts         listSourceExtras
onAutoImportStatus           onImportProgress
removeAllImportRuns          removeImportRun
```

`getImportCapabilities` 说明能力是**动态协商**的（不同版本/不同组织能导的东西不同）。`listInstructionTexts` / `instructionTextAdded` 说明连**自定义指令**也会被导入。

---

## 8. 定时任务

独立的调度 chunk：`index.chunk-1lJXcT8c.js`（41,464 B，`cron` 出现 **133** 次）。

相关 IPC 类：

- `CCDScheduledTasks`（13 方法）
- `LocalSessions` 里的 `runScheduledTask` / 「scheduled task store」

相关 feature flag：`wakeScheduler` `keepAwake` `codeSessionKeepAwake` `mcpScheduledTaskAlwaysAllow` `mcpScheduledTaskApprovalLifetime` `coworkScheduledTaskProjects` `coworkScheduledTaskRepoint`

偏好（S）：`coworkScheduledTasksEnabled` / `ccdScheduledTasksEnabled` / `wakeSchedulerApprovedThisCycle` / `wakeSchedulerRegisteredAtVersion` / `wakeSchedulerCourtesyFlippedKeepAwake` / `wakeSchedulerDisableEmitted`

这组偏好键讲了一个完整的故事：**定时任务需要唤醒机器**（`wakeScheduler`），所以有"本周期是否已批准"、`"注册时的版本"`、`"是否已礼貌地转为 keepAwake"`、`"是否已发出禁用提示"` 四个状态位。

`scheduled` 也是一个权限决策选项（`ToolPermissionBroker` 的 `case "scheduled"`）—— 即"为定时任务永久允许"。

`mcpScheduledTaskApprovalLifetime` 说明定时任务的 MCP 授权有**独立有效期**。

---

## 9. 遥测与配置下发

### 9.1 遥测维度（S，26 个）

```
product_surface  desktop_variant  deployment_mode
config_source  config_source_remote
inference_provider  inference_host_kind
app_version  commit_hash
platform  arch  os_version  os_release  os_build
linux_distro_id  linux_distro_version_id
linux_session_type  linux_desktop_environment
cpu_model
app_session_id  organization_id
vm_network_mode
error_code  error_kind  backend_error_code
nest_local_user
```

`inference_provider` / `inference_host_kind` 是**第三方推理端点**（`CUSTOM3P_*` 窗口）的埋点。
`nest_local_user` —— `nest` 是内部构建代号（`isNestBuild`、`claude-nest` channel）。

### 9.2 第三方 SDK 存在（S）

从 `ion-dist` 的 vendor chunk 可直接看出前端依赖：

```
vendor-datadog-CvLFlOEm.js     148,766 B   ← Datadog RUM
vendor-growthbook-CmLwKXoy.js   42,836 B   ← GrowthBook（特性开关）
vendor-sentry-*                            ← Sentry（错误上报）
vendor-zod-fszujTq6.js         101,522 B   ← Zod（运行时校验）
vendor-query-Dqcf4jOo.js        43,467 B   ← TanStack Query
vendor-router-DOqjo6Uj.js       80,038 B   ← 路由
vendor-motion-DKLOEafD.js      140,176 B   ← Framer Motion
vendor-prosemirror-*           214,007 B   ← ProseMirror
vendor-tiptap-*                150,436 B   ← TipTap（编辑器）
vendor-markdown-*              144,589 B   ← Markdown 渲染
vendor-intl-Db7hDWRO.js         48,564 B   ← 国际化
vendor-base-ui-BAzDEXDQ.js      31,433 B   ← 基础 UI
vendor-icons-CjL3IfnG.js         7,279 B   ← 图标
vendor-utils-h7KXFLrg.js        27,180 B   ← 工具库
```

**三套遥测并存**：Datadog（RUM）、Sentry（错误）、GrowthBook（flag 与服务端配置）。

编辑器栈是 **ProseMirror + TipTap + Markdown** 三件套 —— 说明输入框不是简单 textarea，是完整富文本编辑器（支持斜杠命令、@提及、附件等）。

### 9.3 产物渲染库

`app.asar/resources/artifact-libs/`：

```
chart.js   ← 图表
gridjs     ← 表格
mermaid    ← 图表/流程图
```

这三个库是**预打包**给 artifact 用的 —— 模型生成的 HTML artifact 可以直接 `<script src>` 引用，不需联网。

---

## 10. 边界

- **U**：MCP server 的具体协议实现在 `directMcpHost.js` 内，本次只做了符号/字符串级分析，未逐函数逆向。
- **U**：OAuth 流程的服务端部分。
- **U**：插件市场（`anthropics/knowledge-work-plugins`）的内容与签名验证细节。
- **I**：Office 加载项的具体交互 —— 只有 manifest 声明和文件名，未见运行时。
- **未做**：`bundled-skills/` 下 6 个技能的实际 `SKILL.md` 内容 —— 只读了 manifest。这是有意的，因为技能内容本身是提示词，不是产品实现。

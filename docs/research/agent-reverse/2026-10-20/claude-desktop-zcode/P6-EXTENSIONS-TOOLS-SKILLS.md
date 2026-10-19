# P6 — 旁支：技能、MCP、扩展、Worker、环境变量、Feature Flags

> 全部静态。所有结论带文件锚点。

---

## 1. 六个内置技能（真实内容，非仅文件名）

`resources/bundled-skills/manifest.json` 的 `agentSkillsRef` = `1792020044`（技能集版本）。

| 技能 | 包内字节 | 内部文件数 | 结构 | tier |
|---|---:|---:|---|---|
| `docx` | 163,372 | 61 | `SKILL.md` + `scripts/`（accept_changes / merge_runs / comment / templates/*.xml） | `always` |
| `pptx` | 173,007 | 57 | `SKILL.md` + `scripts/`（apply_theme.js / thumbnail.py / add_slide.py / clean.py / office/validate.py / office/soffice.py） | `always` |
| `xlsx` | 155,709 | 53 | `SKILL.md` + `scripts/`（recalc.py / office/validate.py / office/soffice.py / office/helpers/pptx_*.py） | `always` |
| `pdf` | 21,600 | 12 | `SKILL.md` + `REFERENCE.md` + `FORMS.md` + `scripts/`（fill_fillable_fields / convert_pdf_to_images / extract_form_structure / …） | `always` |
| `pdf-reading` | 7,997 | 3 | `SKILL.md` + `REFERENCE.md`（只读，明确与 `pdf` 分工：读 vs 写） | `always` |
| `frontend-design` | 8,125 | 2 | `SKILL.md` + `LICENSE.txt`（纯指导文本，无脚本） | `always` |

**关键点（S）**：
- 全部是 **ZIP 容器**（magic `PK\x03\x04`），内部根目录与技能同名，主文件为 `SKILL.md`。
- `tier: "always"` —— 意味着不是“按需检索”，而是**默认随会话提供**。
- `docx` / `pptx` / `xlsx` 三个都依赖 `scripts/office/soffice.py`（LibreOffice 转换），说明执行时需要本机或 VM 内有 LibreOffice。
- `pdf-reading` 与 `pdf` 是**同一领域的读写分离**：前者只读+光栅化，后者创建/填表/合并/加密。

## 2. 技能如何被交给模型（关键机制，S）

Desktop **不自己执行技能**。证据链：

1. 主进程把技能目录与开关转成环境变量注入 `claude` 子进程：

```js
...e.workspace.disableBundledSkills && { CLAUDE_CODE_DISABLE_BUNDLED_SKILLS: "1" }
...r && { CLAUDE_CODE_DISABLE_OFFICIAL_MARKETPLACE_AUTOINSTALL: "1" }
```

2. 管理策略 `disableBundledSkills` 的声明（原样）：

```js
disableBundledSkills: U(k().optional(), {
  flatKey: "disableBundledSkills",
  readers: ["desktop", "code"],
  support: { enabled: { scopes: ["3p","1p"], availableInVersion: "1.1596..." } },
  ...
})
```

3. 因此技能的实际执行者是 **内置 Claude Code（CCD）**，Desktop 只负责：打包 → 定位 → 通过环境变量启用/禁用 → 由 CLI 读取 `SKILL.md` 并注入 prompt。

**结论**：`packaged（S）→ registered in manifest（S）→ gated by disableBundledSkills（S）→ executed by external claude CLI（S，环境变量为证）`。**不能**说“Desktop 内置了 docx 生成能力”；正确说法是“Desktop 打包了技能包并把它交给它拉起的 CLI”。

## 3. 环境变量面：1,062 个（`ENV-VARS.tsv`）

| 前缀族 | 数量 | 说明 |
|---|---:|---|
| `CLAUDE_CODE_*` | 653 | 传给 CLI 子进程的完整配置面 |
| `CLAUDE_*` / `COWORK_*` | 242 | 桌面端与 Cowork |
| `ANTHROPIC_*` | 71 | 推理/认证/模型别名 |
| `MCP_*` / `OTEL_*` | 其余 | MCP 与遥测 |

### 3.1 推理后端切换（S）

```
CLAUDE_CODE_USE_BEDROCK / _USE_VERTEX / _USE_FOUNDRY / _USE_GATEWAY
CLAUDE_CODE_USE_MANTLE / _USE_ANTHROPIC_AWS / _USE_ANTHROPIC_GOOGLE_CLOUD
CLAUDE_CODE_SKIP_BEDROCK_AUTH / _SKIP_VERTEX_AUTH / _SKIP_FOUNDRY_AUTH ...
ANTHROPIC_BEDROCK_BASE_URL / _BEDROCK_MANTLE_BASE_URL / _BEDROCK_SERVICE_TIER
```

七个 `USE_*` + 对应 `SKIP_*_AUTH` 成对出现，说明每个后端都支持“由宿主代理认证”的模式（`CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST`、`CLAUDE_CODE_HOST_AUTH_ENV_VAR`）。

### 3.2 模型别名体系（S）

`ANTHROPIC_DEFAULT_{FABLE,HAIKU,SONNET,OPUS,…}_MODEL` 每个都带四个兄弟变量：

```
_NAME, _DESCRIPTION, _SUPPORTED_CAPABILITIES, _MODEL
```

即**模型选项是数据驱动的**：企业可通过环境变量自定义显示名、描述、能力标记。

### 3.3 子代理与上下文（S）

```
CLAUDE_CODE_SUBAGENT_MODEL            ← 子代理可用独立模型
CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL
CLAUDE_CODE_PROMPT_CACHE_TTL
CLAUDE_CODE_MAX_CONTEXT_TOKENS        ← 上下文上限可覆盖
CLAUDE_CODE_EFFORT_LEVEL
CLAUDE_CODE_DISABLE_WORKFLOWS
```

### 3.4 企业网络（S）

```
CLAUDE_CODE_CLIENT_CERT / _CLIENT_KEY / _CERT_STORE   ← mTLS
CLAUDE_CODE_CUSTOM_OAUTH_URL
CLAUDE_CODE_MANAGED_SETTINGS_PATH
CLAUDE_CODE_DIAGNOSTICS_FILE
CLAUDE_CODE_ENHANCED_TELEMETRY_BETA
```

## 4. MCP / 扩展表面（101 个方法）

`MCP-EXTENSION-SURFACE.tsv` 覆盖 9 个服务：

| 服务 | 职责 |
|---|---|
| `MCP` | 服务器配置读写、状态查询、日志定位 |
| `PluginBridgeMcp` | 插件桥接的 MCP 通道 |
| `Extensions` | 扩展目录/安装/启用 |
| `CustomPlugins` | 自定义插件 |
| `LocalPlugins` | 本地插件 |
| `Skills` | 技能（事件 `previewSkillFile`） |
| `Custom3pSetup` / `Custom3pUsage` / `Custom3pHelperRun` | 第三方（企业）配置、用量、help 运行 |

### 4.1 打包但不等于启用

- `resources/github-mcp/github-mcp-server.exe`（20,566,352 B）与 `resources/office365-mcp/*`（含 7.28 MB 的 `office365-mcp-stdio.mjs`）都是**随包交付**（S）。
- 但是否启用取决于：`isLocalDevMcpEnabled`、`managedMcpServers`、`allowedPluginMcpServers`/`deniedPluginMcpServers`、以及账号 rollout（`claudeai_cowork_backend_marketplaces` gate）。
- 静态可见的 MCP host 有两个实现：`mcp-runtime/nodeHost.js`（613,700 B）与 `mcp-runtime/directMcpHost.js`（613,700 B 同目录），说明**“经 Node 宿主”与“直连宿主”两条路径并存**。

### 4.2 扩展生命周期（由方法名归纳，S）

```
安装/导入 → 校验(signature 可选) → 注册(marketplace/installed_plugins.json)
   → 启用/禁用 → 调用(工具) → 更新 → 卸载
```
相关文件：`installed_plugins.json`、`known_marketplaces.json`、`plugin.json`、`marketplace.json`、`.claude-plugin/`（16 处引用）。
签名开关：`isDesktopExtensionSignatureRequired`。

## 5. Worker 全表（8 个目录，`WORKERS.tsv`）

| worker | 文件数 | 字节 | 用途（依据文件名 + 引用上下文） |
|---|---:|---:|---|
| `heavy-work-worker` | 3 | 1,133,689 | 重任务后台执行（含 `dist-*.js` + rolldown runtime） |
| `file-index-worker` | 1 | 906,737 | 文件索引构建 |
| `mcp-runtime` | 2 | 619,607 | MCP 宿主（nodeHost / directMcpHost） |
| `transcript-search-worker` | 1 | 35,452 | 会话记录全文搜索 |
| `msal-broker-worker` | 1 | 21,601 | MSAL 认证代理 |
| `pty-host` | 1 | 12,018 | ConPTY 宿主（配合 `node-pty` 的 `conpty.node`） |
| `shell-path-worker` | 1 | 9,575 | 解析用户 shell 的 PATH |
| `stall-sampler-worker` | 1 | 2,033 | 主线程卡顿采样 |

## 6. Feature Flags（380 行 / 186 唯一键）

`FEATURE-FLAGS.tsv`。scope 分布：`3p` 304、`1p,3p` 38+2、`1p` 22、未知 14 —— 企业面占绝大多数。

按用途归类：

| 类别 | 代表键 |
|---|---|
| 推理后端 | `inferenceAnthropicApiKey`、`inferenceBedrock*`(12)、`inferenceFoundry*`(6)、`inferenceGateway*`(6)、`inferenceIdp*`(2)、`inferenceCredentialHelper*`(6)、`inferenceModelPricing*`(3) |
| Cowork | `coworkTabEnabled`、`coworkSessionRetentionDays`、`coworkVmIpv6Enabled`、`coworkEDRIntegration(+Vendor)`、`coworkEgressAllowedHosts`、`coworkFileReadCheck` |
| 安全 | `disableBypassPermissionsMode`、`blockReadsOutsideWorkingDirectories`、`builtinBrowserBlockedDomains`、`claudeInChromePasswordManagersEnabled`、`isDesktopExtensionSignatureRequired` |
| 插件治理 | `allowedPluginMarketplaces`、`allowedPluginMcpServers`、`deniedPluginMcpServers`、`managedMcpServers` |
| 网络 | `egressProxyUrl`、`egressProxyPacUrl`、`bootstrapUrl`、`bootstrapHeaders`、`bootstrapOidc` |
| 身份 | `loginSsoOrgDomain`、`forceLoginOrgUUID`、`entraClientId`、`entraScope`、`entraAzureCloud`、`disableMultiAccount` |
| 更新 | `disableAutoUpdates`、`autoUpdaterEnforcementHours`、`dangerousMaxVersion` |
| 遥测 | `disableEssentialTelemetry`、`disableNonessentialTelemetry`、`disableNonessentialServices` |
| 数据保留 | `chatSessionRetentionDays`、`codeSessionRetentionDays`、`coworkSessionRetentionDays` |

**flag 的读取端**（S）：`readers: ["desktop","code"]` —— 同一个 flag 同时作用于 Desktop 与内置 CLI。

## 7. 其它旁支资源

| 资源 | 说明 |
|---|---|
| `resources/artifact-libs/` | chart.js 4.5.0 UMD、gridjs 5.0.2 UMD + mermaid 主题、mermaid 11.17.2（3.57 MB）——artifact 渲染库，本地打包 + CDN 兜底 |
| `resources/office365-mcp/msalruntime.dll` + `msal-node-runtime.node` | MSAL 原生运行时（Entra 认证） |
| `resources/office365-mcp/pdf.worker.mjs` + `pdfExtractorProcess.mjs` | PDF 解析 worker（1.09 MB + 425 KB） |
| `ion-dist/`（在 `app/resources/` 下） | 需单独确认的目录（见 UNKNOWN 清单） |
| `compile-cache/*.jsc` | V8 code cache（3 个，最大 6.86 MB），对应 `index.chunk-lzaSYO3Q.js` |
| 本地化 | `app/resources/*.json` 共 40+ 语言包（含 `am`/`bho`/`bn`/`gu`/`ha`/`ig` 等），说明本地化由 Electron 资源层承载，而非远程 |

## 8. 未解 / 未知（不隐藏）

| 项 | 级别 | 说明 |
|---|---|---|
| `ion-dist/` 目录用途 | U | 在 `app/resources/` 下存在，未在本次提取中展开 |
| `nodeHost` 与 `directMcpHost` 的运行时差异 | 部分 | 两文件同尺寸但未逐行 diff |
| `extensions` 市场的真实 URL | U | 依赖账号与 rollout gate |
| `Simulator` / `Launch` / `GrandPrix` / `ViolinFret` / `Gorse` / `Baku` | U | 内部代号服务，方法名已知，业务语义未定 |
| `hardwareBuddyEnabled` 的硬件协议 | U | 仅见 flag 与 `BuddyBleTransport` 服务名（BLE 传输） |

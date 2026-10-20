# P6D — 内置工具清单与模型目录

> 解决 `U-013` 的静态可得部分，并补齐工具面。全部来自 `index.chunk-lzaSYO3Q.js` 的字面量计数。

---

## 1. 内置工具名（出现次数即引用密度）

| 工具 | 引用次数 | 说明 |
|---|---:|---|
| `Bash` | 15 | 执行 shell |
| `AskUserQuestion` | 12 | **向用户提问并等待回答**（交互式澄清） |
| `Edit` | 10 | 精确字符串替换 |
| `Write` | 8 | 写文件 |
| `WebSearch` | 7 | 网页搜索 |
| `Read` | 6 | 读文件 |
| `WebFetch` | 6 | 抓取 URL |
| `NotebookEdit` | 6 | Jupyter notebook 编辑 |
| `Task` | 5 | **子代理任务分发** |
| `Artifact` | 5 | 创建 artifact |
| `Glob` | 4 | 文件名匹配 |
| `Grep` | 4 | 内容搜索 |
| `Skill` | 4 | 调用技能 |
| `CronCreate` / `CronDelete` / `ScheduleWakeup` | 2 each | **定时/唤醒调度** |
| `CronList` | 1 | 列出定时任务 |
| `TodoWrite` | 1 | 待办清单 |
| `ExitPlanMode` | 1 | 退出计划模式 |
| `Search` | 1 | 通用搜索 |

### 1.1 值得单独说明的三组

**调度组**：`CronCreate` / `CronDelete` / `CronList` / `ScheduleWakeup`
这四个是**模型可直接调用的调度工具**，与 `CoworkScheduledTasks` / `CCDScheduledTasks` / `WakeScheduler` 三个 RPC 服务对应。错误串原文：

> `Scheduled tasks have been turned off by your organization.`

门控函数 `x3t(e){return e.workspace?.scheduledTasksEnabled!==!1}` —— 即除非组织显式关闭，否则默认开。

**交互组**：`AskUserQuestion`（12 次引用）说明模型可以主动向用户提问并阻塞等待，不是单向输出。

**子代理组**：`Task`（5 次）—— 模型可派发子任务，与 `CLAUDE_CODE_SUBAGENT_MODEL` / `CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL` 两个环境变量对应。

## 2. 本地会话的组织级禁用（S）

两条精确错误串：

```
"Local sessions are not available on this device because your organization has turned them off."
"Local sessions are not available on this device because its managed settings could not be read."
```

第二条很重要：**读不到托管设置时，本地会话也直接不可用**（fail-closed），不是降级放行。对应函数 `gC()` 返回 `w3t`（当前禁用原因）。

## 3. 模型目录（Model Catalog）

### 3.1 三个相关配置项（来自 AppConfig schema）

| flatKey | 默认 | 说明 |
|---|---|---|
| `modelCatalogEnabled` | `displayOnly:true`, `failClosedValue:false` | 是否启用目录元数据，scope 仅 `3p` |
| `modelCatalogUrl` | `failClosedValue:"https://model-catalog.invalid/unreadable"` | 目录地址，**默认占位是 `.invalid` 域名**（防止误连） |
| `inferenceModelPricing*` | — | 三个价格相关项 |

`modelCatalogUrl` 的额外约束（S）：

- `redact:"hostname"` —— 遥测里脱敏主机名
- `rejectLoopback:true` —— **拒绝 localhost/回环地址**
- `applyUnverified:true`, `hotApplied:true` —— 可热更新
- `egressRequirements` —— 会参与出网白名单计算（`egressRequirementsLabel: "Model catalog mirror"`）
- 占位符示例：`https://mirror.example.com/model-catalog/v1/catalog.json`

**结论**：模型目录是**企业自建镜像**场景的功能。默认官方地址是 `https://downloads.claude.ai/model-catalog/v1/catalog.json`（P3 已记录），但 3P 可整体替换为内网镜像，且禁止指向本机。

### 3.2 为什么拿不到目录内容

`catalog.json` 是**服务端下发**的，包内无缓存副本。schema 文件（`catalog/v1/schema.json`）同样在服务端。因此 `U-003` 保持 U，且**静态无法解决**——除非在允许地区取得一次真实响应。

## 4. 模型校验（S）

函数 `PMe` 的逻辑：把配置里的 `inferenceModels` 数组逐个用 `yo(r, e.name)` 校验，失败的剔除并报：

```
`inferenceModels: "${e}" is not an Anthropic model and was removed from the ...`
```

即 **3P 部署下只能声明 Anthropic 模型名**，自定义名称会被过滤掉。这与 `ANTHROPIC_DEFAULT_*_MODEL` 那一套别名机制配合：允许改显示名，但底层必须是已知模型。

## 5. Claude Code CLI 参数（部分可得）

CLI 本体不在包内（由 `downloads.claude.ai/claude-code-releases` 分发），但 Desktop 侧的调用面可以静态确定：

| 维度 | 已知 |
|---|---|
| 可执行名 | `claude`（`spawn(..., "claude", ...)`） |
| 配置方式 | **主要走环境变量**（653 个 `CLAUDE_CODE_*`），非常规命令行参数 |
| 关键 env | `CLAUDE_CODE_DISABLE_BUNDLED_SKILLS`、`CLAUDE_CODE_SUBAGENT_MODEL`、`CLAUDE_CODE_MAX_CONTEXT_TOKENS`、`CLAUDE_CODE_EFFORT_LEVEL`、`CLAUDE_CODE_USE_{BEDROCK,VERTEX,FOUNDRY,GATEWAY,MANTLE}`、`CLAUDE_CODE_CLIENT_CERT/KEY/CERT_STORE`（mTLS）、`CLAUDE_CODE_MANAGED_SETTINGS_PATH`、`CLAUDE_CODE_OAUTH_TOKEN*` |
| 输出格式 | 从 `stream-json` 相关符号与 `--output-format` 推断为**流式 JSON**（I 级） |
| 会话续接 | `--resume` / `--session-id`（I 级，来自命名一致性） |

**诚实标注**：CLI 自身的完整参数表（`--permission-mode` 等）无法从 Desktop 包内确定，因为参数是运行期组装且 CLI 不在包内。`U-013` 保持 U。

## 6. 证据

| 断言 | 锚点 |
|---|---|
| 工具名与出现次数 | `index.chunk-lzaSYO3Q.js` 字面量计数 |
| 调度工具门控 | 同文件 `x3t` 与字符串 `scheduledTasksEnabled` |
| 本地会话 fail-closed | 同文件 `S3t` / `C3t` 两条错误串与 `gC()` |
| 模型目录配置项 | 同文件 `catalogEnabled` / `catalogUrl` 的 flatKey 定义 |
| 模型名校验 | 同文件 `PMe` 与 `inferenceModels: ... is not an Anthropic model` |

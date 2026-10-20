# P6E — 内嵌模型目录（解决"catalog.json 拿不到"）

> 解决 `U-003`。此前的判断是"catalog.json 由服务端下发，包内无副本"。**这个判断是错的。**
> 包里内嵌了一份完整的目录快照，只是以 JS 字面量形式存在于主 bundle 中。

---

## 1. 快照元数据（S）

```js
var a3t = {
  $schema: "https://downloads.claude.ai/model-catalog/v1/schema.json",
  schema_version: 1,
  version: 2313,
  issued_at: "2026-10-15T05:59:05Z",
  expires_at: "2026-10-22T05:59:05Z",
  key_id: "claude-code-release-signing-key",
  surfaces: JSON.parse('{...}')
}
```

| 字段 | 值 | 含义 |
|---|---|---|
| `schema_version` | 1 | 目录格式版本 |
| `version` | **2313** | 目录内容版本号（单调递增） |
| `issued_at` | 2026-10-15T05:59:05Z | 签发时间 |
| `expires_at` | 2026-10-22T05:59:05Z | **7 天有效期** |
| `key_id` | `claude-code-release-signing-key` | 签名密钥标识 |

**这解答了一个重要问题**：目录不是"每次启动拉取"，而是**随包内嵌一份、带 7 天有效期、过期后必须刷新**。这也解释了为什么 `catalogUrl` 是 3P 可配置项 —— 企业可以指向自己的镜像，但内嵌的这份是兜底。

有效期与签名的组合意味着：**如果客户端长期离线，超过 7 天后目录会被视为过期**。

## 2. 五个 surface（S）

目录按产品表面分区：

| surface | 含义 |
|---|---|
| `cc` | Claude Code（CLI） |
| `ccd` | Claude Code Desktop（本应用） |
| `ccr` | Claude Code Remote（远程会话） |
| `chat` | 网页/通用聊天 |
| `cowork` | Cowork |

`cc` / `ccd` / `ccr` 三个的模型清单**完全相同**（各 13 个），说明同一套模型在 CLI、桌面、远程三种执行形态下一致；`chat` 与 `cowork` 的 entries 结构不同（不含 `models` 数组，是另一套 selector 结构）。

## 3. `cc` / `ccd` / `ccr` 的 13 个模型（完整，S）

| 模型 id | 显示名 | 最大输入 | 最大输出 | 默认 effort |
|---|---|---:|---:|---|
| `claude-opus-5-5` | Opus 5.5 | 1,000,000 | 128,000 | medium |
| `claude-sonnet-5-5` | Sonnet 5.5 | 1,000,000 | 128,000 | medium |
| `claude-fable-5-1` | Fable 5.1 | 1,000,000 | 128,000 | high |
| `claude-haiku-5-5` | Haiku 5.5 | 1,000,000 | 128,000 | medium |
| `claude-haiku-4-5-20251001` | Haiku 4.5 | 200,000 | 64,000 | — |
| `claude-sonnet-5` | Sonnet 5 | 1,000,000 | 128,000 | high |
| `claude-opus-5` | Opus 5 | 1,000,000 | 128,000 | high |
| `claude-fable-5` | Fable 5 | 1,000,000 | 128,000 | high |
| `claude-opus-4-8` | Opus 4.8 | 1,000,000 | 128,000 | high |
| `claude-opus-4-7` | Opus 4.7 | 1,000,000 | 128,000 | **xhigh** |
| `claude-opus-4-6` | Opus 4.6 | 1,000,000 | 128,000 | high |
| `claude-sonnet-4-6` | Sonnet 4.6 | 1,000,000 | 128,000 | high |
| `claude-opus-4-1-20250805` | Opus 4.1 | 200,000 | 32,000 | — |

**注意**：`fable` 是一个此前未在公开信息中出现的模型族，默认 effort 为 `high`，定位描述是 "For your toughest challenges"（比 Opus 更靠上）。

## 4. 每个模型的完整字段（以 `claude-opus-5-5` 为例）

```json
{
  "id": "claude-opus-5-5",
  "name": "Opus 5.5",
  "short_name": "Opus",
  "description": "For complex work and everyday tasks",
  "section": "main",
  "capabilities": {
    "compass": true, "gsuite_tools": true,
    "mm_images": true, "mm_pdf": true, "web_search": true
  },
  "thinking": {
    "type": "effort",
    "description": "Higher effort means more thorough responses, but takes longer and uses your limits faster.",
    "effort_options": [
      {"id":"low","name":"Low"},
      {"id":"medium","name":"Medium","badge":{"message":"Recommended","variant":"neutral"}},
      {"id":"high","name":"High"},
      {"id":"xhigh","name":"Extra"},
      {"id":"max","name":"Max","tooltip":{"content":"May use excessive tokens resulting in long response times and may hit token limits. Use sparingly for the hardest tasks."}}
    ]
  },
  "fast_mode": {
    "type": "toggle", "name": "Fast mode",
    "options": [{"id":"fast","name":"Enable fast mode","selector_label":"Fast"},
                {"id":"off","name":"Off"}]
  },
  "min_claude_code_version": "2.1.280",
  "quick_select": true,
  "runtime": {
    "max_input_tokens": 1000000,
    "max_output_tokens": 128000,
    "effort_levels": ["low","medium","high","xhigh","max"],
    "default_effort": "medium",
    "capabilities": ["compass","gsuite_tools","mm_images","mm_pdf","web_search"],
    "image_limits": {"max_width":2576,"max_height":2576,"max_image_tokens":4784},
    "family": "opus"
  },
  "offered_on": ["first_party","anthropic_aws","bedrock","vertex","foundry","mantle","gateway"]
}
```

### 值得单独解释的字段

| 字段 | 含义 |
|---|---|
| `capabilities.compass` | **Compass** 能力（内部代号，推测为某种导航/规划能力；仅在目录中出现，无进一步说明） |
| `capabilities.gsuite_tools` | Google Workspace 工具集成 |
| `capabilities.mm_images` / `mm_pdf` | **多模态**图像 / PDF |
| `capabilities.web_search` | 网页搜索 |
| `effort_options` 五档 | low / medium / high / xhigh / max，其中 `max` 带明确警告"可能消耗过多 token" |
| `fast_mode` | **Fast mode 是可开关的**，不是模型变体 |
| `min_claude_code_version: 2.1.280` | 该模型要求 CLI ≥ 2.1.280（本包内 CLI 是 **2.1.299**，满足） |
| `image_limits` | 图片最大 2576×2576，单图最多 4,784 tokens |
| `offered_on` | **7 条推理路径**：官方 / Anthropic-AWS / Bedrock / Vertex / Foundry / Mantle / Gateway |

`offered_on` 这 7 项与 P4 里从 flag 推断出的推理后端**完全对上**，互相印证。

## 5. 默认选择（S）

```json
"model_selector_state": [{
  "id": "cc",
  "model": "claude-opus-5",
  "thinking": {"type":"effort","effort":"high"},
  "thinking_by_model": [
    {"id":"claude-fable-5-1","thinking":{"effort":"high"}},
    {"id":"claude-opus-5-5","thinking":{"effort":"medium"}},
    {"id":"claude-sonnet-5-5","thinking":{"effort":"medium"}},
    {"id":"claude-haiku-5-5","thinking":{"effort":"medium"}},
    {"id":"claude-fable-5","thinking":{"effort":"high"}},
    {"id":"claude-opus-5","thinking":{"effort":"high"}},
    {"id":"claude-opus-4-8","thinking":{"effort":"high"}},
    {"id":"claude-opus-4-7","thinking":{"effort":"xhigh"}},
    {"id":"claude-opus-4-6","thinking":{"effort":"high"}},
    {"id":"claude-sonnet-5","thinking":{"effort":"high"}},
    {"id":"claude-sonnet-4-6","thinking":{"effort":"high"}}
  ],
  "selection_source": "global_default"
}]
```

**默认模型 = `claude-opus-5`，effort = `high`**（`selection_source: "global_default"`）。
每个模型有**各自的默认 effort**（Opus 4.7 是 xhigh，其余多为 high/medium）。

## 6. 目录的使用方式（S）

`n3t(e,t)` 按 surface 取该 surface 的 `models` 数组；`r3t(e)` 遍历 `fC` 列表，对每个 surface 尝试取模型，取到即跳出。
过期检查：`i3t(e,t) = expires_at !== undefined && now >= expires_at`。
`m3t(e)` 在目录更新时比较 JSON 字符串并触发订阅回调 —— 即**目录热更新会通知所有订阅者**。

## 7. 对之前结论的修正

| 之前写的 | 实际 |
|---|---|
| "catalog.json 由服务端下发，包内无缓存，静态不可解" | **包内内嵌完整快照（version 2313，2026-10-15 签发，7 天有效期）** |
| `U-003` = U | **改为 RESOLVED** |

## 8. 产物

```
ledgers/MODEL-CATALOG-EMBEDDED.json   完整 5 surface 目录（原始结构）
```

## 9. 仍未解的部分

| 项 | 说明 |
|---|---|
| `compass` 能力的具体实现 | 只有布尔标记，无行为代码 |
| `chat` / `cowork` surface 的完整结构 | 已保存原始 JSON，但结构与 cc/ccd/ccr 不同，未逐字段解释 |
| 服务端是否有比 2313 更新的版本 | 需联网拉取 |

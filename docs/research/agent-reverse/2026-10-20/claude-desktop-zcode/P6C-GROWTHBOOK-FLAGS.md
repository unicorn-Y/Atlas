# P6C — Feature Flag 的真实完整清单（GrowthBook allowlist）

> 这是本轮最大的一块新证据：从 bundle 中恢复出**完整的 GrowthBook 键白名单**，共 **237 个键**。
> 之前 `FEATURE-FLAGS.tsv` 的 380 条是**企业策略/inference 配置项**（另一个体系），这里是**GrowthBook 实验开关**（另一套）。

---

## 1. 两套 flag 体系必须分开

| | 企业策略 flag | GrowthBook 实验 flag |
|---|---|---|
| 载体 | `AppConfig` schema 里的 `flatKey` | 远程 GrowthBook 下发 |
| 数量 | 380 条记录 / 186 唯一键 | **237 个键**（白名单） |
| 作用域 | 3p 为主（304/380） | 双端（桌面 + 前端 SPA 都接 SDK） |
| 默认值 | 本地 schema 定义 | 服务端下发，未登录时走默认 |
| 本报告 | `FEATURE-FLAGS.tsv` | **本节** |

前一轮把两者混在一张表里，现在已分开记录。

## 2. 白名单的代码形态（S）

```js
function Use(e){
  if (e.startsWith("__gb__")) return e.slice(6);        // "__gb__3349513247" -> "3349513247"
  let t = 0;
  for (let n = 0; n < e.length; n++) t = (t<<5) - t + e.charCodeAt(n), t &= t;
  return ((t & 4294967295) >>> 0).toString();           // 32-bit hash -> decimal string
}
new Set("claudeai_safe_prompt_hashes.claude_ai_email_prompt_id_prefill....".split("."))
```

**用途（S）**：把 flag 名**哈希成十进制数字**再上报遥测，避免把实验名泄露到日志/分析平台。`__gb__<n>` 形式则直接取数字。

这套机制解释了为什么遥测里出现的是 `__gb__2111295379` 这类数字 —— 它们是 **flag 名的哈希**，不是随机 ID。

## 3. 237 个键的分类

| 类别 | 数量 | 说明 |
|---|---:|---|
| `cai_<两词代号>` | 57 | 内部代号命名的实验（如 `cai_shiny_clover`、`cai_mighty_kite`） |
| `__gb__<数字>` | 44 | 直接以哈希形式登记的 flag |
| 其余命名键 | 136 | 有语义的键名 |

### 3.1 MCP / 工具权限（高价值）

| 键 | 含义 |
|---|---|
| `sensitive_mcps_per_call_consent` | 敏感 MCP **每次调用都要同意** |
| `sensitive_mcp_tools` | 敏感工具清单 |
| `mcp_tool_approval_config` | 工具审批配置 |
| `disable_destructive_mcp_tools_by_default` | 默认禁用破坏性工具 |
| `claude_ai_mcp_skip_schema_validation` | 跳过 schema 校验（危险开关） |
| `mcp_apps_frame_domains` / `apps_mcp_apps_experimental_flags` | MCP 应用框架域名与实验开关 |
| `mcp_directory_featured_bundles` / `mcp_server_spec_directory` | MCP 目录 |
| `connectors-directory-bff-migration` | 连接器目录后端迁移 |

### 3.2 权限模式（Code / Cowork）

| 键 | 含义 |
|---|---|
| `cowork_bypass_permissions_mode` | Cowork 绕过权限模式 |
| `cowork_auto_permission_mode` / `ccr_auto_permission_mode` | 自动权限模式 |
| `ccr_mcp_permission_mode_override` | MCP 权限模式覆盖 |
| `ccr_plan_mode_enabled` | 计划模式 |
| `ccd_automode_required_models` / `ccd_auto_default_mode` / `ccr_auto_default_mode` | 自动模式与模型约束 |
| `cowork_auto_mode_include_allowed_write_mcp_web` | 自动模式包含写操作/MCP/Web |
| `claudeai_permission_modes_managed_settings` | 托管设置里的权限模式 |

### 3.3 出网与代理（`wiggle` 体系）

| 键 | 含义 |
|---|---|
| `claudeai_default_wiggle_egress_enabled` | 默认出网开关 |
| `claudeai_default_wiggle_egress_enabled_without_spotlight` | 无"聚光灯"提示的出网 |
| `claudeai_default_wiggle_egress_hosts_template` | 出网主机模板 |
| **`yukon_silver_egress_templates`** | **YukonSilver 出网模板**（VM 出网策略） |

这一组直接对应 `P4` 里的 `egressProxyUrl` / `coworkEgressAllowedHosts`。

### 3.4 设备与远程控制

| 键 | 含义 |
|---|---|
| `trusted_device_self_attestation` | 可信设备自证 |
| `cowork_device_attestation_header_send_disabled` | 关闭设备证明头 |
| `cowork_remote_device_revoked_reenroll` | 远程设备吊销后重注册 |
| `ccr_per_message_attestation_web` | 逐消息证明（Web） |
| `cowork_safety_banners` / `cowork_safety_flags_batch_main` | 安全横幅 |

### 3.5 企业治理

| 键 | 含义 |
|---|---|
| `enforce_org_skill_disablement_main` | 强制组织级技能禁用 |
| `cowork_argonaut_org_policies_main` | 组织策略（Argonaut 代号） |
| `ccd_deeplink_trusted_folder_skip_main` | 深链跳过可信文件夹检查 |
| `ccr_epitaxy_disable_bridge_host_reads` | 禁用 bridge 的宿主读取 |
| `ccr_epitaxy_disable_signed_initialize` | 禁用签名初始化 |
| `epitaxy_disable_mcp_elicitation` | 禁用 MCP 引导 |

### 3.6 反滥用 / 验证码（数量最多）

24 个 `*_hcaptcha_sitekey` 键，覆盖：登录、注册接受邀请、加入组织、删号、OAuth 设备、创建/重新激活 API key（含 scoped 与 admin）、额度购买、支付、团队结账、研究招募等。
另有 `*_login_hcaptcha_frontend_enabled`（4 个域）与 `claude_ai_payments_hcaptcha_desktop_enabled`。

**这说明 hCaptcha 的 sitekey 是远程下发而非硬编码** —— 便于按环境/风控等级切换。

### 3.7 年龄验证

`claude_ai_age_verification_hoc_gate`、`claude_ai_share_age_verification_disabled`、`onboarding_age_verification`。

### 3.8 其它值得记的键

| 键 | 含义 |
|---|---|
| `yukon_silver_tool_perms` | VM 内工具权限 |
| `yukon_silver_cuttlefish_ditto_prompt` / `yukon_silver_octopus_prompt` | VM 内两个 prompt 变体（代号 cuttlefish / octopus） |
| `claudeai_yukon_gold_tool_display` | "Yukon Gold" 工具展示（另一代号） |
| `claudeai_majordomo_config` | Majordomo 配置（代号） |
| `claude_grove_config` | Grove 配置 |
| `tengu_hollow_lantern` / `tidal_willow_main` / `wisteria` / `pebble_orchard_quill` / `amber_tributary_siskin` 等 | 纯代号实验 |
| `completion_retry_disabled` / `completion_retry_emergency` | 补全重试的紧急开关 |
| `claude_ai_markdown_mermaid_render` | 前端 Mermaid 渲染 |
| `claudified_skills_academy_video_src` | 技能学院视频源 |

## 4. 与前端的关系

`ion-dist` 的 `vendor-growthbook-*` chunk 证明**前端也直接接 GrowthBook SDK**。因此同一个键可能在两端读取不同值（前端用匿名 id，桌面用设备 id），这也是为什么需要一套统一的哈希脱敏。

## 5. 产物

```
ledgers/GB-ALLOWLIST.txt          237 个键（逐行）
index/GB-KEYS.json                候选 token（含噪音，仅供参考）
```

## 6. 仍未解

| 项 | 说明 |
|---|---|
| 57 个 `cai_*` 代号的业务含义 | 只有代号，无描述字符串；需服务端配置才能知道 |
| `__gb__<n>` 数字对应的原始名字 | 单向哈希（`Use()` 是哈希函数，不可逆）；除非在其它位置同时出现原名 |
| 各键的实际生效值 | 需登录后的 GrowthBook 响应（`CLOUD-UNAVAILABLE`） |

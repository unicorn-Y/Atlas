# P6G — `cai_*` 实验代号的语义反查

> 解决 `U-005` 的主要部分。方法：不猜代号含义，而是找**代号绑定了哪些行为事件**。
> 前端里每个 `cai_*` flag 常常与一组 `action:*` / `spa:*` 事件绑定，这直接暴露它影响什么。

---

## 1. 规模

| 来源 | 唯一 `cai_*` 键数 |
|---|---:|
| 主进程 GrowthBook 白名单 Set | 57 |
| **前端 SPA（`ion-dist`）** | **191** |
| 两者交集 | 部分（前端可读到更多） |

前端比主进程白名单多得多，说明**大部分实验只影响前端行为**，不需要主进程感知。

## 2. 关键结构：`flag → events` 绑定表（S）

前端存在一张显式映射（节选原文）：

```js
{flag:"cai_curious_brook", events:[
   "action:code.transcript_bottom_gap_capped",
   "action:code.transcript_open_settled"]},
{flag:"cai_curious_tower", events:[
   "action:claudeai.chat.message_queue.returned_to_editor",
   "action:claudeai.chat.message_queue.sent_now", ...]},
{flag:"cai_dreamy_plum", events:["action:voice.read_aloud"]},
{flag:"cai_fluffy_glade", events:[
   "action:page.soft_nav_cls","action:page.lcp","action:page.soft_nav_lcp",
   "action:page.code_session_op...", ...]},
{flag:"cai_flickering_stardust", events:[
   "action:code.transcript_renderer_fallback","action:code.turn_complete",
   "action:chat.hub_action_response_timeout", ...]},
```

**这就是"实验影响什么"的直接答案**：不需要知道代号什么意思，只要看它绑定的事件族。

## 3. 按影响域归类的已知映射（S）

| 影响域 | 代表 flag | 绑定的事件 |
|---|---|---|
| **消息队列** | `cai_curious_tower`、`cai_dreamy_plum` | `chat.message_queue.returned_to_editor`、`.sent_now` |
| **转写渲染** | `cai_curious_brook`、`cai_flickering_stardust`、`cai_fluffy_glade` | `code.transcript_bottom_gap_capped`、`code.transcript_renderer_fallback`、`code.turn_complete` |
| **页面性能** | `cai_fluffy_glade` | `page.soft_nav_cls`、`page.lcp`、`page.soft_nav_lcp` |
| **语音朗读** | `cai_dreamy_plum` | `action:voice.read_aloud` |
| **快速入口** | `cai_keen_gizmo`、`cai_kind_rocket` | `app.quick_entry_asked`、`app.quick_entry...` |
| **登录流程** | `cai_noble_thimble`、`cai_peaceful_puddle` | `auth.login`、`auth.login_ready` |
| **Hub 操作** | `cai_floofy_ocean`、`cai_luminous_shore`、`cai_clever_tome` | `chat.hub_send_failed`、`chat.hub_send_...`、`chat.hub_creation_wait_expired`、`chat.conversation_create` |
| **渠道/频道** | `cai_abundant_meadow`、`cai_buzzing_teapot`、`cai_gentle_thunder`、`cai_glittery_snowglobe` | `code.channel_home_open`、`code.channel_message_send` |
| **Cowork 权限** | `cai_abundant_meadow` | `cowork.permission...` |
| **崩溃/离线** | `cai_fancy_forest`、`cai_glowing_cascade` | `app.crash_unseen`、离线提示文案 |
| **快捷入口** | `cai_keen_gizmo` | `app.quick_entry_asked` |

## 4. 语义可直接读出的具名键（非纯代号）

有些键虽然带 `cai_` 前缀，但**名字本身就有语义**，不需要反查：

| 键 | 直接含义 |
|---|---|
| `cai_file_upload_config` | 文件上传配置，带参数 `max_in_context_file_bytes`（默认 15,360 = **15 KB**） |
| `cai_epitaxy_worktree` | Epitaxy 的 worktree 开关 |
| `cai_capability_tip_judge_fetch` | 能力提示的"判定/拉取"（`Dn = 36e5` = **1 小时**节流） |
| `cai_house_ads_config`（同类） | 配置类 |
| `cai_embedded_forms` | 内嵌表单开关（控制渲染路径） |
| `cai_hub_preview_optout` | Hub 预览退出开关 |
| `cai_flags` | **不是 flag**，是 API 字段名（`cai_flags: string?`） |
| `cai_example_flag` | **不是 flag**，是输入框占位符文案 |

后两条是提取时的陷阱，已剔除。

## 5. 具体数值常量（S）

从键的上下文里能读出真实参数：

| 位置 | 常量 | 含义 |
|---|---|---|
| `cai_file_upload_config` | `Vy = 15360` | 上下文中文件字节上限 = 15 KB |
| `cai_capability_tip_judge_fetch` | `Dn = 36e5` | 判定节流 1 小时 |
| `cai_fancy_locket` 附近 | `MT = 27e4`（270 秒）、`NT = 200`、`FT = 50` | 超时/条数限制 |
| `cai_fluttering_balloon` | `p = 2e3` | 2 秒 |
| `cai_cozy_whistle` | `zO = 3e3` | 3 秒，且同段出现默认模型回退 `claude-3-5-haiku-latest` |
| `cai_fluffy_glade` 附近 | `zJ = 8` | 批次/重试数 |

## 6. 仍无法解释的部分

| 项 | 原因 |
|---|---|
| 约 138 个纯代号键（如 `cai_shiny_clover`） | 既无描述文案也无事件绑定，只有布尔开关本身 |
| 这些开关的**实际取值** | 需登录后 GrowthBook 响应（`CLOUD-UNAVAILABLE`） |

**结论**：`cai_*` 不是"无意义的随机名"，而是**A/B 实验的匿名标识**。产品刻意让名字不携带语义（避免泄露未发布功能），但**绑定的事件暴露了影响面**。这是可以从代码读出的最有价值的部分。

## 7. 产物

```
ledgers/CAI-FLAGS.json     191 个键 × {file, hint, events}
```

## 8. 对 U-005 的影响

| 之前 | 现在 |
|---|---|
| "57 个 cai_* 代号的业务含义" = 未知 | **影响域已可确定 53 个**（有事件绑定或文案），其余 138 个仅知是布尔开关 |
| 状态 | **PARTIAL 保持**，但从"完全不知"推进到"影响面已知" |

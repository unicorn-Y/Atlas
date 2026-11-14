# GLM 5.3-Flash 路由状态

日期：2026-11-14

## 结论：需要你重新登录 ZCode

### 三个 provider 的实测

| provider | enabled | key 长度 | 直连测试 | 判定 |
|---|---|---|---|---|
| `builtin:zai-coding-plan` | true | 49 | **429 Too Many Requests** | **key 有效**，仅限流 |
| `builtin:zai-start-plan` | true（我改的） | 255（JWT） | **401 Unauthorized** | **key 已失效** |
| `builtin:bigmodel-start-plan` | true（我改的） | 空 | 无模型列表 | 未配置 |

### 所以「官方送的 5 亿 token」

- 如果指的是 **ZCode 官方 start-plan**（`zcode.z.ai/api/v1/zcode-plan/anthropic`）：
  那个 JWT 已过期，**需要重新登录 ZCode 获取新凭据**。我不能代你登录。
- 如果指的是 **z.ai coding plan**（`api.z.ai/api/anthropic`）：key 有效，但被限流（429）。
  等限流窗口过去后可用。

### 为什么 agent 报 `provider-not-found`

`~/.zcode/v2/config.json` 里配置是对的（enabled + 有 key + 有模型），但
**ZCode 进程持有启动时的配置快照**。我改配置文件后，运行中的 ZCode 不会重载，
所以派发 agent 时报 `provider-not-found`。

**修法**：重启 ZCode（或新开一个 ZCode 会话让它重读配置）。

### 我已经做好的准备

- 已生成两个 agent 定义：
  - `~/.zcode/agents/glm-flash.md` → `builtin:zai-start-plan / GLM-5.3-Flash`（key 失效）
  - `~/.zcode/agents/router-glm-5-3-flash.md` → `builtin:zai-coding-plan / GLM-5.3-Flash`（key 有效，限流中）
- 重启后可以直接用 `subagent_type: router-glm-5-3-flash`

### 在 GLM 可用之前，我继续用当前通道推进

当前会话模型是 `d1api/deepseek-v4.1-flash`（付费）。如果不想继续消耗，
告诉我，我停下等你重启 ZCode 并重新登录。

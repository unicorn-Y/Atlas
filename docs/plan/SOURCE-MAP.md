# Atlas 源码地图：每个能力从哪里拿代码（2026-09-30）

**用户决定的路线：移植**。保留 Atlas 现有后端（Python / FastAPI）和前端（Electron / React / Tailwind v4），从最强的开源项目里**逐块搬代码改**；只有找不到能用的实现才自己写。

## 一、主要代码来源（都已用 `gh api` 核实，数据截至 2026-09-30）

| 代号 | 仓库 | 语言 | 许可证 | 星数 | 最近提交 | 怎么用 |
| --- | --- | --- | --- | --- | --- | --- |
| **H** | [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) | Python（后端）+ React 19 / Tailwind 4 / Electron 40（`apps/desktop`） | MIT | 25.0 万 | 今天 | **首选来源**。语言和技术栈跟 Atlas 一样，后端模块和前端组件都能直接搬 |
| **O** | [openclaw/openclaw](https://github.com/openclaw/openclaw) | TypeScript（界面是 Lit） | MIT | 39.1 万 | 今天 | 自动化、记忆、设备配对、会话分享等设计最完整；**照着逻辑移植成 Python** |
| **OC** | [anomalyco/opencode](https://github.com/anomalyco/opencode) | TypeScript | MIT | 21.1 万 | 今天 | 编程 Agent 的交互细节、权限、压缩、快照 |
| **CX** | [openai/codex](https://github.com/openai/codex) | Rust | Apache-2.0 | 12.7 万 | 今天 | Auto-review（审查员）、沙箱策略、Agent 角色 TOML |
| **GM** | [google-gemini/gemini-cli](https://github.com/google-gemini/gemini-cli) | TypeScript | Apache-2.0 | 10.7 万 | 今天 | 子 Agent、A2A 远程 Agent、沙箱 |
| **OH** | [OpenHands/OpenHands](https://github.com/OpenHands/OpenHands) | TS + Python SDK | MIT | 9.0 万 | 今天 | 子 Agent 定义格式、事件溯源 |
| **CL** | [cline/cline](https://github.com/cline/cline) | TypeScript | Apache-2.0 | 7.0 万 | 今天 | 计划 / 执行模式、检查点、看板 + worktree |
| **G** | [aaif-goose/goose](https://github.com/aaif-goose/goose) | Rust | Apache-2.0 | 5.5 万 | 今天 | 配方（recipe）和子配方 |
| **KC** | [Kilo-Org/kilocode](https://github.com/Kilo-Org/kilocode) | TypeScript | MIT | 2.7 万 | 今天 | 编排模式 |
| **CUA** | [trycua/cua](https://github.com/trycua/cua)（`libs/cua-driver`：Rust + Python 绑定） | Rust / Python | MIT | 2.8 万 | 今天 | **Windows 后台电脑操作驱动**（不抢鼠标）；Hermes 已经在用 |
| **TARS** | [bytedance/UI-TARS-desktop](https://github.com/bytedance/UI-TARS-desktop) | TypeScript | Apache-2.0 | 3.9 万 | 09-24 | 视觉 / DOM 混合浏览器操作、远程电脑操作 |
| **AS** | [simular-ai/Agent-S](https://github.com/simular-ai/Agent-S) | Python | Apache-2.0 | 1.2 万 | 09-05 | OSWorld 第一梯队的电脑操作策略 |
| **BU** | [browser-use/browser-use](https://github.com/browser-use/browser-use) | Python | MIT | 11.7 万 | 今天 | 浏览器 Agent（Atlas 已经接了，升级到新版） |
| **SH** | [browserbase/stagehand](https://github.com/browserbase/stagehand) | TypeScript | MIT | 2.5 万 | 今天 | 操作缓存、重放、自愈（逻辑移植） |
| **SO** | [k2-fsa/sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) | C++（有 Python 包） | Apache-2.0 | 1.5 万 | 09-22 | 本地语音识别（SenseVoice）和合成 |
| **MCPUI** | [modelcontextprotocol/ext-apps](https://github.com/modelcontextprotocol/ext-apps)、`@mcp-ui/client` | TypeScript | 待核实 | — | — | 在对话里渲染 MCP Apps 交互界面（前端） |
| **CM** | [thedotmack/claude-mem](https://github.com/thedotmack/claude-mem) | TypeScript | Apache-2.0 | 9.5 万 | 今天 | 记忆（冻结中，备用） |
| **COMP** | [ComposioHQ/composio](https://github.com/ComposioHQ/composio) | TypeScript / Python SDK | MIT | 3.0 万 | 今天 | 1000+ 托管连接器（可选的云端后备） |
| **CN** | [yehuoshun/awesome-china-mcp](https://github.com/yehuoshun/awesome-china-mcp) | 索引 | — | — | — | 国内服务的 MCP 服务器清单（飞书官方、语雀官方、高德、百度地图、12306、小红书、微博、B 站、Gitee、阿里云、腾讯云、火山引擎…） |

不用的：Roo Code（2026-05 已归档）；OpenHuman（GPL-3.0，自己用可以，但以后分发会受限，只参考设计）；`anthropics/skills`（仓库没有统一许可证，Office 技能用 Hermes 自带的 `skills/productivity/{docx,powerpoint,xlsx,pdf}` 代替）。

### 搬代码的三种方式

1. **当依赖**：pip / npm 安装，锁定版本（例如 sherpa-onnx、cua-driver 的 Python 绑定、browser-use、`@mcp-ui/client`）。
2. **拷代码进来改**：同语言、同许可证的模块，拷到 Atlas 对应目录，文件头注明来源仓库、路径、提交号、许可证（MIT / Apache 要求保留版权声明），然后按 Atlas 的接口改。Hermes 的 Python 模块和 `apps/desktop` 的 React 组件主要走这条路。
3. **照着逻辑移植**：语言不同（OpenClaw、OpenCode、Codex 是 TS / Rust），读懂后用 Python 重写，注释里写明参考的文件。

每个搬进来的文件都要登记到 `docs/plan/VENDORED.md`（来源、提交号、许可证、改了什么），方便以后对照上游更新。

## 二、能力 → 来源对照（按对标表的 20 类 + 新增能力）

格式：**能力**｜Atlas 现状｜**最好的来源（路径）**｜方式｜备注

### A. Agent 循环、模型与上下文

| 能力 | Atlas | 来源 | 方式 | 备注 |
| --- | --- | --- | --- | --- |
| 提示缓存 | ❌ | H `agent/prompt_caching.py`、`prompt_cache_boundary.py`、`prompt_cache_scope.py`；原则见 H 根目录 `AGENTS.md`「Per-conversation prompt caching is sacred」 | 拷贝改 | 同时照 H 的规则检查 Atlas 有没有在对话中途改系统提示 |
| 工具输出上限 / 落盘 | 🟡 | H `tools/tool_output_limits.py`、`tool_output_truncate.py`、`tool_result_storage.py` | 拷贝改 | |
| 工具按需加载 | ❌ | H `tools/tool_search.py`、`tool_search_catalog.py`、`tool_search_validation.py` | 拷贝改 | |
| 上下文压缩 | ✅ 一般 | H `agent/context_compressor*.py`、`micro_compaction.py`、`conversation_compression*.py`；O `extensions/tokenjuice` | 拷贝改 | H 有微压缩 + 归档 + 回复锚点 |
| 用量与计费 | 🟡 | H `agent/usage_pricing.py`、`billing_usage.py`、`account_usage.py`、`context_breakdown.py` | 拷贝改 | |
| 模型服务商（30+，含国内） | 🟡 litellm 单网关 | H `plugins/model-providers/*`（qwen、kimi-coding、deepseek、zai、stepfun、minimax、xiaomi、ollama-cloud、openrouter…）、`agent/provider_registry.py` | 拷贝改 | |
| 多密钥轮换、限流冷却、失败切换 | ❌ | H `agent/credential_pool*.py`、`fallback_cooldown.py`、`rate_limit_tracker.py`、`error_classifier.py`、`retry_utils.py` | 拷贝改 | |
| 多模型会诊 | ❌ | H `agent/moa_loop.py`、`moa_alternation.py`、`moa_trace.py` | 拷贝改 | |
| 辅助模型（标题、摘要、审查用便宜模型） | 🟡 | H `agent/auxiliary_*.py`、`title_generator.py` | 拷贝改 | 「快模型 / 强模型」的配置照这个做 |
| 停止前校验关卡 | ❌ | H `agent/verification_stop.py`、`turn_stop_gates.py`、`verify_hooks.py`、`verification_evidence.py` | 拷贝改 | 研究里列为第七波候选，H 已有 |
| 重复 / 空回复保护 | ? | H `agent/repetition_guard.py`、`empty_response_guard.py`、`turn_truncation.py` | 拷贝改 | |
| 推理强度 | ✅ | H `agent/reasoning_effort.py`、`reasoning_params.py` | 参考 | |
| 侧边提问 | ✅ | H `agent/side_question.py` | 参考 | |

### B. 安全与权限

| 能力 | Atlas | 来源 | 方式 | 备注 |
| --- | --- | --- | --- | --- |
| 审查员（低风险自动过） | ❌ | H `tools/approval_smart.py`、`approval_detection.py`、`approval_floors.py`、`threat_patterns.py`；CX Auto-review（`codex-rs` 里的 guardian，逻辑参考） | 拷贝改 H + 参考 CX | 再加 Atlas 自己的检查点兜底 |
| 危险命令识别 | ❌ | H `tools/terminal_tool_guards.py`、`threat_patterns.py`、`shell_heredoc.py` | 拷贝改 | |
| 路径 / URL 安全 | ✅ 部分 | H `tools/path_security.py`、`url_safety.py`、`website_policy.py`、`file_tools_write_guards.py` | 对照补强 | |
| 网页内容注入防护 | ❌ | H `tools/threat_patterns.py`、`plugins/security-guidance`；O `extensions/policy` | 拷贝改 | |
| 检查点 | ✅ | H `tools/checkpoint_manager.py`、`checkpoint_pruning.py` | 对照补强 | Atlas 的影子 git 已经不错，取 H 的清理策略 |
| 凭据库 / 网站登录保管 | ❌ | H `agent/vault_store.py`、`tools/browser_vault_tool.py`、`agent/secret_scope.py`；O `extensions/onepassword`、`vault` | 拷贝改 | |
| 沙箱 | ✅ Docker | H `tools/environments/docker.py`、`docker_egress.py`（出网控制） | 对照补强 | |
| 紧急停止 | ✅ 停止 | H `agent/estop.py` | 参考 | |

### C. 子 Agent、编排、看板

| 能力 | Atlas | 来源 | 方式 | 备注 |
| --- | --- | --- | --- | --- |
| 子 Agent 委派、并行、后台 | ✅ 基础 | H `tools/delegate_tool*.py`（配置、调度、进度、结果、工具集）、`async_delegation.py`、`subagent_worktree.py`、`agent/subagent_lifecycle.py`、`delegation_context.py` | 拷贝改 | 后台委派和运行中引导 H 已有 |
| 子 Agent 定义文件格式 | ❌ | OH（Markdown + frontmatter，字段最全）、CX（`.codex/agents/*.toml`）、OC（`.opencode/agent/*.md`）、Claude Code（`.claude/agents/*.md`） | 照格式写解析器 | 各家官方文档确认字段 |
| 看板 / 多 Agent 团队 | 🟡 看板页 | H `hermes_cli/kanban*.py`、`tools/kanban_tools.py`、`plugins/kanban`、`gateway/kanban_watchers*.py`；O `extensions/workboard` | 拷贝改 | |
| 配方当 Worker | ❌ | G 子配方（Rust，逻辑参考） | 移植 | |
| 远程子 Agent（A2A） | ❌ | H `plugins/platforms/a2a`；O `extensions/a2a`；GM | 拷贝改 H | |
| 待办清单工具 | ? | H `tools/todo_tool.py` | 拷贝改 | |

### D. 工具：文件、命令、代码、编程

| 能力 | Atlas | 来源 | 方式 | 备注 |
| --- | --- | --- | --- | --- |
| 文件读写、模糊匹配编辑、补丁 | ✅ | H `tools/file_operations*.py`、`fuzzy_match.py`、`patch_parser.py`、`file_state.py` | 对照补强 | |
| 终端 / 后台进程 | ✅ | H `tools/terminal_tool*.py`、`process_registry*.py` | 对照补强 | |
| 执行环境（本机、SSH；**不做沙箱 / 云端环境**，用户决定） | ✅ 本机 / Docker / SSH | H `tools/environments/`（daytona、modal、singularity、vercel_sandbox、ssh、file_sync） | 拷贝改 | `file_sync.py`：远程执行环境的文件同步（按修改时间和大小增量同步、检测删除），SSH 远程目录可以用它补强（已确认） |
| 代码执行内核 | ✅ execute_code | H `tools/code_kernel*.py`、`code_execution_*.py` | 对照补强 | |
| LSP | ❌ | H `agent/lsp/` | 拷贝改 | 编程体验加分项 |
| 改动 diff | ✅ | H `tools/working_diff.py` | 参考 | |
| 依赖漏洞检查 | ❌ | H `tools/osv_check.py` | 拷贝改 | 安全扫描配方的一部分 |

### E. 浏览器与电脑操作

| 能力 | Atlas | 来源 | 方式 | 备注 |
| --- | --- | --- | --- | --- |
| **Windows 后台操作（不抢鼠标）** | ❌ 前台抢鼠标 | CUA `libs/cua-driver`（UIA / MSAA / PostMessage 调度、PrintWindow / WGC 后台截图、透明光标层、命名管道守护进程解决 SSH 下的 Session 0 问题）；H `tools/computer_use/cua_backend*.py`（Python 接法） | 依赖 cua-driver + 拷贝改 H 的接入层 | 这是调研里「开源没人做好」的点，现在有现成的 |
| 电脑操作策略 | ✅ | AS（Agent S3）；TARS | 参考 | |
| 浏览器工具（CDP、快照、视觉、对话框、多帧） | ✅ | H `tools/browser_tool*.py`（底层是 `agent-browser` 命令行，可接本机 Chromium、Browser Use / Browserbase 云、用户提供的 CDP、Camofox；无障碍树快照用 `@eN` 引用元素）、`browser_supervisor*.py`（常驻 CDP 连接，捕获对话框和多帧）、`browser_cdp_tool.py`、`browser_dialog_tool.py` | 拷贝改 | |
| 复用你自己的浏览器配置 | 🟡 | H `tools/browser_tool_real_profile.py`（把你默认的 Chromium 配置**复制一份**给 Agent 用，再用真实浏览器程序打开，不碰原配置） | 拷贝改 | |
| 云浏览器 / 反检测 | ❌ | H `tools/browser_tool_cloud.py`、`browser_camofox.py`、`browser_lightpanda.py` | 可选 | |
| 用浏览器扩展操作你自己的浏览器（类似 Claude in Chrome） | ❌ | H `gateway/browser_control_broker.py`（控制者与调用方的票据绑定：短期、一次性、按身份绑定）、`tools/browser_extension_router.py`（按调用决定走扩展还是原后端，失败一律关闭不乱跳） | 拷贝改 | 已读源码确认 |
| 人工接管（登录、验证码） | ❌ | 没有现成的独立模块，自己写交接卡片；登录用下一行的凭据填表 | 自己写 | |
| 模型看不见密码的自动填表 | ❌ | H `tools/browser_vault_tool.py`（770 行：`browser_vault_list` 只返回句柄、`browser_vault_fill` 由后端直接填密码 / 银行卡 / 地址，银行卡要用户确认）、`agent/vault_store.py` | 拷贝改 | 已读源码确认 |
| 演示录制 → 技能、缓存重放、自愈 | ❌ | SH（缓存目录、选择器自愈）；BU 的 skills | 移植 SH 逻辑 | |
| 读取窗口内容 | ? | H `tools/read_window_tool.py` | 拷贝改 | |

### F. 连接器、MCP、渠道、自动化

| 能力 | Atlas | 来源 | 方式 | 备注 |
| --- | --- | --- | --- | --- |
| MCP 客户端（HTTP、OAuth、健康检查、采样、按作用域） | 🟡 只有 stdio / SSE | H `tools/mcp_tool*.py`（15 个兄弟文件：传输、发现、健康、采样、作用域…）、`mcp_oauth*.py`、`mcp_schema_cache.py` | 拷贝改 | |
| MCP Apps（对话里的交互界面） | ❌ | MCPUI `modelcontextprotocol/ext-apps`、`@mcp-ui/client` 的 `AppRenderer` | 依赖（前端） | |
| 连接器目录 + 一键接入 | ❌ | H `tools/connectors/`（catalog、search、mcp_oauth、live、managed）；国内服务清单 CN | 拷贝改 + 补国内条目 | |
| 飞书文档 / 云盘 | ❌ | H `tools/feishu_doc_tool.py`、`feishu_drive_tool.py`、`feishu_lark.py`；飞书官方 `larksuite/lark-openapi-mcp` | 拷贝改 / 接 MCP | |
| Microsoft 365 | ❌ | H `tools/microsoft_graph_*.py` | 拷贝改 | |
| 聊天渠道（手机派活） | 🟡 Telegram | H `gateway/` + `plugins/platforms/`（feishu、dingtalk、wecom、email、whatsapp、slack、discord、teams、sms…；没有个人微信）；`gateway/platforms/ADDING_A_PLATFORM.md` | 拷贝改 | 国内优先：飞书、钉钉、企业微信、邮件 |
| 定时任务 | ✅ | H `cron/`（预检、补跑、配额等待、失败通知、建议目录）| 对照补强 | |
| 入站 Webhook | ❌ | O `docs/automation/cron-jobs/webhooks.md` 的设计（专用令牌、幂等键、`waitForCompletion`、按路径映射到 Agent 和模板） | 照设计移植 | |
| 邮件触发（IMAP） | ❌ | O `extensions/imap`；H `plugins/platforms/email` | 移植 / 拷贝改 | O 的「受限读信 Agent」处理不可信邮件，必须照做 |
| 条件触发（某事发生时提醒我） | ❌ | O `docs/concepts/standing-intents.md`（关键词全文预筛、不调模型、冷却 24 小时、最多 3 次、90 天过期） | 照设计移植 | |
| 出站 Webhook / 通知 | ✅ 通知 | H `agent/outbound_webhooks.py` | 参考 | |

### G. 记忆与技能（记忆冻结，技能可以做）

| 能力 | Atlas | 来源 | 方式 | 备注 |
| --- | --- | --- | --- | --- |
| 技能市场（skills.sh、ClawHub、GitHub、官方） | 🟡 有联邦 | H `tools/skills_hub*.py`（`skills_hub_skillssh.py`、`skills_hub_clawhub.py`、`skills_hub_github.py`、`skills_hub_official.py`、`skills_hub_install.py`） | 拷贝改 | |
| 技能安全扫描 | 🟡 有信任流程 | H `tools/skills_guard.py`、`skills_ast_audit.py`、`skillevaluator_scan.py`、`skill_linter.py`、`skill_provenance.py` | 拷贝改 | 防「技能误进化」 |
| 技能自学和整理 | 🟡 | H `agent/background_review.py`、`review_engine.py`、`curator.py`、`learning_graph.py`、`tools/skill_manager_tool.py` | 拷贝改（记忆解冻前只做技能部分） | |
| Office 技能（docx、pptx、xlsx、pdf） | ✅ 自己写的 | H `skills/productivity/{docx,powerpoint,xlsx,pdf}` | 对照补强 | |
| 记忆（运行前主动回忆、Wiki、后台整理） | 冻结 | O `extensions/active-memory`、`memory-wiki`、`memory-core`；H `plugins/memory/*`；CM | — | 解冻时用 |
| 外部内容不进长期记忆 | ❌ | O 记忆来源标记（v2026.8.1） | 照设计移植 | 安全项，冻结期也做 |

### H. 语音

| 能力 | Atlas | 来源 | 方式 | 备注 |
| --- | --- | --- | --- | --- |
| 本地识别 | ❌（浏览器识别在 Electron 里用不了） | SO（SenseVoice + Silero VAD）；H `tools/transcription_local.py`、`transcription_*.py` | 依赖 SO + 拷贝改 H 的接入层 | |
| 语音对话模式、唤醒词 | 🟡 | H `tools/voice_mode.py`、`voice_live.py`、`wake_word*.py`、`gateway/run_voice.py` | 拷贝改 | |
| 语音合成 | ✅ 系统朗读 | H `tools/tts_*.py`（本地、OpenAI、流式）；SO | 拷贝改 | |

### I. 产出物

| 能力 | Atlas | 来源 | 方式 | 备注 |
| --- | --- | --- | --- | --- |
| 产物预览（沙箱实时预览） | ✅ | H `apps/desktop` 的产物预览、`tools/preview_tool.py`、`annotate_preview_tool.py`、`apply_layout_tool.py` | 拷贝改（前端） | |
| 网页 / 应用产物 | ✅ | O `extensions/canvas` | 参考 | |
| 文档提取 | ✅ | O `extensions/document-extract`、`web-readability`；H `tools/read_extract.py`、`web_tools_extract.py` | 对照补强 | |
| 图像生成（视频暂不做） | 🟡 | H `plugins/image_gen`、`tools/image_generation_tool.py` | 拷贝改 | |
| 会话分享链接 | ❌ | O `extensions/session-share`（可撤销只读链接） | 移植 | |

### J. 跨设备、手机、常驻

| 能力 | Atlas | 来源 | 方式 | 备注 |
| --- | --- | --- | --- | --- |
| 设备配对 | ❌ | O `extensions/device-pair`（逻辑移植）；H `gateway/pairing.py` 是聊天渠道的**陌生人配对码**（8 位、1 小时、失败锁定，已确认），配对码的安全参数可以照抄 | 移植 O + 参考 H | |
| 手机 / 网页控制台 | ❌ | H `web/`（仪表盘嵌入真实对话）、`hermes_cli/web_routers/`、`dashboard_auth`；O `ui/` | 拷贝改 H | |
| 中转（没有公网 IP 也能从外面连） | ❌ | H `gateway/relay/`、`hermes_cli/proxy` | 拷贝改 | |
| 主机常驻 / 开机自启 / 看门狗 | ✅ Hub | H `hermes_startup_watchdog.py`、`gateway/restart*.py`、`scale_to_zero.py` | 对照补强 | |

### K. 前端（Atlas 自己的界面）

Hermes 桌面端（`apps/desktop`，React 19 + Tailwind 4 + Electron 40 + Vite 8 + xterm + shiki）和 Atlas 技术栈一样，组件可以直接搬过来改样式。优先看：
- 审批、提问、密钥等「Agent 问你」的卡片：`apps/desktop/.../gateway-event/server-requests.ts` 及对应组件
- 连接器接入卡片：`store/connection-request.ts`
- 产物沙箱预览、看板、定时任务、设置页
- 前后端协议用 Pydantic 声明、自动生成 TS 类型（`tui_gateway/contracts/` → `apps/shared/src/gateway-contract.generated.ts`）——Atlas 的 `backend-adapter` 也应该改成这种方式，避免前后端字段对不上

OpenClaw 界面是 Lit（不是 React），只参考交互设计。

## 三、使用规则

0. 本文件的「路径」来自 2026-09-30 的仓库文件列表，用途大多按文件名和架构说明判断；标 ⚠️ 的尤其要先读源码确认。

1. 动手前先打开来源文件读完，确认它在最新提交里还存在（这两个项目每天都在大改，路径可能变；用 `gh api repos/<仓库>/contents/<路径>` 或克隆到临时目录）。
2. 拷贝的文件头写：`# Ported from <仓库>@<提交号>:<路径> (<许可证>). Changes: ...`
3. 登记到 `docs/plan/VENDORED.md`。
4. Hermes 的模块之间耦合很重（门面 + 兄弟文件），**不要整包搬**：只拿需要的函数和数据结构，接到 Atlas 已有的接口上；Hermes 的配置读取（`~/.hermes/config.yaml`、`get_hermes_home()`）全部换成 Atlas 的 `atlas.config`。
5. 搬过来的东西要带上来源项目对应的测试（改成 Atlas 的接口），没有测试的自己补。

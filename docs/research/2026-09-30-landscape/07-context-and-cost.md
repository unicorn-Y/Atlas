# 专题 7：上下文与成本效率（2026-09-30）

同样的模型，harness 做得好不好，成本和速度能差出三成以上。这块用户看不见，但每天都在花钱。

## 一、当前最强做法

1. **提示缓存（降本最有效的一招）**：成本降 41–80%，首字延迟降 13–31%。重复发送的上下文按折扣价计费（Gemini 约一折，DeepSeek 缓存价便宜约 50 倍）。关键是**保持前缀稳定**：系统提示、工具定义放在最前面且不变，只在末尾追加。
2. **「少压缩、多缓存」的新共识**：有了缓存，保留全部历史往往比总结更便宜、更快、记得更牢。**把每个工具输出截到固定的长度上限**，每轮成本降 38%，记忆效果没有可测的损失——因为它缩小了上下文，又不改写缓存依赖的前缀。
3. **按需加载工具**：
   - Claude Code：工具多时只发工具清单，模型用 ToolSearch 按需加载。
   - Cursor（9-23）：动态加载工具、精简系统提示、压缩文件读取、提高缓存复用、调优子 Agent，token 成本降 7%。
   - Manus Cascade：用到才加载模块，token 少 23%、成本低 32%。
   - 注意：动态插入到上下文中间的工具定义会破坏缓存，要放在末尾或用供应商支持的方式。
4. **压缩要按规则优先**（上一轮调研已记）：先删旧的工具输出和重复内容，最后才让模型总结。
5. **上下文优化中间层**：Headroom 这类工具夹在 Agent 和模型之间，压缩工具输出、日志、文件、检索片段。
6. **成本可见**：Codex v0.158 加了 `/usage` 用量面板；Datadog 把 Agent 的 token 成本做进生产监控。

## 二、Atlas 现状

| 能力 | Atlas | 差距 |
| --- | --- | --- |
| 提示缓存 | ❌ 代码里没有 `cache_control` 之类的处理 | **最大的单项浪费** |
| 工具输出长度上限 | 🟡 超长结果存到文件、只给开头和结尾（`full_output_path`） | 已经在做，确认上限是固定的 |
| 按需加载工具 | ❌ 所有工具每轮都发 | |
| 压缩 | ✅ 自动 + 手动 | 改成规则优先 |
| 用量显示 | ✅ 每次运行显示 token 数，上下文占用 | 没有按天、按对话的累计和费用 |

## 三、Atlas 该做的

1. **打开提示缓存**：Atlas 通过 litellm 和 OpenAI 兼容网关调用模型。对 Anthropic 模型加缓存标记，OpenAI / DeepSeek / Gemini 类模型依赖供应商的自动前缀缓存——关键是保证**系统提示 + 工具定义 + 规则文件**这段前缀每轮都一样（不要把时间戳、随机 ID、会变的记忆塞进前缀）。先测一次命中率再说。
2. **稳定的工具输出上限**：确认所有工具输出都有固定上限，超出部分存文件（已有机制）。
3. **按需加载工具**：MCP 和脚本工具多的时候，只发工具清单，需要时再加载（第七波候选，已在上一轮调研里）。
4. **压缩改成规则优先**：先删旧的工具输出，保留最近几轮的完整内容，最后才总结。
5. **用量面板**：按天、按对话、按模型统计 token 和估算费用，显示缓存命中率。

## 资料

- [2026 年上下文工程：为什么我们不再压缩上下文](https://www.louisbouchard.ai/context-engineering-2026/)
- [不要破坏缓存：长程 Agent 任务的提示缓存评估（arXiv 2601.06007）](https://arxiv.org/pdf/2601.06007)
- [2026 年提示缓存工程指南](https://www.digitalapplied.com/blog/prompt-caching-2026-cut-llm-costs-engineering-guide)、[上下文缓存](https://atlan.com/know/context-caching/)
- [8 个降低编程 Agent token 用量的开源工具](https://pinggy.io/blog/tools_to_reduce_ai_coding_agent_token_usage/)
- [让 Agent 的 token 成本在生产中可见（Datadog）](https://www.datadoghq.com/blog/making-agentic-token-costs-visible-in-production/)
- [Cursor 更新日志（2026-09-23 harness 改进）](https://cursor.com/changelog)、[Manus Cascade](https://pandaily.com/manus-2-0-cascade-agent-harness-cue-personal-agents)
- [Codex 更新日志](https://developers.openai.com/codex/changelog)

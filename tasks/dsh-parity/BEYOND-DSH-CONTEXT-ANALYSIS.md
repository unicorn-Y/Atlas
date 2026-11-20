# 多轮上下文增长：只读源码诊断

日期：2026-11-15。固定 Atlas 开工基线 060071ab2ecf86d41cab90e98160183ce126bc69，分析时含当前未提交修改。仅只读代码分析，未运行模型、基准或服务，未访问密钥/用户数据库/真实记忆，未写实现。实施交由 Codex 桌面 6 Luna。

## 核心结论

已证明存在每轮装配上下文随 user 历史累积的机制；尚不能证明历史报告约 +1,612 tokens/轮全部由此造成。历史 MULTITURN.md 只有汇总，旧脚本不验证最终回复恰好一个词，也未记录请求/工具数与最终 wire 分项。

## 证据路径

- run_phases.py:169-174,1338-1350：时钟、召回、技能索引、项目上下文归为 volatile，从 system 抽出。
- kernel/loop.py:947,1011-1018：作为 turn_context 随 user 消息持久化。
- kernel/loop.py:542-559：从 display_metadata 恢复历史 turn_context。
- kernel/loop.py:374-394：装配请求时逐条前置历史 user 的 turn_context，因此相同/近似技能目录可线性累积。
- kernel/loop.py:2798-2802；state/atlas_state_messages.py:1716-1722：无工具最终回复的 reasoning 作为独立字段持久化/恢复，不等于全部发送。models/router.py:731-745 的 OpenAI wire 不发送 reasoning，仅 DeepSeek 分支允许 reasoning_content；工具分支另存 reasoning_content/details（loop.py:2827-2848）。必须按最终 payload 字段归因，不按数据库字段长度猜。
- run_phases.py:1114-1122、kernel/prompt.py:185-194、kernel/model_call.py:864-881：system 每轮重建且 builder 额外前置一次，tools 单独传输；未证明整个 system/schema 每轮追加进历史。真实 tool call/result 则会持久化。
- agent/enrichment.py:262-282：ContextMaintenance 只是筛字段/快照/hook，不是改 messages 的压缩器。常规路径实际使用 ContextManager.prepare（kernel/loop.py:1558,2004-2020,2155），低阈值以下直接返回（kernel/context.py:450-459）。idle维护为prune/vacuum，不能混同。

行号为只读分析快照，后续实施可能变化。

## 最小诊断/修复建议（尚未实施）

1. 用合成八轮与测试 provider 在最终 wire 捕获每个请求的role数、文本/推理字段长度、section摘要指纹、source turn，区分逐请求与整run SUM；不记录真实正文/密钥。
2. 确认证据后在模型surface做来源感知当前态投影/去重，保留原持久审计；不能笼统删除历史上下文、用户文件引用、有效历史约束，也不能破坏缓存前缀。
3. 验证新鲜时钟/权限/技能、历史引用、fork/replay/compact边界，再在隔离数据目录中真实模型复测。
4. 基准另修：DSH累加所有step_end usage，完整prompt包括input+cacheRead+cacheWrite，缺失为unknown；验证final/工具结果，而不只检查completed。

## 置信边界

源码装配/持久化/wire/压缩调用链：高。历史+1,612精确贡献分解：低。不得把此诊断当真实模型验证或性能胜出证据。

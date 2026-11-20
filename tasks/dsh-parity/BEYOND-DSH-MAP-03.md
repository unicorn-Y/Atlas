# 引擎与 SDK：新增语义能力地图

2026-11-16，固定DSH d743267388641bc76f17c45ce8b4c231aed1d32c。独立只读核对，未运行网络/模型/服务/测试，无生产修改。不是CLOSED或全面审计。当前先由桌面Luna收敛X5/X7，随后X30；本图是后续增量，不打断施工。

## A：模型失败尝试隔离与可恢复重试决定

DSH packages/core/agent-loop/src/agent.ts:505/529：失败内容记录assistant/attempt，成功另记assistant/message并进入surface。packages/llm/llm-retry/src/index.ts:125/149/219：按provider/policy投影预算，重试决定先追加llm/retry再等待，等待后llm/retry-started。:194/243有限预算、Retry-After上限、取消/卸载排空。日志投影本身不证明崩溃后自动恢复定时器。

Atlas已有真实入口core/atlas/engine/kernel/loop.py:2689调用complete_stream，传cancel/retry/fallback/usage/on_attempt；model_call.py:288/483/1283已有认证/账单/限流/连接分类、跨fallback总次数与等待预算、可取消等待。不可判这些全无。

静态差距：model_call.py:769在候选循环外初始化combined_text，:970 overlap合并旧文本，:1075成功返回；_overlap_merge(:146)无重叠时拼接。首次输出旧片段后断流、重试不同新答案可混入成功结果，kernel :2872/:2963随后持久化。此为静态可推出路径，未执行复现。:1256 on_attempt及loop.py:1915 model_error已有run日志，但loop.py:996 record失败记录异常后继续；本链未见规范会话日志重建provider/policy预算，不可扩大为全库没有其他恢复器。

建议增量：每次尝试身份；失败片段仅审计，成功历史只提交成功尝试，UI需撤回/替换语义；schedule/start写规范session log并定义重启恢复/终止策略。保留Atlas跨fallback总预算。真实kernel本地流fixture验证部分文本断流→不同成功、失败工具参数不执行、等待取消、日志写失败及重开预算不重置。新增桌面事件需三真源同步。

## B：SDK 入队身份与可组合事件消费

DSH packages/sdk/server/src/index.ts:75派发stdio；server.ts:195 prompt→followup立即返回messageId；agent.ts:154→inbox.ts:227先追加agent/inbox/spliced再唤醒。packages/sdk/client/src/api.ts:195/:311先订阅、发prompt、按receipt收至idle，最终取已提交assistant。server.ts:221 wait拒绝未知/失效并保留未被durable terminal解释的live failure。

Atlas已有core/atlas/cli.py:2050 app-server→serve_stdio，sdk/python/atlas_sdk/app_server.py:48启动并协商版本；core/atlas/tools/app_server.py:421/:702已有preset/审批/取消/断开拒绝，Python无approve回调默认拒绝(:133)。这些能力应保留。

差距限于当前stdio/SDK：tools/app_server.py:580活动时拒第二prompt，:309回执等运行结束；:243/:297转运行事件而非规范session序列；Python SDK :84/:117串行_request跳过不匹配帧，无统一读循环/session队列。wait(:316)返回空对象，run finally(:638)释放waiter，只证明落定不证明成功。DurableInbox(:34/:77)已有先事件后身份/重开pending原语，但kernel/loop.py:2309把注入投影developer；不能直接接用户prompt造成角色提升。

建议加法增量：保留同步prompt，新增enqueue/receipt及规范事件订阅，稳定身份/来源/用户角色，单一reader分派response/notification/approval并按session路由，区分落定/成功。用协议transport fixture交错双会话/审批/通知、丢回执恢复、失败后wait验证。未核验所有HTTP/WS等价路径、子任务屏障或跨进程恢复，不能据此判全缺。旧X25已记完成回执差异，不重复包装成新发现。

## 旧 HARD 边界修正

- S26：session-log-deepseek/README.md:40/:47 是私有dsh_session_log扩展及2xx acceptance watermark，不是普通Chat Completions能力。未审实现，不自动上传会话或宣称私有兼容。
- S30：本轮未审完整记忆子系统，旧“DSH完全没有长期记忆”否定结论未复核；不能凭旧账宣称超越，也不与S26上传混同。
- S10：compaction-image-offload/README.md:38/:80 区分附件字节持久化与图像预算触发的永久occurrence投影。superseded by S19依据不足，需独立核验；本图未完成第三能力族实施核对，不另派上下文施工。

静态数据流high；全替代能力/成本medium。文件行号随工作树变化，实施前复核。135项不是全集，本图不报新覆盖百分比。

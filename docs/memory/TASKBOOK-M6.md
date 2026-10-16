# TASKBOOK-M6：委派上下文 Broker 与结果回收

状态：待后续授权施工。本文件是合同，不表示已实现。

## 目标与来源

Atlas 是唯一规范长期记忆主体；外部 Codex/Claude/其他 agent 拥有用户授权任务所需执行权，但不直接写 Atlas canonical store。参考 `NousResearch/hermes-agent@607a0b0d41e07d903c0b475dd72fb6ac2b37fecc:agent/memory_provider.py:on_delegation` 生命周期接点及 Codex 子会话“不跑第一阶段”的范围策略；ContextBroker 为 Atlas 原生模块。C 线核验的 `MemOS@a7367d07e55db61099f7b4e2c1108bc5831a24f3` adapter transport retry 不保障记忆成功；open-multi-agent 结果 key 随机、默认内存态且 fail-open，不直接移植为授权或持久协议。

## Atlas 目标与替换

目标 Atlas agent dispatch/context preparation 入口与新增 `core/atlas/memory/library/context_broker.py`。替换目前委派路径中只靠静态 prompt 拼接的记忆准备；不得绕过现有 agent 权限或把 memory store 暴露成任意写工具。

## 契约

派发前按任务、项目、权限从 M5 召回；初始 bundle 包含短摘要与可读引用。运行时提供受控 search/read 请求，记录 delegate、scope、request、returned refs。完成后记录 transcript/result 指针，按来源等级标为外部工具观察或模型推断，经 M3 提炼后才能成为规范记忆。broker 调用 fail closed on authorization error；记忆服务暂不可用时任务可继续执行，但必须记录“未注入记忆”而不能伪称完成。

## 数据迁移

旧委派结果可建立外部来源 event wrapper；缺失 delegate identity 或原文的旧结果标 legacy。不得把旧 agent memory 自动导入为 Atlas 事实。令牌/权限仅存引用，不复制凭证。

## 最小真实使用验收

用两个权限 scope 不同的真实委派任务：派发前各自取得正确上下文，跨 scope 引用被拒；运行时追加取忆有审计；完成后结果可回收并进入待提炼队列；broker 故障时任务状态与“无记忆注入”日志一致；外部 agent 无法直接改 canonical Markdown。

## 依赖与并行

依赖 M1、M2、M5。与 M8 可并行，独占 broker/dispatch adapter 文件；M1 不得改 broker 协议。

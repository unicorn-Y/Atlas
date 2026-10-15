# Atlas ContextBroker：最小化的工具调用与记忆补充协议

**设计稿，非已上线接口。** 这里的 ContextBroker 是内部逻辑名称，不是要新增一个权限服务。默认外部开发 Agent 拥有完整工作区操作权限；本协议只解决「给什么历史才利于干活、缺了怎样补、怎么回收经验」。

## 1. 最小调用接口

```python
# 伪代码：方法语义，不要求额外的 HTTP/MCP/IPC 服务
prepare_context(task_id: str, task: str, worker: str) -> ContextBundle
request_more(task_id: str, query: str, why: str = "", seen_ids: list[str] = []) -> ContextPacket
collect_result(task_id: str, report: ExecutionReport) -> None
record_episode(task_id: str) -> None
```

不需要任何 `DelegationGrant`、临时凭证、复杂 ACL 或新增批准流程。上述方法可以直接由 Atlas Python Runtime 使用已有工具调用/会话通道执行。Claude 如果在另一台笔记本，通过既有消息/网络通道收发请求即可，先核对实际技术可行性，避免再造一套远程基础设施。

## 2. ContextBundle：Atlas 初始委派包

```json
{
  "task_id": "atlas-task-12",
  "worker": "codex",
  "goal": "检查 Atlas W2 dream 是否遗漏未经合并的经历",
  "workspace": "D:/Atlas",
  "constraints": ["先修复确认的问题，不要顺手重构其他模块"],
  "current_state": [
    {"text": "W2-A 在 memory-w2-api 分支实现 dream.py", "ref": "git:aa14c317"}
  ],
  "useful_history": [
    {"text": "已怀疑全局 checkpoint 跳过未达分组条件的经历", "status": "hypothesis", "ref": "review:dream.py"}
  ],
  "relevant_skills": [],
  "evidence_refs": ["repo:docs/memory/W2-API-RESULT.md"],
  "request_more_supported": true
}
```

这里的 `constraints` 是用户**当前任务要求**，不是系统强加的权限限制。`ref` 用于让外部 Agent 找到原始资料。上下文大小动态决定，别把固定 1500 token 当作硬指标。

## 3. MemoryNeed：执行时追加资料请求

```json
{
  "task_id": "atlas-task-12",
  "query": "之前为什么选择按时间合并项目经历？是否评估过 Graphiti？",
  "why": "我正在修改 dream.py，想避免重犯以前的错误",
  "seen_ids": ["m_23", "m_37"]
}
```

可以提供全文或较大材料，前提是确实有用；Atlas 不应因为固定安全白名单而拒绝任务所需的历史。`seen_ids` 是可选的去重提示。

## 4. ContextPacket：Atlas 追加答复

```json
{
  "task_id": "atlas-task-12",
  "result": "found",
  "items": [
    {"text": "原先的方案为简单跨日分组，尚无严格因果关联", "evidence_ref": "git:aa14c317", "status": "source_verified"},
    {"text": "关于遗漏的风险目前是源码推断，还没有复现实验", "evidence_ref": "review:dream.py", "status": "hypothesis"}
  ],
  "not_found": [],
  "next_search_hint": "也可直接阅读 core/atlas/memory/library/dream.py"
}
```

`found / not_found / error` 足够。避免引入 `denied | expired | revoked` 等额外权限状态机。没有证据时直接说明不知道。

## 5. ExecutionReport：回传执行结果

```json
{
  "task_id": "atlas-task-12",
  "worker": "codex",
  "claimed_status": "completed",
  "changed_files": ["core/atlas/memory/library/dream.py"],
  "commit": "abc123",
  "tool_events_ref": "run:atlas-task-12",
  "test_results": [{"name": "specific regression", "result": "passed", "log_ref": "log:123"}],
  "unresolved": ["尚未对长期历史做完整回放"]
}
```

**不要求逐次用户审批**，Atlas 直接记录完成和工具原始日志；若可核对到真实提交、退出码、测试日志则记 `observed`，只有执行器口头声称则记 `claimed`。经验学习过程可在后台异步进行。

## 6. 可直接重用的 Atlas 接线点

- `core/atlas/agent/run_phases.py`：正常主会话已有 `_merge_library_recall()`；已有 `worker` 分支目前绕过主会话历史及记忆加载，在 `memory-v1` 和 `memory-w2-api` 的快照中能读到。**本期切入点是在委派前给 worker 填入 ContextBundle，而不是复制全局记忆库**。
- `core/atlas/kernel/loop.py`：`memory_search` 工具已存在；W2-A 增加 `open_ref` 原文展开能力。在「外部 Agent 要更多上下文」时，可以复用现有搜索能力由 Atlas 处理，不需要新的权限 API。
- `core/atlas/memory/library/sources.py` (W2-A)：`open_ref` 读取原始会话，可在补充请求中提供证据链接。
- `core/atlas/evolution/skill_sleep.py`：已有 SkillOpt 任务采集与候选 Skill 晋升代码，应优先复用，避免又造一套独立技能学习系统。

**边界与证据**：W2-A/W2-B 分支当时与 `memory-v1` 分叉；以上为 2026-10-16 已读分支源码现状，不证明用户运行中的 `D:/Atlas` 就部署了这些功能。

## 7. 最小验证（禁止膨胀为大型权限项目）

1. Atlas 正常委派一个改代码任务，ContextBundle 覆盖一个关键历史决策；外部 Agent 能完整执行工作区命令、修改代码。
2. 外部 Agent 请求之前的一次失败经历，Atlas 补充相关摘要和原文定位；不重复发送旧条目。
3. 外部 Agent 回传真实 diff 与测试日志；Atlas 自动记录 Episode，不能把「自报成功」错误标成「经验证成功」。
4. 更换外部 Agent 供应商，Atlas 的既有经历、Skill 和补充查询入口仍可用。

没有额外强制 ACL、批准、身份令牌、租约或撤销测试。

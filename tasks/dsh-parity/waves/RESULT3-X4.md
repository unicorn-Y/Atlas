# WAVE 3 — X4 结果（S5、S7–S9、S12、S14、S17–S18、S20、S23–S24、S26–S27、S29、S31、S33）

日期：2026-11-14  
分支：`wave3`  
基线：`2bc3a626`  
提交：本批提交后补录

## 逐条结论

| Row | 状态 | 依据 / 未完成项 |
|---|---|---|
| S5 | PARTIAL | SessionDB 有 WAL、busy timeout 和 TTL lease；没有 read/append/flush/close handle API，也不能验证持有进程存活。 |
| S7 | PARTIAL | 有压缩 run-log 记录和 DB lease；缺包含 shadowed seqs/token/provider/model 的可重建 bracket。 |
| S8 | PARTIAL | Atlas 使用全局 context window 与 buffer/percentage 配置；没有目标的固定 0.8/0.16 策略及 per-provider-model override。 |
| S9 | PARTIAL | oversized tool result 会内容寻址保存、剪裁预览并写 output metadata；本批未做真实重启后 replay 的模型行为验证。 |
| S12 | PARTIAL | 现有 `state/projections.py` 与 `session_projections.py` 都是进程内缓存；没有 `session_projcache` 持久表。 |
| S14 | PARTIAL | kernel 有 `session_search`、`read_session` 等部分面；无完整五工具 query/trace/event surface。 |
| S17 | PARTIAL | 已有 JSON HTTP 导出路由和 route tests；不是 ZIP，也未证明 live root flush 或附件字节导出。 |
| S18 | PARTIAL | 有内容寻址 spill 文件及清理实现；缺 locator/bytes/hint 统一返回和保存失败保留原文契约。 |
| S20 | PARTIAL | legacy agent 有 `present` 工具与 artifact event；没有 per-turn `workspace/changes`。本批真实模型未执行 `present`。 |
| S23 | NOT-DONE | 无按 `(sessionId,formatVersion,seq)` 去重的规范事件 telemetry ledger。 |
| S24 | NOT-DONE | 无调用方 opt-in 的 OTLP/HTTP product telemetry seam。 |
| S26 | NOT-DONE | 仓库无官方 DeepSeek 会话上传 contract；未猜测或实现对外上传。 |
| S27 | PARTIAL | 有本地 skill catalog/index；缺 provider `list/get` 与 `skills/change` 失效通知契约。 |
| S29 | PARTIAL | 有 `read_session`，缺 `@session` 引用解析、host admission 与显式 untrusted 包裹。 |
| S31 | PRESENT-STRONGER | Atlas 已有 rewind/preview/redo 与文件还原实现；本批不改实现，避免退化。 |
| S33 | PARTIAL | durable run replay/checkpoint 测试通过；run log 不含模型/工具内容，本批没有真实失败尝试重放证据。 |

## 验证命令与真实输出

测试选择时先指定了不存在的 `tests/test_session_format_version.py`；pytest 拒绝执行该命令（`ERROR: file or directory not found`，`no tests ran`）。随后使用仓库内实际存在的测试文件执行：

```powershell
cd D:\Atlas\core
python -m pytest -q -p no:cacheprovider tests/test_session_projections.py tests/test_session_query_corpus.py tests/test_spill_store.py tests/test_conversation_export_route.py tests/test_kernel_checkpoint_barriers.py tests/test_run_replay.py
```

```text
........................................................................ [ 92%]
......                                                                   [100%]
78 passed, 5 warnings in 8.76s
```

5 条 warning 是既有 FastAPI `on_event` 和 Pydantic class-based config 弃用提示。

真实模型通道启动命令：

```powershell
cd D:\Atlas\core
$env:http_proxy='http://127.0.0.1:7897'; $env:https_proxy='http://127.0.0.1:7897'; python -m uvicorn atlas.server:app --port 8874
python scripts/dsh_live_ws_check.py 8874 "Create a file named wave3-s20-evidence.md in the active workspace containing exactly: S20_PRESENT_OK. Then call the present tool for that file with title Wave 3 evidence and summary S20 deliverable check. Reply with exactly the word: DONE"
```

后端实际启动输出包含：

```text
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8874 (Press CTRL+C to quit)
```

模型 helper 实际输出（节选事件顺序与最终状态）：

```text
[event] run.started
[event] tool.preparing name=local_exec
[event] tool.preparing name=tool_search
[event] tool.completed name=local_exec output_contract=text/local_exec output
[event] tool.completed name=tool_search output_contract=text/tool_search output
...（多轮 local_exec/tool_search；未出现 tool.preparing name=present）
[event] tool.preparing name=AskUserQuestion
[event] tool.started name=AskUserQuestion
[event] input.required tool=None waiting
[reply] "...（模型要求确认文件是否存在及 present 是否可用）..."
[result] terminal=None chars=234
```

模型通过 `local_exec` 实际创建了 `core/wave3-s20-evidence.md`，文件内容为 `S20_PRESENT_OK`；但没有出现 `present` 工具事件，随后触发 `AskUserQuestion`，最终不是 `run.completed`。因此只有文件创建行为得到 live 观测，deliverable registration 和 `workspace/changes` 均未证明，S20 保持 PARTIAL。该临时文件已在记录证据后删除。后端随后通过 Ctrl+C 关闭。本批没有把这次未完成的模型交互算成通过，也没有任何 S 行标为 CLOSED。

## 账本修正与未做范围

- 修正 S17 过期描述：JSON 导出 HTTP 路由及 route tests 已存在；目标 ZIP、live flush 与附件内容仍缺失。
- 把 S5、S7、S8、S12、S14、S18、S20、S27、S29、S33 的状态改成带本轮依据的 PARTIAL；S23、S24、S26 为 NOT-DONE；S31 保持 PRESENT-STRONGER。
- 本批没有新增功能代码或测试；没有产品 telemetry、DeepSeek 上传、projection cache 等写路径变更。
- 未运行完整后端测试套件；78 项结果仅涵盖列出的六个文件。

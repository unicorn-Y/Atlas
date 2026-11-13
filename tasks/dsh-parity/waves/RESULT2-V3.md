# WAVE 2 · V3 结果

## Rows

- **E8 — PARTIAL（实现补齐，实时证据受端口冲突阻塞）**：kernel 原来在模型 profile 没有 `max_output_tokens` 时把 `None` 传入 `int()`，导致进入任何模型前失败。现在按请求值、profile、模型配置、4096 的顺序解析输出上限。step 边界仍在每次模型请求前调用 `prepare_compaction()`，overflow 重试仍要求 provider history surface 前进。未能在本分支取得成功的真实模型回合，因此不声称本轮已实测关闭。
- **S9 — PARTIAL**：超阈值工具结果在首次持久化时先保存完整内容，再把 4096 字符头部、1024 字符尾部及全文引用作为 replacement 写入消息；`output_ref`、`microcompacted`、`masked_content` 进入消息 metadata，resume 投影会恢复这两个标记。未做真实 session 重启/恢复验证，保留 PARTIAL。
- **S25 — PARTIAL**：kernel 每个 conversation 请求现在按当前 model/provider route 对有序消息节点调用 `price_surface_nodes()`；逐节点与汇总估算写入 `model_request_envelope` 和真实模型 usage 记录。当前没有 provider route 的图片定价适配器，含图节点仍用既有 heuristic，因此不能关闭 route-aware image pricing 要求。

## 修改文件

- `core/atlas/engine/kernel/loop.py` — 修复空输出上限导致的模型调度崩溃；接入逐请求逐节点 token 计价；持久化工具结果剪枝标记及引用。
- `core/atlas/engine/kernel/context.py` — 新增持久化前 microcompact replacement，保留全文内容寻址引用。
- `docs/parity/DSH-GAP-LEDGER.md` — 更新 S9、S25 的实现范围和未完成证据。

## 静态验证

```text
python -m py_compile core/atlas/engine/kernel/context.py core/atlas/engine/kernel/loop.py
exit=0
git diff --check
exit=0
```

未运行单元测试。

## 真实模型验证（计划要求端口 8833）

计划要求在启动 shell 设置 `http_proxy=http://127.0.0.1:7897`、`https_proxy=http://127.0.0.1:7897`，使用 `deepseek-v4.1-flash` 并获得 `[terminal] run.completed` 与 `[reply] 'OK'`。本轮没有取得这项证据：

1. 本工作树启动 Uvicorn 时绑定 `127.0.0.1:8833` 收到 Windows `10048`，因为端口已被 PID 77480 占用；本次启动已自行退出。
2. 检查占用进程的 live-check 日志，确认服务加载的是另一个工作树 `D:\Atlas\.worktrees\dsh-w13`。对该服务运行计划中的 checker，实际输出为：

```text
[terminal] run.failed data={"category": "runtime", "detail": "TypeError: int() argument must be a string, a bytes-like object or a real number, not 'NoneType' (run log: D:\Atlas\.worktrees\dsh-w13\data\logs\runs\2026-11-13\e7dd1d3b-1385-4c48-80a3-014094c4afbc.jsonl)"}
[reply] ''
[result] terminal=run.failed chars=0
```

该请求由 W13 的进程处理，不能证明本分支的修复或 DeepSeek 通道；没有停止另一工作树的服务，也没有切换到其他端口冒充计划验证。**真实模型验收未通过/未观察，本轮 E8/S9/S25 均保留 PARTIAL。**

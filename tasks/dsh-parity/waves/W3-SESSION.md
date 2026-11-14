# WAVE 3 独立会话任务书

## 你的身份

你是一个 **批次负责人**（不是普通 worker）。你要：
1. 把本批次的行**再拆成 2–4 个子任务**
2. 为每个子任务 **spawn 一个子代理**（用你的 sub-agent 能力）
3. 你负责：读任务书、定文件清单、分派、验收、写 RESULT、commit
4. 子代理负责：具体实现 + 测试

**必须真的用子代理**。单线程串行做是上一轮的瓶颈，本轮要求并行。

## 必读

- `D:\Atlas\tasks\dsh-parity\WAVE3-PLAN.md` — 规则与验收标准
- `docs/parity/DSH-GAP-LEDGER.md` — 你负责行的 `path:line` 证据
- `AGENTS.md` — 仓库禁区

## 硬规则

1. 不重写 `messages` 表语义
2. 不在 `_execute_write` 回调里再调 `_execute_write`（死锁）
3. 事件名三处真源同步（`event_names.py` / `runtimeEvents.ts` / `runtime.ts`）
4. 测试需 `@pytest.mark.unit` 或 `integration`
5. **CLOSED 标准**：E/S/X 要单元测试 + 真实模型回合证据；D 要 vitest + TS 0 错误 + 组件测试
6. 不许把「写了代码」当 CLOSED；RESULT 必须贴真实命令输出

## 真实模型通道（已实测可用）

```bash
cd core
http_proxy=http://127.0.0.1:7897 https_proxy=http://127.0.0.1:7897 \
  python -m uvicorn atlas.server:app --port <你的端口>
python scripts/dsh_live_ws_check.py <你的端口> "Reply with exactly the word: OK"
```
模型 `deepseek-v4.1-flash`，key 在系统凭据库，不需要环境变量。

## 你的工作目录

**只在你被分配的 worktree 里改文件**。路径在启动消息里。

## 交付

1. 开工先输出：「子任务拆分 + 每个子任务的文件清单」
2. spawn 子代理并行做
3. 你验收每个子任务（跑测试、看证据）
4. 写 `tasks/dsh-parity/waves/RESULT3-<你的批号>.md`
5. commit 到你的分支

## 禁止

- 串行做完一个再做下一个（要并行）
- 跳过子代理自己全干
- 把 PARTIAL 说成 CLOSED
- 改别人的 worktree

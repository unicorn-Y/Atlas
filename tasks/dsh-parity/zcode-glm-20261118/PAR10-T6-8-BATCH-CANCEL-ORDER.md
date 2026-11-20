# PAR-10 · T6-8 任务书 · 工具批取消的结果顺序

## 选行与依据

- QUEUE 行:`F05-host`;ATLAS-MAP `B-F05-CANCEL-SYNTH-01` / `B-F05-BATCH-01`。
- 依据:`PAR10-RUNTIME-READY-NEXT.md` §工具批取消的结果顺序;`evidence/exec06-f05-batch-retry-sandbox-20261118.txt` §A。
- 已知契约:DSH `batch.ts` — runGroup slot 按 model order、committed 连续区间、abort 停止补位/排干已启动/为跳过调用合成结果;Atlas `tools.py` — `_execute_parallel`/`_gather_parallel` 取消已启动保留 receipt、未启动 `_cancelled_result(started=False)`、`_apply_batch_verdict` 统一终态。

## 工作树

- `D:\Atlas\.worktrees\zcode-par10-batch-cancel-order`
- 分支 `zcode/par10-batch-cancel-order`,HEAD `060071ab`。
- 主树 `core/atlas/engine/kernel/tools.py`/`loop.py` 在途只读;候选 HEAD 干净;只写本树与 `evidence/par10-t6-8.md`。
- 不 commit/push/merge/stash。

## 任务

1. 读候选树 `core/atlas/engine/kernel/tools.py` 的批调度入口(`run`/`_execute_parallel`/`_gather_parallel`/`_apply_batch_verdict`)与现有取消 receipt 测试;用临时确定性工具(可控延迟/Event)走正常调度入口,不只手写 mock。
2. 覆盖:
   - 请求顺序 A,B,C;完成顺序 C,A,B → 最终结果/上下文仍按 model order,每个 call ID 恰好一个最终结果;
   - 运行中取消(B 正在跑、C 排队)→ 已启动保留 terminal receipt,未启动合成 cancelled(started=False),取消原因留存;
   - 排队时取消(尚未 dispatch)→ 不伪造已启动结果;
   - 区分「模型工具结果顺序」与「进度事件顺序」,分别断言。
3. 只有复现缺口才补最小实现;若 Atlas 已对齐,交付隔离证据与可重放测试并更新结论。主树 `tools.py` 在途时不得改主树;若需产品修复,交付本树改动 + 对主树 `git apply --check`/冲突文件行。
4. 测试 `@pytest.mark.unit`;命令 `--basetemp=<worktree>/.tmp/... -p no:cacheprovider`;记录解释器/版本、完整命令、退出码、通过数;ruff 改动文件。

## 验收

- 每个 call ID 恰一个最终结果;结果按 model order;取消原因留存;进度事件顺序与结果顺序分开可判定。
- 若为对齐项,给出「无产品改动、测试/证据已对齐」结论;若有差异,最小修复与重放补丁。
- 回执 `evidence/par10-t6-8.md`,末行 `PAR10_RECEIPT T6-8 READY|PARTIAL|BLOCKED`。
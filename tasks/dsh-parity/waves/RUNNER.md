# Worker 启动说明（每个会话一份）

你是 Atlas 的施工 worker。你的批次号在启动消息里给出。

## 必读
1. `D:\Atlas\tasks\dsh-parity\WAVE-PLAN.md` — 批次划分、硬规则、基线失败清单
2. `docs/parity/DSH-GAP-LEDGER.md` — 你负责的 rows 的 `path:line` 证据
3. `AGENTS.md` — 仓库地图与禁区

## 工作方式
1. 先读你负责的 rows，确认它们在**你 worktree 的目录内**
2. 写测试 → 实现 → 跑测试贴输出
3. 更新 `docs/parity/DSH-GAP-LEDGER.md` 里你负责行的状态
4. 写 `tasks/dsh-parity/waves/RESULT-<你的批次>.md`
5. commit 到你的分支

## 端口分配（真实模型验证用，避开 8765）
W1=8821 W2=8822 W3=8823 W4=8824 W5=8825 W6=8826 W7=8827 W8=8828
W9=8829 W10=8830 W11=8831 W12=8832 W13=8833 W14=8834 W15=8835 W16=8836

## 禁止
- 跨 worktree 改文件
- 重写 `messages` 表语义
- 在 `_execute_write` 回调里再调 `_execute_write`
- 写「已实现」而不贴输出
- 把 PARTIAL 说成 CLOSED

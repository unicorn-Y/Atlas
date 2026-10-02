# Atlas Current Task

CURRENT: ATLAS-C1R-FINISH
STATUS: AWAITING_REVIEW
EXECUTOR: GPT-6 Luna / reasoning=high
TASKBOOK: tasks/taskbooks/ATLAS-C1R-FINISH.md
RESULT: tasks/results/ATLAS-C1R-FINISH.result.md
REVIEW: tasks/reviews/ATLAS-C1R-FINISH.review.md

BASE_BRANCH: main

## 当前目标

完成 C1 Hermes 内核替换的最后收尾：只修已经确认的真实缺口，完成最小必要回归与一次全量验证，然后停止，等待独立验收。

## 流程

1. ZCode 把本文件和 TASKBOOK 路径交给 Codex。
2. Codex 使用 GPT-6 Luna / high 施工，直接从仓库读取任务书。
3. Codex 完成后自行提交并 push，写 RESULT，并把本文件状态改为 `AWAITING_REVIEW`。
4. ZCode 通知上游规划者。
5. 上游规划者直接检查提交、代码和结果，写 REVIEW：
   - 通过：立即发布下一阶段任务书并更新 CURRENT；
   - 不通过：直接在仓库发布补做指令，不询问用户。
6. 循环直到 ROADMAP 完成。

## 执行原则

- 速度优先，优先复用成熟实现。
- 禁止过度防御编程：不为理论异常堆 fallback、兼容层、抽象层、重复 try/catch。
- 禁止过度验收：只做任务要求的聚焦测试 + 一次全量，不做重复测试矩阵和无意义审计。
- 不用真实模型，除非某个后续阶段任务书明确要求。
- 不进入下一阶段，直到上游规划者验收通过。

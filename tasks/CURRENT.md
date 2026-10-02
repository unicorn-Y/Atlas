# Atlas Current Task

CURRENT: ATLAS-C3R-FINISH
STATUS: AWAITING_REVIEW
CONTROLLER: GPT-6.1 Sol / reasoning=medium
WORKERS: GPT-6 Luna / reasoning=high (parallel)
TASKBOOK: tasks/taskbooks/ATLAS-C3R-FINISH.md
RESULT: tasks/results/ATLAS-C3R-FINISH.result.md
REVIEW: tasks/reviews/ATLAS-C3R-FINISH.review.md

BASE_BRANCH: main
PREVIOUS: ATLAS-C3-SESSION-INTERACTION
PREVIOUS_REVIEW: PARTIAL — tasks/reviews/ATLAS-C3-SESSION-INTERACTION.review.md

## 当前目标

只补 C3 两个未完成硬要求：
1. Automation 持续目标统一到 Hermes GoalManager，不再保留第二套 goal lifecycle；
2. 补子 Agent 启停 + 默认模型设置 UI。

其余 C3 已验收项禁止重做。

## 流程

1. ZCode/Codex 读取本文件和 TASKBOOK。
2. GPT-6.1 Sol / medium 主控，能并行的两块可各派 Luna high。
3. 完成 focused verification、前端四项，写 RESULT，并把 STATUS 改为 AWAITING_REVIEW。
4. push main 后通知上游验收。
5. 上游通过后直接发布 C4；不通过只发最小补做。
6. 不允许施工者自行进入 C4。

## 并行施工说明

ZCode 的独立 C5 施工线继续按 `tasks/ZCODE-CURRENT.md` 和 `zcode/c5-models-parallel` 工作；C3R 不得覆盖或合并那条线。

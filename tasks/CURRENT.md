# Atlas Current Task

CURRENT: ATLAS-C2-TOOLS-CONTEXT
STATUS: AWAITING_REVIEW
EXECUTOR: GPT-6 Luna / reasoning=high
TASKBOOK: tasks/taskbooks/ATLAS-C2-TOOLS-CONTEXT.md
RESULT: tasks/results/ATLAS-C2-TOOLS-CONTEXT.result.md
REVIEW: tasks/reviews/ATLAS-C2-TOOLS-CONTEXT.review.md

BASE_BRANCH: main
PREVIOUS: ATLAS-C1R-FINISH
PREVIOUS_REVIEW: PASS — tasks/reviews/ATLAS-C1R-FINISH.review.md

## 当前目标

完成 C2：删除 legacy LangGraph 循环，并把工具与上下文补到当前路线要求的水平：防打转、图片直读、编辑容错、模型族短提示词、压缩摘要、新上下文切换、Git Bash/PowerShell 回退。

## 流程

1. ZCode 把本文件和 TASKBOOK 路径交给 Codex。
2. Codex 使用 GPT-6 Luna / high，从仓库完整读取任务书后施工。
3. Codex 自行提交并 push；写 RESULT；把本文件改为 `AWAITING_REVIEW`。
4. ZCode 通知上游规划者。
5. 上游规划者验收：
   - 通过：直接发布 C3 并更新 CURRENT；
   - 不通过：直接发布最小补做任务，不询问用户。
6. 不允许施工者自行进入下一波。

## 执行原则

- 速度优先，优先搬成熟实现。
- 禁止过度防御编程。
- 禁止过度验收；聚焦测试 + 一次全量即可。
- 不用真实模型/真实外部服务。
- 不碰用户真实数据、design/、C3 分支。

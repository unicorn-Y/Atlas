# Atlas Current Task

CURRENT: ATLAS-C3-SESSION-INTERACTION
STATUS: READY_FOR_EXECUTION
CONTROLLER: GPT-6.1 Sol / reasoning=medium
WORKERS: GPT-6 Luna / reasoning=high (parallel)
TASKBOOK: tasks/taskbooks/ATLAS-C3-SESSION-INTERACTION.md
RESULT: tasks/results/ATLAS-C3-SESSION-INTERACTION.result.md
REVIEW: tasks/reviews/ATLAS-C3-SESSION-INTERACTION.review.md

BASE_BRANCH: main
PREVIOUS: ATLAS-C2-TOOLS-CONTEXT
PREVIOUS_REVIEW: PASS — tasks/reviews/ATLAS-C2-TOOLS-CONTEXT.review.md

## 当前目标

完成 C3：把日常会话交互补齐到可长期使用——立即转向、会话树/分支摘要、撤回重做、权限档位、计划模式、Goal、斜杠命令、状态栏/上下文、后台任务、子 Agent 验收和界面。

## 流程

1. ZCode 把本文件和 TASKBOOK 路径交给 Codex。
2. Codex 使用 GPT-6.1 Sol / medium 作为主控；Sol 读取完整任务书后，按文件/模块并行 spawn 多个 GPT-6 Luna / high 子代理施工。
3. Codex 自行提交并 push；写 RESULT；把本文件改为 `AWAITING_REVIEW`。
4. ZCode 通知上游规划者。
5. 上游规划者验收：
   - 通过：直接发布 C4 并更新 CURRENT；
   - 不通过：直接发布最小补做任务，不询问用户。
6. 不允许施工者自行进入下一波。

## 执行原则

- 速度优先：Sol 主控尽量并行派多个 Luna high；按文件/模块隔离，避免互相覆盖。
- 优先接 Hermes 和复用 wip/c3-frontend-from-laptop。
- 禁止过度防御编程。
- 禁止过度验收；聚焦测试 + 两条 E2E + 一次全量。
- 不用真实模型/真实外部服务。
- 不碰用户真实数据、design/。

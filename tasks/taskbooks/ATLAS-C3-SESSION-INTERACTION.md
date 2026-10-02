# ATLAS-C3-SESSION-INTERACTION：会话与交互

> **当前正式任务。执行模型：GPT-6 Luna，reasoning=high。**
> 前提：C2 已验收通过。不要回头重做 C2，不要开始 C4。
> 本波功能多，但要求是“功能做全、实现尽量复用、验证最小”，不要做大型重构或测试工程。

先读：
- `docs/plan/ROADMAP-TO-PRODUCT.md`
- `docs/plan/CORE-PARITY.md` 中 C3 行：L6、S2、S3、I1、I2、I3、I5、I6、I7、X7、A2、A4
- `docs/plan/EXECUTION-GUIDE.md`
- `tasks/reviews/ATLAS-C2-TOOLS-CONTEXT.review.md`

参考界面分支：`wip/c3-frontend-from-laptop`。**只挑能复用的界面组件，不直接整分支合并；事件和字段以当前 Hermes 内核为准。**

工作目录：`D:\Atlas`。Hermes fork：`D:\hermes-agent` 的 `atlas` 分支。

## 1. L6：插话两档

保留现有“下一步生效”，再加“立即转向”。

- 下一步生效：当前行为不变。
- 立即转向：如果模型正在流式输出，停止当前模型输出，保留已输出内容并标记“被用户打断”，然后带新输入继续。
- 工具正在执行时不强杀工具；工具结束后立刻转向。
- 输入区加一个简单切换，默认“下一步生效”。

参考 Codex `instant_interrupt` 和 Hermes steer/interrupt 控制；不要另造第二套中断状态机。

## 2. S2：会话树 + 分支摘要

- Atlas 现有分叉树改为使用 Hermes SessionDB 的真实分支关系。
- 分叉、继续、切回都保留完整记录。
- 离开一条分支时生成一条简短分支摘要，挂在分叉点；回来时可见。
- 摘要格式复用 C2 的结构化摘要，不新建摘要系统。

参考 Pi session tree / branch summarization + Hermes branch。

## 3. S3：检查点只留一套主链

Atlas 已有 shadow-git checkpoint，Hermes 也有 snapshot/rollback。

先读两套代码后做最小决策：
- **优先保留当前已经和 Atlas 撤回/重做/改动面板接好的那套作为主链**；
- 只把另一套确实更好的“数量/总大小上限、最旧清理”等独有能力合并过来；
- 不保留两套并行生产路径。

要求：消息撤回时文件和对话一致；重做可恢复；旧快照有简单上限清理。

## 4. I1：权限档位

在现有权限系统上补齐日常需要的档位，默认仍 **完全访问**：

1. 每步都问；
2. 改文件前问；
3. 文件可自动改，命令/MCP 写操作前问；
4. 计划模式；
5. 完全访问；
6. 只读（保留现有）。

- 输入框权限菜单可切换；
- Shift+Tab 循环常用五档（只读可从菜单选）；
- 按对话保存；
- 子 Agent 权限不能高于父级。

不要做“智能自动审批分类器”，那属于安全审查。

## 5. I2：计划模式

直接接 Hermes plan 能力，补两件事：

- 计划模式允许只读命令：git status/log/diff/show、ls/dir、rg、cat/type/Get-Content 等；
- 写命令仍拦截；
- 计划完成用一个明确“提交计划”动作回到界面现有计划卡片。

安全命令判断优先参考/移植 Codex 已有判定，不自写大量正则。

## 6. I3：对话内 Goal

- `/goal <目标>` 直接走 Hermes goal/subgoal；
- 允许附一句验证条件；
- 运行头部显示当前 goal；
- 能暂停、替换、清除；
- 自动化页原有持续目标也走同一后端，不保留第二套。

## 7. I5：斜杠命令

不要做长研究报告。先枚举当前 Atlas/Hermes 已经有的命令，再把**日常主体相关**的入口补齐。

至少保证这些可用：
`/model /context /diff /resume /fork /undo /redo /status /usage /compact /goal /plan /btw /permissions /agents /export /rename /new /clear /ps /stop /copy`

`/review`、`/init` 留到 C6 做真正编程专项；现在可以显示“C6 提供”或不出现在菜单，**不要提前重复实现**。

输入 `/`：
- 分组显示；
- 模糊搜索；
- 已有 Hermes 命令优先直接调用，不再写一套同名后端。

## 8. I6 + X7：状态栏和上下文构成

底部状态栏显示最有用的：
- 模型
- 推理档位
- 上下文占用 %
- 本轮用量/花费（有数据才显示）
- Git 分支
- 权限档位
- 后台进程数

`/context` 和右侧上下文页接 Hermes context breakdown，显示：
系统提示词、工具、规则、记忆、历史、工具输出、剩余额度。

不要为了像素级定制做复杂配置器；设置里能开/关主要状态项即可。

## 9. I7：后台任务

接 Hermes/Atlas 现有 process registry：
- 列表；
- 看最近输出；
- 停止；
- 完成通知；
- `/ps`、`/stop` 走同一数据源。

不要再建一套后台任务数据库。

## 10. A2 + A4：子 Agent 验收与界面

### 后端
修掉 W07 旧验收误判：子任务结果必须按真实完成状态和验收结果记录，失败能重派，不把“有输出”误判成“通过”。

### 前端
优先从 `wip/c3-frontend-from-laptop` 挑现成组件搬：
- Worker/子任务卡片；
- 已通过 / 未通过状态；
- 点开看结果和验收意见；
- 补充要求；
- 后台完成卡片；
- 待办条；
- 子 Agent 设置（启停、默认模型）；
- 团队看板；
- 项目 NOTES.md 简单编辑。

只搬当前确实有后端数据支撑的部分。旧分支里没有新内核事件支撑的 UI 不要硬留假数据。

## 11. 最小验证

禁止过度验收，只做：

1. 每个后端能力 1–2 个聚焦测试；
2. 两条假模型 WebSocket E2E：
   - 立即转向 → 分叉 → 切分支 → 撤回 → 重做；
   - 计划模式 → 切权限 → Goal → 子 Agent 失败一次后重派 → 完成；
3. 后端全量 pytest **只跑一次**；
4. 前端四项各一次：renderer tsc、electron tsc、Vitest、Vite build；
5. UI 只截 3 张代表图即可：主对话、会话树/上下文、子 Agent/任务面板。不要浅色深色重复截图矩阵。

不用真实模型，不用真实外部服务。

## 硬约束

- **禁止过度防御编程**：不堆 fallback、兼容层、重复状态机、重复数据库、重复事件协议。
- **禁止过度验收**：不反复跑全量，不做大矩阵。
- 能接 Hermes 现成能力就接，不重写。
- 能搬 `wip/c3-frontend-from-laptop` 的成熟 UI 就搬，不从零重画。
- 不放宽 `core/atlas/origin_guard.py`。
- 不做安全审查分类器。
- 不碰用户真实数据、`design/`。
- 不开始 C4。

## 交付

完成后：
1. 更新 CORE-PARITY 的 C3 行；
2. 写 `tasks/results/ATLAS-C3-SESSION-INTERACTION.result.md`，只写：
   - 各项完成情况；
   - 从 wip 分支复用了什么；
   - Atlas/Hermes 提交号；
   - 聚焦/E2E/一次全量/前端检查结果；
   - 仍有的真实缺口。
3. `tasks/CURRENT.md` 改为 `AWAITING_REVIEW`；
4. pull --rebase → push → 核对远端 HEAD，然后停止。

**完成后由 ZCode 通知上游规划者验收；不要自行进入 C4。**

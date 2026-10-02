# 日常使用 → 优化的循环（K1 之后长期执行）

用户决定（2026-10-02）：K1 检查完后，用户自己实测、开始日常使用 Atlas，之后按每次使用的实际情况判断、优化。这份文件规定这个循环怎么转。

## 一、用的时候怎么记问题（用户）

遇到不顺手的地方，随手记一条，越短越好。用户可以选下面任意一种方式：

1. **直接告诉 Atlas**：在 Atlas 里说「记一个问题：……」。Atlas 会把它追加到 `tasks/feedback/INBOX.md`，并且自动附上当时的对话 ID、时间、版本（提交号）和最近的错误日志。
   - 这个「记问题」的小功能现在还没有，可以作为第一波 F 波的第一条去做：一个工具 `report_issue`，加上一个界面入口（消息菜单里的「这里有问题」）。在那之前，用第 2 种方式记。
2. **自己写进 `tasks/feedback/INBOX.md`**，格式随意，例如：
   ```
   - 10-05 改代码时它把我的注释删了（对话：xxx）
   - 10-05 浏览器登录后卡住不动
   - 10-06 希望能像 Claude Code 那样 /compact 后告诉我压掉了什么
   ```
3. **截图**：放进 `tasks/feedback/shots/`，在 INBOX 里提一句。

**什么都可以记**：bug、慢、看不懂、不好用、某家有而 Atlas 没有的功能、想要的新功能。

## 二、多久处理一次

攒到 **5 到 10 条**，或者遇到**影响使用的大问题**时，开一波「F 波」（F1、F2、F3……，F 是 Feedback 的意思）。

## 三、怎么派发一波 F 波（用户）

在主机 Codex 开新对话，模型选 **GPT-6.1 Sol / 中**，贴下面这段：

```
你是 Atlas 这一波的主控。工作目录 D:\Atlas，先 git pull；Hermes fork 在 D:\hermes-agent（atlas 分支），也拉到最新。
先读 docs/plan/USAGE-FEEDBACK.md、docs/plan/EXECUTION-GUIDE.md、docs/plan/CORE-PARITY.md，再读 tasks/feedback/INBOX.md 里所有未处理的条目。
1. 逐条分类：bug / 体验 / 缺功能 / 新需求 / 不是问题。每条用附带的对话 ID 和日志复现或定位原因。
2. 写本波任务书 tasks/taskbooks/ATLAS-F<编号>-FEEDBACK.md：每条写现象、原因、别家（Hermes、Claude Code、Codex、ZCode、OpenCode、Pi）怎么做的（看源码或当月文档）、Atlas 怎么改、怎么验证。缺功能和新需求先列出来，标「需要用户确认」，不要直接做。
3. 对 bug 和体验类：开 GPT-6 Luna（reasoning_effort high）子代理按文件分工并行修，每条一个提交；你审 diff、跑相关测试。规矩照 EXECUTION-GUIDE。不用真实模型，除非某条只有真实模型才能复现，那时先问用户。
4. 全量测试和前端四项检查跑一次。
5. 把处理过的条目从 INBOX.md 移到 tasks/feedback/DONE.md，写上处理结果和提交号；需要用户确认的留在 INBOX.md 并标记。
6. 写结果文件 tasks/results/ATLAS-F<编号>-FEEDBACK.result.md，推送，停止。
```

做完后，用户看结果文件，再看 INBOX 里「需要用户确认」的那几条，决定做不做。

每一波照常可以另开一个 Sol 做独立验收（HANDOFF 第 6 节）。F 波通常不大，用户也可以觉得没必要就跳过。

## 四、什么时候不走这个循环

- **影响使用的大问题**（崩溃、丢数据、完全用不了）：不用攒，马上开一波，INBOX 里只放这一条。
- **想要的大功能**（比如 X1 的聊天渠道、X7 的常驻个人 Agent）：不走 F 波，按 `ROADMAP-TO-PRODUCT.md` 和 `ATLAS-X-EXTERNAL-PHASE.md` 开正式的一波。
- **解决不了、两轮都没修好的**：找 Claude，带上 INBOX 那一条、结果文件和提交号。

## 五、长期

- 记得每两周合并一次 Hermes 上游（`ROADMAP-TO-PRODUCT.md` 第七节）。合并后照常用一阵子，有问题就记进 INBOX。
- X5（自我进化）做完以后，INBOX 的分类和任务书草稿可以由 Atlas 自己生成，用户只负责批准。

# B-TC-08｜Git：PR、分支与历史

实现分支：`card-b-tc-08`（基于 `origin/memory-v1`）

## 条目结果

- **B062｜Git Review/PR、检查状态和差异定位：已补齐本卡缺项。** Changes 面板里的行级本地评论可编辑、删除并发给 Atlas；PR 面板在本地显示真实 GitHub PR 活动、评论、审查与现有 checks，失败检查仍可打开或交给 Atlas 修复。PR 评论通过 `gh` 发布为 PR 对话评论。没有增加 GitHub 行内 review-thread 评论发布；Atlas 的行级评论仍是发给当前 Atlas 会话的本地草稿。
- **B091｜Codex 会话 PR 操作时间线、评论及推送选择：已实现。** 时间线从 GitHub issue timeline API 分页读取并合并评论、审查、提交和 PR 活动；可在 Atlas 内发布 PR 对话评论。Git 操作提供“提交”“提交并推送”“仅推送”三个真实动作。代码审查行为依据 Codex 官方说明，PR 时间线和评论/推送选择依据 26.409 官方 changelog。
- **B113｜Git 操作菜单、提交/推送动作与错误详情：已实现。** Git 工作区面板显示真实改动文件并允许选择提交范围；提交调用 `git add`/`git commit`，推送调用 `git push -u origin HEAD`。失败时展示后端错误详情；提交成功但推送失败时明确保留提交结果并提示推送错误。
- **B114｜Git 分支切换与新建入口：已实现。** 可查看当前分支、切换已有本地分支或新建并切换；成功后刷新工作区状态和 PR 信息。若当前 Atlas 会话绑定的工作树与操作目录相同，会同步保存会话的分支字段。工作区有冲突时显示 Git 返回的真实错误，不自动丢弃改动。
- **B115｜Git 提交历史拓扑图：已实现。** 新面板读取真实 `git log --graph --decorate --all --date-order` 图形输出，并显示最多最近 200 条提交的摘要、父提交、作者和日期；没有伪造节点或提交。

## 上游实现说明

核对了 ZCode `GitPane.tsx`、`GitPaneChangeCard.tsx`、`GitActionMenu.tsx` 中的 Git 变更定位、提交/提交并推送/仅推送选择和错误状态，以及 Codex 的 code review 文档与 26.409 changelog。Atlas 使用自己的 React 面板、后端路由和 `gh`/`git` 命令重做对应行为；没有复制上游代码，因此没有添加移植头或修改 `THIRD_PARTY_NOTICES.md`。

## 验证

- `npm --prefix frontend run build`：通过。
- 后端：在 `ATLAS_UPSTREAM_AUTO=0`、Python 3.14 和隔离的 `ATLAS_DATA_DIR` 下启动；`/api/health` 返回 `status: ok`，全部组件为 `ready`；随后已关闭验证进程并移除隔离数据目录。
- 未编写或运行测试套件（按任务要求）。

## 提交

- 实现提交：`ffba758bb93c589583c6fa65edf14cda52840819`
- 卡片记录提交：见本次后续提交。

# ATLAS-C6：编程专项 + 长会话性能 + 主体 UX 收口

> 当前正式任务。C4、C5、C6A 已 PASS 并进入 main。
> **不要重做 `core/atlas/lsp/**`。** C6A 已完成 LSP client/server/workspace/delta/Windows lifecycle，本波只做真实编辑链接线和 UI。

先读：
- `tasks/CURRENT.md`
- `tasks/reviews/ATLAS-C5-C6A-INTEGRATION.review.md`
- `docs/plan/CORE-PARITY.md`：T8、P1、P2、第 11 节
- `docs/plan/EXECUTION-GUIDE.md`
- C6A result/review

## 本波一次收完

1. T8：LSP 核心接真实写/编辑链和 UI
2. P1：`/init`
3. P2：`/review`
4. 长会话性能
5. 主体 UX 最后一轮打磨
6. 修正 C6 负责的 CORE-PARITY 缺口，准备进入 T1

速度优先。能直接搬成熟实现就搬，不写缩水版。

## 并行施工

Sol 按真实文件所有权拆块，能独立的尽量派 Luna high 并行，使用当前运行环境允许的最大并发，不写死数量。

建议独立块：
- LSP 写路径接线
- LSP UI
- /init
- /review backend
- /review frontend
- 长会话性能
- UX polish
- benchmark / fake E2E / focused tests

共享热文件（App/store/server/Composer/ConversationActivity 等）只给一个 integration owner 或最后串行接线。

---

## 1. T8：LSP 接线

已有：
- `core/atlas/lsp/**`
- `snapshot_baseline(path)`
- `edit_report(path, pre_content, post_content)`
- `diagnostics_for(path)`
- `missing_hint(path)`

不准再造第二套 LSP manager/client。

### 后端

找到 Hermes/Atlas 文件写入的最薄公共边界：

- 写/编辑前 snapshot baseline
- 成功后取 delta
- 工具结果只附“本次新增诊断”
- 原有错误仅移动行号不算新增
- 修好后诊断消失
- LSP 不可用时文件操作照常成功
- 缺 server 只返回短中文安装提示，不自动安装
- SSH/远程 workspace 不启动本机 LSP
- worktree 删除/切换时释放对应 workspace

### 前端

- 改动/diff 面板显示每文件 diagnostics 数量，可展开 line/severity/message
- 时间线出现轻量事件「发现 N 个新问题」
- 0 diagnostics 不刷事件
- 不新建大型 LSP 页面

---

## 2. P1：/init

开工先核当前 Hermes / OpenCode / Codex 的 /init 行为，优先复用成熟实现，不写长研究报告。

行为：
1. 扫描 workspace 结构、语言、包管理器、入口
2. 找 build/test/lint/typecheck 命令
3. 读取已有 AGENTS.md / CLAUDE.md / 规则
4. 生成精炼 AGENTS.md 建议
5. 保留已有人工内容，只补缺项或更新 Atlas 自管区段
6. 写入前展示 diff
7. 用户确认后才写
8. 二次运行近似幂等，不越写越长

入口直接进现有 / 菜单；diff/确认复用现有 UI，不造第二套。

---

## 3. P2：/review

把现有“让审查员检查”和成熟 code review 合成一个功能，不留两套 reviewer。

开工对比：
- Hermes `agent/review_engine.py`
- Codex /review
- OpenCode review template

优先搬 Hermes review engine 结构，再吸收 Codex/OpenCode 强项。

至少支持：
- 默认：当前未提交改动
- `/review branch <name>`
- `/review commit <sha>`

执行：
- 用现有 child runtime
- reviewer 强制只读
- 可跑只读 shell、git diff、搜索、测试/lint/typecheck 验证判断
- 不得修改文件
- finding 必须有证据，不凑数量

finding schema：
- file
- line/range
- severity
- title
- explanation
- evidence
- suggested_fix

前端 review cards：
- 打开文件/定位行
- 让 Atlas 修这一条
- 全部发回对话修复
- 复制 finding
- 与现有 reviewer/trajectory review 合并入口

---

## 4. 长会话性能

如果当前前端没有成熟虚拟化方案，选一个支持**动态高度聊天消息**的成熟 React virtualization 库；不要手搓固定行高方案。

目标：
- 2000 条消息会话打开到可交互首屏 < 1s
- 切换两个已存在大对话 < 300ms
- 流式输出无持续卡顿
- 长工具输出默认折叠
- 多会话不预加载所有历史正文，缓存有边界

要求：
- 消息/活动时间线真正虚拟化或窗口化
- Markdown、动态高度、工具卡展开不破坏滚动
- 流式时保持跟底；用户上滚后不强拉到底
- 高频事件批量/合并更新，避免每 token 全 store 重算
- inactive conversation 不无限缓存正文

做可重复 benchmark fixture：2000 条消息 + 大工具输出，用 Playwright/Performance API 测，不用真实模型。硬件噪声大时写真实数字和瓶颈，不伪造 PASS。

---

## 5. 主体 UX 最后一轮

这是打磨，不是重做视觉设计。

对照当前 Claude Code、Codex、ZCode 的成熟交互，逐项只修真实问题：
1. 输入框
2. 普通消息
3. 工具步骤 / 思考 / 子 Agent
4. 改动 diff
5. 终端
6. 文件面板
7. 权限切换
8. 模型选择
9. 状态栏
10. / 菜单
11. 设置页
12. 错误 / 重试 / 恢复
13. 空状态
14. 快捷键

每项结果只写：
- 真实问题
- 借鉴哪家
- Atlas 实际改了什么

规则：
- 减少点击/弹窗，状态更清楚
- 中文白话，英文原始错误只放详情
- 不加大动画
- 不改用户已定浅色方向和整体结构
- 三套现有主题都不能坏

最终截图：主聊天、改动/终端、设置页、review UI、大对话，各至少一张。

---

## 6. 顺手修已知旧测试漂移

检查此前 full pytest 唯一已知漂移：C3R 将 ScheduledTask goal 迁为 legacy_goal 后旧测试未更新。

如果当前仍存在，只修测试预期；不要改回生产实现。若已不存在则不碰。

---

## 7. 验证

各 worker 只跑 focused tests；主控整合后统一验证。

后端：
- fake LSP E2E：干净 → 编辑引入错误 → 工具结果出现新增诊断 → 修复 → 消失
- /init：已有 AGENTS.md 保留 + diff preview + 确认写入 + 二次运行幂等
- /review：working tree / branch / commit 各 1 个 fixture；验证只读
- finding schema + no finding
- 相关 child/read-only 回归

前端：
- renderer tsc
- electron tsc
- Vitest
- Vite build

性能：
- 2000 message benchmark，写出真实数据

E2E：
- 一条 fake-model 主链：代码 workspace → 编辑 → LSP 新诊断 → /review 找到问题 → “让 Atlas 修”回到正常执行入口

backend full pytest：
- 最多跑一次，只在 focused 全绿以后
- 不循环跑全量

不用真实模型/provider。

---

## 8. 交付

更新：
- `docs/plan/CORE-PARITY.md`
- 必要的 `docs/PARITY.md`
- `tasks/results/ATLAS-C6-CODING-POLISH.result.md`

result 必须写：
- T8/P1/P2 最终状态
- 上游复用来源和具体文件
- LSP 接线点
- review 只读链
- 性能实测数字
- 14 项 UX 修改清单
- screenshots 路径
- focused / frontend / full-suite 汇总
- 仍存在的真实缺口

目标：C6 负责的 CORE-PARITY 行全部 ✔。做不到就明确列 blocker，不准偷偷标 ✔。

最后：
- `tasks/CURRENT.md` → `AWAITING_REVIEW`
- pull --rebase
- push main
- 核对 local HEAD == origin/main
- 停止
- **不要自行进入 T1**

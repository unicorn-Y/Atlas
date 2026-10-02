# ATLAS-C4-EXTENSIONS：扩展体系

> **当前正式任务。主控：GPT-6.1 Sol / reasoning=medium；施工子代理：GPT-6 Luna / reasoning=high。**
> 前提：C3/C3R 已验收通过。
> ZCode 正在独立分支做 C5；本波不得合并或覆盖 `zcode/c5-models-parallel`。

先读：
- `tasks/CURRENT.md`
- `tasks/reviews/ATLAS-C3R-FINISH.review.md`
- `docs/plan/CORE-PARITY.md` 的 E2–E6
- `docs/plan/EXECUTION-GUIDE.md`
- `tasks/HANDOFF.md`

## 目标

把 Atlas 扩展层做到可直接吃 Claude Code / Agent Skills 生态，同时保留 Hermes/Atlas 自己已有的扩展能力：

- E2 技能目录合一
- E3 Hooks 兼容 Claude Code
- E4 插件兼容 Claude Code
- E5 自定义命令
- E6 从 Claude Code / Codex 导入

完成后 E2–E6 全部 ✔。

## 主控并行方式

Sol 读完任务书后按真实文件所有权拆成 4–6 个并行块，优先：
1. Hooks
2. Plugin loader/marketplace
3. Skills + custom commands
4. Claude/Codex import
5. 前端扩展设置
6. focused tests / fake plugin E2E

每个 Luna high 只改明确文件；共享入口文件交给一个 integration owner 或最后串行接线。

不要让多个 worker 同时改：
- `core/atlas/server.py`
- `frontend/src/renderer/App.tsx`
- 共享 plugin/skill registry

## 与 ZCode C5 的冲突隔离

ZCode C5 正在独立分支改模型层。本波原则上不要碰：
- `core/atlas/models/**`
- `frontend/src/renderer/pages/SettingsPage.tsx`
- `frontend/src/renderer/pages/UsagePanel.tsx`
- backend-adapter 中纯模型字段
- provider / credential / reasoning / usage 逻辑

C4 前端优先使用/新增独立扩展页面或现有 `HooksPanel`、Integration/Plugin 类面板；确实需要共享路由时，把接线压成单独小 commit。

E6 的“模型偏好导入”只写入**现有** Atlas 设置格式，不在 C4 改模型系统设计；C5 合并后再自然读取。

## 0. 先核当前格式，不写研究报告

施工开始先查当月 Claude Code 官方文档和当前本地/上游实现，确认：
- Hooks 事件、stdin/stdout/exit code、matcher 格式
- plugin manifest / marketplace 格式
- Agent Skills / SKILL.md 当前格式与目录
- custom command / prompt 文件格式
- subagent 定义格式

只把最终需要兼容的字段写进结果对照表；不要先花大量时间写调研文档。

## 1. E3：Hooks

目标：Claude Code 格式的 hooks 配置可以直接读。

来源优先级：
1. 现有 Atlas hooks
2. Hermes plugin hooks
3. Claude Code settings 兼容 adapter

要求：
- 读取项目和用户 Claude settings 里的 hooks；
- 支持当前官方核心事件；
- stdin JSON / stdout JSON / exit code 语义按当前官方格式；
- matcher 按工具/事件匹配；
- 可拦截、可改写工具输入、可追加上下文；
- Atlas 现有事件保留，不破坏已有用户 hooks；
- Hermes 已有 hook 直接映射，缺的只在 Atlas engine/runtime 加最小触发点；
- 前端能列事件、启停/试跑、看最近日志。

不要再造第二个完整 hook runtime。

## 2. E4：Claude Code 插件兼容

Atlas 能直接识别 Claude Code 当前 plugin/marketplace 格式。

至少支持插件内：
- commands / prompts
- agents
- skills
- hooks
- MCP
- manifest metadata

支持：
- 本地目录
- git/marketplace 源
- 安装 / 启用 / 停用 / 卸载 / 更新

Hermes 插件 SDK继续可用，两种来源最终进入 Atlas 同一 registry/发现层，不要维护两套运行时。

不用做插件安全扫描。

## 3. E2：技能合一

以 Atlas 当前 skill registry 为唯一目录/索引层。

读取：
- Atlas 用户技能目录
- 项目 Agent Skills / Claude skills 目录
- 用户 Claude skills 目录
- plugin 自带 skills
- Hermes 自带技能作为可选 source

要求：
- 同名技能有稳定优先级；
- 提示词只放 name/description 等索引；
- 真正使用时再加载 SKILL.md 和关联资源；
- 不重新启用 Hermes 的第二套 skill registry。

## 4. E5：自定义命令

读取当前 Claude Code command/prompt 目录和 Atlas 自己的 commands 目录。

至少支持：
- Markdown 命令
- 参数占位
- 当前官方 frontmatter 中 Atlas 能对应的模型/工具限制字段
- 出现在现有 `/` 菜单
- Atlas Recipe 保留，可导出/映射为 command

不要重复实现 C3 已有 slash command backend；这里只加“用户定义命令来源”。

## 5. E6：Claude Code / Codex 导入

设置里提供两个导入入口：
- Claude Code
- Codex

导入前先扫描并显示清单，让用户选择；导入后给简短报告。

范围：
- MCP
- hooks
- CLAUDE.md / AGENTS.md 等规则
- skills
- agents
- commands/prompts
- 现有格式可表示的模型偏好
- 最近对话作为只读历史

要求：
- 源目录只读，绝不修改；
- 重复项按稳定规则跳过/合并；
- 优先复用 Codex external-agent migration 的成熟解析思路，不自己造大迁移框架。

## 6. 子 Agent 定义兼容核实

C3 已有子 Agent runtime；这里只确认：
- 项目/用户 Claude agent 定义仍可识别；
- plugin 自带 agent 能进入同一发现层；
- 不复制第二套 child runtime。

## 最小验证

速度优先，不做巨大矩阵。

- Hooks：按“事件类别”覆盖核心路径，不要求机械地每个事件复制一套测试；
- Plugin：一个完整 fake Claude-format plugin，带 command + agent + skill + hook + MCP，走安装→发现→生效→禁用/卸载；
- Skills：同名优先级 + progressive load 1–2 组；
- Commands：自定义 command 1–2 组；
- Import：fake `.claude` 和 fake `.codex` 各一组，确认源目录不变；
- 一条 fake-model E2E：插件安装后 command/hook/skill/MCP 至少跨一次真实 Atlas runtime 路径；
- 后端 full pytest **最多一次，且只在全部代码整合完成后**；
- 前端 renderer tsc、electron tsc、Vitest、Vite build 各一次；
- 不用真实模型、真实外部 MCP 或用户真实配置。

## 硬约束

- 优先复用成熟实现，不写缩水版。
- 禁止过度防御编程。
- 禁止第二套 plugin/skill/hook runtime。
- 不放宽 `origin_guard.py`。
- 不碰用户真实数据和 `design/`。
- 不进入 C6。
- 不合并 ZCode C5 分支。
- C4 若必须触碰 C5 热文件，必须是最小 integration touchpoint 并在 RESULT 单列。

## 交付

- 更新 `docs/plan/CORE-PARITY.md` E2–E6；
- 更新需要的 `docs/PARITY.md`、`docs/plan/VENDORED.md`；
- 写 `tasks/results/ATLAS-C4-EXTENSIONS.result.md`：
  - E2–E6 完成情况
  - 官方格式兼容表
  - 复用来源
  - 测试结果
  - 与 ZCode C5 可能的 merge touchpoints
  - 真实剩余缺口
- `tasks/CURRENT.md` → `AWAITING_REVIEW`
- pull --rebase → push → 核对 local == origin/main → 停止
- 不自行进入下一阶段。

# 终局总审任务书（所有独立会话研究提交以后执行）

本文件不是初始“调研计划”；只有收到研究分支后才执行。对单个独立研究的遗漏，可退回该产品继续查证。

## 输入
- 派工入口 `tasks/research/agent-reverse/2026-10-19/START-HERE.md`
- 各产品 `research/agent-reverse-20261019-<slug>` 分支的真实提交和 `docs/research/agent-reverse/2026-10-19/<slug>/START-HERE.md`
- 发布包 `agent-client-packages-20261019`
- Atlas 当时最新 `main@SHA` 源码、原有功能矩阵/以前拆包成果

## 审查动作
1. 按成果目录逐一核实分支、commit、源码路径、证据等级；**不能只阅读每份报告的摘要**。抽查原证据与真正调用链；按已发现未知盲区向对应会话退回。
2. 聚合所有 Discovery ID，发现同名不同机制、不同名同机制、厂商和社区的差异；去重但**保留来源和原始 ID**，不要用预设功能矩阵裁剪。
3. 从原包/源码探索覆盖面评估遗漏：UI entry/命令表/服务路由/事件 schema/后台 worker/插件 registry 等是否被查全；记录遗漏等级与最小补采手段。
4. 与 Atlas 源码建立可执行缺口账：未有 / 有外壳 / 后端半接线 / 有但失效 / 有且相当；严禁以 README、任务书测试数推断实现质量。
5. 对每个机制建议保留最成熟的上游实现路径和必要依赖，标记是否可直接利用源码、按原机制重新实现或仍缺关键闭源服务器数据；明确工作量和相互依赖。
6. **不在总审阶段改 Atlas 正式代码**。最后才给 Codex 分波施工任务，以用户既定优先级“完整吸收成熟方案，性能与真实可用为主、尽量少做无意义审查”。

## 交付
单独开总审会话及分支 `research/agent-reverse-20261019-integration`；统一目录 `docs/research/agent-reverse/2026-10-19/_integration/`：
`GLOBAL-CAPABILITY-MAP.md`, `BACKEND-MECHANISM-MAP.md`, `UI-COMPONENT-MAP.md`, `ATLAS-REALITY-LEDGER.md`, `REUSE-SOURCE-MAP.md`, `UNRESOLVED-RESEARCH.md`, `NEXT-CODEX-WAVES.md`, `START-HERE.md`。
给每个条目来源证据引用和分支 commit，避免仅粘贴之前的功能分类。

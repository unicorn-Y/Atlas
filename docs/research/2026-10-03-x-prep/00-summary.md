# ATLAS-X-PREP 总览

日期：2026-10-03（Asia/Hong_Kong）。目标：七波外部阶段正式施工任务书与可核查来源，不实施任何 X 波。执行基线：Atlas `9e6d6fde949a0f581ba7e0031004b1f6c4fdd2f4`，分支 `sol/x-prep`；`core/pyproject.toml` 锁定 Hermes fork `unicorn-Y/hermes-agent@e287231d7906bcce5bc373d20fb2e3e1e6427220`，与只读核对的 `D:/hermes-agent` HEAD 一致。旧 VENDORED 条目和源码注释中的其他 commit 为历史来源，不覆盖当前依赖锁定。

## 正式交付入口

| 波 | 正式任务书 | 研究 |
|---|---|---|
| X1 | [连接外部世界](../../../tasks/taskbooks/ATLAS-X1-CONNECT-WORLD.md) | [来源](01-x1-sources.md) |
| X2 | [电脑与浏览器](../../../tasks/taskbooks/ATLAS-X2-COMPUTER-BROWSER.md) | [来源](02-x2-sources.md) |
| X3 | [设备与产出物](../../../tasks/taskbooks/ATLAS-X3-DEVICES-DELIVERABLES.md) | [来源](03-x3-sources.md) |
| X4 | [技能市场](../../../tasks/taskbooks/ATLAS-X4-SKILL-MARKET.md) | [来源](04-x4-sources.md) |
| X5 | [自我进化](../../../tasks/taskbooks/ATLAS-X5-SELF-EVOLUTION.md) | [来源](05-x5-sources.md) |
| X6 | [语音与统一入口](../../../tasks/taskbooks/ATLAS-X6-VOICE-UNIFIED.md) | [来源](06-x6-sources.md) |
| X7 | [常驻个人 Agent](../../../tasks/taskbooks/ATLAS-X7-ALWAYS-ON-PERSONAL-AGENT.md) | [产品对比](07-x7-products.md)、[架构](08-x7-architecture.md) |

[总 source map](09-source-map.md) 是文件级索引；evidence JSON 和 validation 记录 commit、文件存在性及文档范围核验。正式任务书是后续施工依据；旧 `ATLAS-X-EXTERNAL-PHASE.md` 仅保留背景，不再提供未经本轮核实的产品事实。

## 唯一 authority 与波次责任

- runtime：Atlas AgentOrchestrator → HermesRuntime → Hermes AIAgent。新增 ingress 和 worker 都调用这条链。
- history / goal：Hermes SessionDB / GoalManager，经 `core/atlas/engine/session_sync.py` 同步。监控和设备状态不能成为另一个 goal lifecycle。
- schedule：AtlasScheduler 负责触发时间和事件，复用 Hermes monitor 的确定性检查；持久执行交现有 DBOS adapter。
- permission：既有 `full_access` / `ask_writes` / `read_only` 与审批 callback。X7 动作分类映射既有执行边界，不能旁路或建立第二套审批。
- skills：C4 SkillManager 为唯一 registry；X4 负责市场获取/更新，X2 只捕获示范，X5 生成审核候选，X7 只运营已获准技能。
- devices：X3 负责配对、trust、远程路由与产出物传输；X6 负责统一入口与 bounded collaboration，X7 负责长期身份、worker可用性与持久交接运营。

## 施工依赖与停止点

先完成并验收 T1/T1F，然后用户分别授权 X 波。默认 X1 → X2 → X3 → X4 → X5 → X6 → X7；各波严格使用自身 taskbook，不因为前置完成就自动开始下一波。X7 必须依赖 X1 事件/身份接入、X2 持久 profile 与交互 worker、X3 设备信任/交接、X4 技能版本、X5 候选审核、X6 统一 session 与多 agent 合作。不能为先跑通 X7 临时复制这些子系统。

每波 fake 验收可在临时数据和本机 fixture 下完成；真实账号、设备、邮箱/IM身份、浏览器登录、通话/收费能力另由用户选择并授权。没有授权或测试环境时明确 BLOCKED/PARTIAL，不以 fake 通过代替真实成功。

## 笔记本作为 Atlas 的电脑

专用笔记本天然提供持久磁盘、真实 Windows apps、浏览器登录和交互桌面；需要补持久任务恢复、入站可达、trust、网络重连、电源策略、服务/用户worker监督及版本更新。Windows 服务默认不能控制交互桌面，必须与用户会话 worker 分开；worker unavailable/锁屏/退出登录有明确 blocked 状态。合盖、主动 sleep、断电、硬件不支持 wake 都不能被“always-on”文案掩盖。

[Microsoft interactive services](https://learn.microsoft.com/en-us/windows/win32/services/interactive-services) 与 [SetThreadExecutionState](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setthreadexecutionstate) 于 10-03 核实：service 非交互、保持唤醒调用不能阻止用户主动睡眠/合盖。X7 真实验收必须分别证明 renderer关闭、backend崩溃、断网、重启与sleep恢复，不宣称与云 VM SLA 相同。

## 事实、设计与可搬边界

产品公开能力用官方链接和发布日期/核实日证明；没有公开内部实现就写闭源，不编造源文件。开源来源锁定 commit 和 license，逐文件验证，区分直接启用依赖、移植小模块、仅合同/算法参考以及不可直接搬入（平台/语言/许可证差异）。新 glue 文件是后续计划，不应误标为当前已存在路径。产品实际账号可用性、性能和真实任务成功率未在本轮测试。

准备任务完成后仅设置 `tasks/SOL-CURRENT.md` 为 `AWAITING_REVIEW`、提交并推送 `sol/x-prep`，不 merge main，不启动 X1。

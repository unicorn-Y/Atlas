# ATLAS-X：外部功能阶段（X1–X7）

更新：2026-10-03，ATLAS-X-PREP 文档准备。**不是施工授权；本轮不开始 X1–X7。**

前提：T1/T1F 完成并验收，用户审查本轮七份任务书后逐波授权。每波完成、交付独立验收结果后停止，不自动开始下一波。旧 W08–W13 不再作为新 Hermes 内核的直接施工依据。

## 正式任务书

| 波 | 唯一施工入口 | 责任 |
|---|---|---|
| X1 | [ATLAS-X1-CONNECT-WORLD](ATLAS-X1-CONNECT-WORLD.md) | MCP/OAuth/Tasks/Apps、连接器、单一 channel gateway、trigger/monitor |
| X2 | [ATLAS-X2-COMPUTER-BROWSER](ATLAS-X2-COMPUTER-BROWSER.md) | computer/browser lifecycle、持久 profile、vault/handoff、示范捕获与安全 replay |
| X3 | [ATLAS-X3-DEVICES-DELIVERABLES](ATLAS-X3-DEVICES-DELIVERABLES.md) | device trust/pairing、A2A transport、phone/web、artifact editing/share/sync |
| X4 | [ATLAS-X4-SKILL-MARKET](ATLAS-X4-SKILL-MARKET.md) | 来源市场接入、版本/provenance/dependencies/scopes；C4 SkillManager 唯一 registry |
| X5 | [ATLAS-X5-SELF-EVOLUTION](ATLAS-X5-SELF-EVOLUTION.md) | upstream/diff/parity建议、taskbook草稿、候选技能审核、隔离实现/merge proposal |
| X6 | [ATLAS-X6-VOICE-UNIFIED](ATLAS-X6-VOICE-UNIFIED.md) | Pipecat实时语音、统一session入口、bounded collaboration、图像/音频（无视频） |
| X7 | [ATLAS-X7-ALWAYS-ON-PERSONAL-AGENT](ATLAS-X7-ALWAYS-ON-PERSONAL-AGENT.md) | 专用笔记本常驻、durable工作、主动性/自主权、身份运营、crash/restart/remote handoff |

## 来源与产品事实 authority

[本轮研究总览](../../docs/research/2026-10-03-x-prep/00-summary.md)、[产品对比](../../docs/research/2026-10-03-x-prep/07-x7-products.md)、[X7 架构](../../docs/research/2026-10-03-x-prep/08-x7-architecture.md)、[总 source map](../../docs/research/2026-10-03-x-prep/09-source-map.md) 提供官方证据、锁定 repo/file、Atlas/Hermes已有、可搬模块、薄接线与所属波。旧版总览中的产品发布日期、数量和架构描述均已被本轮核实材料取代；闭源产品不被当作可搬源代码。

当前基线为 `sol/x-prep@9e6d6fde949a0f581ba7e0031004b1f6c4fdd2f4`；Hermes 以 `core/pyproject.toml` 锁定的 `unicorn-Y/hermes-agent@e287231d7906bcce5bc373d20fb2e3e1e6427220` 为准。后续接入变更若发生在 T1/T1F 或 C6 之后，按任务书启动检查重新比对接口及版本，不把历史注释当当前来源。

## 全阶段约束

1. 复用现有 HermesRuntime/AIAgent、GoalManager/SessionDB、AtlasScheduler/DBOS、C4 SkillManager、Atlas permission modes 与配置 API，不创建第二套同类 authority。
2. X7 将专用笔记本作为 Atlas 的电脑，主机/手机/IM/语音只派活和审查。Windows service 与交互桌面 worker 分层；sleep/offline/锁屏/缺登录/重启有明确状态，不虚称与云 VM 的可用性相同。
3. X1提供事件/channel/auth，X2提供computer/browser及示范记录，X3提供device trust与transport，X4管理skill版本，X5审核候选，X6统一入口/协作，X7负责常驻运营与恢复。不能重复施工同一能力。
4. 用户负责安装安全审查；不额外建设scanner，不新增沙箱，不做视频生成。现有 permission、trust、OriginGuard 和审批链仍按正式任务书接线，不因去掉额外scanner就绕过已有authority。
5. 真实账号、专属邮箱/IM/电话、设备电源/自启配置、付费服务必须在该波获得用户选择与授权后验收。本轮只记录需要什么，不改变用户账户/设置。
6. 每波在 CORE-PARITY 的“外部功能”节新增 `EXT-Xn-*` 行，保留主体已有同名 X 分类；真实验收结果写对应 result。fake不代替真实服务、产品官方描述不代替 Atlas 实测。

默认顺序 X1 → X2 → X3 → X4 → X5 → X6 → X7；用户可授权独立子能力提前施工，但不可省略依赖或复制前置系统。准备结果见 [ATLAS-X-PREP.result](../results/ATLAS-X-PREP.result.md)。

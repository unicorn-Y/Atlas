# 第一批 A–F 派工与文件所有权

模型统一 GPT-6 Luna，推理 xhigh。用户已授权最多三个子智能体并行；当前复用 A 通道施工 D，与 B/C 并行，E/F 等空槽立即补位。本文件不代表产品验收。

## 通用交付与红线

每包完整阅读 MEMORY-V1 的 00/01/02/03/CURRENT 与适用 AGENTS，先保存自己所有文件的既有 diff。不是独自施工，不回退/覆盖他人改动，不自行提交。每个文件同一时刻只有一个施工者；需越界时向总控提出精确路径与原因。配置写入由 A 唯一负责，生命周期与 run_phases 接线由 B 唯一负责。总控独占 CURRENT.json、progress/S<n>.md、VENDORED.md 的整合。

测试使用 ATLAS_DATA_DIR、MEMORYOS_DATA_ROOT、MEMORYOS_DB_PATH 隔离根，真实模型另隔离 HERMES_HOME。MEMORYOS_DB_PATH 必须是临时 SQLite 文件路径；service/db.py 不消费 MEMORYOS_DB_DIR。禁止碰 D:/Atlas/data、D:/MemoryOSData、user-settings.json 和生产配置。两个 Python 环境仅 HTTP 通信；模型调用只在 Atlas ModelRouter，记忆权威只有 MemoryOS。严守第 6 节：禁预填自然输入 key/value/人物/主题，禁答案注入、预设效果、假模型冒充、缩水规则冒充上游模型、删/skip/xfail 测试、降低门槛、第二事实库/调度器/模型配置、合并 main、自写 ACCEPTED。

每包提供精确 diff 文件列表、命令/退出码/测试数、原始日志与可重复真实冒烟命令、模型 id/token、逐条红线核对、已知问题；单测 fake_provider 显式标注且不计真实效果。凭据/模型缺失立即报 BLOCKED。总控亲读 diff、复跑测试、抽查真实冒烟后才整合，完整步骤完成后才写 DONE_PENDING_REVIEW。

## A：S0 清场与冻结（冻结子包已整合，整体仍部分完成）

所有权：Atlas 测试 harness、test_bootstrap*、memory/v1_features.py、windows_sources.py 冻结入口、core/atlas/config.py 和相关新测试；MemoryOS service/app.py 的冻结后台入口、legacy import 测试和对应导入修复。config.py 与 app.py 已由总控登记为 A 独占。禁止 B 的所有热文件、MemoryOS D/E 热文件、automation/engine.py 和 durable。

临时所有权补充：D/E 尚未派出期间，A 可以编辑 MemoryOS service/unified/api.py、retrieval.py、maintenance.py、utility.py **仅为 S0 冻结门控**。不得实施 D/E 的形成、整理或排序能力。A 交付后 api.py 转 D、retrieval.py 转 E；交接前后不允许两个写者。此项覆盖上句对这两个文件的暂时禁止。

A 另独占 core/pyproject.toml 的 fake_provider marker 登记，不能改默认测试筛选；真实服务/WS/重启测试只标 fake_provider，不能为了标记假模型而把整个模块重新归类 unit。旧 scripts/unified_memory/gen_manifest.py、learning_trial.py、repair_baseline.py 的伪效果路径由 A 检查，其他包不编辑。

A 增补 models_settings_router.py 的 memory_model 字段（同一用户设置 store 与已有模型校验），测试 test_models_routes.py（仅新增隔离用例）；scripts/unified_memory/cutover.py 仅移除 fixture/helper 的无条件假应用证据，不得执行 cutover 或改生产启用语义。

A 独占 MemoryOS 七个既有专测文件的 HTTP opt-in 接线：test_associative_recall.py、test_conditional_utility.py、test_grounded_probe.py、test_experience_distillation.py、test_multimodal.py、test_prediction_feedback.py、test_strategy_operations.py。仅显式设置冻结开关测试头，原用例/断言/筛选不变，不全局改变所有测试默认策略。原始媒体证据存取不用 opt-in。

A 另负责 test_transfer_gate.py 的同类显式 opt-in 和共用测试头 helper。冻结 utility 只能退出其学习/画像演化，基础实际应用回执的校验与存储仍须开放，供 V1 实际使用强化接线。

判据：harness 不替产品固定作答；冻结清单全部退出运行入口、保留测试；bootstrap 泄漏修好，legacy import 失败修好或有干净 HEAD 复现原因。必须跑针对测试、合理全套基线、至少一条真实服务/模型冒烟；扫描造假符号，不能为消除命中删除测试。独占 progress/packages/A.md。

## B：S1 读路径和自动拉起（施工中）

独占 run_phases.py、memory/__init__.py、unified_client.py、unified_facade.py、api/unified_memory_router.py、server.py/deferred_startup.py 生命周期部分、新服务生命周期模块、B 专属测试。禁止 observer/reflector/recall_context 和 MemoryOS 产品代码。后续 C/E 接线仍由 B 实现。

B 增补 capture.py 现有 tick/ACK 后注册/清理薄回调所有权，不重写捕获内容、哈希、水位和投递可靠性；Observer 模型调用在 singleflight 后台任务，不阻塞 drain/主回答。未经删除边界验证，不在 DELETE conversation 后触发新增记忆写入。

B 增补 observer_drain.py 及专属 drain 测试，只负责现有 capture tick 驱动 pending/resume→真实 HTTP ack→ack_batch；结束信号须同步持久化，再开始后台模型工作。

判据：启用统一后用户事实读全部 HTTP 委托，独有本地 facts 不出现在上下文；健康检查/自动启动/仅关闭自有进程，离线不阻塞；隔离 legacy dry-run 有记录数、哈希、出处。必须生命周期/读路径/本地污染回归测试和 S1 五条真实模型经 run_phases 的冒烟，覆盖 remember、新会话、服务离线、重启自动拉起。独占 progress/packages/B.md。

## C：S2 Atlas Observer（施工中）

独占 observer.py、必要提示词/schema/预算模块、test_memory_v1_observer*.py、scripts/memory_v1/smoke_observer.py、progress/packages/C.md 与 C_vendored.md。给 B 提钩子需求，给 A 提配置需求；不写 B/D/E 热文件。

C 增补独占 outbox.py 的 Observer 操作状态、待观察/待 HTTP ack 队列和每日 token 预算持久化扩展，复用已有 OperationalOutbox SQLite，禁止另建事实库、配置库、调度器或重写 capture 可靠性。B 只消费其恢复/提交接口，启动和既有周期后台接线仍归 B。

判据：固定 Mastra commit/blob 完整源读与条目保留；ModelRouter purpose memory_observe、模型回退顺序；批内真实出处、JSON schema、speaker/epistemic、DERIVED、预算顺延、异步阈值/结束 flush。必须 schema/预算/出处/第三方/路由/异步测试，十条真实中文模型冒烟 ≥9 正确形成、0 提问/网页归用户、全部 evidence 可打开；D 未接好不声称完整形成。记录上游行号到目标符号映射。

## D：S2 MemoryOS 形成与 S4 整理接口（A 通道接续施工）

独占 D:/MemoryOS/service/unified/formation.py、consolidation.py、api.py，D 专属测试，新增迁移号 **0031**（只有需要新字段时创建 0031_memory_v1_consolidation.sql）。app.py 已归 A 独占，需要接线时向 A 提需求。禁 retrieval.py、现有迁移修改、Atlas 热文件。配置向 A、Atlas client 方法向 B 提需求。

2026-10-07：A 确认停止冻结文件编辑，总控独立验收后提交推送 MOS ba86134。api.py 正式转 D；retrieval.py 留给 E，当前无写者。A 通道接续 D，但其 Atlas 配置所有权仍保留，其他通道不得并写。先完成无 key 自然正文形成供 C 跑真实十条，再实施整理接口。

D 增补 sources.py 的 _write_dependencies 及其直接 DERIVED source_event_id 解析校验，保留原字典依赖兼容。原始 payload/hash/derived_from 不改写；解析为已存在同主体实际 ref/revision，缺失或跨主体或删除屏障拒绝，不可凭命名拼 ref 假装存在。

判据：无 key 非空正文形成记忆，归一正文去重、保留全部来源；带 key 的冲突/迟到/时态保持；consolidation:apply 合法操作、同主体/出处/删除屏障校验、逐操作原子接受或拒绝与 revision；被删来源导致概括 stale，不能复活。必须无 key/provenance/冲突/时态回归、非法与跨主体 ref、拒绝操作不部分生效、幂等、HARD_ERASE 和概括 stale 测试；真实隔离 HTTP 服务至少一条形成与一条整理冒烟，模型提议来自 C/G，不能用规则替代真实模型宣称 S4 达标。独占 progress/packages/D.md。

## E：S3 召回装配和 S4 排序（待派）

独占 D:/MemoryOS/service/unified/retrieval.py、E 专属测试；Atlas 新 recall_context.py、专属测试、scripts/memory_v1/smoke_recall.py、progress/packages/E.md 和 E_vendored.md。禁止 B 热文件及 D schema/API；新增字段需求交 D，统一配置交 A，run_phases 接线交 B。

判据：画像 ≤600 token，相关 top8 ≤1500 token，日期/当前历史/ref，embedding+轻规则闸门不另调大模型，冲突/同名候选标记，每轮 ref/理由日志；排序四项公式、facet 半衰期、真实使用回执强化、高重要性下限，衰减不丢失。必须预算/闸门/出处/冲突测试、200天 EPISODE 精确及时间召回、强化/半衰期/HIGH 回归；S3 十条真实模型经 run_phases（E1/E2/E3/E4/E6 各2条），S4 轨迹冒烟与 C/G 配合；引用前端校验交 H，不能把装配单测当效果达标。

## F：S8 评测准备（待派）

只拥有 docs/plan/MEMORY-V1/eval/、scripts/memory_v1/ 的评测脚本（排除 C 的 smoke_observer.py、E 的 smoke_recall.py），progress/packages/F.md。不改产品代码、测试配置、CURRENT 或任务书。

判据：锁定官方 LongMemEval commit 9e0b455f4ef0e2ab8f2e582289761153549043fc；LongMemEval_S 六类各20题、种子20261007，保存真实题号、数据sha256，不提交大数据集；30场景全保留、反例全过/E5E7E8全过/E1–4E6≥90%；官方判分与完整 Observer→存储→召回→回答链，不向模型泄漏答案；2周每天3–5段自然轨迹，真实Observer形成。必须抽样确定性/类别数/答案泄漏隔离测试，真实入口至少一条评测脚本冒烟；120题门槛≥80%、1万条本地p95≤800ms 与标定脚本保留，准备完成不能标为 S8 效果通过。

## 后续接续

空槽立即补 D/E/F，然后 G reflector（C/D 可用后）、H Electron 记忆页面（B/E 接口稳定）、I 接续提醒验证（仅修坏处）、J 整合。A 热配置、B 热接线维持唯一写者。S7 只能准备清单与隔离 dry-run；生产启用和回填须停下请用户授权，不能擅自执行。

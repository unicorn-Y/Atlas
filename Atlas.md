# Atlas Ledger

<!-- Maintained by atlas-ledger. Confirmed clauses are loaded into new Goal Contracts by atlas-contract.
     Keys (WHEN/DON'T/INSTEAD, IDs, severity, Source) are fixed English; content is localized.
     Keep confirmed clauses general and <= 15.

     This file is PROCESS memory: rules about how work on this repository must be done.
     It is NOT the same document as data/memory/事/Atlas.md, which is PRODUCT memory
     (facts about Atlas that the agent writes for itself, inside the git repo at
     data/memory/). Conflating the two is itself recorded below as an observation.

     Every clause here was distilled from a drift actually caught in the 2026-11 full
     review with a concrete artifact behind it. Nothing was invented to fill the file. -->

## Confirmed Clauses

- [L1] (seen 4x, severity: high)
  WHEN:    给 Atlas 新增一个能力、服务、事件或接口
  DON'T:   只提交实现模块本身，把依赖注入、路由挂载、前端消费留空，然后宣称"已完成"
  INSTEAD: 在同一个改动里把它接进现有接缝 —— AppServices / get_app_services /
           application.py 的 include_router / 渲染层的 known 与 AgentEventType ——
           并用 introspect 的 services.unbound 与 tools.hidden 自查到 0
  Source:  2026-11 全量评审 P1-14「built but never wired」；/api/introspect/query

- [L2] (seen 2x, severity: high)
  WHEN:    后端新增、重命名或删除一个桌面事件名
  DON'T:   只改发送端，认为渲染层"以后再说"
  INSTEAD: 同一次改动里更新三处真源 —— atlas/api/event_names.py、
           runtimeEvents.ts 的 known 集合、runtime.ts 的 AgentEventType ——
           并跑 core/tests/test_event_contract.py
  Source:  P0-6 十六个事件被静默丢弃；subtask.steered 的反馈永远不显示

- [L3] (seen 1x, severity: high)
  WHEN:    实现"先生成建议、再落盘"的两阶段流程
  DON'T:   只实现生成端，把落盘端留成 TODO、注释或一个没人调用的函数
  INSTEAD: 在同一条主路径里显式排好两步，并在返回值里分别带上两段的产物，
           这样"没有改动"是一个可观测的结果，而不是一个猜不出来原因的空值
  Source:  P0-2 dream 只 propose 从不 apply，梦境跑了几百次，记忆库一条没变

- [L4] (seen 2x, severity: high)
  WHEN:    任何会返回配置、环境或能力清单的接口或日志
  DON'T:  直接返回 raw / base_raw 或叶子值，指望 redact() 兜住
  INSTEAD: 一律过 secrets_store.scrub，并且按完整点号路径判断是不是密钥字段
           （只看叶子名会把 web.keys.bocha 和 models.custom[].api_key 放过去）
  Source:  config.keys 曾明文返回两个真实 key；scrub 两轮修补

- [L5] (seen 1x, severity: high)
  WHEN:    发现某个本应存在的产物、文件或能力不存在
  DON'T:   报告一句"不存在"就收工，或把它当成阻塞点交回给用户
  INSTEAD: 先分清"根目录没有"和"真的没有"（它可能在别的路径、别的 git 库里），
           确实没有就新建，并接进现有接缝；缺什么补什么，不要另起一套
  Source:  用户两次纠正：「什么叫不存在？」「没有的东西就加上，融入进去」

- [L6] (seen 2x, severity: medium)
  WHEN:    启动后端（CLI serve 或桌面入口）
  DON'T:   假定端口空闲，把冲突留给底层 socket 异常去报
  INSTEAD: 启动前先 probe；端口被占就打印出占用进程并退出，
           让用户看到"已经有一个后端在跑"，而不是一个 connection refused
  Source:  port_guard.py；两处入口接线

- [L7] (seen 1x, severity: medium)
  WHEN:    在 run_drive.py 这类超长 async 函数里增删语句
  DON'T:   凭视觉对齐缩进 —— 错一级不会报错，只会让语句在错误的时机执行
  INSTEAD: 改完用 AST 校验目标语句的父节点与缩进深度，
           确认它落在模块级而不是某个 if 分支里
  Source:  P0-1 run.user_input 被缩进进 else 分支，记忆写回静默失败

- [L8] (seen 1x, severity: medium)
  WHEN:    声称某个功能已经可用
  DON'T:   只拿单元测试通过当作证据，或把"测试全绿"说成"能用"
  INSTEAD: 真机真模型跑一遍并把看到的输出贴出来；
           没跑就说没跑，不要让通过率冒充可用性
  Source:  用户明示「不要搞那一堆没有用的测试」；接受标准是真机真模型

- [L9] (seen 1x, severity: high)
  WHEN:    用关键词检索判定"某能力存在 / 不存在"
  DON'T:   拿命中数直接下结论 —— 短词会命中别的词内部（otel 命中 hotel / remote /
           telegram 共 3 次，真实为 0），带下划线的复合词会被漏搜
           （搜 whisper 得 0，但 sherpa_onnx 实现齐全）
  INSTEAD: 计数只用来挑候选；每条判定都要读到实现体与调用点，
           并先自问这个短词还会出现在哪些词里；复合词搜主词干
  Source: 对照 DSH 时四项误判，两个方向都错过（见 review §7.7）

## Provisional Observations

- [O1] (seen 1x)
  WHEN:    同时维护内存索引与磁盘上的 Markdown 记忆库
  DON'T:   假定两者始终一致
  INSTEAD: 改动后同步 index，并把"磁盘有、索引没有"当成需要修的状态
  Source:  P1-16 索引与磁盘两套真源；语义候选.md 未被索引

- [O2] (seen 1x)
  WHEN:    阅读或写入名为 Atlas.md 的文件
  DON'T:   把仓库根的流程台账与 data/memory/事/Atlas.md 的产品记忆混为一谈
  INSTEAD: 先看路径 —— 根目录这份是给"怎么改这个仓库"用的，
           data/memory 那份是产品记忆，两份文档、两个 git 库、两种生命周期
  Source:  governance provider 文档；本文件诞生时的实际混淆

- [O3] (seen 1x)
  WHEN:    在工作区已有大量未提交改动时继续修改
  DON'T:   把工作区当成干净的基线，或顺手整理那些既有改动
  INSTEAD: 只对自己的新增负责，并明确说明哪些改动属于本次
  Source:  P1-11 工作区 523 项未提交（194 D / 176 M / 153 ??）

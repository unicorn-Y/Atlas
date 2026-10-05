# GitHub 源码搬运与适配清单

本清单是施工依据。下面链接均锁定到研究时实际核查的 commit；文件 SHA256 见 `04_来源锁定与基线.json`。这些代码尚未搬入 Atlas。每个 ADAPT 项都必须先读取点名源码和直接依赖，再保留其关键机制；只换存储、模型、身份和日志等接线处。无法保持机制或无法闭合依赖时，标记 PARTIAL，不得用自行写的简化实现冒充搬运完成。

## 所有搬运项共同要求

1. `docs/plan/VENDORED.md` 每个条目记录来源仓库、commit、来源文件/符号、目标文件/符号、原许可证和 NOTICE、改动理由、依赖闭包、parity 测试及结果。
2. 来源原始副本放施工工作目录用于差分，不放第二套可运行引擎。需要实际 vendoring 的公共依赖放单独目录，保留许可证。适配后的目标仍服从 UM-WIN-1.0 契约。
3. parity 比較固定输入下的关键输出、不变量、错误和来源链。LLM 部分使用固定响应/记录重放验证解析与操作，再用真实模型单独验证效果；不得把随机逐字一致作为标准。
4. 每个模块必须列出实际调用方和集成证明。无人调用、默认关闭但宣称已上线、仅单测通过，都不算接入完成。
5. 锁定清单不是允许自动升级到 master 的授权。升级需要重做兼容性、许可和 parity 判断，写入变更记录。

## S01 Graphiti

- 仓库：[Graphiti](https://github.com/getzep/graphiti)；固定 commit：`2a85bbbf27f3d0d07dd3a8bf6dc8700c5193c066`；许可：Apache-2.0。
- 方式：ADAPT；波次：UM03；目标：`service/unified/identity.py; service/unified/temporal.py`。
- 搬什么：抽取实体、别名候选与重复关系；搬 valid_at / invalid_at / expired_at 的分工和带证据的矛盾判定流程。
- 接线与不得缩水之处：resolve_nodes、resolve_edge_contradictions；SQLite graph_store 替代上游图数据库，LLM 调用经过 Atlas ModelManager。姓名相同不能自动合并，时间按事件时区解释，不能照搬 naive UTC 假设。
- 必验收：同名不同人、改名、跨项目同名、否定与撤回、过去/现在查询；对同一固定 fixture 比较上游与适配器的实体/关系集合、证据与有效区间。
- 已锁定的来源文件：

  - [graphiti_core/edges.py](https://github.com/getzep/graphiti/blob/2a85bbbf27f3d0d07dd3a8bf6dc8700c5193c066/graphiti_core/edges.py)，SHA256：`6715bbe5763d30aa58134fc601ad21c761aaf4a7b5785809f507146b5f821af2`。
  - [graphiti_core/utils/maintenance/edge_operations.py](https://github.com/getzep/graphiti/blob/2a85bbbf27f3d0d07dd3a8bf6dc8700c5193c066/graphiti_core/utils/maintenance/edge_operations.py)，SHA256：`5f9ff2a5cc3ce5cc0bac4aee202ad6fadb7172464aa7af33e26bc2bcd6cb5d6e`。
  - [graphiti_core/search/search_filters.py](https://github.com/getzep/graphiti/blob/2a85bbbf27f3d0d07dd3a8bf6dc8700c5193c066/graphiti_core/search/search_filters.py)，SHA256：`ad26e1ca011a52d433d993d4165d08ce66e211b9cfe3dbf3626467db21430065`。
  - [graphiti_core/utils/datetime_utils.py](https://github.com/getzep/graphiti/blob/2a85bbbf27f3d0d07dd3a8bf6dc8700c5193c066/graphiti_core/utils/datetime_utils.py)，SHA256：`b6b029185344a6a74937e91759b6cfbc966cad6df0cfda0498075765bac82d15`。

## S02 Hindsight

- 仓库：[Hindsight](https://github.com/vectorize-io/hindsight)；固定 commit：`b89ce287464fe10790d67ba86bfabe29d8926253`；许可：MIT。
- 方式：ADAPT；波次：UM04；目标：`service/unified/formation.py; service/unified/dependencies.py`。
- 搬什么：搬观察归并、重复 create 转 update、更新依赖集合、活跃来源检查。
- 接线与不得缩水之处：_duplicate_create_target、_dedup_decision、_apply_create/_apply_update、_filter_live_source_memories、_sources_changed；去掉 asyncpg 存储实现，保留判定语义。来源编辑后重新计算，不能把旧摘要作为新证据。
- 必验收：重复写入、来源被编辑/删除、重复摘要、并发更新、来源集合变化；删除后派生事实不继续召回。
- 已锁定的来源文件：

  - [hindsight-api-slim/hindsight_api/engine/consolidation/consolidator.py](https://github.com/vectorize-io/hindsight/blob/b89ce287464fe10790d67ba86bfabe29d8926253/hindsight-api-slim/hindsight_api/engine/consolidation/consolidator.py)，SHA256：`b6958ada908fcc74a0f2c7173b9b1ca96b2cb87a83fbaf3e8d8547900c0d4c01`。
  - [hindsight-api-slim/hindsight_api/engine/memory_engine.py](https://github.com/vectorize-io/hindsight/blob/b89ce287464fe10790d67ba86bfabe29d8926253/hindsight-api-slim/hindsight_api/engine/memory_engine.py)，SHA256：`38d2504b970cb06f6da458f4d57199284ab62586cf0135f2912a11cf79e01aae`。

## S03 TiMem

- 仓库：[TiMem](https://github.com/TiMEM-AI/timem)；固定 commit：`6d279a5f5d40ee229e1995df15c182cb2062c71c`；许可：Apache-2.0 + MIT (directory specific)。
- 方式：ADAPT；波次：UM04;UM07；目标：`service/unified/consolidation.py; service/unified/query_planner.py`。
- 搬什么：搬分层总结和查询规划的机制与必要提示词。
- 接线与不得缩水之处：L1–L5 生成流程按日/周/事件适配；analyze_query / parse_analysis 保留时间与查询类型分解。复用 Atlas 模型、日志和配置；不增加第二套模型管理。
- 必验收：粒度选择、跨天事件、预算收缩、原文回溯、层级摘要重算；摘要不能成为比原始来源更高的权威。
- 已锁定的来源文件：

  - [timem/memory/memory_generator.py](https://github.com/TiMEM-AI/timem/blob/6d279a5f5d40ee229e1995df15c182cb2062c71c/timem/memory/memory_generator.py)，SHA256：`870bfaa2d243eefad3cd685c03be5010b6f9d3dd310606af31ea0c46a5204452`。
  - [timem/workflows/memory_retrieval.py](https://github.com/TiMEM-AI/timem/blob/6d279a5f5d40ee229e1995df15c182cb2062c71c/timem/workflows/memory_retrieval.py)，SHA256：`247c5c1ff7c45874fcbc1219f07f92ae2c6bb95b6b0ee25f566ffdedd14324a0`。
  - [timem/workflows/retrieval_nodes/llm_retrieval_planner.py](https://github.com/TiMEM-AI/timem/blob/6d279a5f5d40ee229e1995df15c182cb2062c71c/timem/workflows/retrieval_nodes/llm_retrieval_planner.py)，SHA256：`3f4792ee519ecb144f197f2f48ebf90c3469362663f6faf332e528c6700676f9`。

## S04 Myelin

- 仓库：[Myelin](https://github.com/myelinagent/Myelin-AI)；固定 commit：`48b1f47a2b634678ece45adcc71a3b20764b8a04`；许可：MIT。
- 方式：ADAPT；波次：UM06;UM11；目标：`service/unified/working_set.py; service/unified/self_probe.py`。
- 搬什么：搬 observe/commit/attend 的工作集循环、健康探测和来源约束。
- 接线与不得缩水之处：把会话工作集绑定 Atlas run/session；dream 的答案键评分只作探测线索，不作为现实成功证明。检索器缺失不得静默继续；prune 不代替 HARD_ERASE。
- 必验收：中断恢复、过期工作集、缺来源探测、检索失败、被删除来源；真实工具结果单独验证。
- 已锁定的来源文件：

  - [myelin/client.py](https://github.com/myelinagent/Myelin-AI/blob/48b1f47a2b634678ece45adcc71a3b20764b8a04/myelin/client.py)，SHA256：`d9f9fd3b4b172b1c308755cd4dec45c7ecb782edd6d033804ccaa30ddd6d4349`。
  - [myelin/_internal/dream.py](https://github.com/myelinagent/Myelin-AI/blob/48b1f47a2b634678ece45adcc71a3b20764b8a04/myelin/_internal/dream.py)，SHA256：`3336ef540f7d5a80382a697f7acd76f7b1a1f59fe3528f87b20df5ec363dcb7d`。
  - [myelin/_internal/health.py](https://github.com/myelinagent/Myelin-AI/blob/48b1f47a2b634678ece45adcc71a3b20764b8a04/myelin/_internal/health.py)，SHA256：`544d0fee3f8d044a7463e9ecb5eac2a6ea107b3b3000ee13ceb41afe9d665f46`。

## S05 M3-Agent

- 仓库：[M3-Agent](https://github.com/ByteDance-Seed/m3-agent)；固定 commit：`0e3e41939bd8a0b66d756e7b7eb8d5fe9992da5c`；许可：Apache-2.0。
- 方式：ADAPT；波次：UM05；目标：`service/unified/multimodal.py`。
- 搬什么：搬视频/图像/声音/文字节点及等价关系、关联检索与候选筛选。
- 接线与不得缩水之处：Node、多模态节点、connected/retrieve/query selection；按源码依赖闭包保留 NumPy/sklearn/PIL 或证明等价替代。仅接 Atlas Windows 已授权媒体；不安装上游训练流水线。
- 必验收：同一截图重复入库、截图与 OCR 关系、声音转写定位、时间片段引用、敏感媒体清除；OCR 推测不能写成用户断言。
- 已锁定的来源文件：

  - [mmagent/videograph.py](https://github.com/ByteDance-Seed/m3-agent/blob/0e3e41939bd8a0b66d756e7b7eb8d5fe9992da5c/mmagent/videograph.py)，SHA256：`80b4aa8adc5867f90530e636ce70a4d7cfc89c0e71cfceb69eaf5c13e141f613`。
  - [mmagent/retrieve.py](https://github.com/ByteDance-Seed/m3-agent/blob/0e3e41939bd8a0b66d756e7b7eb8d5fe9992da5c/mmagent/retrieve.py)，SHA256：`1571169038f40b5766376cfdd2f4096c8dd063ca460d9f036a4ae016bec45ff7`。

## S06 A-mem

- 仓库：[A-mem](https://github.com/agiresearch/A-mem)；固定 commit：`ceffb860f0712bbae97b184d440df62bc910ca8d`；许可：MIT。
- 方式：ADAPT；波次：UM07；目标：`service/unified/associations.py`。
- 搬什么：搬 process_memory 的关联与演化操作。
- 接线与不得缩水之处：LLM 提出的连接作为有版本的派生关系；验证实体、项目、时间与来源后才能采纳。不得原地改写历史事实。
- 必验收：相关词但无关系、跨项目污染、关系撤回、引用链不丢失；关联带来的召回提升须与无关联基线比较。
- 已锁定的来源文件：

  - [agentic_memory/memory_system.py](https://github.com/agiresearch/A-mem/blob/ceffb860f0712bbae97b184d440df62bc910ca8d/agentic_memory/memory_system.py)，SHA256：`22e5bfd1c98060e1e87704aa771e3ab29952d23a1f9e3c1a4b6fed148020e5d1`。

## S07 HippoRAG

- 仓库：[HippoRAG](https://github.com/OSU-NLP-Group/HippoRAG)；固定 commit：`2bfd831417202b49cda9da7973e141a456e16872`；许可：MIT。
- 方式：ADAPT；波次：UM07；目标：`service/unified/graph_retriever.py`。
- 搬什么：搬检索中的事实识别、密集召回与图传播组合。
- 接线与不得缩水之处：retrieve 的函数依赖闭包在施工时逐项登记；适配现有图实体，不建立第二套权威图。图质量差或超预算时降级并留下原因。
- 必验收：两跳关系、无图证据、错误边传播、缓存过期、跨 subject 过滤；比较向量基线和图增强的检索正确率。
- 已锁定的来源文件：

  - [src/hipporag/HippoRAG.py](https://github.com/OSU-NLP-Group/HippoRAG/blob/2bfd831417202b49cda9da7973e141a456e16872/src/hipporag/HippoRAG.py)，SHA256：`63374f66c2e92056026e4f9df27bd417621a2bd70ff045a91094bc90a0830293`。

## S08 ReasoningBank

- 仓库：[ReasoningBank](https://github.com/google-research/reasoning-bank)；固定 commit：`ed80611788292ea739f1effd31f16c53823b8a0d`；许可：Apache-2.0。
- 方式：ADAPT；波次：UM09；目标：`service/unified/experience_distiller.py`。
- 搬什么：搬成功/失败轨迹提炼及经验筛选。
- 接线与不得缩水之处：format_trajectory、筛选与诱导提示词；输入实际 actions/results/verification 和失败边界，不依赖模型私有思维链。使用 Atlas provider。
- 必验收：假成功、工具失败、相反教训、过时环境；无独立验证的策略保持候选。
- 已锁定的来源文件：

  - [WebArena/induce_memory.py](https://github.com/google-research/reasoning-bank/blob/ed80611788292ea739f1effd31f16c53823b8a0d/WebArena/induce_memory.py)，SHA256：`9efa53164f22772f1716476667577bd222597bdcba24a210ee1f6cb5c2eae169`。
  - [WebArena/memory_management.py](https://github.com/google-research/reasoning-bank/blob/ed80611788292ea739f1effd31f16c53823b8a0d/WebArena/memory_management.py)，SHA256：`ac40e71d216668ed5af49bb5c94b77cf7906ef0149c74e4e55ade792e88fd4e2`。

## S09 ACE

- 仓库：[ACE](https://github.com/ace-agent/ace)；固定 commit：`82709de050e1db6e6ef2f07bcb0393560b94992a`；许可：Apache-2.0。
- 方式：ADAPT；波次：UM09;UM11；目标：`service/unified/strategy_updates.py`。
- 搬什么：搬增量 ADD/UPDATE/MERGE/DELETE 的结构化更新与校验。
- 接线与不得缩水之处：curate/propose/validate、apply_curator_operations 与 JSON 解析；写入统一版本库，不使用独立 playbook 文件作为新权威。
- 必验收：增量重复、删除不复活、错误操作拒绝、合并保留来源、并发冲突；每条策略可回滚。
- 已锁定的来源文件：

  - [ace/core/curator.py](https://github.com/ace-agent/ace/blob/82709de050e1db6e6ef2f07bcb0393560b94992a/ace/core/curator.py)，SHA256：`dafe08bb9392ab5ba66b567921e6b6f38a16f0b5c08a89db61f1cb00e00187a7`。
  - [playbook_utils.py](https://github.com/ace-agent/ace/blob/82709de050e1db6e6ef2f07bcb0393560b94992a/playbook_utils.py)，SHA256：`2819e089427e73e6f247715abf9bcaa704df968c1dab9408a84b90057c3b31f4`。

## S10 MemRL

- 仓库：[MemRL](https://github.com/MemTensor/MemRL)；固定 commit：`c1b322ca43de36ddf64c6712f89d0095bfc35ce0`；许可：MIT。
- 方式：ADAPT；波次：UM09；目标：`service/unified/utility.py`。
- 搬什么：搬两阶段价值选择、Q 更新和奖励归因。
- 接线与不得缩水之处：ValueAwareSelector、QValueUpdater、MemoryCurator；效用绑定任务族/模型/环境，不把一次成功分给全部召回项，不把全局 Q 当真实性。
- 必验收：未使用记忆不获奖励、失败归因、模型更换、任务迁移、样本稀少；查看实际采用与最终结果分别记录。
- 已锁定的来源文件：

  - [memrl/service/value_driven.py](https://github.com/MemTensor/MemRL/blob/c1b322ca43de36ddf64c6712f89d0095bfc35ce0/memrl/service/value_driven.py)，SHA256：`d9b3fc1f9792bf641d4bf615ca53e3893622e1d0ea1268ea836989c54b482079`。
  - [memrl/service/retrievers.py](https://github.com/MemTensor/MemRL/blob/c1b322ca43de36ddf64c6712f89d0095bfc35ce0/memrl/service/retrievers.py)，SHA256：`35ae5e0aae26fdd3d36f887ccb972ca275dbb7103d280188715635d390ff21cf`。

## S11 WorldMind

- 仓库：[WorldMind](https://github.com/zjunlp/WorldMind)；固定 commit：`712b0fd53b4bd6a1948603f087a1e9f25a5adaea`；许可：MIT。
- 方式：ADAPT；波次：UM10；目标：`service/unified/prediction.py`。
- 搬什么：搬目标/过程经验分解与经验精炼。
- 接线与不得缩水之处：experience_refiner 的结构化提炼、GoalManager/Process manager 的检索组织；JSON 保存替换为统一仓库。预期结果带不确定性，真实结果用于校准。
- 必验收：正确预测、错误预测、环境改变、失败前提；具身任务论文结果不算 Windows 验收。
- 已锁定的来源文件：

  - [Plugin/worldmind_plugin/experience_refiner.py](https://github.com/zjunlp/WorldMind/blob/712b0fd53b4bd6a1948603f087a1e9f25a5adaea/Plugin/worldmind_plugin/experience_refiner.py)，SHA256：`d589d4cce3d514571c65c5dde74da3144bc92363892384130f878999fffe141f`。
  - [Plugin/worldmind_plugin/knowledge_manager.py](https://github.com/zjunlp/WorldMind/blob/712b0fd53b4bd6a1948603f087a1e9f25a5adaea/Plugin/worldmind_plugin/knowledge_manager.py)，SHA256：`dae67ab0c8079a37254120341ffb0534cc218cd6168325b0bddf79c59a704989`。

## S12 Memento-Skills

- 仓库：[Memento-Skills](https://github.com/Memento-Teams/Memento-Skills)；固定 commit：`ee9b9a45efd093d669c06fe318b4b1dceb246d19`；许可：Apache-2.0。
- 方式：ADAPT；波次：UM10；目标：`core/atlas/memory/skill_evolution.py`。
- 搬什么：搬失败驱动技能改写、结果记录、原子发布和回滚。
- 接线与不得缩水之处：SkillEvolutionEngine record_outcome/evolve_failure/rollback_last；提示词、schema/loader/LLM 依赖映射到 Atlas 已有技能注册表。保留沙盒验证和发布版本；不自动替换生产技能。
- 必验收：语法/结构验证、恶意或错误改写、留出任务、版本冲突、原子切换失败、回滚；同一名称只有一个活跃版本。
- 已锁定的来源文件：

  - [core/skill/evolution/engine.py](https://github.com/Memento-Teams/Memento-Skills/blob/ee9b9a45efd093d669c06fe318b4b1dceb246d19/core/skill/evolution/engine.py)，SHA256：`3d4db783a3ecbe28bcf6cec4b7ec10211ca3b0bc82400e36a7cfe303e59bd89f`。

## S13 Recuris

- 仓库：[Recuris](https://github.com/Gen-Verse/Recuris)；固定 commit：`7d3745ab787b1206ccd981cb1511100476097266`；许可：Apache-2.0。
- 方式：ADAPT；波次：UM10;UM13；目标：`service/unified/learning_gate.py`。
- 搬什么：搬技能记忆组织与成对评估发布门。
- 接线与不得缩水之处：gate 的 paired bootstrap 修复率/净增益/退化限制；换成 Windows 任务样本。原项目条件不能证明持续成长，本包另加独立留出和跨模型对照。
- 必验收：过拟合训练集、净收益为负、低样本、严重退化、模型替换；失败候选不得发布。
- 已锁定的来源文件：

  - [src/recuris/skillmemory.py](https://github.com/Gen-Verse/Recuris/blob/7d3745ab787b1206ccd981cb1511100476097266/src/recuris/skillmemory.py)，SHA256：`435ca3b0d7da473c1da40f0bbba45e7ccd5646d827172d1becbe5e2070a3ca42`。
  - [src/recuris/metaagent/gate.py](https://github.com/Gen-Verse/Recuris/blob/7d3745ab787b1206ccd981cb1511100476097266/src/recuris/metaagent/gate.py)，SHA256：`0e6a937f2fc72fe0807d26d9fbeb523e2985791b836539feb6ad1f609313af10`。

## S14 OpenSkill

- 仓库：[OpenSkill](https://github.com/OpenLAIR/OpenSkill)；固定 commit：`84ca182da055fafb6453dcec4a6defdbbfd987c1`；许可：Apache-2.0。
- 方式：ADAPT；波次：UM10；目标：`core/atlas/memory/targeted_learning.py`。
- 搬什么：搬失败分类→定向资料检索→独立验证的闭环。
- 接线与不得缩水之处：targeted_dr 与 independent_verifier 的可适配函数；pipeline 只参考执行次序，不搬 Docker/Harbor 框架。移除硬编码模型，走 Atlas ModelManager。验证者看证据而非接受生成者结论。
- 必验收：错误问题分类、不可验证资料、依赖不可用、生成者/验证者共同错误；必须有真实任务结果和回滚。
- 已锁定的来源文件：

  - [libs/openskill/targeted_dr.py](https://github.com/OpenLAIR/OpenSkill/blob/84ca182da055fafb6453dcec4a6defdbbfd987c1/libs/openskill/targeted_dr.py)，SHA256：`0149fab1259cbe75051e78cb9564b12f5797c4ba1146a05c71064ce3ddf23484`。
  - [libs/openskill/pipeline.py](https://github.com/OpenLAIR/OpenSkill/blob/84ca182da055fafb6453dcec4a6defdbbfd987c1/libs/openskill/pipeline.py)，SHA256：`a1f989d224204ef8c862020a01445cc1f926eda660e7046b8bd40213e9fb06fa`。
  - [libs/terminus_agent/evolution/independent_verifier.py](https://github.com/OpenLAIR/OpenSkill/blob/84ca182da055fafb6453dcec4a6defdbbfd987c1/libs/terminus_agent/evolution/independent_verifier.py)，SHA256：`a956048e88348e4ebbaa062969c895cabd291909d95ace0cf52c7c994e7dde82`。

## S15 Mem0

- 仓库：[Mem0](https://github.com/mem0ai/mem0)；固定 commit：`c93420c49a6b14c3d446bdb156d96811908fd90a`；许可：Apache-2.0。
- 方式：REFERENCE_ONLY；波次：UM01;UM07；目标：`No copied whole memory store; compare lifecycle/filter design only`。
- 搬什么：只参考生命周期操作、过滤与工具接口形状，不搬整套存储。
- 接线与不得缩水之处：user_id 参数不能证明权限，MCP 客户端也不是主体权威；Atlas→统一 MemoryOS 仍是唯一写入链。
- 必验收：比较 add/update/delete/search 的边界；任何接口不产生第二套事实库。
- 已锁定的来源文件：

  - [mem0/memory/main.py](https://github.com/mem0ai/mem0/blob/c93420c49a6b14c3d446bdb156d96811908fd90a/mem0/memory/main.py)，SHA256：`f63b856ff86b2b9da3730548116bfbc023560fe941dbfbd34075519b855c46d3`。
  - [integrations/agent-plugin-core/python/mcp_server.py](https://github.com/mem0ai/mem0/blob/c93420c49a6b14c3d446bdb156d96811908fd90a/integrations/agent-plugin-core/python/mcp_server.py)，SHA256：`5ef21e016e7c38a713331c9237671f29a4da016b4dd6470243ffd67ce8c4ae5a`。

## S16 MemoryAgentBench

- 仓库：[MemoryAgentBench](https://github.com/HUST-AI-HYZ/MemoryAgentBench)；固定 commit：`538026089d1a8a8eff05121d0db89b388f360eba`；许可：MIT。
- 方式：EVALUATION_ADAPTER；波次：UM13；目标：`tests/unified_memory/public_benchmark_adapter.py`。
- 搬什么：搬增量评测协议和评测适配代码，作为外部对照。
- 接线与不得缩水之处：测试目录独立，不安装为运行时记忆引擎；公开基准与本地日常/Windows 任务分开汇报。
- 必验收：来源许可保留，基准版本固定，增量输入不得提前泄漏后续答案；通过公开集不替代真实入口验收。
- 已锁定的来源文件：

  - [agent.py](https://github.com/HUST-AI-HYZ/MemoryAgentBench/blob/538026089d1a8a8eff05121d0db89b388f360eba/agent.py)，SHA256：`fb313eea68abaab01aec5d29a09b8e7f9bddee1ea71e96689becf83d747bf747`。
  - [main.py](https://github.com/HUST-AI-HYZ/MemoryAgentBench/blob/538026089d1a8a8eff05121d0db89b388f360eba/main.py)，SHA256：`809c44650730ad64cc93757f56980330c5db4de19c2abde5a2aef059210e7677`。

## 施工时必须补齐的依赖文件

锁定 JSON 是本轮读取并校验的入口文件清单，不声称已经穷举全部上游依赖。UM00 创建逐项源码移植工作表；执行每个条目前必须从上述 commit 获取直接 imports、提示词、类型、序列化和被调用函数，逐个登记 hash 和许可证。尤其核查 Graphiti 的 node_operations/dedupe_nodes/dedupe_edges，Hindsight 的 consolidation/prompts，TiMem 的 prompt_manager 与 prompts.yaml，M3-Agent 的 memory_processing，Memento-Skills 的 evolution/prompts 和上游 evolution 测试。它们是必须的依赖闭包候选，不能漏读后直接凭本文重写算法。来源未读齐、依赖未闭合、parity 未通过时，该条目保持未完成。

## 未选择的项目与边界

Screenpipe 的当前商业授权路线不作为本包必要依赖，Windows 观察复用 Atlas 现有电脑/浏览器能力。EgoLife、HaluMem 的非商业/禁止演绎等条件不适合直接照搬到这里；MemTools 缺乏可确认的根许可证，ProPlay/EviMem 缺乏本轮可确认的代码许可，都不作为复制来源。论文可作研究参考，但不得把论文机制当成已获许可的实现。本期不建设手机、微信、邮箱等外部平台专用采集器，也不把其他 agent 作为独立记忆主体。

## 两个私有仓库的复用规则

Atlas 和 MemoryOS 的现有代码首先按总任务书清点与复用：MemoryOS 事件追加、既有图表、ProtectedCore、来源撤销、HARD_ERASE、episode/experience；Atlas 实际运行链、Hermes SessionDB、Automation、ModelManager、工具和技能注册表、MemoryPage。它们属于现有主体接线，不用外部项目覆盖。研究时的 HEAD 与工作树 SHA256 已单独登记，施工开始必须重新检查；未提交修改必须原样保留并确认所有权。不要运行会创建或打开默认生产数据库的导入来做只读检查。


# TASKBOOK-M8：任务经验晋升为 Skill 候选

状态：待后续授权施工。本文件是合同，不表示已实现。

## 目标与来源

把重复且可复用的操作经验变为独立 Skill 草稿，并经验证后晋升；记忆库仍只记录使用效果/来源。考考 MemOS skill `eligibility`, `verifier`, `lifecycle`（按 C 报告 pinned commit/path）；考考 Atlas `core/atlas/evolution/skill_sleep.py:harvest_atlas/run` 与本地 SkillOpt `cycle.py` staged validation/adopt。SkillOpt 默认不 auto-adopt，但配置可关闭 gate；其 aggregate strict improvement 不是每条 holdout 都提升的保证。Anthropic skills format 只作文件格式考考，逐子目录核许可。

## Atlas 目标与替换

目标 `core/atlas/evolution/skill_sleep.py` 与现有 skill manager 的候选接线；保持 `evolve_memory=False`，不把 M4 dream 与 SkillOpt 混为一个写入状态机。候选草稿写隔离 staging，不直接覆盖 live skill。

## 候选与门控

候选至少附 M2 来源、M3 task experience、成功/失败轨迹及适用边界；重复任务/明确可复用 workflow 才可进入。验证需 replay train/heldout；Atlas 默认要求配置的 aggregate quality metric 严格高于 baseline，且无安全/正确性 blocker。候选再由用户或现有审批流程 adopt。记忆引用指向 skill ID/version，skill 成败反馈回使用统计，不将整份 skill 复制进长期事实库。

## 数据迁移

扫描现有 3,298 技能目录时仅建立只读索引；先核归属、重复率、格式、目录许可证，不复制内容。旧候选无来源轨迹标 legacy，不能因存在于目录就推定有效。

## 最小真实使用验收

挑一项真实重复 workflow 生成候选，人工查看来源引用；holdout 未提升时留在 rejected/staging，提升时也不自动 adopt；批准后生成独立版本，运行一次真实任务并记录成功/失败反馈。测试 `gate_mode=off` 配置不可被 Atlas 默认启用。

## 依赖与并行

依赖 M3、M4、M7 evidence/lineage。可在 M6 broker 独立文件完成后并行；独占 evolution adapter 与候选模型文件，不修改记忆库 store/dream。

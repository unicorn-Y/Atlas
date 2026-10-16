# M8 施工结果

状态：`IMPLEMENTED_PENDING_INTEGRATION_AND_REAL_ACCEPTANCE`。功能代码已施工；未写 `M8 DONE`。M4 的真实 Atlas 使用验收尚未完成，M8 依赖的真实经验、模型重放和晋升门也未在本轮运行。

## 基线与隔离

- 工作树：`D:\atlas-mem-m8`，分支 `mem-m8`。
- 基线：`origin/mem-m4`，commit `a0acc44de98a4df72239e267f823d3697b2d21c2`（含 M3/M7 代码和 M4 实现）。
- 主机 `D:\Atlas` 保持未提交改动，未触碰。
- M8 专属源文件：`core/atlas/evolution/skill_sleep.py`、新建 `skill_candidate.py`、新建 `skill_staging.py`。没有改 M3/M4/M7 文件或 SkillManager 注册文件。

## 实现

- `harvest_atlas()` 现在从 `经历/*.md` 的 M3 Entry/`episode_details`/`source_refs` 构造 SkillOpt `SessionDigest`；保留旧 `state_db` 参数兼容但不读取它，不复制 SessionDB transcript。没有足够的已验证经历时不进入候选/晋升流程。
- 候选生成通过 Atlas `ModelRouter` 使用中文提示，输入 schema 包含 `experience_id/source_ref/source_level/recorded_at/task/outcome/verified/steps/files/commands/open_items`。每步必须引用经历 ID；命令必须逐字存在于被引用经历；需要两条有来源的成功经历、同一流程重复证据；格式或出处校验只重试一次，失败原因写入候选拒绝 Markdown。
- 候选 Markdown 存在记忆库根的 `技能候选/`，带经历 ID、source refs、状态与验证元数据；SkillOpt state 置于同目录且由局部 `.gitignore` 排除。`evolve_memory=False` 保持；`auto_adopt=True` 只作用于候选暂存文件，不直接触碰 live skill。
- 晋升门默认固定 `gate_mode=on`，要求 SkillOpt accepted、至少两个任务、candidate aggregate 严格高于 baseline、无报告 blocker，并且本地数据集含成功与失败/未完成经历。否则候选保持 staging。候选 frontmatter 保存模型、样本 ID、工具、指标和成功标准。
- 通过门后，版本写入现有 `skills/learned/<name>/SKILL.md`，旧版本快照保存在记忆库根 `技能候选/versions/`，并向 `日记/<date>.md` 写带 source refs、版本和回滚版本的每日变动。`rollback_promotion()` 提供恢复前版本或移除首次晋升 skill 的函数；默认 SkillManager 已递归扫描 `learned/<name>/SKILL.md`，无需修改其注册源。
- `derived_manifest_for_sources()` 返回库根内候选/快照/SkillOpt state 相对路径供 M7 `propagate_forget()` 清除。库外 live skill 若所有来源都被忘记则列入 `external_live_paths`；若仍混有其他来源则列入 `external_live_needs_rebuild`，供回调撤下并人工重建，避免整包删除独立来源内容。

## 核查

- `python -m py_compile core/atlas/evolution/skill_sleep.py core/atlas/evolution/skill_candidate.py core/atlas/evolution/skill_staging.py`：通过，使用 Hermes Python 解释器做语法编译。
- `git diff --check`：通过。
- 未添加或运行 pytest。当前可用解释器没有安装可选依赖 `skillopt_sleep`；因此没有运行真实 replay。
- 未执行真实 Atlas 会话、真实模型候选生成、 heldout baseline/candidate 对比、SkillManager 实际调用、晋升回滚或重启后复查。没有证据可以宣称 M8 gate 通过。

## 需要后续接线/验收

1. M7 `propagate_forget()` 只接受 `library.store.root` 内路径。调用方应把 `derived_manifest_for_sources(...)["memory_paths"]` 传入其 `derived_manifest`；还需在遗忘事务中调用对应 cleanup callback 删除 `external_live_paths`，并撤下 `external_live_needs_rebuild` 后安排人工重建。当前 M7 call-site 尚未接入。
2. 现有 `/api/memlib/revert` 只回滚记忆 Git 提交，不会自动恢复库外 learned skill。需要 API/界面接线调用 `rollback_promotion(name, previous_version=...)` 并刷新 SkillManager，才能兑现一键回滚；M8 未改 API/UI 文件。
3. 在 SkillOpt 安装的 Atlas 环境里，以隔离真实记忆库和真实 M3 经历完成 TASKBOOK-M8 所列四组 gate：来源逐步复核与格式重试；一成功加一失败/未完成 heldout 的真实重放；严格提升时自动晋升及实际调用/回写反馈；忘记传播、历史清理与重启不复现。还须完成上一波 M4 七项真实验收后才可将 M8 标 DONE。

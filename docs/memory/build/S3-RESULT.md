# S3 总调度施工与集成结果

状态：**集成实现已完成；真实 Atlas 使用验收仍待执行。此结果不把 M1–M8 标记为 DONE。**

工作树：`D:\atlas-mem-integrate`，分支：`mem-integrate`。主机 `D:\Atlas` 的既有未提交改动未触碰。

## 合并顺序

基于 `origin/mem-m2`，按调度顺序无冲突合入：

1. M1 `11b6eddf7f55fb3ef3f56bb2f032ec46d298c5cb`
2. M3 `211962cd8dd0a459c730a9b5ee4a73e34dbf44b6`
3. M7 `ba38782b871aff468737ef5d54387de462b79597`
4. M5 `720de7110f6f1e2db733b709575f5150c64fb0ad`
5. M9 `65a7776370691d37d65f026af4d08efe1c8e19f5`
6. M4 `a0acc44de98a4df72239e267f823d3697b2d21c2`
7. M6 `b8eec99ec5a60c9292764dc4e5ba15c20e4e0d29`
8. M8 `0cc5fff4ecf4ecbc3fa4e95b118da990579e09c7`

## 集成补线与决策

- 完成 M6 调用点：delegate 传递 parent conversation ID；Atlas 子会话在请求保留时不删除 SessionDB/MemoryStore 对话；DelegationService 投影保留 `delegation` 元数据。
- 完成 M5 的显式 `memory_open(ref)` 只读工具并保留既有 `memory_search(open=...)` 兼容路径。M2 曾约束不重复注册工具，M5 taskbook 明确要求 `memory_open(ref)`；按用户要求的较强选项注册显式工具，并以相同 `open_ref` 实现避免重复取证逻辑。
- M8 自动候选生成不自动晋升。只有 heldout 明确包含成功与反例、SkillOpt 明确报告安全/正确性 blocker 均为零、严格提升且用户显式审核后，才允许晋升。报告缺少 heldout 成员或 blocker 字段时 fail closed。候选每步要求成功经历来源 ID 和逐字引文；反例/恢复只接受失败或未完成经历。
- 补入 M8 API 候选查看、人工晋升、learned skill 回滚、`/revert` 联动和 SkillManager 刷新。
- 将 M7 `propagate_forget` 接入 `MemoryLibrary.forget_entry`：传递候选派生清单、写墓碑并重写可达 Git 历史；同时清除匹配的外部 learned skill。混合来源技能采取隐私优先策略：撤下整份 live skill 并返回 `skills_needing_rebuild`，不保留可能含已忘记来源的旧版本。原始 Atlas SessionDB 对话和用户外部备份仍按 M7 边界明确列为未覆盖。
- 遗忘派生 Markdown 时跳过独立 YAML frontmatter 分隔符 `---`，避免把通用结构行误当成遗忘内容，导致历史重写无法通过残留文本校验。仅对确实出现在可达历史中的字符串执行重写校验。
- 修正 `test_c1_lifecycle_subtask.py` 过期 fixture：补充 `FixtureConfig.raw` 和 fake model provider API；原测试在 M6 原始分支同样失败，属于 fixture 与当前服务器配置接口不一致。

## 验证

- 整合集成测试：`15 passed, 5 warnings`，范围为 `test_memory_integration_tools.py`、M1 kernel memory recheck、M4 library 和 Atlas 子任务生命周期测试。
- 新增覆盖：工具注册/精确 ref dispatch、子会话保留、heldout 与 blocker fail-closed、晋升必须显式审核、forget 清除候选/外部 live skill 并重写记忆 Git 历史。
- 对所有修改的 Python 文件执行 `py_compile`：通过。
- `git diff --check`：通过。
- warnings 为 Pydantic v2 class Config 与 FastAPI `on_event` 弃用提示；不是本次失败。

## 尚未完成的验收

- M1–M7 的真实 Atlas 对话、重启、模型失败重试、队列水位、真实工具调用与来源打开、M4 七项真实使用门均未在本次集成回归里完成。
- 当前解释器未安装可选依赖 `skillopt_sleep`。M8 的真实候选生成、真实 heldout replay、调用/反馈、晋升/回滚/重启与 forget 后不复现均未执行；即使后续安装依赖，也必须确认 SkillOpt 报告提供实际 heldout ID 和 blocker 字段，否则按当前实现拒绝晋升。
- 用户要求的其他并行 Codex 分支不在此整合分支内；此分支只包含上述 S3 指定波次。

## 最终状态

- 代码与测试整合：完成。
- 真实运行时验收：待执行，不宣称完成。
- 集成提交：`b7965c8126c0edfe587ba74e2ff675f8e1ec63d4`。
- 结果文档提交：`e1f0cf18730fcf9a8b61d8f7c030b3e185ff1a82`，已推送到 `origin/mem-integrate`。

# 任务 09：查明 OpenCode small model 选择规则

请阅读仓库 `source/upstream/opencode` 的 `packages/opencode/src/provider/provider.ts`，用结构化事实说明未显式配置 `small_model` 时，small model 的选择顺序：插件提供的模型与 Azure 特例在哪里生效；OpenCode 和 GitHub Copilot provider 的 family 优先级分别是什么；候选模型如何排序；Amazon Bedrock 的候选有什么区域选择规则？

将答案写为仓库根目录的 `answer.json`，JSON 顶层字段为 `repository`、`commit`、`source_path`、`facts`、`evidence`。`repository` 填 `anomalyco/opencode`；`commit` 填下方 pinned commit；`source_path` 填 `packages/opencode/src/provider/provider.ts`。`facts` 必须包含：字符串 `configured_small_model` 和 `azure_provider_fallback`；布尔值 `plugin_precedes_provider_fallback`；字符串数组 `opencode_family_priority`、`github_copilot_family_priority`、`other_family_priority`、`candidate_sort`、`bedrock_candidate_order`；字符串 `bedrock_region_prefix`。`evidence` 是对象数组，每项含 `path`、整数 `start_line`、整数 `end_line`。

每组事实须引用真实相对路径和覆盖该事实的行号。仓库固定在 anomalyco/opencode commit `1ddb0873aee50d209d1a8d7f91b89c5daf692d49`。若完整仓库暂不可用，可使用 `source/snapshot` 中从真实上游文件逐字复制的离线自测快照；真实 benchmark setup 会准备完整 pinned checkout。

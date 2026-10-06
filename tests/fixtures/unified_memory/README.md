# unified_memory fixtures（仅测试资料，非产品实现）

本目录是 UM00/T00.2 冻结的效果验收资料包（UM-WIN-1.0 契约语境）。**它只是测试
资料，不是产品实现**：manifest 与 seeds 不实现任何记忆功能，不声称任何成绩或
通过率，也不能作为任何"能力已存在"的证据。

## 内容

- `manifest.json` — 320 项冻结核心用例 = 16 域（A–P）× 每域 4 方面 × 每方面 5
  场景。64 方面清单（编号/能力/负责施工任务）逐项照抄
  `docs/plan/UNIFIED-MEMORY/05_acceptance_matrix.md` §2。字段：case_id、
  aspect_id、domain、scenario_kind、seed、aux_seeds、split、input_steps、
  allowed_sources、expected_record_refs、expected_statuses、must_not_recall、
  expected_actions、truth_locator、severity、model_requirement、timeout、
  minimum_evidence。
- `seeds/*.jsonl` — 29 个命名 seed（与 02_wave_tasks.md 公共规则一一一致）。
  每行一个 JSON record：`key` / `meta` / `observations`（01_contracts.md §2
  Observation schema，`content_hash` 为真实 sha256）/ `messages` /
  `tool_receipts` / `ground_truth`。每份 seed 的 ground truth 独立自洽。
  `desktop` / `scale` / `longitudinal` 是定义型数据（交互脚本步骤清单 / 生成器
  参数 / 30 天回顾问题定义），但其 ground_truth 真实可判定。
- 生成脚本：`scripts/unified_memory/gen_manifest.py`（可重复生成；meta 内含
  `cases_sha256` 自校验）。

## 关键规则（照抄 05 §3）

- split：`sha256(case_id)` 前 2 位 hex < 0x40 → `dev`，否则 `holdout`
  （≈25/75；当前 78/242）。
- severity：隔离/删除/副作用相关方面 M03/L03/L04/G02/I03/N01/N02 =
  `critical`，其余 `standard`。
- `expected_record_refs` 用符号引用 `{seed:<name>:<key>}`，不硬编码 UUID。
- **真值不进模型输入**：seed 的 ground_truth 由独立评测器读取，禁止注入检索
  目录、后台整理或候选训练；live 成绩不得取自 fake provider 的预设答案。
- 模板化初版：`input_steps`/`expected_*` 由场景模板生成，**UM13 执行前必须
  逐案人工可判定化**（见 manifest.meta.honesty_note）。

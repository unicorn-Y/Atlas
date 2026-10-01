# ATLAS-W14-FINAL-ACCEPTANCE（第十四波：收尾与总验收）

STATUS: READY（W13 审查通过后）
执行：Luna。审查：Sol。之后由 Claude 按 `docs/plan/FINAL-REVIEW.md` 做最终审查。

## 本波目标

前面各波都是「加能力」，这一波把 Atlas 当成一个完整产品收尾：装得上、跑得稳、文档对、每项能力都能用。不加新功能。

---

## 1. 端到端回归（真实模型，隔离环境）
- 写一套可重复运行的端到端脚本 `core/tests/e2e/`（默认不在全量测试里跑，手动 `pytest -m e2e`）：用真实模型、独立 `ATLAS_DATA_DIR`、去掉 MCP、独立端口、临时目录。
- 覆盖每一波的真机场景（W06–W13 任务书里列的全部），每个场景断言关键事件和文件结果。
- 跑通并把结果（通过 / 失败 / 耗时 / token）写进结果文件。失败的修掉再跑。

## 2. 稳定性与性能
- 长时间运行：连续跑 2 小时混合任务（委派、看板、触发器、浏览器），检查内存、数据库大小、后台进程、文件句柄有没有泄漏。
- 启动时间：后端冷启动到 `/api/health` 正常的时间；Electron 等后端的超时（现在 15 秒，首次启动约 20 秒会失败，见记忆）改成按实际情况等待并显示进度。
- 并发：同时跑 5 个对话的任务不互相影响。
- 把对时机敏感的测试改稳（例如 `test_process_endpoints_read_output_kill_and_404`）。

## 3. 安装包
- `npm --prefix frontend run dist:win` 生成一体化安装包（带冻结的后端和 Node）；新增依赖（sherpa-onnx、cua-driver、agent-browser、Univer 等）都要打进去或首次使用时下载。
- 在一台干净的 Windows（或新用户账户）上：安装 → 首次向导 → 配模型 → 跑一个任务 → 卸载，全程记录截图。
- 升级：旧版本数据目录升级到新版本不丢对话、配置、技能。

## 4. 文档
- `README.md`（中文）：Atlas 是什么、能做什么（按能力分类的清单）、怎么安装、怎么配模型、常见问题。
- `docs/api-protocol` 更新到最终协议版本，列出所有事件和 WS 消息。
- `docs/PARITY.md` 最终版：统计、每项的对标对象和「超过最强」的点。
- `docs/plan/VENDORED.md` 和 `THIRD_PARTY_NOTICES.md` 核对完整。

## 5. 清理
- 删掉不再用的代码和配置（包括旧的 `CODEX-ATLAS-*` 任务书可以移到 `tasks/archive/`）。
- 依赖去重、锁定版本。
- 全量测试、前端四项检查全部通过，没有跳过的失败。

## 6. 交付
结果文件 `tasks/results/ATLAS-W14-FINAL-ACCEPTANCE.result.md`：端到端结果表、稳定性数据、安装包测试记录、文档清单。Sol 审查记录 `tasks/reviews/ATLAS-W14-FINAL-ACCEPTANCE.review.md`。

# ATLAS-W07-ORCHESTRATION 结果

状态：**PARTIAL / 未达到验收**。后端代码已落地并有聚焦测试，但开源代码搬运完整度、六项真机场景和全量测试均未全部满足任务书，不能标记为完成。

## 范围与差异

- 本波只改后端。未改 `frontend/`、`backend-adapter/`、`core/atlas/origin_guard.py` 或 `core/atlas/safety/`；安全审查按用户要求未执行。
- 实现覆盖委派生命周期、并行验收/一次重派、Agent 定义导入、配方派发、Todo/看板 API、MoA 调用及项目 NOTES。协议端点版本改为 1.9。
- 任务书要求将 Hermes 委派、看板等实现完整搬入并适配。本次仅迁移/适配了已核对的局部逻辑和接口，没有完整搬入 H 的 async delegation/lifecycle/toolset 模块（约 3,600 行）、Kanban siblings/watcher/CLI、MoA alternation/trace。上游规则和较大的数据文件未完整复制；这是实质性偏差，不能声称已完成源码等价移植。
- 本机真实模型为 `deepseek-v4.1-flash`，通过已配置的远端网关成功返回 `MODEL_OK`。另一配置的本地端点此前拒绝认证，本波未以该端点作为验收模型。认证信息未写入结果。

## 六项真机场景

| # | 结果 | 证据与限制 |
|---|---|---|
| 1 explore + researcher 并行调查 | 部分 | 模型完成了一次并行委派，但 researcher 获得的工具集不适合本地文件研究，主 Agent 随后走 fallback explore。没有达到“两种角色有效并行调查”的完整验收。 |
| 2 verify 并行组、失败项重派一次 | 部分通过 | `s2_verify_retry_logic` 事件记录两个 worker、两个 verifier、失败项 B 的一次 retry；A 为 `verified=true`、B 为 `verified=false` 且有 verifier note。模型最终叙述与事件有矛盾，另一次强制失败场景超时，因此端到端验收不完整。 |
| 3 后台委派、主 Agent 继续回答、补充要求 | 通过 | `s3_background_steer` 记录 `subtask.started=1`、`subtask.steered=1`、`subtask.background_completed=1`，后台任务完成时主对话已继续。 |
| 4 Claude reviewer 定义 | 通过 | `s4_claude_reviewer` 读取 `.claude/agents/reviewer.md` 并调用 reviewer；记录了只读发现 `app.py:2` 的空列表除零问题。 |
| 5 NOTES 写入并在新对话复用 | 通过 | 隔离新项目中，受信任的 NOTES 写入了 `python -m unittest discover -s tests -v`，结果 1 passed；下一次新对话只说“跑测试”时复用了该命令，1 passed。首次未受信任写入被拒绝，之后按项目规则信任流程重跑。 |
| 6 Kanban 三步依赖任务 | 未通过 | 两次模型尝试均未创建验收用 board 或启动 delegate 子任务；结果摘要中的模型文字声称数据库锁定，但工具记录没有足够的底层输出验证该原因。隔离数据库上的 REST 建板探针成功，不等同于指定模型工作流验收通过。 |

上述真机运行数据位于系统 `%TEMP%\atlas-w07-isolated-e2e`，不在仓库；真实模型接受过 API 调用。模型生成的错误路径断言（声称访问 `D:\Atlas\data\atlas.db`）未作为事实采信。

## 自动化验证

- 聚焦：`core/tests/test_agent.py` 38 passed；`core/tests/test_backend_parity_wave7.py` 11 passed；`core/tests/test_server.py` 中 W07 workspace orchestration 与 runtime protocol 相关用例 8 passed；本次新增配方参数回归 `core/tests/test_agent_recipe_delegation.py` 2 passed。最后两项通过 `--basetemp` 指向系统临时目录运行。`compileall -q core/atlas` 与 `git diff --check` 通过。
- 全量：当时收集 962 项；按测试文件/节点分批运行，累计 **945 passed、9 skipped、8 项未验证**。未验证项为 7 个 APScheduler 集成用例及 `test_hub_process_starts_serves_and_shuts_down`；整套 pytest 进程反复被外部 SIGINT（`KeyboardInterrupt`，退出码 `-1073741510`）打断，不能报告为全量通过。之后增加的 2 个配方回归用例单独通过；它们未纳入上述全量统计。由于已不是一次完整、不中断的全量进程，此汇总用于透明交代覆盖情况，不构成全量 suite 绿灯。
- 测试隔离数据目录放在系统临时目录；没有在仓库中新建测试临时目录，也未使用真实网络作为 pytest 依赖。

## 来源与接口

- Hermes Agent 仓库：`NousResearch/hermes-agent`，核对提交 `330d9d6df9c7bffe125ba0ae64a0abc488a7d2c3`。本波使用范围及文件登记见 `docs/plan/VENDORED.md`；许可证见 `THIRD_PARTY_NOTICES.md`。
- Agent 格式适配参考 Claude Code、GitHub Copilot、OpenCode、OpenHands 与 OpenAI Codex 文档：
  - https://code.claude.com/docs/en/sub-agents
  - https://docs.github.com/en/copilot/reference/custom-agents-configuration
  - https://opencode.ai/v2/docs/agents
  - https://docs.openhands.dev/sdk/guides/agent-file-based
  - https://github.com/openai/codex/blob/main/codex-rs/config/src/config_toml.rs
  - https://github.com/openai/codex/blob/main/codex-rs/agent-roles/src/agent_role_config.rs
- 对任务书接口的偏差：协议 endpoint 由 1.8 升为 1.9；UI 展示、嵌套关系视觉化和界面委派补充要求未交付（前端明确不在本波范围）。其余未确认的接口/字段一致性及未完成的上游复制范围如上，不宣称完全符合。

## 提交与交付

章节提交（按任务书顺序；共享编排内核包含多个后端章节共用的接线）：

| 章节 | 提交 |
|---|---|
| 1 委派内核 | `bceeb2c` |
| 2 Agent 定义 | `e1a6a71` |
| 3 并行验收及回归 | `e96b3a0` |
| 4 配方委派参数回归 | `35e33af` |
| 5 看板与待办 | `2041eff` |
| 6 多模型会诊 | `c6d378d` |
| 7 项目记事本及 API | `a5334fe` |

交付记录文件随后另作一个 handoff commit。`tasks/CURRENT.md` 标记为 PARTIAL。push 与 remote HEAD 核验尚待执行。安全审查留给用户，本波没有执行。

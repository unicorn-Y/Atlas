# ATLAS-C1-HERMES-CORE 独立验收

日期：2026-10-02。角色：独立验收者；施工结果起点为 `main@7697e38`，Hermes fork 起点为 `atlas@562ad75`。产品修复交由 GPT-6 Luna（high）按文件分工完成，验收者审查 diff、独立复测并汇总证据。

**当前结论：验收进行中，不能据此认定整体验收通过。** 最终全量、WebSocket、Windows 源测试和 Edge 证据尚待收齐；下面的阶段结果与最终结果分别记录。安全审查由用户负责，本记录不作安全评价。

## 验收依据与来源规模

已完整阅读 `docs/plan/00-MASTER-PLAN.md`、`CORE-PARITY.md`、`EXECUTION-GUIDE.md`（含 §3.6、§5）、任务书和施工结果。采用外部 Hermes fork 作为完整内核；Atlas 适配层位于 `core/atlas/engine/`，没有把 Hermes 的恢复、压缩等模块改写成缩小的平行实现。

实际安装的 `hermes-agent` 是指向 `D:/hermes-agent` 的 editable 安装；`find_spec('run_agent').origin` 为该 fork 的 `run_agent.py`。按 Git 跟踪的 Python 文件计数：`agent/` 312 文件、129419 行；`tools/` 341 文件、120575 行；`hermes_cli/` 631 文件、253854 行。关键文件 `run_agent.py` 1582 行、`context_compressor.py` 5753 行；恢复的六个模块合计 4156 行。最终 fork 差异及 pin 在最终验证后补入。

## 发现的问题、影响和修法

| 问题 | 影响 | 修法及提交（已推送的 main 提交） |
| --- | --- | --- |
| 测试在 collection 前未隔离用户目录 | 导入阶段可能读取真实 MCP 配置 | `71b64ec` 在 conftest 导入前隔离六个目录及凭据，补 subprocess 回归 |
| 原生文件工具被简化别名替代 | 行号、分页、正则、补丁格式等参数丢失 | `c7a6c5a` 保留 Hermes 原生实现，Atlas 只挂接策略和快照 |
| 自检未挂到新循环 | 改代码后可无验证直接结束 | `8302659` 挂接 Hermes stop gate，真实假模型编辑后要求运行验证 |
| 恢复状态未接通 Atlas | 出错恢复和续写不可见，记录修复缺少接入证据 | `924acd5` 保留原恢复链并发布恢复诊断；SDK 超时、overflow、fallback 和 transcript repair 均补测试 |
| notify/watch/heartbeat 丢失 | 后台命令没有要求的通知 | `4167882`、`e00252d`、`d1ad337` 接入事件、持久通知及下一轮读取 |
| handoff 未通知父级 | 父 Agent 不知道移交进程已结束 | `6afe0a8` 将完成回调接到父级事件和 steer 收件箱 |
| inline/deferred todo 未同步 | 待办显示、压缩后重新注入不一致 | `e991290` 同步 Atlas 与 Hermes todo 状态 |
| 原生写操作未进入 Atlas 检查点，错误结果误报成功 | 撤回不能恢复文件；界面无法识别工具失败 | `bacab1e`、`8918fc4`、`2cbb89d` 接入写前快照和原生错误语义 |
| 原生 inline delegate 绕开 Atlas 生命周期 | 子 Agent 上下文、工具权限及清理没有统一约束 | `3ff199a`、`58e05ce`、`76a19cb`、`d40bd58` 使用 Atlas 委派、父级权限交集及退出清理 |
| 并行运行修改共享模型选择 | 两个 run 的模型身份可能串扰 | `cb4b8ea` 对每个 run 固定模型快照 |
| 自动标题只做了生成，没有完整发布链 | 迟到标题无法进入 Memory/UI，或覆盖手动标题 | `4a339f6`、`e5da90f`、`2610a41` 绑定回调、持久化与事件；补手动标题优先测试 |
| 图片附件未进入 Hermes 请求 | 新内核对图像附件丢失输入 | `c0de77d` 传递实际多模态内容，假 HTTP 请求检查图片字段 |
| 旧工具 shell/process 参数和输出语义退化 | shell 选择、分页、输出流、stdin 等行为改变 | `1adb4f5` 保留旧行为；T19 逐动作证据另列 |
| V4A Move to 目标路径未检查 | 指定范围的工具行为不一致 | `8918fc4` 对源和目标同时执行既有 allowed_paths 契约，补恢复/拒绝测试；不作安全审查评价 |
| UTF-16 patch/write 编码损坏，采样可能截断 surrogate pair | Windows 文件 BOM、非 ASCII 字符和 CRLF 无法保留 | fork `7f167dd`、`f6f8a84` 保留 UTF-16 LE/BE；采样层处理边界，完整内容解码保持严格 |
| 默认 terminal cwd 变为服务启动目录 | 相对命令在错误目录执行 | `75f630c` 绑定 run workspace，保留显式 cwd 和 SSH 远端路径；独立复测通过 |
| 看板同步 SQLite 操作阻塞 asyncio | MemoryStore 未能释放写锁，看板工具返回 database is locked | `f10ec5c` 将板/卡 SQLite 操作移到线程；同库竞争回归及独立复测通过 |
| direct local_exec/process 绕过 registry 的 cwd 默认值 | 旧入口仍可能使用错误目录 | `049c207` 补 Agent 调用点；独立运行 3 passed |
| 完整文件读取偶发记为 partial | 已完整读取后仍拒绝 write，UTF BOM 和普通文本均可触发 | 已定位 Windows stat/fstat ctime 差异；修复及最终验证待补 |

检查点的原回归只验证恢复到旧内容，没有先断言写入成功，属于假阳性。验收者加强为读、写、确认已改变、再恢复的真实文件断言；该加强暴露了最后一项读取基线问题。

## CORE-PARITY C1 逐行核对

C1 共 **36 行**，包括 `X1` 的“C1，C2 打磨”。下表列出实现和验收证据；最终结果待所有统一检查结束后更新。

| 行 | 已核对的实现/证据 | 状态 |
| --- | --- | --- |
| L1 | Hermes iteration_budget；真实 WebSocket 超过 10 轮 terminal | 最终复测待收齐 |
| L2 | 原 turn_recovery/API error/empty/truncation/overflow/transcript 模块；C1 recovery、SDK timeout、overflow/fallback 用例 | 已补接入，待最终全量 |
| L4 | verification_stop/turn_stop_gates；编辑后实际执行验证命令 | 已补接入，待最终全量 |
| L5 | Hermes tool_executor 并行机制；Atlas 并行子任务独立上下文 | 并行工具与并行子任务分别核对，待最终汇总 |
| L7 | Hermes steer/Atlas queue；两条插话真实进入下一轮请求，运行中取消 | 最终 WS 待收齐 |
| L10 | prompt/env_probe；Atlas workspace、SSH 环境传入 | 默认 cwd 已修，待最终汇总 |
| T1 | 原 read_file 行号/offset/limit、截断续读 | 原实现保留，待最终源测试 |
| T2 | 原文档解析；实际 DOCX/XLSX/PPTX 文件读取 | 最终 WS 待收齐；不声称全部格式均实测 |
| T4 | file_state/write_guards；未读、部分读、外部变更拒绝；写前检查点 | 完整读误判仍在修复 |
| T6 | LF/CRLF、UTF-8 BOM/UTF-16 LE/BE 实际文件字节 | fork 编码已修，最终串联 WS 待收齐 |
| T7 | 原 patch 模型格式适配、V4A Move to | 目标路径检查已补；最终源测试待收齐 |
| T9 | 原 ripgrep 正则/过滤/输出模式/分页，保留参数 | 待最终源测试 |
| T10 | 前后台、notify/watch/heartbeat、事件和 durable notice | 已补，待最终全量/截图 |
| T11 | stdin/submit/close、Windows PTY、handoff 父级通知 | 已补，待最终全量 |
| T12 | PowerShell/Git Bash 选择及无 Bash fallback | 已补兼容回归，待最终全量 |
| T13 | Atlas web_search/web_extract registry | 假服务及既有测试；未进行真实外网验收 |
| T14 | eager/deferred todo 同步及压缩后活跃待办重新注入 | 最终真实压缩 WS 待收齐 |
| T15 | clarify 与 Atlas 回调、审批输入 | 最终 WS 待收齐 |
| T16 | execute_code 仍路由至 Atlas handler | 既有回归及映射；待最终全量 |
| T17 | 原 tool_search/tool_call 按需加载 | deferred inner ACL/真实 MCP 路径；最终 WS 待收齐 |
| T18 | 原 tool_result_storage/truncate；落盘文件可实际续读 | 定向回归，待最终全量 |
| T19 | 31 个静态工具定义及各 action；直接入口与等价原生工具分别检查 | 逐动作表待补 |
| X1 | 原 5753 行 compressor，规则修剪及辅助模型总结 | 最终真实自动压缩 WS 待收齐 |
| X2 | focus topic/manual compression 接口 | 定向回归，待最终全量 |
| X3 | 原分层提示词，动态 Atlas 内容按会话开始注入 | 既有前缀回归，待最终全量 |
| X4 | 原 provider cache/prompt_cache_scope | 假请求/既有缓存测试，不声称真实供应商计费验证 |
| X6 | AGENTS.md、CLAUDE.md、.atlas/rules.md | 路径和规则载入回归，待最终全量 |
| X8 | 实际 usage 与上下文上限事件 | 假服务及前端回归，待最终统一检查 |
| X9 | 原 SessionDB 完整工具历史与 Atlas 消息同步 | 真实多轮和重启/恢复回归，最终 WS 待收齐 |
| S1 | transcript repair + SessionDB resume | 缺失工具结果修复定向回归，待最终全量 |
| S4 | Hermes title generator 到 Memory、事件和 UI | 迟到/手动标题定向回归，待最终全量 |
| S5 | 原 FTS session_search 与 Atlas inline/deferred 入口 | 已核对映射/回归，待最终全量 |
| A1 | Atlas 生命周期、独立 child session、父权限交集、pause/cancel/fail 清理 | 已补，最终并行 WS 待收齐 |
| E1 | Hermes MCP，独立假 stdio server，无真实用户 MCP | 最终 WS 待收齐；HTTP/OAuth 无真实远端实测 |
| M3 | fallback model 身份与实际请求 | SDK/fake HTTP 回归，待最终全量 |
| M4 | Atlas effort 传入原 reasoning_params | effort 有证据；其他供应商参数未逐一真实验证 |

## CORE-PARITY 第 11 节回归范围

运行事件/断线续传；插话/队列/暂停继续/取消；审批/clarify/信任；检查点/rewind/redo/diff；plan/Goal/side/recipes/Specs；子任务/并行/看板/项目笔记/项目检索；SSH/worktree/额外目录/限定目录；Hooks/脚本/MCP/skills；usage/cache/输出上限/fallback；外部 Claude Code/Codex backend。逐条最终结果及测试文件待统一测试后补入。

## 测试证据与隔离边界

独立初始全量（按指南排除整个 `tests/test_computer_use.py`，避免驱动主机鼠标）：**1 failed, 979 passed, 9 skipped, 1 warning in 236.31s**。失败是 scheduler default 断言受隔离 runner 的强制关闭配置影响，已用 `fb0dc6e` 清除该测试的覆盖变量。

第一次独立真实 WebSocket 验收：**14 failed, 9 passed in 348.15s**。其中审批字段、板卡 API 包装、子任务必填 title、假模型 provider 前缀、压缩窗口下限、MCP auto_start/deferred 调用等为验收夹具问题，已经修正；工作目录、看板锁、文件读取基线属于产品问题，上表记录修复。不能把夹具修正后的未运行状态计为通过。

原施工结果记录 **21 failed, 279 passed, 14 skipped in 94.48s**，只给出 `%TEMP%/atlas-c1-hermes-source-20261001/`。用户确认该目录和原始用例清单均已不存在。按用户最新指示，以当前 fork 相同选择集的独立重跑为准逐项判定，不尝试捏造历史 21 项对应关系。独立初始当前选择集：**10 failed, 544 passed, 5 skipped in 53.72s**；最终同集重跑及每个失败理由待补。

隔离环境为独立 HOME、USERPROFILE、APPDATA、LOCALAPPDATA、HERMES_HOME、ATLAS_DATA_DIR，另外隔离 TEMP/TMP/TMPDIR、清除真实凭据及代理。后端动态独立端口且明确排除 8765，假模型全部使用 localhost；默认去掉 MCP，MCP 场景只加入单独假 stdio 服务。后端启动 cwd 与任务 workspace 都是不同的假目录。

必须如实记录两次隔离偏差：

1. 子代理曾误执行 fork `scripts/run_tests.sh`，未带完整隔离 home。脚本进入主机 Hermes 工具缓存的 install lock 等待，约 33 秒后中断，尚未进入 pytest。不能据此证明脚本没有读取/写入其它缓存；后续全部改用隔离 Python runner，不接触锁持有者。
2. 第一次 WS 的后端 cwd 是 `D:/Atlas/core`，默认 cwd 缺陷导致相对命令在那里执行，误建 `core/actions.txt`（内容 ` second`）、空 `core/action-dir` 和 `acceptance-branch`。已核实为本轮创建后仅删除这些文件/空目录/分支；实际 git add/commit/push/fetch/pull 用例没有成功。没有触碰 8765 服务，`design/` 未动。后续后端启动也改成假目录，并在每个文件/Git命令执行前断言假 workspace/Git remote。

`.playwright-cli/` 是本地截图工具生成目录，`core/uv.lock` 是本地依赖解析产物，不作为源码提交；`b9e4493` 增加精确忽略规则。保留用户原有 `design/`。

最终 Atlas 全量汇总、Hermes Windows 每项判断、前端四项检查、Edge 对话/改动/终端截图、最终 Git 一致性及临时工作树清理：待收齐后更新本记录。

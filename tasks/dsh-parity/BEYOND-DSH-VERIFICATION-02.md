# 上下文投影批次：监督检查点

日期：2026-11-16。生产实施仍由 Codex Desktop GPT-6 Luna 高完成，主控通过本机 CDP 观察和 steer；本回执不代表本批验收通过。

## 首次真实多轮尝试

实施端命令：

```text
python scripts/omni_multiturn.py --turns 3 --only atlas --port 8914 --out ..\tasks\dsh-parity\MULTITURN-CONTEXT-FIX-3.md
```

主控在原桌面会话直接观察到命令结束及实施端报告：180 秒内未收到终态，命令退出码 1；后端启动/关停正常。该次没有可用模型结论，不计为三轮通过或性能数据。主控未独立重跑该命令；没有保存事件类别的旧尝试不能倒推其精确原因，也不能确定是否真正发出模型请求。

## 已确认的接收路径与待确认的等待点

- `core/atlas/api/runtime_ws_router.py` 约 64–66 行的服务端 envelope 使用顶层 `event` / `data`；基准脚本读取这两个字段，与协议相符。
- `omni_multiturn.py` 该次指定真实仓库工作目录，而数据根为全新隔离根。`run_drive.py` 约 2405–2419 行在存在未信任工作目录规则时发出 `rules.trust_required` 并等待 `trust_future`。脚本当时未处理该等待事件。这是源码支持的候选原因，尚无该次事件记录证明实际走到此分支。
- 已通过 CDP 给实施端反馈：记录无正文的事件/阶段计数和首个等待类别；`protocol.error`、信任、审批和输入等待应有界失败并留报告；使用整轮绝对 deadline；下一次先短探针。ONE/TWO/THREE 可使用本次临时根内空 workspace，保持生产信任闸开启，对测时核对两侧工作目录条件。

## 短探针的已确认失败类别

实施端更新后的 `MULTITURN-WAIT-PROBE.md` 已保存新探针结果，主控读取文件并通过桌面观察确认：

```text
terminal=run.failed
first_waiting_type=none
failure_category=authentication
events={rules.loaded:1, run.context.sources:2, run.started:1, run.status:3,
        run.phase:1, session.title:1, run.failed:1}
child exit=0; forced_termination=False; graceful_lifespan=True
startup=complete; shutdown=complete; errors=4; last_error_type=CancelledError
```

该新探针的失败类别已确认是 authentication；最后一个日志异常类型不等于认证根因。未取得有效模型答案或 usage。旧 180 秒运行没有事件证据，仍不能将新探针归因回填到旧运行。下一步只核对既有获准路由及隔离进程凭据来源，不切换模型/账号/网关；若外部权限阻塞则记录并继续可执行工程。

## 投影修复的剩余验收门

此前一条 synthetic 测试的通过仅证明手工历史下的最终 wire 投影，不证明真实非 ephemeral kernel 自动保存审计。以下仍需实际实现及验证：

1. 当前 user 使用本轮身份定位；相同文本新轮和展开后的多模态消息不能误匹配旧 user，不能被最近三条文本去重吞掉。
2. 非 ephemeral kernel 实际执行后读取自动保存的审计 metadata，测试不得手工伪造 kernel 输出。
3. 区分过期时钟/权限/技能/项目快照与仍有用的召回事实、来源引用、持续约束；覆盖仅在旧动态区提供的事实在次轮仍可用。
4. 核对附件、tool 配对和 fork/replay/compact 路径。
5. 历史 user 从含动态块变为裸文会改变请求前缀。记录实际公共前缀、cached/uncached usage、耗时和费用；缺字段标 unknown，不以总 token 变小宣称缓存改善。

## 本批首次独立定向回归

主控于 2026-11-16 独立运行当时磁盘版本：

```text
python -m pytest tests/test_kernel_volatile_context_projection.py -q -p no:cacheprovider --basetemp=<本次唯一 atlas-context-supervisor 临时目录>
2 passed, 5 warnings in 5.22s
INDEPENDENT_EXIT_CODE=0
```

Python：`C:/Users/25011/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe`；工作目录 `D:/Atlas/core`。两个测试实际执行，子进程自然退出。warning 为已有 FastAPI on_event / Pydantic Config 弃用。

本次覆盖四轮非 ephemeral kernel + 本地 FakeLLMServer，读取 kernel 自动保存的四条 user 审计记录，末两轮相同文本仍各自保留；最终 wire 保留旧召回事实/引用/hook 约束和附件，并只保留最新时钟、权限、技能索引。另有同文多模态消息当前块按 run 身份定位的 helper 回归。

此结果不是远端真实模型测试，也未证明 fork/replay/compact、所有来源分类、上下文有界增长或缓存收益。独立 focused 静态审查随后返回 needs-fix，见下节。

## 新四项边界测试独立复跑

后续补丁新增 Project 状态/资料分源、原始 user / steer 的独立 `kernel_message_id`、压缩快照中的历史投影状态。主控独立复跑当前四项：

```text
python -m pytest tests/test_kernel_volatile_context_projection.py -q -p no:cacheprovider --basetemp=<本次唯一 atlas-context-boundary-supervisor 临时目录>
4 passed, 5 warnings in 5.41s
INDEPENDENT_EXIT_CODE=0
```

子进程自然退出。新增覆盖：真实 SessionDB compaction publish/restore 保存历史事实投影、当前 tail 正文恢复后 ref 仍可重新投影；legacy 多段计划归属 helper。该测试手工调用发布接口并显式传 snapshot_state，尚不证明 kernel 自动 compaction 的所有调用点或 fork/steer live 全链。原五项正由同一审查者定点复核，未收到结果前不算关闭。

## 确定性身份与项目分源受影响回归

本轮补丁进一步移除当前 user 未找到时回退到尾部 user 的逻辑，新增同 run steer 独立身份断言，并更新项目上下文测试。主控独立执行：

```text
python -m pytest tests/test_kernel_volatile_context_projection.py tests/test_projects.py tests/test_prompt_cache_boundary.py -q -p no:cacheprovider --basetemp=<本次唯一 atlas-context-project-supervisor 临时目录>
13 passed, 5 warnings in 6.64s
INDEPENDENT_EXIT_CODE=0
```

子进程自然退出。此为三个受影响文件的定向测试，不是整库测试、自动 kernel compaction 全链或远端模型实测。定点静态复核结果尚待返回。

## 新增 fork/replay 与持久压缩边界独立回归

```text
python -m pytest tests/test_kernel_volatile_context_projection.py::test_context_audit_metadata_survives_replay_and_fork tests/test_w3_session_compaction.py::test_compaction_bracket_and_rebuildable_summary_are_durable -q -p no:cacheprovider --basetemp=<本次唯一 atlas-context-fork-supervisor 临时目录>
2 passed, 5 warnings in 3.05s
INDEPENDENT_EXIT_CODE=0
```

子进程自然退出。本项增量检查 fork/replay 审计 metadata 和既有 SessionDB 压缩持久化接口，不等于真实模型全链。

## 后续稳定截点独立验证

生产方修正 current-project 前缀、legacy hook 边界、canonical 旧身份重绑及 snapshot builder 契约后，主控独立运行：

```text
python -m pytest tests/test_kernel_volatile_context_projection.py tests/test_projects.py tests/test_w3_session_compaction.py -q -p no:cacheprovider --basetemp=<本次唯一 atlas-context-checkpoint-supervisor 临时目录>
20 passed, 5 warnings in 7.73s
INDEPENDENT_EXIT_CODE=0
```

子进程自然退出。新增测试调用真实 `_compaction_snapshot_state` → SessionDB publish/restore；原先不合法旧诊断字段 fixture 已对齐生产白名单。尚未覆盖 kernel 自动压缩模型回合或 live steer。

待补：摘要正文中保留 ref 仅证明引用可搜，不足以证明超预算裁剪的事实正文可由模型工具读回。已要求以实际受会话/workspace 权限约束的工具 dispatch 验证正文恢复及越权拒绝。该项仍在实施，不能将本截点标为全批通过。

## 审计读取处理器独立回归

```text
python -m pytest tests/test_kernel_session_query_dispatch.py -q -p no:cacheprovider --basetemp=<本次唯一 atlas-audit-supervisor 临时目录>
7 passed, 5 warnings in 3.12s
INDEPENDENT_EXIT_CODE=0
```

子进程自然退出。此截点覆盖新增 context search/read 的实际共享处理器、原事实正文检索、长段字符续读、单次正文 10,000 字符预算和跨 workspace 拒绝。测试尚通过共享 dispatch_session_query 调用，不等于已执行 AtlasKernel._dispatch；实施端正补实际 kernel 工具入口回归。

## 实际 kernel 审计工具链独立验证

```text
python -m pytest tests/test_kernel_session_query_dispatch.py::test_fake_provider_drives_kernel_context_search_and_workspace_denial -q -p no:cacheprovider --basetemp=<本次唯一 atlas-audit-kernel-supervisor 临时目录>
1 passed, 5 warnings in 4.92s
INDEPENDENT_EXIT_CODE=0
```

子进程自然退出。本地 FakeLLMServer 实际驱动 AtlasRuntime，通过工具 schema、kernel dispatch 和工具结果回传，验证审计事实正文可达且跨工作区被拒绝；与前述共享处理器分页 7 项结合形成限定范围证据。远端真实模型认证仍阻塞，自动模型压缩、live steer 和性能优势仍未证明。新审计读取路径仅做一次有界最终静态检查，实施端继续 X6，不追加全库审计。

## 审计工具最终两项修复独立回归

最终窄范围检查发现同 workspace 私有 worker source 可见性与 limit 恰好填满时的搜索 cursor 缺口；生产方已分别加入 source/delegate 可见性门与后续匹配探测。主控独立执行：

```text
python -m pytest tests/test_kernel_session_query_dispatch.py::test_context_audit_dispatch_hides_private_worker_from_same_workspace tests/test_kernel_session_query_dispatch.py::test_context_search_limit_cursor_continues_to_second_user_without_duplicates -q -p no:cacheprovider --basetemp=<本次唯一 atlas-audit-final-supervisor 临时目录>
2 passed, 5 warnings in 3.03s
INDEPENDENT_EXIT_CODE=0
```

子进程自然退出。新查询私有 worker 仅自身可读，普通会话不可因同 cwd 越权；两条各一匹配的 user 在 limit=1 时可顺序续读、无重复。当前上下文增量冻结，后续转 X6；远端模型认证、自动模型压缩和 live steer 仍未完成验收，不给超越结论。早期 needs-fix 各段为历史截点，不应当作当前未修清单。

## 原问题第二次定点复核：仍需修正

同一审查者限定原五项，未跑测试或模型，已停止检索并通过 CDP 交实施端稳定修复：

- Compaction：事实投影已加入，但实际 kernel publisher 还传 provider/model/before_tokens/after_tokens/policy，snapshot state 白名单未接纳这些真实字段，restore 会拒绝实际产物。属于既存契约不一致，本批需闭环，不能记为本次新引入。helper 测试只手工传 projection，未覆盖实际生产 payload。
- Project：来源已拆分，但新前缀 `Current project state (refreshed each turn):` 未列入 current-only 分类，旧状态仍会保留。
- 身份：新写记录的稳定 run_id:user、独立 steer ID 和五处图像回填静态 PASS；旧记录 local setdefault 的别名在 canonical reread 后丢失，仍有 legacy 恢复边界。
- Legacy：原空行计划症状已修，但可信来源列表漏 InstructionsLoaded hook，clock+hook 可能整块判当前态而丢 hook 事实。
- 有界投影：已有预算和历史标签，但裁剪后内容只留 metadata，现有 content-only 搜索无法检索；current 文本去重又针对全部 historical，可能吞掉因历史预算未投射的同文本轮事实。

这些结果不否定已观察到的定向测试通过，但说明它们不足以证明实际全调用链正确。不得把该截点记为批次完成。

## 新分段补丁首次独立静态审查：needs-fix

限定实际 diff 与直接调用点；未改文件、未跑模型。3 major / 2 minor，已通过 CDP 提交实施端，以下为该截点未修快照，不代表后续补丁状态：

- Major：历史事实只临时合并入当前 user，旧轮被 compaction、当前 user 作为 tail 保留时，摘要输入缺事实，发布又恢复 tail 原正文及本轮 metadata，恢复后独有 ref 消失。纯函数复现 `fact_before=True; fact_after=False; tail_count=1`。需要压缩事务内显式保留事实/ref 并验证恢复。
- Major：`Project context` 含 active project/status/goal/workspace/last state，但分类默认永久保留，旧新项目状态并列。应在来源处区分状态快照和资料/事实，刷新状态、保留必要事实。
- Major：`accept_steer` 的 user 使用同一 `kernel_run_id`，当前反查会命中 steer；循环内若干图像回填仍按文本定位。同 run 同文 steer 会收到原始消息图片及 context。需要原始 user 唯一消息身份贯通所有回填位置。
- Minor：legacy 按任意空行拆段会将旧计划标题和正文拆开，正文误判未知事实。需要可信来源边界归属。
- Minor：unknown/hook/recall 按整段精确去重后集中搬入当前 user，仍可能线性增长，且没有历史来源标签。需历史 run/时间标签、稳定 ref 去重及有界投影，溢出内容保留可检索审计路径。

审查未发现该 diff 新增权限放松或 provider 未知字段透传；fork 直接 clone 路径未见主动剥除 metadata，但未运行 fork/replay 全链路，不能据此算通过。

本回执仅落监督检查点；最终结果继续写实施进度和新实测报告。没有 Atlas 全面对齐或超越 DSH 的结论。

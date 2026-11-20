# X30 同 authority 执行世界：有界静态核对

日期：2026-11-16。固定 DSH commit d743267388641bc76f17c45ce8b4c231aed1d32c。依据独立只读架构核对；未运行网络、模型、远端命令或测试，未改生产代码。生产实施仍由原 Codex Desktop GPT-6 Luna 高负责。本地图不构成 CLOSED 或可用性证据。

## 已有与缺口

Atlas 已有 SSHEnvironment（core/atlas/engine/tools/environments/ssh.py:45）及 core/atlas/ssh.py 的连接池、SFTP、文件/edit/Git/shell/exec/checkpoint；run_drive.py:3734 附近实际向 orchestrator 传入代理。子任务已有 SSH callbacks 继承，不应宣称原语或全部子任务路径不存在。

真实缺口是受管 process/PTY、LSP、桌面终端、sandbox 与文件共享 authority、canonical cwd、远端平台、权限和 owner/cancel 域。

| Atlas 生产入口 | 静态事实与后续落点 |
|---|---|
| core/atlas/ssh.py:66 | URI 解析只返回 hostname/path，显式 port 需明确支持或拒绝；统一 alias/user/key 身份。:153 词法 containment 不能证明远端 symlink 目标安全。:317 唯一旧串匹配不是并发版本守卫。:126 传输失败重试整条命令可能重复副作用，提交后丢回执需 unknown 或可查 operation identity。:106 reaper 对长跑 LSP/PTY 需活动租约。 |
| core/atlas/api/run_drive.py:3734 | callback 捕获父 workspace/run id，需 world/owner/cancel 接线；:2153 Docker+SSH、:2591 外部 executor+SSH 的显式拒绝应在支持并验证前保留。 |
| core/atlas/agent/tool_node.py:1751 | 五类工具有SSH分流；:234 local_process 仍走本机 cwd，:236 完整 ssh URI 可能传入只接受远端路径的实现。子任务已有继承(:186/:1111)，应继承 world 并分配 child owner。 |
| core/atlas/engine/kernel/loop.py:1347 | 受管执行派发 local_process；:3682 LSP 调用本地 query_lsp。需交同一 world，扩白名单不够。 |
| core/atlas/engine/kernel/exec.py:497 | 可复用 handle/轮询/stdin/后台/输出管理；:532 本机日志读取需改为 authority-bound 输出接口。 |
| core/atlas/tools/local_execution.py:1760 | 当前为 local provider 的本机 Path/spawn/winpty；:2218 本机 PID/进程组取消不得处理远端 handle。 |
| core/atlas/lsp/manager.py:609 | binary/root/client 池为本地语义；:96 trusted multi-root 合池需至少按 authority/信任域分离。 |
| core/atlas/lsp/client.py:252 | stdio本机spawn；:584 本机读文件；:80 本机OS生成URI。远端接入需同时注入process/fs/URI，单换spawn不够。 |
| core/atlas/api/tools_router.py:125 | /ws/terminal 直接本机PowerShell/winpty；应消费同world PTY输入/resize/信号/清理。 |

行号为本截点，后续实现可能移动；关键词仅用于定位，结论来自对应实现和调用者。

## DSH 对照

- packages/ssh/fs-ssh/src/index.ts:25 resolve；:82 expected version/写入意图/cancel/sandbox policy。
- packages/ssh/subprocess-ssh/src/index.ts:114 prepare/start/流；:157 terminate确认；:293 PTY写入/resize/前台信号/清理。
- packages/ssh/sandbox-ssh/src/index.ts:13 远端 confinement。
- packages/lsp/lsp-stdio/src/index.ts:146 同世界fs/process；packages/terminal/terminal-bash/src/index.ts:202 policy/process。

功能等价不要求照搬DSH私有helper线协议。

## 建议实施与验证边界

首选保留Python/asyncssh，用小型world接口携带authority、远端平台、canonical workspace、fs、process/PTY、sandbox policy及资源所有权；依次接身份/失败语义、受管进程、LSP、桌面终端/child。继续沿现有架构，不引入旁路未接服务。

- 条件写入需真实远端目标/版本拒写与原子提交；路径检查不冒充进程confinement，不能执行请求策略时拒绝。
- 取消要确认远端退出/清理，取消Python await不等于完成；副作用命令不盲重试；断连未知单列。
- child继承同authority与收紧权限，但分离owner/cancel域；共享连接不等于共享资源所有权。
- 零网络验证可注入内存fs/transport，从真实kernel触发file/exec/process/LSP，断言不调用本机spawn/kill；覆盖跨authority同路径、完整URI cwd、symlink、stale write、sandbox拒绝、丢回执、reaper与child取消。
- 可用loopback临时SSH服务器/临时host key，无需真实凭据。现有 core/tests/test_ssh_execution_world.py:44 fixture 覆写_connect(:84)，不证明生产alias/host-key/连接池。后续应以隔离配置走真实_connect；不能用known_hosts=None当认证边界通过。

静态调用链置信度high；改造成本及跨平台清理方案medium。需实施与真实验证后才可收口。

# X5/X7 安装操作：有界审查截点

2026-11-16，生产实施由原Codex Desktop GPT-6 Luna 高执行。独立只读审查，仅AST抽取内存复现，无网络/真实安装/服务/模型；以下是施工截点，修复前不关闭X5/X7。

已另行修复并通过主控独立2项回归的目录交换失败备份丢失、stale approval不重复计入。

1. **major：审批前pnpmfile代码执行。** runtime.py:547 install --ignore-scripts不禁用pnpmfile；stage完整复制源目录，.pnpmfile.cjs/.mjs可在审批前require/import执行，且继承backend环境。需由宿主禁用pnpmfile/config-dependency hooks并控制配置执行策略。回归：可信离线fixture带顶层写marker hook，无任何审批时marker不存在；不以--ignore-scripts单独证明不执行代码。
2. **major：退出等待不在总期限。** runtime.py:474 600秒只覆盖输出/取消竞争；stdout先EOF之后无期限process.wait，worker不再监听取消，可占事务锁并卡shutdown。内存复现确认仍等待。用同一deadline覆盖read/exit/termination cleanup；回归stdout立即EOF、wait被Event阻塞，短期限后应终止并结束。
3. **major：取消状态竞争与过早终态。** runtime.py:381先await终止，worker可能先cancelled+done，cancel随后覆盖为cancelling。worker又在finally清理前发布终态，:393 close按status过滤可能漏掉尚在清理的task并清空表。两路径已内存复现。先发布取消意图，不覆盖终态；清理完成才发布终态；shutdown按task完成状态drain。
4. **major：锁未覆盖旧变更入口。** runtime.py:499新worker锁未覆盖install-local/update/uninstall等。新安装等待审批时旧DELETE可先成功，批准后安装复活已卸载插件；目录/state提交也可竞争。统一runtime mutation锁或明确冲突拒绝；回归卡住安装，通过真实router卸载同名插件，不得先成功后复活。
5. **major：首次响应丢失无恢复身份。** ConsolePage.tsx:465-467只有POST成功才取得/保存服务端requestId，runtime.py:341仅生成新ID。请求已入队但回执断线时无法查询/取消，重试重复安装。请求前生成持久客户端ID；服务端按ID幂等启动/恢复并校验同ID参数一致。回归POST已创建后模拟断线、重挂载/重试，只保留同一任务。

重启unknown分支未发现误报成功；未发现新配置原值返回路径。真实pnpm ignored-builds/rebuild仍需实际验证，模拟输出不算通过。

## 独立类型检查

安装面板接线后的TypeScript renderer noEmit退出0；不是组件或真实浏览器证据。

## 原五项限定复核（仍施工）

1项已修、4项部分修复，未跑真实安装/测试：

- hooks：--ignore-pnpmfile及env/userconfig隔离已修原路径；当前install不带--ignore-scripts，源pnpm-workspace.yaml仍可用allowBuilds自行批准，须host控制workspace执行策略。真实marker应写固定临时路径，不依赖被隔离掉的ATLAS_*环境。
- deadline：文件输出捕获/exit_task已覆盖stdout EOF漏洞；Windows taskkill的killer.wait仍无deadline。应补永不返回taskkill桩的短期限回归。
- cancel/drain：先发布cancelling、清理后终态+done、按task.done drain已封住原竞态；仍需Event卡清理的精准时序回归。
- mutation：当前仅idle检查持锁，旧uninstall通过检查后暂停、新install取得claim、旧uninstall再继续，可两者成功。新旧入口需原子取得并持有同一target变更权，测试反向顺序。
- unknown：同runtime客户端ID幂等已接；localStorage pending保留，GET unknown自动POST，重启丢内存表后会重装。持久幂等记录或runtime epoch区别丢回执与跨重启未知；真unknown不自动重提。补同runtime丢回执仅一worker、新runtime unknown无POST两项。

此为历史截点，不把未来修复预记通过。

## 原项后续复核与完整入口边界

原deadline/取消/drain/旧API瞬时检查已由当前guard/deadline封住，不重复开项。真实长路径marker链另见VERIFICATION-04独立通过，但仍有以下限定残留：

- **major安全**：runtime.py:712附近safe workspace采用字段删除，遗漏dangerouslyAllowAllBuilds（workspace/package pnpm均可能），install未带ignore-scripts，源仍可自批依赖构建。应host首次构建策略强制定值/白名单；真实fixture加该字段验证审批前无marker。
- **major首次响应竞争**：ConsolePage.tsx:471设置requestId即启动poll，但后端plugins_router.py:148仍await validate_source，GET可能先unknown；UI清存储/ID，POST成功只更新operation不恢复ID，导致正在执行任务失去wait/cancel入口。补延迟POST+GET先unknown→POST成功用例；创建未决期间unknown不作最终结论。
- **范围未完成**：runtime.install只有local/Git/GitHub分支，npm包名@版本不支持，scoped spec可能误识别GitHub；registry参数只用于本地插件依赖。Git走legacy_install同步旧路径，审批/依赖事务未接且取消too_late；marketplace独立API仍复制无requestId/wait/cancel。必须继续统一真实包安装任务链，不能将当前本地目录依赖增量称X5/X7全能力。

只读静态复核，未对新残留运行测试/安装。

## 统一来源主体写入后的限定审查

新增4项入口主控独立通过见VERIFICATION-04；未作最终验收。三项major：

1. Git repo slug作为source_record.plugin_name/提交/discover身份，但_effective_manifest对无market overlay直接返回manifest名；repo-a / plugin-b且带命令/MCP时重装会和自身冲突。需validation/冲突排除/commit/load同身份；不同名fixture连续装两次回归。
2. _copy_replace(stage, prepared)看不到真实旧target patch；随后旧target→backup，成功删除backup导致patch丢失。需从旧target carry_over到prepared并reapply再交换；回归任务升级后patch清单/内容仍在且revert恢复新版上游。
3. 首次无旧target，交换成功后save_state/on_complete异常，backup不存在，rollback未删除新target，failed但discover仍发现插件。Git还可能部署指向已回滚checkout。需committed且无backup时删除新增target/相关enabled/source；回归固定refresh失败后target/checkout/source/discover均无新增。

限定路径未发现npm身份同类问题，npm pack带ignore-scripts和显式registry；commit前有cancel检查，旧checkout备份恢复分支存在。只读无测试/网络，待Luna生产修复与独立回归。


# Codex 桌面端 CDP 派工核验

日期：2026-11-15。此文件为主控观察记录，不是能力对齐完成报告。

## 已直接观察

- 用户指定：Codex 桌面端 6 Luna 实施，改用 CDP。用户另行批准重启一次 Codex 并开启仅本机 CDP。
- 已通过有界重启开启 `127.0.0.1:9222`，监听地址确认为 `127.0.0.1`，不是公网地址。未更改模型、账号、权限档或购买/重置额度。
- 连接目标经 `/json/list` 确认是 `app://-/index.html` 的 Codex 桌面页面。已通过 Playwright 的 CDP 客户端读取 DOM 与操作真实会话；未以 CLI 模型调用替代桌面执行。
- 项目 Atlas，分支 wave3；实际模型控件为 `6 Luna High`。新任务提交于桌面会话“完成 DSH parity 六批任务”（2026-11-15 17:53，本机时间）；完整新任务明确覆盖旧六批的范围限制。
- Luna 已收到并读取 `BEYOND-DSH-CODEX-MANDATE.md`，返回真实目录 `D:\Atlas`、分支 `wave3`、Atlas HEAD `060071ab2ecf86d41cab90e98160183ce126bc69`，并实际运行仓库命令。
- 主控从磁盘 diff 直接观察到 `server.py` 生产依赖注册 helper、依赖边和 owner 清理的首批代码，以及新增定向测试；原有 service_registry 等未提交修改不归为本轮新增。
- Luna 报告首轮服务注册定向测试 `21 passed`；主控当时通过桌面正文读到此结果，尚未自行独立复跑，因此不把它写成独立验收通过。
- 已收到非中断 steer：Luna 自身不需要再嵌套 CDP，它是实施端，主控是 CDP 派工/观察端。Luna 已明确接受并纠正先前“指定通道尚未执行”的误判。

## 已交回实施端的问题

1. `unregister_owner` 不能替代实际资源关闭。要求真实异步关停动作按依赖图执行，验证异常/取消/重复关闭路径，而不是仅让图可见。Luna 正实施，不是已验收。
2. 旧 `omni_bench.py` 的 hook 隔离函数会写真实 `data/hooks.toml` 且 finally 删除，usage 又硬读真实 `data/atlas.db`。主控未运行该危险路径，要求专用数据目录隔离后才能实测。
3. 固定 DSH 源码 `packages/bundle/headless/src/json-stream.ts:266-290` 在每个 step_end 报告本步 usage，turn_end 不带 usage。旧基准保留最后一步，却与 Atlas 整轮 SUM 比较。要求整轮累计、未知保留未知，并纳入 cacheWrite。
4. 任务成功必须校验最终答案/实际工具与文件结果，不能只检查 completed；多轮连续性保留 sessionId 证据。

## 独立检查边界

实施代码仍由用户指定的桌面 6 Luna 编写。主控另行安排两个只读检查：生产依赖/生命周期对抗审查、多轮上下文根因分析；它们不得写代码、启动真实模型或改用户数据。结论返回后由主控交给 Luna 修复。

## 当前状态

CDP 连接与派工：已核实。Luna 实施：进行中。首批运行闭环、完整 DSH 能力地图、剩余阶段与可重复超越：均未完成，不得据此文件宣称全面对齐或超越。具体后续进度见 `BEYOND-DSH-PROGRESS.md`。

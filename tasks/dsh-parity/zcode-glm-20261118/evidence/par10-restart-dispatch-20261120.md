# PAR-10 重启恢复派发记录（2026-11-20）

运行时崩溃后核查：端口 189xx / 8765 无监听，相关 Electron/后端/pytest 进程为 0；五条旧工位均未恢复，原生续接返回 “No active local_agent task found”。五个包全部在原候选树、原 D 盘 probe 目录上从落盘断点重新启动，不重做已通过步骤，不重置候选树。

| 包 | 旧工位 | 恢复工位 | 恢复点（落盘） |
|---|---|---|---|
| T6-12 桌面双窗验收 | agent_f7049aa8-f04f-49cf-9cf2-107a540d50d0 | agent_8cc304d7-5d45-4371-af28-fdc595113268 | t6-12-r2：diag-window/scenario；两窗口同加载 dist/index.html，T+10~12s mainEval/pageEval 3s 连续超时；43 已过 CSV/TSV、BIFF8、技能、worktree；候选树 38 项改动 |
| T6-18 解包发行链 | agent_b044c438-b4e5-4b06-ab85-153e6a95b3c4 | agent_45623162-f235-4213-87fa-3dbaae76b1ea | t6-18-r2：后端 SHA 80bfca54… 三处一致；verify-chain PASS failures=0；app.asar a83c44b8…；Electron 44.7.0；v2 health 200 有残留，v3 优雅退出 health 000 |
| T6-19 rc.5 搜索 | agent_83a893f3-cf54-4e64-bd80-e0cade811bb0 | agent_ff83d952-a16d-464e-8d3a-42acdb6c22d2 | t6-19-r2：rerun-45.txt 45 passed；桌面设置页与路由差异未做；候选树 22 项改动 |
| T6-20 Windows 插件 | agent_b41c795d-56f5-4898-a946-cfe4f42eae9b | agent_f01b026e-4ebe-4cc6-80df-1d42dae685de | t6-20-r2：corepack pnpm 12.21.0、store11b/v11、state11b；logs 空，基线对照未落盘；候选树 23 项改动 |
| T6-17 同模型配对 | agent_f54a494e-a44b-40e2-a56d-f5a1b298d3e6 | agent_3ad81167-e3e1-42cc-b4a3-6821d31324be | t6-17-r2：loopback-wire 310KB、Atlas t1–t3、DSH short/multi-t1、run1-partial、gateway-probe2；先对账旧两份 out 与 8 回合上限 |

实际启动数：5 / 5。恢复方式：重新 run_in_background（原生续接不可用）。约束不变：D 盘独立 TEMP/TMP/profile/日志/端口段，禁止 8765，不碰主工作树源码、用户数据/凭据/开始菜单/注册表，不运行安装器，不 commit/push/merge/reset。
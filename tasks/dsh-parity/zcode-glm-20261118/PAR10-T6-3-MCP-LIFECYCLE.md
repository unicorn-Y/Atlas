# PAR-10 · T6-3 任务书 · MCP 生命周期全回归

## 选行与依据

- QUEUE 行:`F09-extensions` / `B-F09-MCP-MANAGER-01`;T5 已验 stdio 掉线重连与 v24.21.0 退出恢复,本包只处理 T5/PAR-09 源树/`060071ab` 同败的 3 个 `test_mcp_lifecycle_shutdown.py` 节点。
- 依据:`PAR10-READY-NEXT.md` §MCP 生命周期全回归;`evidence/par10-t5.md`;`CODEX-WATCH-RECEIPT.md`;T5 源树 `D:\Atlas\.worktrees\zcode-par10-mcp-recovery`。

## 工作树

- `D:\Atlas\.worktrees\zcode-par10-mcp-lifecycle-gate`
- 分支 `zcode/par10-mcp-lifecycle-gate`,HEAD `060071ab`。
- 先确认 T5 源树写者已停,再把 T5 的已验改动(含 IMPL-2 + recovery/reconnect budget/stop 并发)以明确文件或 patch 移入本树,记录源 sha256 与基线;本树独占。

## 任务

1. 用真实本地 MCP stdio 子进程复跑 3 个失败节点:
   - `test_stdio_session_shutdown_exits_its_real_child`
   - `test_cancelled_mcp_discovery_stops_its_real_stdio_child`
   - `test_cancelled_owner_does_not_skip_other_server_cleanup`
   分别在准备、启动中取消、已连接停止、多服务器清理时点断言进程退出、owner 清理、status 保留。
2. 判明原因:基线夹具若错用「启动完成」语义,修正等待条件并保留原断言;若存在产品关闭缺陷,先复现最小路径再改产品。
3. 同树回归 T5 的 recovery、reconnect budget、stop/concurrent restart;记录已修与剩余失败,保留旧证据。
4. 命令:`--basetemp=<worktree>/.tmp/... -p no:cacheprovider`;记录解释器/版本、完整命令、退出码、通过数;旧打包 Node 证据对应实际路径/版本。

## 验收

- 3 节点在修正后通过,或逐条给出仍失败的产品/环境原因与最小复现;同树 T5 回归全过。
- 回执 `evidence/par10-t6-3.md`,末行 `PAR10_RECEIPT T6-3 READY|PARTIAL|BLOCKED`。
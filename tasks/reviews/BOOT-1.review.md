# BOOT-1 审查与验收（Claude，2026-10-15）

分支 `boot-1-int` = `boot-1-core` + `boot-1-shell` + 审查修复，快进合入 `memory-v1`。

## 实测（主机，`D:\atlas-boot-int`，真实配置，真实启动路径 `scripts/atlas-update.mjs --launch-only`）

后端未运行时双击（5 次）：

| 次 | 窗口出现 | 后端可聊 | 首条真实回复（其中模型） |
|---|---|---|---|
| 1 | 0.49s | 3.77s | 6.99s（2.39s） |
| 2 | 0.48s | 3.74s | 14.71s（10.15s） |
| 3 | 0.50s | 4.12s | 13.84s（8.90s） |
| 4 | 0.49s | 4.08s | 25.15s（20.26s） |
| 5 | 0.49s | 4.12s | 9.03s（4.09s） |

中位数：窗口 0.49s（目标 ≤1s ✅），后端可聊 4.08s（目标 ≤3s，差约 1s）。回复耗时主要是模型（本地反代 127.0.0.1:8045）波动。

常驻（点 × 关窗口隐藏到托盘，后端保持运行，再双击打开，5 次）：

| 次 | 窗口出现 | 后端可聊 | 首条真实回复（从发送起） |
|---|---|---|---|
| 1 | 0.22s | 0.03s | 11.46s（10.62s） |
| 2 | 0.19s | 0.06s | 7.70s（6.88s） |
| 3 | 0.22s | 0.03s | 5.56s（4.71s） |
| 4 | 0.22s | 0.03s | 5.85s（5.01s） |
| 5 | 0.21s | 0.03s | 6.00s（5.16s） |

常驻目标（≤1s 可聊）✅。全部 10 次均为真实回复，无 mock。冷开机（重启电脑后首次）未测。

## 审查中发现并修复

1. 启动偶发永久卡死：Windows 上 asyncio 建事件循环用 `socket._fallback_socketpair`，`accept()` 偶发永远等不到回环连接，后端停在 `config.loaded` 之后（10-14 01:11 那次同因）。`desktop_entry` 改为 3s 超时换端口重试并写日志（`fe3c10f`）。具体是谁扣住连接（火绒/Clash TUN）未定。
2. Electron 先探活再做 netstat/PowerShell 进程检查，常驻时不再多花 1–2s；`--launch-only` 恢复 build-stamp 检查，提交变了才重建（`83951af`）。
3. 后端移植不完整：`scripts/diag/import_check.py` 查出 59 处坏导入（退回 Codex 补齐到 0）；另补 `tool_search_validation` 残留的顶层 `model_tools` 导入（`arg_coercion`/`schema_sanitizer`，`720604a`）。
4. 界面发消息悄悄走 mock 运行时：后端“能聊即就绪”后，后台组件接口返回 5xx，适配层把整个客户端标成断开，之后的消息由 mock 运行时假装回复。改为 5xx 不掉线、桌面端禁用 mock（重连失败直接报错）（`0fda3a3`、`5154f74`）。Codex 的 9 项对话验收是用 Python 直连后端做的，没走界面，所以没发现。

## 遗留

- 后端可聊 4.1s，未达 3s；下一步可继续压导入或默认常驻。
- `backend-adapter` 测试 "accepts successful empty responses" 在旧代码上同样失败，非本次引入。
- 本地模型运行（GGUF 下载/运行）随 Hermes 移除变为“不支持”；主机配置未使用。
- 主机 70+ 个 `mihomo-egress` 进程堆积（非 Atlas）。

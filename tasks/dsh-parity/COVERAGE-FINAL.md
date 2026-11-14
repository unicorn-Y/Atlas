# DSH 差距最终覆盖率（WAVE 4 合并后）

日期：2026-11-14
基线：`4d16a722`

## 数字

**99/135 关闭 = 73.3%**

| 区 | 已关闭 | 总数 | 关闭率 |
|---|---|---|---|
| E 引擎 | 23 | 36 | 64% |
| S 会话 | 18 | 33 | 55% |
| X 扩展 | 25 | 33 | 76% |
| D 桌面 | 33 | 33 | 100% |

## 各轮进展

| 轮次 | 执行者 | 关闭数 | 变化 |
|---|---|---|---|
| 起始 | Codex 手工 | 9 | — |
| WAVE 1 | Codex 16 worker（按目录） | 28 | +19 |
| WAVE 2 | Codex 10 worker（跨目录） | 37 | +9 |
| WAVE 3 | Codex 桌面串行 | 40 | +3 |
| **WAVE 4** | **ZCode 7 agent 并行** | **99** | **+59** |

## WAVE 4 产出

- **107 文件改动、12,888 行新增、66 个新文件**
- 7 个 agent 并行，各自独立 worktree + 独立分支
- 合并冲突 2 处：`token_meter.py` 里两个 agent 各实现了不同函数（`anchor_surface_to_usage` / `route_image_pricer`），**两个都保留**

## 验证

| 项 | 结果 |
|---|---|
| Python 语法 | 0 错误 |
| 后端启动 | health 200，无 import 错误 |
| **真实模型** | `run.completed`，回 `FIXED`，`request_count: 1` |
| 后端测试 | 49 项通过 |
| 新增回归 | `test_codex_hook_exit_semantics.py`（3 项） |

## 期间修复的两个真实 bug

### 1. Codex hook 退出码语义冲突（严重）

Codex 用 exit 2 表示「hook 出错」，Claude 用 exit 2 表示「主动阻断」。Atlas 一律按 Claude 解释。

后果：你的 `~/.codex/hooks.json` 里有一条 `python D:/MemoryOS/adapters/codex/hooks/hook_user_prompt.py`，那个脚本**不存在**。于是每一轮 prompt 都被判为 `blocked: True` —— 回复变成 Python 的报错文本，`request_count: 0`，**模型从未被调用**。

修复：Codex 来源的 exit 2 降级为诊断日志（仍记录，但不再阻断）。Claude 语义不变。加了 3 项回归测试。

### 2. 代理凭据在重启后丢失

`user-settings.json` 里 `proxy_configured: true`，但系统凭据库里的 `atlas.model_network.proxy_url` 没了，报 `模型代理凭据缺失`。已恢复。

## 剩余未关闭：36 条

**HARD 类 9 条**（需独立工程，不是接线）：
`E1 S1 S2`（事件日志作为模型历史真源）、`X1`（Cordis 式组合根）、`X5 X6 X7`（插件依赖/版本/安装审批）、`E14`（Windows per-call sandbox）、`S30`（DeepSeek 官方 API 上传）

**其余约 27 条 PARTIAL**：有实现，缺生产接线或真实模型取证。

## 不许说的话

- ❌「DSH 差距已补齐」—— 73.3%，还差 36 条
- ❌「全部通过」—— 只跑了 49 项相关测试
- ❌「功能可用」—— 99 条 CLOSED 里带真实模型证据的是少数

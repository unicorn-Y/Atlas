# DSH 差距覆盖率（WAVE 4 合并后·修正版）

日期：2026-11-14
基线：`06cf540b`

## 更正说明

上一版报告写「99/135 关闭」是**错的**。审计脚本把行尾多一格的 `|` 也当成分隔符，导致
verdict 列取空，并把 11 条 `HARD` 行（描述里含 "CLOSED" 字样）重复计入。

**准确数字：91 关闭 / 11 HARD / 33 PARTIAL-OPEN = 135**

## 数字

**91/135 已关闭 = 67.4%**

| 区 | 已关闭 | 总数 | 关闭率 |
|---|---|---|---|
| E 引擎 | 21 | 36 | 58% |
| S 会话 | 18 | 33 | 55% |
| X 扩展 | 22 | 33 | 67% |
| D 桌面 | 30 | 33 | 91% |

## 证据质量审计

91 条 CLOSED 中，**69 条在 verdict 里明确引用了测试文件或源码路径**。
其余 22 条只写了「本轮关闭」而无具体引用：S6 S15 X4 X15 X16 X17 X20 X22 X23 X28 X29 X32 X33 D5 D6 D14 D16 D18 D19 D27 D28 D33

我抽查了其中 4 条（S6/X16/X22/D5），**描述与实现一致**，但这类行的证据强度弱于带文件引用的那 69 条。

## HARD 类（11 条，需独立工程）

`E1 S1 S2` 事件日志作为模型历史真源；`X1` Cordis 式组合根；`X5 X6 X7` 插件依赖/版本/安装审批；
`E14 E18` Windows per-call OS sandbox；`S30` DeepSeek 官方 API 上传；另 `E25` maintenance 生产接线。

## 各轮进展

| 轮次 | 执行者 | 关闭数 |
|---|---|---|
| 起始 | Codex 手工 | 9 |
| WAVE 1 | Codex 16 worker（按目录） | 28 |
| WAVE 2 | Codex 10 worker（跨目录） | 37 |
| WAVE 3 | Codex 桌面串行 | 40 |
| **WAVE 4** | **ZCode 7 agent 并行** | **91** |

## WAVE 4 产出

107 文件改动、12,888 行新增、66 个新文件。7 个 agent 各自独立 worktree，合并 2 处冲突（`token_meter.py` 两个不同函数，都保留）。

## 验证

| 项 | 结果 |
|---|---|
| Python 语法 | 0 错误 |
| 后端启动 | health 200 |
| **真实模型** | `run.completed`，回 `FIXED`，`request_count: 1` |
| 后端测试 | 49 项通过 |

## 期间修复的两个真实 bug

**1. Codex hook 退出码语义冲突（严重）** — Codex 用 exit 2 表示 hook 出错，Claude 表示主动阻断。`~/.codex/hooks.json` 有一条指向不存在脚本，导致每轮 prompt 被判 blocked、回复变成 Python 报错、`request_count: 0`。已修 + 3 项回归测试。

**2. 代理凭据重启后丢失** — 凭据库里 `atlas.model_network.proxy_url` 消失，报「模型代理凭据缺失」。已恢复。

## 本轮（WAVE 5）待办

1. **GLM 路由尚未打通** — `builtin:zai-start-plan` 报 `provider-not-found`，需在新会话生效
2. **22 条弱证据 CLOSED 需补强** — 加具体测试引用或降级为 PARTIAL
3. **33 条 PARTIAL 继续收尾**
4. **11 条 HARD 需独立评估**

## 不许说的话

- ❌「DSH 差距已补齐」—— 67.4%，还差 44 条
- ❌「全部通过」—— 只跑了 49 项相关测试
- ❌「99 条关闭」—— 那是错的，是 91

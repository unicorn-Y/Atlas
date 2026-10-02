# ATLAS-C6A-LSP-CORE-PARALLEL：LSP 自动诊断核心（ZCode 独立施工线）

> 这是 ZCode 的下一单，独立于 main 当前 C4。
> 目标不是重做整个 C6，只把 **T8 LSP 诊断核心**先做成可直接接线的成品模块。
> 不 merge main，不碰 C4 扩展层，不碰 C5 模型层。

## 先读

- `tasks/ZCODE-CURRENT.md`
- `tasks/taskbooks/ATLAS-C6-CODING-POLISH.md` 的第 1 节
- `docs/plan/CORE-PARITY.md` 的 T8
- `docs/plan/EXECUTION-GUIDE.md`
- Hermes：`agent/lsp/**`、`tools/file_operations_lint.py`
- OpenCode：`packages/opencode/src/lsp/**`、`src/tool/lsp.ts`

施工时查当前最新上游实现，优先搬成熟代码，不凭记忆重写。

## 目标

做出 Atlas 可复用的 LSP 诊断核心，后续 C6 主线只需要做很薄的“写文件后自动调用 + UI 展示”接线。

至少做到：

1. Python：pyright / basedpyright
2. TypeScript / JavaScript：typescript-language-server
3. 自动按文件类型/项目检测合适 server
4. server 按 workspace 复用，不要每次编辑都重新起
5. Windows 下能启动、复用、停止，不留孤儿进程
6. 支持请求某个文件当前 diagnostics
7. 能比较“编辑前 vs 编辑后”，只返回本次新增问题
8. 修复后问题消失时能正确清空
9. 语言服务没安装时返回明确、短的中文缺失提示；不要自动下载安装
10. 所有诊断结构统一成 Atlas 自己的简单类型：
   - file
   - line
   - column
   - severity
   - code
   - message
   - source

## 代码边界

优先新建独立模块，例如：

- `core/atlas/lsp/**`
- `core/tests/test_lsp_*.py`

如必须改现有文件，只允许非常薄的接线，并在 result 单列。

本波**不要碰**：
- `core/atlas/server.py`
- `core/atlas/plugins/**`
- `core/atlas/skills/**`
- `core/atlas/models/**`
- `frontend/src/renderer/App.tsx`
- `frontend/src/renderer/services/runtimeEvents.ts`
- ConversationActivity / timeline
- SettingsPage
- C4 hooks/plugin/import/commands 相关文件
- C5 model/provider/credential/reasoning/usage 文件

如果自动诊断必须接进 Hermes 写文件路径，优先做一个独立 adapter/hook，避免大改共享 engine。不要为了这一波强行完成 UI。

## 实现取舍

先快速对比 Hermes 与 OpenCode：

- language server 启动/发现
- JSON-RPC/LSP client
- workspace 生命周期
- diagnostics 缓存
- Windows 进程管理
- 新增错误过滤

选择更强的实现直接搬/改；若两家各有强项，允许组合，但不要造新的大框架。

规则表/语言表如果上游已有成熟整表，整份搬，不写缩水版。

## 子代理施工方式

尽可能把可独立部分交给子代理并行：
- 上游源码对比 / vendor
- Windows process lifecycle
- diagnostics diff/cache
- Python language adapter
- TS/JS language adapter
- fake LSP tests

**尽量使用当前运行环境实际允许的最大子代理并发**。不要预设固定数量；运行时若拒绝部分 spawn，自动调整后继续。

每个子代理明确文件所有权，避免改同一文件。

## 最小验收

不要跑全 Atlas。

至少验证：

1. fake LSP：打开文件 → 返回一个类型错误
2. 修文件 → 同一错误消失
3. before/after diff 只返回新增 diagnostics
4. 同 workspace 两次诊断复用同一 server
5. workspace 关闭后 server 正常退出
6. server 不存在时返回“未安装/如何安装”的中文提示
7. Windows lifecycle 回归（可 mock process，但要覆盖 terminate/kill/cleanup）
8. Python 与 TS/JS 各一个代表文件

如果测试机正好装了 pyright/typescript-language-server，可以额外跑一条真实本地 smoke；没有就不装、不阻塞。

## 不做

- 不做 /init
- 不做 /review
- 不做长会话性能
- 不做主体 UI 打磨
- 不做 C4
- 不做 C5
- 不做真实模型
- 不跑 backend full pytest
- 不跑前端四项（本波原则上不应改前端）

## 交付

写：

`tasks/results/ATLAS-C6A-LSP-CORE-PARALLEL.result.md`

必须写清：
- 选了 Hermes / OpenCode 哪些实现，为什么
- 搬入/新增文件
- Windows 进程生命周期
- diagnostics diff 语义
- 测试结果
- 是否触碰共享热文件
- 后续 main C6 只需要补哪些接线

然后：

- `tasks/ZCODE-CURRENT.md` → `AWAITING_REVIEW`
- push `zcode/c6a-lsp-parallel`
- 回报 HEAD
- 不 merge main
- 不自行进入下一阶段

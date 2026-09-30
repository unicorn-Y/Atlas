# CODEX-ATLAS-BACKEND-PARITY-WAVE2 Review

REVIEW_RESULT: ACCEPTED（一处安全问题由审阅方直接修复）
REVIEWED_HEAD: `e3fcef1`
BASE_HEAD: `dc6ce0f`

## Verdict

12 节全部按契约实现。笔记本复跑全量 `core/tests`（跳过 `test_computer_use.py`）：**572 passed, 5 skipped**，仓库里没有再产生 `core/.pytest-*`。协议 `1.4`。

前端接线后用真实模型端到端验证过：worktree 创建、在独立分支提交、主目录不变、压缩合并回 main；`@` 文件引用；`/btw` 旁问（ephemeral）；存为配方与配方列表；角色列表；分支列表；工作区搜索。

## 审阅方修复

**`/api/workspace/raw` 让预览的 HTML 能读 Atlas 数据（HIGH）。** raw 接口从后端自己的源（`127.0.0.1:8765`）返回 HTML，浏览器对同源 GET 不带 `Origin`，`origin_guard` 把它当成本机进程放行。实测：工作区里一个 HTML 文件被预览时读到了全部会话列表。

- raw 接口对 HTML / XHTML / SVG / XML 加 `Content-Security-Policy: sandbox allow-scripts allow-forms allow-popups allow-modals`（脚本照常运行，但源变成不透明，请求带 `Origin: null` 被拒），所有类型加 `X-Content-Type-Options: nosniff`。PDF、图片不加 sandbox，避免挡住浏览器自带的查看器。
- `origin_guard` 增加：浏览器标记 `Sec-Fetch-Site: same-origin` 的请求在没有 token 时一律拒绝。后端从不提供自己的界面，合法前端只会是 same-site（Vite）或 cross-site（`file://`）。以后别的接口再返回 HTML 也不会重新打开这个口子。
- 测试：`core/tests/test_origin_guard.py` 新增两条。

## 留给下一波（非阻塞）

1. 在 worktree 里运行的任务存为配方时，`workspace` 记录的是 worktree 目录；删掉 worktree 后配方失效。应该记录原始 workspace。
2. `from-run` 生成的配方描述是英文（"Created from a conversation run"），改成中文或留空。
3. 分叉 / 复制会话时没有带上源会话的 `workspace`，新会话需要重新选目录。
4. `worktree.name` 被接受但不起作用（结果文件已说明），要么去掉，要么用于分支名后缀。

# D-TC-01：文件读写与本机进程接口

基线：`origin/memory-v1`（`e9be4b4b`）
分支：`card-d-tc-01`

## 逐项结果

- **D001 文件读取 — 已完成。** `local_file action=read` 默认拒绝超过 256 KiB 的文件；支持 1-based 行范围（单页最多 2,000 行、1 MiB）和字节范围（单页最多 1 MiB），输出包含总字节数、下一偏移和完成状态。只有完整读取的文件可作为精确编辑的 read-before-edit 依据。实现参考 Claude Code Read、ZCode Read 和 OpenCode 分页读取行为。
- **D002 文件写入 — 已完成。** `local_file` 的 write、append、mkdir、copy、move、delete，以及 `local_edit` / `local_edit_batch` 均要求目标解析后仍位于活动本地工作区内；copy/move 同时检查来源和目标。无法取得工作区或目标越界时拒绝操作。SSH workspace 继续走其既有独立适配器。
- **D003 文件编辑、批量编辑 — 部分完成。** 新增 `local_edit_batch`（最多 32 个文件）：执行前统一检查工作区边界、读前置、唯一目标、编码和精确匹配；逐个写入同目录临时文件后替换，并在失败时尝试按原始字节回滚已替换文件，返回提交结果和路径清单。文件系统没有跨多个路径的原子提交原语，因此替换期间其他读者仍可能观察到中间状态；回滚失败时也只能由底层错误揭示，不能声称具备真正的多文件事务隔离。现有单文件 edit 保留原有精确匹配和 checkpoint。
- **D011 后台进程 — 已完成。** 已有 `local_process` 覆盖启动、状态/等待、输出分页、stdin、取消；新增 Claude 兼容 callable `TaskOutput`（文档已弃用，映射到受管输出读取）和 `TaskStop`（按 execution ID 停止），复用同一进程登记表，不造独立任务状态。
- **D046 会话移动与工作树生命周期 — 部分完成。** `workspace_session_manage move` 可在审批后把当前会话元数据转到已存在的本机目录，明确只对下一次运行生效；当前运行继续绑定原 workspace。若会话仍登记了专属 worktree，则拒绝移动并要求先按现有 clean-only 流程移除，保留分支。尚未实现跨 workspace 活动会话的即时 handoff，也没有自动扫描/回收未登记的工作树：现有代码没有可安全判定孤立工作树无用户改动的生命周期索引，自动删除会有数据丢失风险。
- **D127 向客户端发送文件 — 未实现。** Claude Code 当前公开工具参考未列出通用的本地文件发送 callable；Atlas Electron preload 仅暴露目录选择、路径打开等能力，没有带授权绑定、文件内容传输及成功/失败回执的桌面传输通道。单加 callable 或回传路径不能证明客户端收到文件，所以本卡不加入假成功路径。需要先有明确的目标客户端传输协议/接收方合同。

## 验证

- `py -3.14 -m uvicorn atlas.server:app --port 28797`：设置 `ATLAS_UPSTREAM_AUTO=0`，并使用系统临时目录中的独立 `ATLAS_DATA_DIR`、`MEMORYOS_*` 和 `HERMES_HOME`；`/api/health` 返回 `status: ok` 且列出的组件全部 ready，之后已停止服务。默认 `python` 指向 Python 3.11 Hermes venv 且缺少 `tomli_w`，因此按既有锁定环境约定改用已装依赖的 Python 3.14。
- `npm --prefix frontend run build`：通过（Vite production build）。构建有既存依赖 deprecation 和大 chunk 警告。
- 未写入或运行测试。

## 提交

- 实现提交：待生成。
- 本结果文档随后的文档提交号将在实现提交后补齐。

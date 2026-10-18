# 独立会话任务：Squad Multi-agent CLI/TUI

**单独新建 ChatGPT 会话执行，Wave 3，研究代号 `squad`。**
**总协议必读：** `tasks/research/agent-reverse/2026-10-19/PROTOCOL.md`
**仓库：** `unicorn-Y/Atlas`
**派工分支：** `research/agent-reverse-dispatch-20261019`
**从派工分支创建个人工作分支：** `research/agent-reverse-20261019-squad`
**唯一成果目录：** `docs/research/agent-reverse/2026-10-19/squad/`
**原始归档：** https://github.com/unicorn-Y/Atlas/releases/tag/agent-client-packages-20261019

## 已经取得的原始材料
Squad-Windows-x64-CLI-TUI-release-v0.7.6-b07e35cb16.zip、Squad-Pinned-source-snapshot-v0.7.6-b3a5e48caf.zip。

先阅读 `docs/research/agent-clients/2026-10-19/{manifest.json,PACKAGE-INDEX.md,START-HERE.md}` 和适用的 `indexes/`。所有版本、hash、来源只按原索引与实际包核实。

## 特别深挖的方向（只是探索起点，不是全部内容）
1. 多 Agent 团队协作、角色、任务拆分/队列/并行管理与对话协同的真实代码路径
2. 任务交付、人工干预、监工、进度可观测、工具调用、上下文共享/隔离与失败策略
3. TUI 呈现、多会话管理、消息/事件结构、进程生命周期、状态恢复
4. 是否存在能直接吸收的代码/协议，避免只写多代理产品描述。

## 必须做到
- 通过原发行物与固定源码真实分析 UI/CLI/引擎、状态和数据流、命令/插件注册、后端运行时、IPC/RPC/事件流、持久化、重试与恢复；寻找功能与机制上原本不知道的东西。
- 每个发现 `SQUAD-NNN` 编号，记用户操作或可观察行为、上游代码路径+符号、版本与哈希、证据等级 S/R/D/I/U。区分确认、推断和不可见服务器端机制。
- 追到可复用的成熟代码、组件与必要配套依赖，不仅描述功能名字；不要将这些功能简单包装成外部插件代替 Atlas 原生整合的可能性。
- 实际读 Atlas `main@SHA` 源码对照，标清 UI 存在但运行不通、部分接线、缺机制与有完整等价行为；不要沿用旧功能矩阵“已完成”的假结论。
- 若大文件无法在当前 ChatGPT 会话打开：在独立分支的成果目录创建 `EXTRACTION-REQUEST.md`，写可供本地 Codex 执行的**指定 asset → 提取文件/路径 → 上传索引**指令；资料不足时标 PARTIAL，不造假。
- 提交并 push `START-HERE.md`, `DISCOVERY-LEDGER.md`, `IMPLEMENTATION-TRACE.md`, `UI-AND-WORKFLOWS.md`, `ATLAS-GAP.md`, `EVIDENCE-INDEX.md`，必要时 `REUSE-CANDIDATES.md`。独立分支、独立目录，不修改 Atlas main/业务代码。
- 保持调研开口：发现新方向就继续追到代码与行为，不因本任务书没提就不查；覆盖盲点明确披露。

## 新 ChatGPT 会话启动语
“请研究 Atlas 竞品/生态：Squad Multi-agent CLI/TUI。读取私库 unicorn-Y/Atlas 的 research/agent-reverse-dispatch-20261019 分支中的 `tasks/research/agent-reverse/2026-10-19/sessions/squad.md` 和统一 PROTOCOL.md。执行真实发行物与源码逆向及后端机制研究，主动发现未知能力，与 Atlas main 对照，成果提交并 push 到 research/agent-reverse-20261019-squad。不要只列功能或规划，不要改 Atlas 正式代码。”

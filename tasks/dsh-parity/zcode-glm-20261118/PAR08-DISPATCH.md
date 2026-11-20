# PAR-08 返工任务单

承接 D:\Atlas\tasks\dsh-parity\zcode-glm-20261118\evidence\par07-codex-acceptance-20261119.md。范围是五包的本次验收缺口，返工后继续原官方 DSH 全量对齐与超越队列。

## 主会话调度

1. 读独立验收记录和现有 PROGRESS.md、QUEUE.tsv。用 ZCode 原生 Agent 在同一轮启动五个 general-purpose 子代理。容量四个时先发四包，首个回收立即补发第五包。
2. 每包只给自己的任务、文件范围和验收条件。如果旧 Goal 或其他人仍在写指定树，新建独立树并从只读快照续接。子代理不改主工作区和总账。
3. 主会话按完成顺序收件、查 diff、复跑关键命令和实际入口，再一次性更新台账。完成状态以验收证据为准。先关闭返工缺口，再按原队列推进其他可以做的工作。

## A · CSV/TSV 预览

沿用 zcode-exec06-csv-preview 的修复，仅负责 csvPreview 及其测试。解析器能保留单个带引号的空字段，渲染层仍把单行全空视作空文件。区分零记录与含合法空字段的记录。在组件级测试同时覆盖真正空文件和引号空字段。复验首列跨行的分号 CSV、普通 CSV/TSV、文件树点开与 renderer 类型检查。使用隔离 Electron 窗口点开两种边界输入，保留界面和退出码证据。

## B · 快捷键并发

沿用 zcode-exec06-keybindings-cas，仅负责 keybindings 客户端、ShortcutsPanel、该路由及测试。保留 revision 与 409。重试基于最新文件重放本窗口实际编辑的操作，不能上传整张陈旧快捷键表。删除绑定、恢复默认、快速连改的编辑意图需要正确保留。遇到双方改同一操作时给出清楚的冲突处理。用两个 Electron 窗口连接临时 FastAPI，分别修改两个不同操作，验证第二次收到 409，刷新重试后两项都落盘。

## C · 桌面工作区技能源

沿用 zcode-exec06-skill-sources，仅负责技能源、作用域解析及测试。保留 CLI 和 custom/runtime/bundled 的已有文件式接线。桌面实际运行要按会话工作区解析项目 .dsh/skills 和 .agents/skills，避免全局默认工作区污染其他项目。优先复用 SkillManager 的作用域机制，遵守已有项目配置 opt-out 和调用策略。用两个工作区各自的同名技能与独有技能通过正常运行入口验证，加测无项目路径与 CLI。虚拟 runtime provider 单列状态。

## D · worktree API 回滚

从 zcode-par07-worktree-api-fix 继续，仅负责 worktree REST 创建和测试。保留 conversation.workspace 为 base。持久化失败且清理失败时，返回准确结果并保存可定位的恢复信息，避免悄悄留下无人管理的工作树。使用真实临时 Git 仓库验证正常 create/status/merge/delete，注入记录失败与清理失败并再次请求，证据要能确认残留可恢复，路由快照保持合法。

## E · SDK 取消移植

新树名建议 zcode-par08-sdk-port。先读当前 D:\Atlas 的 AppServer、Python SDK 和在途测试。旧 zcode-par07-sdk-cancel 补丁不能直接应用。仅在自己的树按当前文件实现移植，保留原作者现有 task queue、durable request/event、取消与重连能力，记录只读基线与本包增量。验收须从实际 SDK 子进程提问，校验取消通知恰好一次、迟到应答拒绝、首次进程关闭成功、重启后状态延续。Python 3.11 与 D:\Atlas\core\.venv 的 Python 3.14 均复跑，调查 3.14 退出码 1 的原因。桌面卡片通知保持独立范围。

## 交付

- 保留当前模型和账号配置，遵守 Atlas AGENTS.md。各包只写自己的隔离树和 evidence/par08-a.md 至 par08-e.md 及各自日志。
- 记录基线、准确改动、复现步骤、命令、退出码、产品入口和待验边界。主会话先复核，再调整 QUEUE.tsv 与 PROGRESS.md。
- 五包均留在隔离工作树等待主控验收，避免覆盖其他作者的改动、真实数据和凭据。

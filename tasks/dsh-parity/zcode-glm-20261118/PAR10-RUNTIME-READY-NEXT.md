# PAR-10 · 运行时与工作树后续候选

主会话可在任一工位空出时领取，并以实际已经启动的包为准去重。取下一个可用的 T6-n，继续 PAR10_RECEIPT、PAR10_REVIEW 与隔离工作树方式。主工作区和既有产物只读。

## 工具批取消的结果顺序

- QUEUE 的 F05-host，ATLAS-MAP 的 `B-F05-CANCEL-SYNTH-01`，参考 `evidence/exec06-f05-batch-retry-sandbox-20261119.txt`。已有取消合成证据，剩下 DSH 同批有序回执与 Atlas 正式工具批入口的实证。
- 新树 `zcode-par10-batch-cancel-order`。用临时任务和确定性测试工具，从正常调度入口覆盖请求顺序与完成顺序不同、运行中取消、排队时取消。验证每个 call ID 只关联一个最终结果、取消原因留存且输出顺序符合已核实契约。区分模型工具结果顺序和进度事件顺序。
- 只有复现缺口才补最小实现。主树 tools.py 仍有作者改动时保持只读，交付隔离证据及可重放差异。能复验的对齐项更新台账。

## Windows 工作树被文件占用时的恢复

- QUEUE 的 `PAR09-D2-recovery-boundary` 和 `PAR10-T4-desktop-candidate`，参考 `evidence/par10-t4.md` 的真实文件锁未覆盖项。
- 新树 `zcode-par10-worktree-windows-lock`。从 T4 的已验 D2 最小差异起步，用真实 Windows 文件句柄、临时 Git 仓库和已管理的工作树。校验创建写记录失败后真实文件占用、恢复记录和错误语义，以及释放该测试句柄后的重试。验证不会清理到其他临时树，保留正常 create/status/delete 和路由快照。
- 只操作可验证归属的临时目录；用独立的句柄进程或测试夹具，退出时释放该句柄。未能实证平台行为时如实给出测试输出。需要代码修复时做最小差异，保留现有路径和归属校验。

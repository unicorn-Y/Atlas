# 记忆系统并行施工安排（Claude 定稿，2026-10-16）

先读 `docs/memory/survey/VERDICT.md` 顶部的「Claude 定稿」一节，再读本文件和你负责的 `TASKBOOK-*.md`。任务书里标「Claude 定稿」的段落优先。

**为了快，四个 Codex 对话同时开工，不再一波一波等。** 用户已拍板的规则不要再问。遇到要拍板的事写进结果文件，按更强的选项继续做，不要停下来等。每个对话都可以开子智能体（GPT-6 Luna 高）并行，按任务书的文件所有权分工，两个子智能体不改同一个文件。

## 分支约定

- **代码基线 `origin/memory-w2-api`**：W2 后端，已包含 `memory-w2-plan`。所有 M 任务都从它开分支，**不等 A0**。
- A0 完成、推送 `ui-redesign` 以后，由 S4 负责把各 M 分支摘到 `ui-redesign` 上。
- 每个 M 任务一个分支 `mem-<m>`（如 `mem-m2`），一个工作树 `D:\atlas-mem-<m>`。结果文件写 `docs/memory/build/<M>-RESULT.md`，提交并推送到自己的分支，最后一行写 `<M> DONE`。
- 不改 `D:\Atlas` 工作区，那里有别人未提交的改动。只有 S4 在最后执行 `git -C D:\Atlas pull --ff-only`。

## 四个会话

### S1：A0（W2 合并上线）

照 `TASKBOOK-A0.md` 做。F2、F4 要自己实现，`memory-w2-fix` 上没有现成的代码提交。完成后推送 `ui-redesign`，写 `docs/memory/build/A0-RESULT.md`，最后一行写 `A0 DONE`。

### S2：M2（原文指针与条目元数据），先冻结接口

1. **第一件事，30 分钟内**：把 `SourceRef` 格式、Markdown 条目元数据字段（`source_level`、`recorded_at`、`valid_from`、`valid_to`、`supersedes`、`retracts`、`source_ref`）、`open_ref` / `memory_open` 的函数签名写成 `docs/memory/build/CONTRACT-M2.md`，同时写好对应的 Python 类型或空实现，提交推送到 `mem-m2`。这一步就是 S3 的开工信号。
2. 然后照 `TASKBOOK-M2.md` 完成实现，最后一行写 `M2 DONE`。
3. 接口冻结以后如果非改不可，在 `CONTRACT-M2.md` 末尾追加「变更」一节，写清改了什么，并通知 S3（在 S3 会读的 `CONTRACT-M2.md` 里写明即可）。

### S3：M1、M3、M7、M5、M9，然后 M4，然后 M6、M8（总调度，用子智能体）

1. 每 5 分钟 `git fetch origin`，等 `origin/mem-m2` 上出现 `docs/memory/build/CONTRACT-M2.md`。等的时候先读任务书，安排好子智能体的分工。
2. 契约出现后，**同时开 5 个子智能体**做 M1、M3、M7、M5、M9。每个子智能体：
   - 从 `origin/mem-m2` 开 `mem-<m>` 分支；
   - 只改任务书分给自己的文件；
   - 照自己的任务书施工；
   - 按任务书「最小真实使用验收」自查；
   - 写 `<M>-RESULT.md`，推送。
3. M3、M7 都做完后，开子智能体做 M4，基线为 M3 和 M7 的分支合并。
4. M1、M5 做完，并且 M2 写了 `M2 DONE` 之后，开子智能体做 M6。M3、M4、M7 都做完之后，开子智能体做 M8。M6、M8 可以并行。
5. 子智能体做完一个，你就核对它的 diff 有没有越过文件所有权、有没有违背「Claude 定稿」里的规则，有问题立刻让它改。
6. 全部完成后，在 `mem-integrate` 分支上按 `M2 → M1 → M3 → M7 → M5 → M9 → M4 → M6 → M8` 的顺序合并，解决冲突，推送。写 `docs/memory/build/S3-RESULT.md`，最后一行写 `S3 DONE`。

### S4：验收与上线（独立对话，不写功能代码）

1. 每 10 分钟 `git fetch origin`。每看到一个新的 `<M> DONE`，就去验收：
   - 读 diff，按「Claude 定稿」和对应任务书核对；
   - 跑该任务书的「最小真实使用验收」，用临时数据目录和真实模型；
   - 结论追加到 `docs/memory/build/ACCEPTANCE.md`，写「通过」或「打回」加原因。
   - 打回的写清要改什么。S3 会读 `ACCEPTANCE.md`，你在里面写的打回意见它要处理。
2. A0 写了 `A0 DONE` 后，验收 A0：主机 8765 健康，记忆页能打开，没有 mock。
3. S3 写了 `S3 DONE`，而且 `ACCEPTANCE.md` 里各项都通过以后：
   - 把 `mem-integrate` 摘到最新 `ui-redesign` 上，用临时工作树 `D:\atlas-mem-ship`，只做快进推送，不 force；
   - 然后 `git -C D:\Atlas pull --ff-only`；
   - 用计划任务 `AtlasDev` 重启；
   - 用真实对话走一遍：记一件事 → 新会话问回来 → 打开原文 → 改一条记忆 → 让它忘掉 → 委派一个子任务。
4. 写 `docs/memory/build/SHIP-RESULT.md`，最后一行写 `MEMORY SHIPPED`。上线前如果有打回项没修好，不要上线，写明卡在哪。

## 共同规则

- 移植上游代码时，`docs/third_party/atlas-memory-port/NOTICE.md` 要写清仓库、commit、文件和许可证。AGPL 的代码不复制。
- 不搞大测试。每个任务只做任务书里那几条真实使用验收，靠日志判断。
- 主机 CLI 的 codex 没余额，别用。网络慢就走代理 127.0.0.1:7897。
- 结果文件只写事实：做了什么、改了哪些文件、验收看到了什么、还有什么没做。没观察到的不要写「通过」。

# CODEX-ATLAS-BACKEND-PARITY-WAVE5 — Review

VERDICT: ACCEPTED（有修复，见下）
REVIEWER: Claude

## 验证

- 后端全量（笔记本，修复后）：644 passed, 6 skipped。Codex 那边全量仍没跑完（长命令被终端中断），修复前笔记本上是 4 failed / 639 passed。
- 审阅重点：子 Agent 的权限继承、网页提取的内网防护、脚本工具、Telegram 授权与 token 保密。

## 审阅中修掉的问题

1. **网页提取的 10 MB 上限不起作用**：`client.get()` 先把整个响应读进内存，之后才逐块计数。改成 `client.send(stream=True)` 边读边计，超限立即停；重定向响应读完头就关闭。
2. **trafilatura 提取为空时没有退路**：只在没装 trafilatura 时才用自带解析器；装了但提取为空（短页面、非常规结构）就返回空文本。现在为空也退回自带解析器。（测试在装了 trafilatura 的机器上失败，Codex 机器上没装所以没发现。）
3. **项目资料查不到会让整个任务启动失败**：启动任务时查项目指令抛异常就直接失败。项目指令只是附加内容，现在出错时记日志、不带项目指令继续。（这也是全量测试里两个「单跑能过、全量挂」的原因：上一个测试关掉的项目存储被下一个测试复用。）
4. 测试用例绕过构造函数时 `self._projects` 不存在，改为 `getattr`。
5. 并行汇总的提示词是英文，汇总结果会是英文；改为中文。
6. Telegram：显式把 `httpx` 日志级别压到 WARNING（Bot API 的 token 在请求网址里）。异常里的网址 Codex 已处理。
7. `core/pyproject.toml` 里 `keyring` 重复声明，去掉一个。

## 审阅结论（没问题的部分）

- Atlas 子 Worker 继承父 run 的模型、`permission_mode`、`allowed_paths`、沙箱、hooks、审批；禁止再委派；12 轮上限；结束后删除临时会话。
- 网页提取：只允许 http/https，拒绝带凭据的网址，每一跳都检查是否为内网/本机地址。
- 脚本工具：编号和脚本名校验到位，超时杀进程树，输出上限 64 KB，按写操作处理。
- Telegram：消息和按钮回调都校验用户 ID；token 存系统凭据库，GET 不回显。

## 已知问题 / 下一波

- **DNS 重绑定**：网页提取先解析域名做检查、再由 httpx 重新解析去连接，两次之间域名可以换成内网地址。要彻底防住需要固定使用已检查过的 IP 连接（自定义 transport）。
- 子 Worker 用的是全局当前模型（`model_mgr.current_model`），不是父 run 实际用的模型。
- Codex 所在环境跑长命令会被中断，全量测试两波都没跑完；下一波任务书要求它用后台进程跑全量并把结果写进结果文件。

## 实测后追加修复（Atlas Worker）

真机并行测试（两个 Worker 各数一个文件的行数）暴露了三个问题，测试里模型是 mock 所以都没发现：

1. **Worker 根本收不到任务**：`run()` 只从会话记录里读用户消息，Worker 的目标从没保存过，模型只看到系统提示——于是编造技能（`hiring-assessment`）、反问「你的目标是什么」。现在 Worker 模式直接把目标作为用户消息交给模型。
2. **Worker 被用户记忆带偏**：`run()` 会注入长期记忆、反思、目标知识、技能索引、项目上下文，并把 Worker 指令当成用户输入提取记忆。一个 Worker 跑去登录 Twitter，另一个在工作目录里写了 `arxiv_search.py`。新增 `run(worker=True)`：只保留任务、工作目录和规则，不注入、不学习（不提取记忆候选、不写反思）。
3. **执行者名字乱填**：模型把执行者填成 `default`，被当成外部 Agent 而失败；现在不是已配置外部 Agent 的名字一律由 Atlas 执行。
4. Worker 提示词加上「后台运行，不要提问，信息不够按合理假设做完并写明假设」；没有任何输出的 Worker 记为失败，不再显示成功。

修复后实测：两个 Worker 分别给出 3 行 / 5 行，未改文件，中文汇总，34 秒。全量 645 passed。

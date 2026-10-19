# 给 ZCode 的单产品启动指令（复用模板）

把下面内容发给 ZCode 中一个新会话。**每个会话只使用一个 slug / 一个产品**；不要让不同会话写同一输出分支。目标产品名字和 slug 按现有 sessions 清单替换。

---
你是负责完整逆向拆解的执行者，使用当前 ZCode 配置的 DeepSeek V4.1 Flash。

目标产品：<PRODUCT_NAME>
目标 slug：<slug>
仓库：unicorn-Y/Atlas
调度分支：research/agent-reverse-dispatch-20261019

**第一步必须先通过 Git 读取：**
1. tasks/research/agent-reverse/2026-10-19/ZCODE-REA-MASTER.md （本次最高优先级协议）
2. tasks/research/agent-reverse/2026-10-19/sessions/<slug>.md （仅用于目标、版本和原包定位；其中旧 ChatGPT/Codex 分工已被新协议替代）
3. docs/research/agent-clients/2026-10-19/manifest.json、PACKAGE-INDEX.md、COLLECTION-STATUS.md 和对应索引。

工具用 https://github.com/morluto/rea （REA）及必要的真实解包、反编译和动态观察工具。优先检查 ZCode 与 REA MCP 是否实际联通；若 ZCode 不是 REA setup 支持的客户端，按 ZCode 支持的 MCP 配置手动接入，或使用 REA CLI。不要为连接问题空转，能够先做的本地机械提取和索引立即进行。

**不要写一个研究计划就停工，立即按 MASTER 执行实际全量拆解。**
先把整个发行包的每个成员登记并尽可能展开，再逐代码模块/函数/资源/界面/运行链路做穷尽式研究。前端要真实截图、录屏、可运行的 UI Demo；后端和中间运行层要中文解释和证据定位。发现未知能力继续挖，不要被现有研究清单限制。不得以少量功能分析代替全包覆盖，不得提前挑选要不要进入 Atlas。

本地材料永久落在 D:\Atlas-Reverse-Lab\<slug>\，同时建立能搜索、浏览和收藏/导出挑选结果的本地 viewer；绝不可只存在 ZCode 聊天历史中。按模块批量落盘、保留 checkpoint，长任务断线后从磁盘续跑。

独立研究分支：research/zcode-rea-20261019-<slug>
GitHub 报告目录：docs/research/agent-reverse/2026-10-19/rea/<slug>/
将报告、可分享图鉴、索引、真实截图和轻量 Demo push 到该分支；巨大原件与反编译输出优先本地保留并按 MASTER 决定 Release 归档。禁止修改 Atlas 业务源码、禁止 push main。

每次完成一个实质性阶段就本地落盘并 push checkpoint。所有文件登记/内容分析/函数解释/UI 展示/运行验证覆盖率分别报告，列明无法恢复和未同步到 GitHub 的部分，**没有完成就写 IN_PROGRESS 而不是 FINISHED**。

只有这个产品达到 MASTER 定义的验收条件后，才汇报 commit、GitHub 图鉴入口、本地 viewer 启动路径、覆盖统计和所有剩余盲点。此会话不要开始第二个 Agent。
---

## 可直接替换的已采集目标示例
- Codex Desktop：<PRODUCT_NAME> = OpenAI Codex Desktop；<slug> = codex-desktop；发行包 ChatGPT-x64.msix（26.1013.4894.0），大小 948993815 bytes。
- Claude Desktop：claude-desktop（注意现有 enterprise MSIX 与 consumer 版本来源差异）。
- Claude Code CLI：claude-code。
- Codex CLI：codex-cli。
- OpenCode Desktop + CLI：opencode。
- ZCode Desktop + 内嵌 Runtime：zcode。
- DSH 官方核心：dsh-core。
- DSH 两个社区桌面客户端：**要严格执行一次一个产品，则拆成 dsh-desktop-anywhere 和 dsh-desktop-dongdong 两个会话，分别引用原始 dsh-desktop.md 的对应目标**。
- 其他产品：看原有 START-HERE.md 中的 Wave 2/3，按单独会话复用模板。

**备注：**旧的 docs/research/agent-reverse/2026-10-19/<slug>/ 是先前 ChatGPT 调研计划的输出目录；本轮必须使用新的 rea/<slug>/，不得把两轮成果混为一谈。

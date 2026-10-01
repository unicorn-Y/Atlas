# ATLAS-C6：编程专项与界面打磨

> 先读 ROADMAP-TO-PRODUCT、CORE-PARITY（T8、P1、P2 和第 11 节）、EXECUTION-GUIDE。前提：C5 验收通过。

## 本波目标

1. 改完代码自动拿到诊断；`/init`、`/review` 做到 Codex 和 OpenCode 的水平。
2. 长会话不卡。
3. 把主体界面逐项对照 Claude Code、Codex、ZCode 打磨一遍，这是进实测前的最后一波。

## 1. LSP 诊断（T8）

- **来源**：OpenCode `packages/opencode/src/lsp/`（`client.ts`、`server.ts`、`launch.ts`、`language.ts`、`diagnostic.ts`）、`src/tool/lsp.ts`；Hermes `agent/lsp/`、`tools/file_operations_lint.py`。
- **做法**：
  1. 对比两家：支持哪些语言、怎么启动和管理语言服务、怎么把诊断附进工具结果，选强的一家。
  2. 编辑或写入文件后自动取这个文件的诊断，只把这次新增的错误附在工具结果后面（Hermes 的做法）。
  3. 支持 Python（pyright 或 basedpyright）、TypeScript 和 JavaScript（typescript-language-server），其他语言能检测到就用。语言服务缺失时，在设置里提示怎么安装，不自动下载。
  4. Windows 下能正常启动和退出，不能留下孤儿进程。
- **前端**：改动面板里每个文件显示诊断数量；时间线里显示「发现 N 个新问题」。
- **测试**：用假的语言服务器，或者测试机上真有的 pyright，跑通改出一个类型错误 → 结果里出现诊断 → 修好后诊断消失。

## 2. `/init`（P1）

- **来源**：OpenCode `packages/opencode/src/command/template/initialize.txt`；Codex `/init`；Hermes `/init`。
- **做法**：`/init` 扫描项目（结构、构建和测试命令、代码约定），生成或更新 `AGENTS.md`；已有的内容保留，只追加缺的部分；写之前先给用户看 diff。

## 3. `/review`（P2）

- **来源**：Codex `/review`（审当前改动，找问题）；OpenCode `command/template/review.txt`；Hermes `agent/review_engine.py`；GitHub Copilot 9 月的代码审查（会用 shell 验证改动）。
- **做法**：
  1. 对比三家的审查提示词和流程，择优合并。
  2. `/review` 可以审：未提交的改动、某个分支和 main 的差异、某个提交。
  3. 审查跑在一个只读的子 Agent 里，可以执行只读命令和测试来验证自己的判断。
  4. 输出逐条问题，每条带文件、行号、严重程度、修改建议。前端显示成卡片，可以一键「让 Atlas 修」，也可以把整批发回对话。

  和现有的「让审查员检查」合并成同一个功能。

## 4. 长会话性能

- 对话列表做虚拟滚动；时间线里的长输出默认折叠；事件很多时合并渲染。
- 指标（测试机上测，结果写进结果文件）：

| 场景 | 要求 |
| --- | --- |
| 打开 2000 条消息的会话 | 首屏小于 1 秒 |
| 流式输出 | 不掉帧 |
| 切换会话 | 小于 300 毫秒 |
| 内存 | 不随会话数量线性增长 |

## 5. 主体界面打磨

逐项对照 Claude Code 桌面端、Codex 桌面端、ZCode 的同类界面打磨下面这些：

1. 输入框；
2. 消息和工具步骤的显示；
3. 改动面板；
4. 终端面板；
5. 文件面板；
6. 权限菜单；
7. 模型菜单；
8. 状态栏；
9. 斜杠菜单；
10. 设置页；
11. 错误和重试；
12. 空状态；
13. 快捷键。

要求：
- 每一项写出「对方哪里做得好 → Atlas 怎么改」，并附截图。
- 三套主题都要截图检查。
- 中文文案统一：白话，不出现英文报错原文。原文可以放在「详情」里。

## 6. 测试和交付

- 每节各自的测试；性能指标的数字；界面打磨的对照清单和改前改后截图。
- 更新 CORE-PARITY 和 PARITY。到这一波结束，CORE-PARITY 应当**全部是 ✔**，有遗漏的列出来。

## 验收清单

1. LSP 在 Windows 上不留孤儿进程。
2. 性能指标都达到。
3. CORE-PARITY 全部 ✔。
4. 已有功能不倒退。

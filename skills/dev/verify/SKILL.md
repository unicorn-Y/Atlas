---
name: verify
description: "提交前验证约定：跑焦点测试与类型检查，并明确说出哪些没验证。触发: verify、提交前检查、before commit。"
version: 1.0.0
category: dev
triggers:
  - pattern: "verify|验证一下|提交前|before commit|pre-commit|提交检查"
  - command: "/verify"
author: Atlas
tags: [verification, testing, typecheck, quality-gate, commit]
related_skills: [coding-discipline, systematic-debugging]
---

# verify — 提交前验证

约定（对齐 Claude Code 2.1.286）：**只要存在名为 verify 的技能，提交（commit）前必须执行一次**，并向用户给出简短、诚实的验证小结。

## 步骤

### 1. 焦点测试（只跑受影响的）

针对本次触碰的文件，运行直接对应的测试文件与其紧邻测试，不跑全量套件：

- Python（Atlas 仓库约定）：
  `cd core && .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider <触碰的测试文件 + 直接相邻测试>`
- 找不到同名测试文件时，退到所在包/直接导入方的相邻测试；两者都没有时，记录"无对应测试"。
- 前端/其他语言：用该仓库已有的最窄测试命令（vitest/jest 单文件等）。

### 2. 类型检查 / 静态检查

对触碰文件运行可用的最快检查（Python: ruff / mypy；TS: tsc --noEmit）。项目没配置就写"未配置，跳过"，不要现搭工具链。

### 3. 汇报格式（简短）

- 已验证：`<命令>` → `<结果（通过数/失败数）>`
- 未验证：明确列出没跑到的部分——全量测试、运行时手工行为、前端视觉、集成/外部服务、性能等。

## 红线

- 不允许只说"验证通过"而不列出实际跑过的命令与结果。
- 不允许把"没来得及跑"留成沉默——必须写进"未验证"。
- 有失败先修复；修不了就明确说明阻塞原因，再决定是否提交。

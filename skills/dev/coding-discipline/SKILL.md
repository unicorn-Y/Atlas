---
name: coding-discipline
description: "编码纪律：先想再写，外科手术式改动，小步验证。"
version: 1.0.0
category: dev
triggers:
  - pattern: "写代码|改代码|重构|implement|refactor|编码"
  - command: "/discipline"
author: Atlas
tags: [coding, discipline, best-practices, quality]
related_skills: [systematic-debugging]
---

# 编码纪律

写代码前触发。所有编码工作必须遵守以下纪律。

## Instructions

### 先想再写
- 动手前列假设、弄清改动范围与要改的文件
- 有多种理解就摆出来不默默选一个
- 不清楚就停下提问

### 简洁优先
- 写解决问题的最少代码
- 不加没要求的功能/抽象/可配置性
- 不为不可能场景写错误处理

### 外科手术式改动
- 只碰必须碰的，不改相邻代码/注释/格式
- 不重构没坏的东西
- 匹配现有风格
- 清掉自己改动产生的孤儿（未用 import/变量/函数）

### 小步改、一次一件事
- 改完立刻本地验证（能编译就跑，能测试就跑，能 lint 就跑）

### 代码质量
- 用类型提示、明确错误处理、规范命名
- 与现有风格一致
- 不引入无用依赖

### 省 Token
- 先读关键文件再写
- diff 只看改动
- 聚合多次小操作
- 不重复读同一文件

### 不伪造
- 没实测通过的不说完成
- 报错带真实输出
- 改完给验证证据

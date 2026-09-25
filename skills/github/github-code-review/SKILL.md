---
name: github-code-review
description: "Review PRs: diffs, inline comments, structured feedback."
version: 1.0.0
category: github
triggers:
  - pattern: "review.*pr|code.?review|审.*代码|代码审查|检查.*代码"
  - pattern: "review.*before.*push|推送前.*检查"
  - command: "/review"
dependencies:
  mcp_servers:
    - git
  commands:
    - gh
author: Atlas
tags: [github, code-review, pull-requests, quality]
related_skills: [github-pr-workflow, github-issues]
---

# GitHub Code Review

Perform code reviews on local changes before pushing, or review open PRs on GitHub.

## When to Use

- 用户要 review PR 或本地改动
- 推送前代码检查
- NOT for: 创建/合并 PR（用 github-pr-workflow）

## Prerequisites

- `gh` CLI authenticated or `$GITHUB_TOKEN` set
- Inside a git repository

## Instructions

### 1. Reviewing Local Changes (Pre-Push)

```bash
# Staged changes
git diff --staged

# All changes vs main
git diff main...HEAD

# File names only
git diff main...HEAD --name-only

# Stat summary
git diff main...HEAD --stat
```

**Common checks:**

```bash
# Debug statements left behind
git diff main...HEAD | grep -n "print(\|console\.log\|TODO\|FIXME\|HACK\|debugger"

# Secrets or credential patterns
git diff main...HEAD | grep -in "password\|secret\|api_key\|token.*=\|private_key"

# Merge conflict markers
git diff main...HEAD | grep -n "<<<<<<\|>>>>>>\|======="
```

### 2. Reviewing a PR on GitHub

**With gh:**

```bash
gh pr view 123
gh pr diff 123
gh pr checks 123
gh pr checkout 123
```

**With curl:**

```bash
PR_NUMBER=123
curl -s -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/$OWNER/$REPO/pulls/$PR_NUMBER

curl -s -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/$OWNER/$REPO/pulls/$PR_NUMBER/files
```

### 3. Leaving Review Comments

**With gh:**

```bash
gh pr review 123 --approve --body "LGTM!"
gh pr review 123 --request-changes --body "See inline comments."
gh pr review 123 --comment --body "Some suggestions."
```

**With curl (atomic multi-comment review):**

```bash
HEAD_SHA=$(curl -s -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/$OWNER/$REPO/pulls/$PR_NUMBER \
  | python -c "import sys,json; print(json.load(sys.stdin)['head']['sha'])")

curl -s -X POST \
  -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/$OWNER/$REPO/pulls/$PR_NUMBER/reviews \
  -d "{
    \"commit_id\": \"$HEAD_SHA\",
    \"event\": \"REQUEST_CHANGES\",
    \"body\": \"Code review\",
    \"comments\": [
      {\"path\": \"src/auth.py\", \"line\": 45, \"body\": \"Use parameterized queries.\"}
    ]
  }"
```

### Review Output Format

```
## Code Review Summary

### Critical
- **src/auth.py:45** — SQL injection: user input passed directly to query.

### Warnings
- **src/models/user.py:23** — Password stored in plaintext.

### Suggestions
- **src/utils/helpers.py:8** — Duplicates logic in core/utils.py:34.

### Looks Good
- Clean separation of concerns in the middleware layer
```

### Review Checklist

**Correctness** — Does the code do what it claims? Edge cases handled?
**Security** — No hardcoded secrets? Input validation? Auth checks?
**Code Quality** — Clear naming? DRY? Single responsibility?
**Testing** — New code paths tested? Error cases covered?
**Performance** — No N+1 queries? No blocking in async code?
**Documentation** — Public APIs documented? Non-obvious logic explained?

### Decision Guide

- **Approve** — no critical/warning issues
- **Request Changes** — any critical or warning issue
- **Comment** — observations only, nothing blocking

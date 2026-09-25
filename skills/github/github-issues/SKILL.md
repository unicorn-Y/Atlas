---
name: github-issues
description: "Create, triage, label, assign GitHub issues via gh or REST."
version: 1.0.0
category: github
triggers:
  - pattern: "issue|bug.*report|提.*issue|创建.*issue"
  - pattern: "triage|分类.*issue"
  - command: "/issue"
dependencies:
  mcp_servers:
    - git
  commands:
    - gh
author: Atlas
tags: [github, issues, project-management, bug-tracking, triage]
related_skills: [github-pr-workflow, github-code-review]
---

# GitHub Issues Management

Create, search, triage, and manage GitHub issues.

## When to Use

- 创建、查看、管理 GitHub Issues
- Issue 分类和分配
- NOT for: PR 相关操作（用 github-pr-workflow）

## Prerequisites

- `gh` CLI authenticated or `$GITHUB_TOKEN` set
- Inside a git repo with a GitHub remote

## Instructions

### 1. Viewing Issues

**With gh:**

```bash
gh issue list
gh issue list --state open --label "bug"
gh issue list --assignee @me
gh issue view 42
```

**With curl:**

```bash
curl -s -H "Authorization: token $GITHUB_TOKEN" \
  "https://api.github.com/repos/$OWNER/$REPO/issues?state=open&per_page=20"
```

### 2. Creating Issues

**With gh:**

```bash
gh issue create \
  --title "Login redirect ignores ?next= parameter" \
  --body "## Description\nAfter login, users always land on /dashboard.\n\n## Steps to Reproduce\n1. Navigate to /settings while logged out\n2. Get redirected to /login?next=/settings\n3. Log in\n4. Actual: redirected to /dashboard" \
  --label "bug,backend" \
  --assignee "username"
```

### Bug Report Template

```
## Bug Description
<What's happening>

## Steps to Reproduce
1. <step>

## Expected Behavior
<What should happen>

## Actual Behavior
<What actually happens>
```

### 3. Managing Issues

```bash
# Labels
gh issue edit 42 --add-label "priority:high,bug"
gh issue edit 42 --remove-label "needs-triage"

# Assignment
gh issue edit 42 --add-assignee @me

# Commenting
gh issue comment 42 --body "Root cause found. Working on fix."

# Close/Reopen
gh issue close 42
gh issue reopen 42
```

### 4. Linking Issues to PRs

Keywords in PR body auto-close issues on merge:
```
Closes #42
Fixes #42
Resolves #42
```

### 5. Triage Workflow

1. List untriaged: `gh issue list --label "needs-triage" --state open`
2. Read and categorize each issue
3. Apply labels and priority
4. Assign if owner is clear
5. Comment with triage notes

## Quick Reference

| Action | gh | curl endpoint |
|--------|-----|--------------|
| List issues | `gh issue list` | `GET /repos/{o}/{r}/issues` |
| View issue | `gh issue view N` | `GET /repos/{o}/{r}/issues/N` |
| Create issue | `gh issue create` | `POST /repos/{o}/{r}/issues` |
| Add labels | `gh issue edit N --add-label` | `POST /issues/N/labels` |
| Comment | `gh issue comment N --body` | `POST /issues/N/comments` |
| Close | `gh issue close N` | `PATCH /issues/N` |
| Search | `gh issue list --search` | `GET /search/issues?q=` |

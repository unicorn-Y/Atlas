---
name: github-pr-workflow
description: "GitHub PR lifecycle: branch, commit, open, CI, merge."
version: 1.0.0
category: github
triggers:
  - pattern: "pr|pull.?request|合并请求|提PR"
  - pattern: "开.*分支|创建.*分支|新分支"
  - command: "/pr"
dependencies:
  mcp_servers:
    - git
  commands:
    - gh
author: Atlas
tags: [github, pr, git, ci, automation, merge]
related_skills: [github-code-review, github-issues]
---

# GitHub Pull Request Workflow

Complete guide for managing the PR lifecycle. Each section shows the `gh` way first, then the `git` + `curl` fallback.

## When to Use

- 用户要创建 PR 或合并代码
- 用户要查看 PR 状态或 CI 结果
- 用户要自动修复 CI 失败
- NOT for: 创建 issue（用 github-issues 技能）

## Prerequisites

- `gh` CLI authenticated (`gh auth status`)
- Inside a git repo with GitHub remote

### Quick Auth Detection

```bash
if command -v gh &>/dev/null && gh auth status &>/dev/null; then
  AUTH="gh"
else
  AUTH="git"
  if [ -z "$GITHUB_TOKEN" ]; then
    echo "Warning: No GITHUB_TOKEN set and gh not available"
  fi
fi
echo "Using: $AUTH"
```

### Extracting Owner/Repo from the Git Remote

```bash
REMOTE_URL=$(git remote get-url origin)
OWNER_REPO=$(echo "$REMOTE_URL" | sed -E 's|.*github\.com[:/]||; s|\.git$||')
OWNER=$(echo "$OWNER_REPO" | cut -d/ -f1)
REPO=$(echo "$OWNER_REPO" | cut -d/ -f2)
echo "Owner: $OWNER, Repo: $REPO"
```

---

## Instructions

### 1. Branch Creation

```bash
git fetch origin
git checkout main && git pull origin main
git checkout -b feat/add-user-authentication
```

Branch naming conventions:
- `feat/description` — new features
- `fix/description` — bug fixes
- `refactor/description` — code restructuring
- `docs/description` — documentation
- `ci/description` — CI/CD changes

### 2. Making Commits

Commit message format (Conventional Commits):
```
type(scope): short description

Longer explanation if needed. Wrap at 72 characters.
```

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `ci`, `chore`, `perf`

### 3. Pushing and Creating a PR

```bash
git push -u origin HEAD
```

**With gh:**

```bash
gh pr create \
  --title "feat: add JWT-based user authentication" \
  --body "## Summary\n- Adds login and register API endpoints\n\nCloses #42"
```

Options: `--draft`, `--reviewer user1,user2`, `--label "enhancement"`, `--base develop`

**With curl:**

```bash
BRANCH=$(git branch --show-current)
curl -s -X POST \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  https://api.github.com/repos/$OWNER/$REPO/pulls \
  -d "{
    \"title\": \"feat: add JWT-based user authentication\",
    \"body\": \"Closes #42\",
    \"head\": \"$BRANCH\",
    \"base\": \"main\"
  }"
```

### 4. Monitoring CI Status

**With gh:**

```bash
gh pr checks          # one-shot check
gh pr checks --watch  # watch until all checks finish
```

**With curl:**

```bash
SHA=$(git rev-parse HEAD)
curl -s \
  -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/$OWNER/$REPO/commits/$SHA/status
```

### 5. Auto-Fixing CI Failures

**With gh:**

```bash
gh run list --branch $(git branch --show-current) --limit 5
gh run view <RUN_ID> --log-failed
```

Auto-fix loop:
1. Check CI status → identify failures
2. Read failure logs → understand the error
3. Fix the code
4. `git add . && git commit -m "fix: ..." && git push`
5. Wait for CI → re-check status
6. Repeat if still failing (up to 3 attempts, then ask the user)

### 6. Merging

**With gh:**

```bash
gh pr merge --squash --delete-branch
# Or enable auto-merge:
gh pr merge --auto --squash --delete-branch
```

**With curl:**

```bash
PR_NUMBER=<number>
curl -s -X PUT \
  -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/$OWNER/$REPO/pulls/$PR_NUMBER/merge \
  -d "{ \"merge_method\": \"squash\" }"
```

## Quick Reference

| Action | gh | curl |
|--------|-----|-----------|
| List my PRs | `gh pr list --author @me` | `GET /repos/{o}/{r}/pulls?state=open` |
| View PR diff | `gh pr diff` | `git diff main...HEAD` |
| Add comment | `gh pr comment N --body "..."` | `POST /issues/N/comments` |
| Request review | `gh pr edit N --add-reviewer user` | `POST /pulls/N/requested_reviewers` |
| Close PR | `gh pr close N` | `PATCH /pulls/N` |
| Check out PR | `gh pr checkout N` | `git fetch origin pull/N/head:pr-N` |

---
name: systematic-debugging
description: "4-phase root cause debugging: understand bugs before fixing."
version: 1.0.0
category: dev
triggers:
  - pattern: "debug|调试|排查|bug|报错|崩溃|crash"
  - pattern: "root.?cause|根因|为什么.*失败"
  - command: "/debug"
author: Atlas
tags: [debugging, troubleshooting, problem-solving, root-cause, investigation]
related_skills: [coding-discipline]
---

# Systematic Debugging

## Overview

Random fixes waste time and create new bugs. Quick patches mask underlying issues.

**Core principle:** ALWAYS find root cause before attempting fixes. Symptom fixes are failure.

## The Iron Law

```
NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST
```

If you haven't completed Phase 1, you cannot propose fixes.

## The Feedback Loop Rule

Before reading code to build a theory, create a **tight** command that goes red on the user's exact symptom and green when the bug is fixed. A tight loop is fast, deterministic, agent-runnable, and specific enough to catch this bug.

## When to Use

- Test failures, production bugs, unexpected behavior
- Performance problems, build failures, integration issues
- **Especially when:** under time pressure, "just one quick fix" seems obvious, you've tried multiple fixes

## The Four Phases

### Phase 1: Root Cause Investigation

**BEFORE attempting ANY fix:**

1. **Read Error Messages Carefully** — Don't skip. Read stack traces completely. Note line numbers, file paths, error codes.

2. **Build a Tight Feedback Loop** — Can you trigger the exact symptom with one command? Is it deterministic? Try in order:
   - Failing test at the seam
   - HTTP script / curl against dev server
   - CLI invocation with fixture input
   - Headless browser script
   - Throwaway harness for the smallest useful slice

3. **Check Recent Changes**
   ```bash
   git log --oneline -10
   git diff
   git log -p --follow src/problematic_file.py | head -100
   ```

4. **Gather Evidence in Multi-Component Systems** — For EACH component boundary: log what enters, log what exits, verify config propagation.

5. **Trace Data Flow** — Where does the bad value originate? Keep tracing upstream until you find the source. Fix at the source.

**Phase 1 Checklist:**
- [ ] Error messages fully read
- [ ] Tight loop command exists and has been run
- [ ] Loop is red-capable for the exact symptom
- [ ] Recent changes reviewed
- [ ] Evidence gathered
- [ ] Root cause hypotheses can be stated

**STOP:** Do not proceed until you understand WHY.

### Phase 2: Pattern Analysis

1. **Minimize Reproduction** — Shrink to smallest scenario that goes red
2. **Find Working Examples** — Locate similar working code in codebase
3. **Compare** — What's different between working and broken?
4. **Understand Dependencies** — Config, environment, assumptions

### Phase 3: Hypothesis and Testing

1. **Form 3-5 Ranked Hypotheses** — Each with testable prediction
2. **Test Minimally** — One variable at a time. Prefer debugger over logs.
3. **Verify** — Worked? → Phase 4. Didn't? → NEW hypothesis. Don't pile fixes.

### Phase 4: Implementation

1. **Create Failing Test** — Regression test MUST exist before fixing
2. **Single Fix** — ONE change. No "while I'm here" improvements.
3. **Verify**
   ```bash
   pytest tests/test_module.py::test_regression -v  # specific
   pytest tests/ -q                                  # no regressions
   ```
4. **Rule of Three** — If 3+ fixes failed, STOP. Question the architecture. Discuss with user.

## Red Flags — STOP and Follow Process

- "Quick fix for now, investigate later"
- "Just try changing X and see"
- "I don't fully understand but this might work"
- Proposing solutions before tracing data flow
- Each fix reveals new problems in different places (→ architectural issue)

## Quick Reference

| Phase | Key Activities | Success Criteria |
|-------|---------------|------------------|
| 1. Root Cause | Read errors, reproduce, trace data | Understand WHAT and WHY |
| 2. Pattern | Find working examples, compare | Know what's different |
| 3. Hypothesis | Form theory, test minimally | Confirmed or new hypothesis |
| 4. Implementation | Regression test, fix root cause | Bug resolved, all tests pass |

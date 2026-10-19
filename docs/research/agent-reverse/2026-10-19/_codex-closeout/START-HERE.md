# Atlas Agent Reverse Research Closeout — 2026-10-19

**Status: all eight lane reports have been updated and pushed; all eight remain PARTIAL by their own evidence limits.** This closeout records the pushed branch tips and starts an independent GPT-6 review. It does not claim exhaustive reverse engineering or Atlas feature parity.

Repository: `unicorn-Y/Atlas`

Dispatch branch: `research/agent-reverse-dispatch-20261019` at `9cab2a89b2aa737550cb61c17af544a1c2105bc8`

Atlas comparison baseline: `main` at `aa6196f550098cc46081dc6db2c376cb87ddffa5`.

The lane investigations verified and unpacked their exact requested Release assets, traced package/source mechanisms, and compared each lane to the same Atlas `main` snapshot. The desktop applications were not run. Bounded CLI `--version`/`--help` probes were run for Claude Code, Codex CLI, OpenCode, and DeepSeek Harness CLI; none constitutes an authenticated Agent-turn acceptance. Static bundle/parser integrity mismatches and analysis timeouts remain recorded as unknowns, not attributed causes.

## Read next

1. [BRANCH-STATUS.md](BRANCH-STATUS.md) — each pushed lane tip, report entry, packages, ledger S/R counts and key discoveries.
2. [UNRESOLVED.md](UNRESOLVED.md) — lane-specific unknowns and cross-cutting limits.
3. [REVIEW-ENTRY.md](REVIEW-ENTRY.md) — review checklist and exact branch/file entry points for GPT-6.

No Atlas business source was changed. The independent lane commits contain research reports and bounded evidence indexes/excerpts only; original vendor archives and full extraction trees were kept in local scratch. The only local untracked scratch is outside the closeout commit and is not part of the pushed deliverable.

Every lane report explicitly distinguishes package/source observations (S), runtime observations (R), declarations (D), inferences (I), and unresolved items (U). The ledger counts below are **rows with a static/runtime marker**, not a claim that all mechanisms in a product have been enumerated. The open questions in each START-HERE and EVIDENCE-INDEX remain authoritative.

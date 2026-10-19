# GPT-6 review entry

Review these eight remote branches and their lane report directories. Compare every claim to the evidence index and preserved package hashes/paths. The branch-status rows are navigation, not a replacement for per-lane review.

## Review gates

1. Confirm each lane `HEAD` still equals its published GitHub branch tip and that commits only change the lane's research directory (no Atlas business source, no full vendor package/source upload).
2. Verify asset identities against the pinned Release `manifest.json` and the lane's `EVIDENCE-INDEX.md`; check that exact product/version and source-snapshot differences stay explicit.
3. For each new finding, follow at least one representative entry from real package file/path/hash/offset through its code path to UI/IPC/RPC/host/state. Keep strings/symbol names alone below S-level behavior proof.
4. Check Atlas claims against the same current `main@aa6196f550098cc46081dc6db2c376cb87ddffa5` paths in `ATLAS-GAP.md`. A related but architecturally different Atlas feature is not “missing”; verify “UI only”, “API only”, incomplete wiring and mechanism mismatch distinctions.
5. Inspect all declared U items and integrity mismatches. Reject any upgrade from static S to runtime R without exact operation evidence. No lane claims complete product coverage.
6. Review dependency/license reuse notes before proposing code absorption; no code implementation is part of this handoff.

## Branch and report list

| Product | Branch | Review path |
|---|---|---|
| Claude Desktop / Cowork | `research/agent-reverse-20261019-claude-desktop` | `docs/research/agent-reverse/2026-10-19/claude-desktop/` |
| Claude Code CLI | `research/agent-reverse-20261019-claude-code` | `docs/research/agent-reverse/2026-10-19/claude-code/` |
| Codex Desktop | `research/agent-reverse-20261019-codex-desktop` | `docs/research/agent-reverse/2026-10-19/codex-desktop/` |
| Codex CLI / Code Mode | `research/agent-reverse-20261019-codex-cli` | `docs/research/agent-reverse/2026-10-19/codex-cli/` |
| OpenCode v2 / v1 source comparison | `research/agent-reverse-20261019-opencode` | `docs/research/agent-reverse/2026-10-19/opencode/` |
| ZCode Desktop / Embedded Runtime | `research/agent-reverse-20261019-zcode` | `docs/research/agent-reverse/2026-10-19/zcode/` |
| DeepSeek Harness Core | `research/agent-reverse-20261019-dsh-core` | `docs/research/agent-reverse/2026-10-19/dsh-core/` |
| DeepSeek Harness community Desktop projects | `research/agent-reverse-20261019-dsh-desktop` | `docs/research/agent-reverse/2026-10-19/dsh-desktop/` |

This closeout branch is independent and based on `research/agent-reverse-dispatch-20261019`; it contains no lane changes and should not be merged automatically. GPT-6 should return specific findings by branch/path/line and either accept the bounded handoff or request targeted amendments.

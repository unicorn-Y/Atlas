# CODEX-ATLAS-P15C-FIX-INTEGRITY-APPROVAL-VERSION Result

STATUS: IMPLEMENTED; REVIEW REQUIRED FOR LIVE PROVIDER HASH GATE
WORKER: Luna
BASE_HEAD: 5a193059d5c86400b6fe9937156e447551e1d978

## Changes

- Added a canonical payload SHA-256 helper that hashes normalized relative POSIX paths and UTF-8 contents in deterministic case-insensitive path order. Computed hashes, provider verification, and Registry provenance use this value. Remote hash mismatches remain BLOCK.
- Switched skills.sh inspection to its snapshot download endpoint before the authenticated v1 detail fallback. The v1 401 path continues through the public GitHub fallback.
- Added pending acquisition state, server-created approval events, short-lived single-use installation authorization, acquisition/hash binding, expiry checks, WARN second confirmation, and rejection of client-supplied approval claims. Registry provenance records the server event ID and approved timestamp. Authorization is retained only as a hash in volatile server memory.
- Normalized a missing manifest version to `0.0.0`; malformed supplied versions still fail validation.
- Rejects recursive GitHub Trees responses marked `truncated`.
- Serializes concurrent same-identity installs and preserves existing Registry entries and skill directories.
- Updated Skill Center to request approval from the server and then consume the returned one-time authorization.

## Verification

- Backend P15A/P15B/P15C regression suites: **84 passed** (`test_skill_acquisition.py`, `test_skill_registry.py`, `test_skill_registry_api.py`, `test_skill_discovery.py`, `test_skills.py`).
- Frontend tests: **13 passed** across 4 test files.
- Production frontend build: **passed**. Vite emitted its existing large-chunk advisory (557.15 kB JS bundle).
- Ruff on changed acquisition and test modules: **passed**.
- Full-file Ruff on `core/atlas/server.py` still reports 7 findings in untouched pre-existing regions (3 undefined `log` references, 3 line-length findings, and 1 unused `skill` assignment); no reported finding is on the new server changes.
- `git diff --check`: **passed**.
- Smoke testing only inspected public remote content; no skill was installed into the production skills directory.

## Live Network Smoke

All checks were performed on 2026-09-27 without a `VERCEL_OIDC_TOKEN` in the worker environment.

| Check | Endpoint | Result |
|---|---|---|
| skills.sh public search | `GET https://skills.sh/api/search?q=find+skills&limit=50` | HTTP 200; 50 results |
| Selected public result | `vercel-labs/skills/find-skills` | Public result selected |
| v1 detail | `GET https://skills.sh/api/v1/skills/vercel-labs/skills/find-skills` | HTTP 401; this environment has no required Vercel OIDC token |
| v1 audit | `GET https://skills.sh/api/v1/skills/audit/vercel-labs/skills/find-skills` | HTTP 200 in this environment |
| Snapshot download | `GET https://skills.sh/api/download/vercel-labs/skills/find-skills` | HTTP 200; one file returned |
| Versionless fallback fixture | GitHub Trees API plus `raw.githubusercontent.com/vercel-labs/skills/main/skills/find-skills/SKILL.md` | HTTP 200; version normalized to `0.0.0`; one file inspected |
| Public GitHub acquisition | `https://github.com/vercel-labs/skills`, path `skills/find-skills` | HTTP 200 through repository/tree/raw endpoints; one file inspected |
| Real multi-file provider payload | `GET https://skills.sh/api/download/vercel-labs/agent-skills/vercel-react-best-practices` | HTTP 200; 76 files; provider hash `ca7b0c0c6e5f2750043f7f0cd72d16ac4e2abc48f9b5500d047a4b77a2506212`; Atlas/current upstream algorithm hash `3219a1944e404ffc14d1d9d6aef6dd2e3855b81387ee0a044ccbfe14d34c2357`; correctly BLOCKed as mismatch |

The versionless snapshot endpoint also returned HTTP 200, but its remote hash did not match the downloaded file (`b146008599c31057cef1c145774cea5d5afb30e8f43fa802e47a4b461419aaaf` versus Atlas `913b9d37d0d54047dd65222bb8c67b2bf04e3cb87dcad1729068d7a8b2c8c396`). A separate scan of 12 public multi-file snapshots found the same mismatch. The remote hashes were not ignored or bypassed; mismatching acquisitions remain BLOCK. This means live acceptance criterion 1 (a real multi-file provider hash passes) is **not met** with the provider responses available in this environment, so the P15C queue must remain blocked pending provider-side/hash-source resolution.

Automated tests independently calculate and verify the expected multi-file digest and cover a matching provider hash and a mismatching hash. The live service discrepancy is recorded above for review; it is not represented as a passing live hash check.

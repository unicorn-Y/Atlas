# CODEX-ATLAS-P7K-SKILL-CLEANUP-AND-GOVERNANCE Result

## RESULT

Stabilized Atlas-owned skill discovery, added clear frontmatter validation and deterministic duplicate resolution, documented validation rules, and excluded the runtime-generated schedule file from Git.

## HEAD values

- Taskbook `CODE_BASE_HEAD`: `016bb83cadf9561451d50b728c0f3aa81a9a2a6a`
- Actual starting `BASE_HEAD` after pull: `33c79249b1e793e34867654a970c198e4b5da53c`
- Implementation commit pushed to `origin/main`: `4aeb231`

## Changes

- The skill manager now scans only `skills/<category>/<skill-name>/SKILL.md` and sorts those paths case-insensitively before building the index. Duplicate names therefore select the same path every run; the existing duplicate warning identifies both paths.
- Invalid skill metadata is skipped with a `skills.invalid_metadata` warning and a field-specific reason. YAML errors retain their parser diagnostic.
- Added tests for malformed metadata, stable duplicate selection, canonical path filtering, repository-owned skill discovery, and UTF-8 coding-discipline content.
- Documented the accepted skill metadata and discovery rules in `skills/SKILL-FORMAT.md`.
- Added `data/schedules.toml` to `.gitignore`; the existing runtime-generated file was left untouched.
- Cowork-injected skill files outside the canonical directory layout were left untouched and are no longer included in Atlas discovery.
- `skills/dev/coding-discipline/SKILL.md` already contains readable UTF-8 Chinese text in the pulled baseline; the regression test confirms the text and absence of replacement characters.

## Tests and checks

- `python -m pytest tests/test_skills.py tests/test_agent_capabilities.py -q --tb=short -p no:cacheprovider` — 45 passed.
- `python -m ruff check atlas/skills/__init__.py tests/test_skills.py` — passed.
- `git diff --check` and staged diff check — passed.
- Full core suite is not green on this Windows environment: `tests/test_config.py::TestAtlasConfigFromData::test_db_path_absolute` expects POSIX `Path('/absolute/path/test.db')`, while Windows resolves it as `D:/absolute/path/test.db`. The failure is outside this task's scope.

## Changed files

- `.gitignore`
- `core/atlas/skills/__init__.py`
- `core/tests/test_skills.py`
- `skills/SKILL-FORMAT.md`
- `tasks/results/CODEX-ATLAS-P7K-SKILL-CLEANUP-AND-GOVERNANCE.result.md`

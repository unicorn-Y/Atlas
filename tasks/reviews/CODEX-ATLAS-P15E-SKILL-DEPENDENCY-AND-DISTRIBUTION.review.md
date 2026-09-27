# CODEX-ATLAS-P15E-SKILL-DEPENDENCY-AND-DISTRIBUTION Review

STATUS: REWORK_REQUIRED

REVIEWED_HEAD: 1fa1c29783304b5c866b06d8d92b9b63a8c89f03
IMPLEMENTATION_COMMIT: ecbe0aac7784513b7c5486b9d02fa90990d1e281
RESULT_COMMIT: 1fa1c29783304b5c866b06d8d92b9b63a8c89f03

## Decision

P15E is NOT accepted yet.

The worker delivered a substantial implementation and the reported regression suite is green, but direct code review found two acceptance-blocking semantic gaps that the current tests do not cover.

Do not advance to P16 or E01-E04.

## Acceptance blockers

### 1. Standard structured dependencies packages can pass review and then become permanently unknown

The repository's canonical Skill format documents a mapping such as:

    dependencies:
      python_packages:
        - requests
      commands:
        - ffmpeg

It also supports the P15E extension of named version constraints.

However, core/atlas/skills/acquisition.py::_parse_manifest() does this when dependencies is a mapping:

    requirements = [f"{key}: {value}" for key, value in requirements.items()]

That turns a structured declaration into strings such as:

    python_packages: ['requests']

The dependency parser treats list strings as the legacy kind:name@constraint syntax. Therefore the resulting declaration is parsed as unknown, not as a Python package or command dependency.

inspect_skill_package() then compares the package manifest against the same malformed normalization, so the package can pass inspection even though the installed Registry metadata contains an unusable dependency declaration. Activation subsequently sees unknown and blocks the Skill.

This is a false-green path in the new distribution feature and directly conflicts with the documented Skill format plus P15E's first-class dependency contract.

Required fix:

- introduce one canonical dependency normalization path;
- preserve structured dependencies mappings instead of stringifying them;
- make package manifest comparison use the same canonical representation;
- ensure installed Registry requirements remain consumable by dependency_preflight;
- cover the documented mapping form with and without version constraints;
- prove an imported package with satisfied dependencies can actually activate.

### 2. Package import treats any existing Skill name as a conflict, not only the same name+version identity

The P15E contract says same name + version conflicts must not overwrite existing Registry/filesystem state.

Current code is broader:

- /api/skill-packages/inspect sets name_conflict when any Registry record has the same name;
- the Skill Center disables package import whenever name_conflict is true;
- /api/skills/lifecycle/decision for package install rejects when any Registry record has the same name.

This means an incoming package such as foo@2.0.0 cannot be handled when foo@1.0.0 is already installed.

The Registry itself is versioned by (name, version), and P15D already has an audited update/downgrade lifecycle. Therefore the package path must distinguish:

- exact same name + version: deterministic conflict, no overwrite;
- same name, different version: not an identity collision. It should either enter the existing lifecycle update/downgrade path with explicit review/approval, or present a deterministic update-required state without mutating anything. It must not be silently overwritten.

Required fix:

- separate exact_version_conflict from same_name_existing;
- preserve the existing version and filesystem on conflict/failure;
- route a different package version through the existing audited lifecycle update/downgrade mechanism, or provide an explicit update-required result if that is the intentionally bounded behavior;
- add backend and frontend regression coverage for same-name/different-version packages;
- retain the exact same-version conflict test.

## Validation reviewed

Worker reports:

- P15A-P15E regression/new tests: 143 passed
- frontend: 14 passed
- backend adapter: 8 passed
- production build: passed
- modified-file Ruff: passed
- git diff --check: passed
- isolated HTTP smoke: passed
- local/remote HEAD: 1fa1c29783304b5c866b06d8d92b9b63a8c89f03

Those results are accepted as execution evidence, but they do not cover the two cases above.

## Non-blocking observations

- Dependency plans are currently process-memory state. A restart can discard a pending plan. The P15E taskbook did not require durable dependency-plan persistence, so this is not an acceptance blocker for this rework.
- The Python adapter is deliberately test-substituted rather than performing a real package installation in the worker environment; the taskbook permits that validation boundary.

## Queue decision

P15E remains incomplete pending the bounded fixes above.

Next READY task:
CODEX-ATLAS-P15E-FIX1-DEPENDENCY-CANONICALIZATION-AND-VERSIONED-PACKAGE-IMPORT

P16 and E01-E04 remain BLOCKED.

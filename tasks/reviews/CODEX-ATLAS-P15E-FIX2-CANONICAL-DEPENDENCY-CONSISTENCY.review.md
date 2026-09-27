# CODEX-ATLAS-P15E-FIX2-CANONICAL-DEPENDENCY-CONSISTENCY Review

STATUS: REWORK_REQUIRED

REVIEWED_HEAD: 2bb0cbb63cad2e116b012eddd84fb8bdb97eee6a
PREVIOUS_REVIEW: tasks/reviews/CODEX-ATLAS-P15E-FIX1-DEPENDENCY-CANONICALIZATION-AND-VERSIONED-PACKAGE-IMPORT.review.md
IMPLEMENTATION_COMMIT: 2bb0cbb63cad2e116b012eddd84fb8bdb97eee6a
RESULT_FILE: tasks/results/CODEX-ATLAS-P15E-FIX2-CANONICAL-DEPENDENCY-CONSISTENCY.result.md

## Decision

P15E-FIX2 is NOT accepted yet.

The specific FIX1 blockers are substantially fixed:

- modern dependencies and legacy requirements are merged through one canonical helper;
- deterministic de-duplication produces canonical {kind,name,requested} records;
- package inspection compares the package declaration against the complete canonical SKILL.md dependency set;
- Registry persistence for imported packages stores the canonical dependency set;
- SkillManager activation/preflight uses the canonical dependency contract;
- the remote review UI now formats canonical dependency records instead of joining objects directly.

However, direct source inspection found one remaining acceptance-blocking path that still persists a non-canonical dependency set, plus one related serialization inconsistency.

Do not advance to P16 or E01-E04.

## Acceptance blocker: startup local Skill registration still persists raw dependencies

core/atlas/server.py lifespan still registers missing local Skills with:

    "requirements": skill.dependencies,

SkillInfo now contains both:

- dependencies: the raw modern dependencies mapping from SKILL.md;
- dependency_contract: the merged canonical dependencies + requirements representation.

The startup Registry registration uses skill.dependencies instead of skill.dependency_contract.

Therefore a local Skill containing both declarations can still enter Registry with an incomplete dependency set. Example:

    dependencies:
      python_packages:
        - requests
        - pydantic

    requirements:
      - python:requests

SkillManager activation sees requests + pydantic through dependency_contract, but startup Registry initialization would persist only the raw dependencies mapping, not the legacy requirement, and this is also not guaranteed to match the canonical persisted representation used by package acquisition.

This violates the FIX2 requirement that Registry persistence and activation consume the same canonical dependency set.

Required fix:

- startup local Skill registration must persist skill.dependency_contract;
- any other local Skill serialization path that represents dependencies must use the canonical contract where the contract is intended to be consumed;
- do not change the semantic meaning of the raw dependencies field merely to hide the problem;
- add a regression that creates a local Skill with modern-only and legacy-only/merged declarations, runs the same registration path used by startup, and asserts Registry requirements equal the exact canonical contract;
- assert Registry preflight and SkillManager preflight return the same dependency records.

## Related serialization consistency

SkillInfo.to_dict() still returns:

    "dependencies": self.dependencies

rather than the canonical dependency contract.

This is not necessarily an active production endpoint bug today, but it leaves a public SkillInfo serialization path exposing the raw declaration while the new contract is intended to be canonical.

Required fix:

- decide and document that the serialized dependency field is canonical, or explicitly expose the raw declaration under a separate name and the canonical contract under the consumed dependency field;
- keep all consumers consistent;
- add a regression for the chosen contract.

Do not perform a broad SkillInfo/API redesign.

## Validation reviewed

Worker reported:

- P15A-P15E regression modules: 158 passed;
- frontend tests: 16 passed;
- production build: passed, with Vite bundle-size warning;
- Ruff: passed;
- git diff --check: passed;
- package inspection/import/activation and manifest completeness regressions passed;
- exact-version conflict, same-name different-version update/downgrade, approval replay/retarget, and unknown-dependency blocking regressions passed;
- full core/tests was NOT completed; worker reported stopping after two failures at roughly two-thirds of the suite. No exact failure details were included in the result file.

GitHub Actions reports no workflow runs/status checks for the reviewed commit, so the review relies on the worker evidence plus direct source inspection.

Remote main is 2bb0cbb63cad2e116b012eddd84fb8bdb97eee6a; the worker also reported a clean local working tree.

## Queue decision

P15E-FIX2 remains incomplete.

Next READY task:
CODEX-ATLAS-P15E-FIX3-STARTUP-REGISTRY-CANONICALIZATION

P16 and E01-E04 remain BLOCKED.

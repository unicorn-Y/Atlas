# CODEX-ATLAS-P15E-FIX1-DEPENDENCY-CANONICALIZATION-AND-VERSIONED-PACKAGE-IMPORT Review

STATUS: REWORK_REQUIRED

REVIEWED_HEAD: 35cd5182a0599c725aa5d97b60278c61f372796d
PREVIOUS_REVIEW: tasks/reviews/CODEX-ATLAS-P15E-SKILL-DEPENDENCY-AND-DISTRIBUTION.review.md
IMPLEMENTATION_COMMIT: 35cd5182a0599c725aa5d97b60278c61f372796d
RESULT_COMMIT: 35cd5182a0599c725aa5d97b60278c61f372796d

## Decision

P15E-FIX1 is NOT accepted yet.

The two original P15E blockers are materially addressed:

- structured dependency mappings are no longer stringified into the legacy unknown form;
- exact name+version conflicts are distinguished from same-name different-version candidates;
- same-name different-version package changes use the existing lifecycle update/downgrade approval path;
- the worker added the requested regression and frontend coverage.

However, direct review found one remaining acceptance-blocking consistency defect in the canonical dependency contract, plus one closely related frontend contract defect.

Do not advance to P16 or E01-E04.

## Acceptance blocker: dual dependency declarations use different semantics

The new canonicalization is not actually one canonical path when a SKILL.md contains both modern dependencies and legacy requirements.

core/atlas/skills/acquisition.py::_parse_manifest() still selects:

    raw.get("requirements", raw.get("dependencies", []))

Therefore, when both fields exist, only requirements is normalized and persisted into the acquisition/Registry metadata.

But core/atlas/skills/__init__.py::_frontmatter_to_skill_info() does:

    normalize_dependencies([
        *normalize_dependencies(deps),
        *normalize_dependencies(requirements),
    ])

So SkillManager activation/preflight considers BOTH declarations, while the acquisition/Registry path considers only requirements.

This creates a split-brain dependency contract:

1. package inspection can compare the package manifest against only the legacy requirements subset;
2. Registry metadata can omit a modern dependency declared in SKILL.md;
3. SkillManager activation can still see the omitted dependency directly from the file;
4. lifecycle dependency checks that consume Registry requirements can therefore operate on an incomplete dependency set.

The existing P15E-FIX1 test fixture makes this easy to miss because SKILL_TEXT contains both fields, but the assertions only contain the duplicated requests dependency. That does not prove that a structured dependency absent from legacy requirements is preserved.

Required fix:

- define one canonical semantic rule for coexistence of modern dependencies and legacy requirements;
- preferably treat both as declarations and canonicalize their union with deterministic de-duplication;
- if a different precedence rule is chosen, apply that rule identically everywhere;
- make _parse_manifest(), SkillManager indexing/activation, package inspection, Registry persistence, and lifecycle dependency checks consume the same canonical representation;
- package manifest comparison must fail if a modern dependency in SKILL.md is omitted from the package dependency declaration;
- add a regression where dependencies contains a dependency that is NOT present in requirements, and prove it survives inspection -> Registry -> preflight -> activation.

This is bounded to P15E-FIX1's stated one canonical normalization path requirement.

## Related frontend contract defect

core/atlas/skills/acquisition.py now returns canonical dependency records in validation.dependencies, but the frontend Review type still declares:

    validation.dependencies: string[]

The remote review UI later renders:

    review.validation.dependencies.join(', ')

For canonical dependency objects this produces [object Object] rather than a useful dependency description.

The local package review already uses dependency_state and is fine; the remote/catalog review path still has the stale string-array contract.

Required fix:

- update the frontend type to the canonical dependency shape;
- render kind/name/requested clearly in the review UI;
- add one frontend regression for canonical dependency display.

## What is accepted from FIX1

The following original blockers are considered addressed by the current implementation and tests.

### 1. Structured dependency parsing

parse_dependencies() accepts:

- mcp_servers
- python_packages
- commands
- named version/constraint objects
- legacy kind:name@constraint strings

and returns {kind,name,requested} records.

### 2. Versioned package import semantics

The package inspection API distinguishes:

- new_skill
- exact_version_conflict
- update_candidate

Exact same name+version is rejected without overwrite.

Same-name different-version packages are sent through the existing update/downgrade lifecycle path with current-hash, acquisition-hash, server-held decision, and one-time approval binding.

### 3. Failure preservation

The added tests cover failed version updates preserving the previous Registry record and filesystem.

## Validation reviewed

Worker reports:

- P15A-P15E regression: 154 passed
- frontend: 15 passed
- production build: passed
- Ruff: passed
- git diff --check: passed
- isolated package HTTP/API smoke: passed
- remote main: 35cd5182a0599c725aa5d97b60278c61f372796d

GitHub Actions currently reports no workflow runs/status checks for this commit, so the review relies on the worker-reported test evidence plus direct source inspection.

The worker-reported .pytest-temp/ residue was subsequently cleaned by the monitor; the remote commit itself is cleanly pushed.

## Queue decision

P15E-FIX1 remains incomplete pending the bounded fixes above.

Next READY task:
CODEX-ATLAS-P15E-FIX2-CANONICAL-DEPENDENCY-CONSISTENCY

P16 and E01-E04 remain BLOCKED.

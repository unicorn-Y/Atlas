# T1-METHOD-CONFIG-CONTRACTS-033

Status: DONE_SCOPED

## Scope and dependencies

Dependencies: pinned DSH source `d743267388641bc76f17c45ce8b4c231aed1d32c`, Task 1 source index, and T1-SEMANTIC-OBLIGATION-EXTRACTOR-017.

Files:

- `core/scripts/dsh_capability_audit.py`
- `core/tests/test_dsh_capability_audit.py`
- regenerated `tasks/dsh-parity/atomic/source-index.json`
- this batch record, `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`, and atomic capability/interaction-edge/batch-queue ledgers
- pinned DSH checkout is read-only input

## Binary acceptance

1. A Python method contract captures qualified owner/name, source span, parameter defaults, exception branches, and method-local platform/state obligations with source line evidence.
2. Configuration fields capture stable field path, source location, and default/value digest; no credential values are copied into evidence.
3. Every newly indexed behavior remains `UNRESOLVED` unless linked to a valid atomic/consumer edge or backed by a specific exclusion reason; the global completion gate remains incomplete.
4. Extractor version/digest checks reject a stale v3 index. Full pinned-source scan is reproducible and reports the actual new unresolved count.

## Implementation and evidence

- Red before extractor changes: method contract node failed because no `Engine.start` qualified contract existed; TOML fields produced no `configuration_field` rows; stale `completion.json` retained `total=1` after an index with 6 units; YAML nested keys were first emitted without parent paths; YAML list mappings were first omitted. These were parser/schema gaps, not DSH production defects.
- Extractor v4 / index schema v2 adds Python function/method qualified owner, async flag, source span, parameter default digests, and method-local exception/platform/state-assignment obligations. Config JSON fields use token-derived source lines; TOML sections and YAML nested maps/lists include stable dotted/indexed field paths, type, line, and value digest. Configuration values are not copied into the ledger. New semantic rows carry `interaction_ids` beside `atomic_ids`; all remain `UNRESOLVED` until reviewed and explicitly linked/excluded.
- `scan_to_ledger` now refreshes the existing completion source-obligation total/unresolved counts and keeps status `INCOMPLETE` whenever unresolved obligations remain. This avoids stale counts and never promotes overall completion by scanning.
- Final audit unit command from `D:\Atlas\core`: `python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py --tb=short` → `16 passed, 5 warnings in 4.84s`, exit 0. Earlier run before adding YAML sequence coverage was `16 passed, 5 warnings in 5.38s`; it was superseded by the final run.
- Final full fixed-source scan command, supervised from `D:\Atlas\core`: `python scripts/dsh_validation_runner.py --cwd D:\Atlas\core --log-dir C:\Users\25011\AppData\Local\Temp\dsh-t1-033-scan-final3-20261117 --timeout 300 --cleanup-timeout 5 -- python scripts/dsh_capability_audit.py --source D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness --ledger ../tasks/dsh-parity/atomic --scan` → runner JSON `{"duration_seconds":105.89100000000326,"leftover_count":0,"returncode":0,"status":"PASS","timed_out":false}`. Child stdout: `{"component_count":369,"file_count":14988,"head":"d743267388641bc76f17c45ce8b4c231aed1d32c","mode":"scan","package_manifest_count":369,"semantic_unit_count":285444,"unresolved_semantic_unit_count":285444}`. `source-index.json` SHA256 `4D6EE420A1103A153ABE84112BE9150E770D8533216B443E791E67EC1112D246`; `completion.json` total/unresolved both `285444`, status `INCOMPLETE`.
- Final fail-closed checker command, supervised from `D:\Atlas\core`: `python scripts/dsh_validation_runner.py --cwd D:\Atlas\core --log-dir C:\Users\25011\AppData\Local\Temp\dsh-t1-033-check-final-20261117 --timeout 300 --cleanup-timeout 5 -- python scripts/dsh_capability_audit.py --source D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness --ledger ../tasks/dsh-parity/atomic --check` → runner JSON `{"duration_seconds":25.687000000005355,"leftover_count":0,"returncode":1,"status":"FAIL","timed_out":false}`. Child stdout: `{"finding_count":286572,"findings_by_code":{"ENTRY_POINT_UNRESOLVED":1128,"SEMANTIC_UNIT_UNRESOLVED":285444},"mode":"check"}`. This nonzero result is the expected incomplete-ledger guard, not a successful full parity check.
- The source index still contains 285,444 unresolved behavior/config/file-review obligations and 1,128 unresolved package entry points. This batch structures only Python methods and JSON/TOML/YAML configuration fields; it does not claim exhaustive method parsing for TypeScript/JavaScript/other source languages, reviewed runtime consumer edges, or semantic resolution. Pinned source was read only; no DSH code ran.

`DONE_SCOPED`: auditable contracts and current counts are generated for this covered subset; Task 1 remains incomplete and Task 2/total DSH parity gates remain open.

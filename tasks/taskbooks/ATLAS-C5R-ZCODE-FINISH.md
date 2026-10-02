# ATLAS-C5R-ZCODE-FINISH：C5 两项最小补做

> ZCode parallel lane only. Do not merge main.
> Review: `tasks/reviews/ATLAS-C5-ZCODE-PARALLEL.review.md`

Branch: `zcode/c5-models-parallel`

## Only two fixes

### 1. Provider alias validation on model edit

Fix `ModelManager.update_model()` so a valid Hermes provider id such as:
- `alibaba` for catalog `qwen`
- `kimi-coding` for catalog `kimi`

is accepted.

Use the existing `resolve_catalog_id()` alias mapping for validation. Keep storing/returning the Hermes provider id expected by runtime routing.

Add one focused regression that edits a Qwen/alibaba model through the same payload shape the frontend sends.

### 2. No ghost key metadata on keyring write failure

Fix `ModelManager.add_key()`:
- keyring write failure => raise `RuntimeError`;
- do not append metadata;
- do not persist provider key slot;
- API should report failure via the existing route handling.

Add one focused regression for the manager or route.

## Validation

Only run affected focused tests:
- relevant tests from `test_models.py`
- relevant tests from `test_models_routes.py`

Then one compact combined run of those two files if desired.

Do **not** rerun all 172 tests, frontend four checks, or backend full pytest for these two tiny fixes unless your change unexpectedly spreads.

## Delivery

- update `tasks/results/ATLAS-C5-ZCODE-PARALLEL.result.md` with a short repair appendix;
- set `tasks/ZCODE-CURRENT.md` to `AWAITING_REVIEW`;
- push `zcode/c5-models-parallel`;
- report new head;
- do not merge main and do not start another stage.

# ATLAS-C5-ZCODE-PARALLEL Review

Verdict: **PARTIAL — two tiny production fixes required before merge.**

Reviewed branch/head:
- `zcode/c5-models-parallel`
- `a0bf87e`

## Accepted

The C5 architecture and focused evidence are sufficient to accept the main implementation direction:

- **M1** provider catalog/native routing is wired through Hermes provider profiles while legacy models without `hermes_provider` keep the old gateway path.
- The catalog/Hermes provider namespace is normalized at the runtime routing boundary (`qwen ↔ alibaba`, `kimi ↔ kimi-coding`, etc.).
- **M2** multi-key pool implements the Hermes credential-pool protocol used by the real recovery path and persists secrets only in the existing keyring.
- **L8** staged reasoning is applied per model request and leaves existing behavior unchanged when disabled.
- **M5** cache-miss diagnostics are additive and flow into usage events/ledger.
- **M6** custom model edit/delete and provider-first UI are present.
- Focused backend **172 passed**, frontend TypeScript/Vitest/Vite and adapter tests passed.
- OriginGuard was not weakened and the C5 hot-file touches are narrow.

No full-suite rerun is required for this review.

## Blocking fix 1 — edit models whose Hermes provider id differs from catalog id

`ModelManager.update_model()` validates:

```py
_catalog.get_provider(str(hermes_pid))
```

but the frontend's `buildUpdatePatch()` sends the model's existing `hermes_provider`.
For providers such as Qwen this is `alibaba`, while the catalog id is `qwen`.
Therefore a legitimate edit of a Qwen/Kimi-style model can be rejected as “unknown provider”.

Required fix:
- validate through `resolve_catalog_id()` (or equivalent alias-aware check);
- preserve the model-facing Hermes provider id after validation;
- add one regression using a provider where ids differ, e.g. qwen/alibaba.

## Blocking fix 2 — keyring write failure must not create a ghost key slot

`ModelManager.add_key()` currently catches a keyring write failure, logs it, then still appends metadata and returns success.

That can make the UI show a configured key that has no secret behind it and can make pool sizing/counts incorrect.

Required fix:
- if secret persistence fails, do **not** append/persist key metadata;
- raise `RuntimeError` so the existing route returns a failure;
- add one focused regression proving no ghost metadata remains.

## Scope

Everything else in C5 stays closed. Do not rework provider routing, credential cooldown logic, staged reasoning, cache diagnostics, or UI.

After these two fixes pass focused tests, C5 may be marked PASS and prepared for rebase/merge after the active C4 main-line work reaches a safe merge point.

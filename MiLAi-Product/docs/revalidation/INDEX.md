# Phase 2 behavior revalidation

This directory records behavior revalidation for Product technical debt. It is
evidence, not a second source of truth for the frozen architecture. Every
receipt is bound to a Product tree digest and must distinguish a scoped
behavioral result from full architecture-item coverage.

## Baseline

| Field | Value |
| --- | --- |
| Goals | `MILA-PRODUCT-BEHAVIOR-REVALIDATION-01`, `MILA-PRODUCT-BEHAVIOR-REVALIDATION-02` |
| Baseline commit | `2ce622b86ec4aa9b6df7dc79243159eca3ceb8a0` |
| Product manifest SHA-256 | `eb28065c57b2d518b4e4fa7ca47555ba3039502a20059e42ab17cec2321ad971` |
| Product tree SHA-256 | `77b13141c2aed57802c4d89adbe9e4597defc430b77e5f9bc0d373c3a199a443` |
| Frozen architecture | `1.0.0` |

## Receipts

| Technical debt | Decision | Receipt |
| --- | --- | --- |
| projection purge/rebuild | `FIXED` | [`projection-purge-rebuild/REVALIDATION.md`](projection-purge-rebuild/REVALIDATION.md) |
| CAS blob-first orphan possibility | `FIXED` | [`cas-blob-orphan/REVALIDATION.md`](cas-blob-orphan/REVALIDATION.md) |
| confirmation binding to query/action | `OPEN` | [`confirmation-binding/REVALIDATION.md`](confirmation-binding/REVALIDATION.md) |
| validation-token TTL vs ContextCapsule lifecycle | `OPEN` | [`context-validation-lifecycle/REVALIDATION.md`](context-validation-lifecycle/REVALIDATION.md) |

`FIXED` means the current mechanism, the positive path, the negative or
fail-closed path, and the recovery path were executed successfully for the
receipt's declared scope. It does not promote every related frozen
G/I/TX/role item automatically. The conformance map records the exact scoped
claims and only promotes an item when a receipt explicitly declares
`coverage: COMPLETE` with both positive and negative case coverage.

`OPEN` receipts deliberately carry `execution.status: FAIL`. A failed
execution receipt is valid diagnostic evidence, but it cannot promote an
architecture item to `PASS`. It leaves the architecture item `UNVERIFIED`
unless a separate, explicit review concludes that the frozen statement itself
is violated and records a `DEVIATION`.

The next cross-boundary items remain outside this directory until their own
revalidation is executed:

```text
OpenWorker HTTP auth/exposure
process-local task continuity/state
cache-miss Host continuation
```

# Phase 2 behavior revalidation

This directory records behavior revalidation for Product technical debt. It is
evidence, not a second source of truth for the frozen architecture. Every
receipt is bound to a Product tree digest and must distinguish a scoped
behavioral result from full architecture-item coverage.

## Current Product identity

| Field | Value |
| --- | --- |
| Goals | `MILA-PRODUCT-BEHAVIOR-REVALIDATION-01`, `MILA-PRODUCT-BEHAVIOR-REVALIDATION-02` |
| Product source commit | `c1895e37defe5effbb5ce489613d0528dc8f3fd5` |
| Product manifest SHA-256 | `c588ef3e5fca4744f23ba534b0a84f25970563b3270ee7380644631703a88595` |
| Product tree SHA-256 | `f9d6f6ebf90712160441c3d57835131851ece12c945670cc607c225e22566344` |
| Frozen architecture | `1.0.0` |

## Receipts

| Technical debt | Decision | Receipt |
| --- | --- | --- |
| projection purge/rebuild | `FIXED` | [`projection-purge-rebuild/REVALIDATION.md`](projection-purge-rebuild/REVALIDATION.md) |
| CAS blob-first orphan possibility | `FIXED` | [`cas-blob-orphan/REVALIDATION.md`](cas-blob-orphan/REVALIDATION.md) |
| confirmation binding to query/action | `FIXED` | [`confirmation-binding/REVALIDATION.md`](confirmation-binding/REVALIDATION.md) |
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

When Product behavior is repaired, the original diagnosis receipt remains
immutable and a separate remediation receipt is added. Historical receipts
are validated against the Product manifest at their baseline commit; only
receipts matching the current Product manifest/tree contribute current
Conformance claims.

The next cross-boundary items remain outside this directory until their own
revalidation is executed:

```text
OpenWorker HTTP auth/exposure
process-local task continuity/state
cache-miss Host continuation
```

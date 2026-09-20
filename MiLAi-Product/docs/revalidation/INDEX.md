# Phase 2 behavior revalidation

This directory records behavior revalidation for Product technical debt. It is
evidence, not a second source of truth for the frozen architecture. Every
receipt is bound to a Product tree digest and must distinguish a scoped
behavioral result from full architecture-item coverage.

## Current Product identity

| Field | Value |
| --- | --- |
| Goals | `MILA-PRODUCT-BEHAVIOR-REVALIDATION-01`, `MILA-PRODUCT-BEHAVIOR-REVALIDATION-02` |
| Product source commit | `28fa9211d54032243eac3aac6a3819aca41bff2b` |
| Product manifest SHA-256 | `0647966eed14887c6602b4a61c8fb5e8599978cbdcababb885bfd273f34e337e` |
| Product tree SHA-256 | `a93268d94a73e5aee53150ca4be9bbc5f37f76d0173c5be72633cc54cf2ea382` |
| Frozen architecture | `1.0.0` |

## Receipts

| Technical debt | Decision | Receipt |
| --- | --- | --- |
| projection purge/rebuild | `FIXED` | [`projection-purge-rebuild/REVALIDATION.md`](projection-purge-rebuild/REVALIDATION.md) |
| CAS blob-first orphan possibility | `FIXED` | [`cas-blob-orphan/REVALIDATION.md`](cas-blob-orphan/REVALIDATION.md) |
| confirmation binding to query/action | `FIXED` | [`confirmation-binding/REVALIDATION.md`](confirmation-binding/REVALIDATION.md) |
| validation-token TTL vs ContextCapsule lifecycle | `FIXED` | [`context-validation-lifecycle/REVALIDATION.md`](context-validation-lifecycle/REVALIDATION.md) |

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

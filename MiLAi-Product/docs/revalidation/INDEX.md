# Phase 2 behavior revalidation

This directory records behavior revalidation for Product technical debt. It is
evidence, not a second source of truth for the frozen architecture. Every
receipt is bound to a Product tree digest and must distinguish a scoped
behavioral result from full architecture-item coverage.

## Last behavior-revalidated Product identity

The table below is the cleanup identity to which the existing receipts are bound. The additive
Host owner testkit changes the current Product manifest; consult
[current status](../PRODUCT_CURRENT_STATUS.md) and the generated
[conformance map](../conformance/CURRENT_ARCHITECTURE_CONFORMANCE.md) for the candidate identity.
Existing receipt bytes are retained as historical evidence, not silently rebound to the new tree.

| Field | Value |
| --- | --- |
| Goals | `MILA-PRODUCT-BEHAVIOR-REVALIDATION-01`, `MILA-PRODUCT-BEHAVIOR-REVALIDATION-02`, `MILA-PRODUCT-BEHAVIOR-REVALIDATION-03` |
| Product source commit | `432153a0065f6ccc6706d670ba7eafafc002c950` |
| Product manifest SHA-256 | `7927bb6a0cad2ed139a7ce05f34f64cd47e3c0cd75bb77ff431a433b83c0c693` |
| Product tree SHA-256 | `7135d3388f9360ab3acf7b160ad20451da1883a09d10bf7f51ac9a404942f521` |
| Frozen architecture | `1.0.0` |

## Receipts

Phase 3B-1 adds a current-tree scoped trace-ownership receipt. Its exact baseline is
recorded separately in [the report](trace-ownership/REVALIDATION.md); the table above
remains the historical cleanup identity. Prior receipt bytes are unchanged.

| Technical debt | Decision | Receipt |
| --- | --- | --- |
| projection purge/rebuild | `FIXED` | [`projection-purge-rebuild/REVALIDATION.md`](projection-purge-rebuild/REVALIDATION.md) |
| CAS blob-first orphan possibility | `FIXED` | [`cas-blob-orphan/REVALIDATION.md`](cas-blob-orphan/REVALIDATION.md) |
| confirmation binding to query/action | `FIXED` | [`confirmation-binding/REVALIDATION.md`](confirmation-binding/REVALIDATION.md) |
| validation-token TTL vs ContextCapsule lifecycle | `FIXED` | [`context-validation-lifecycle/REVALIDATION.md`](context-validation-lifecycle/REVALIDATION.md) |
| OpenWorker HTTP auth/exposure | `FIXED` | [`openworker-http-exposure/REVALIDATION.md`](openworker-http-exposure/REVALIDATION.md) |
| worker `--once` docs/behavior (Phase 3A-1) | `FIXED` | [`worker-once/REVALIDATION.md`](worker-once/REVALIDATION.md) |
| Runtime / Host / Provider ownership (Phase 3B-1, serial query-first testkit) | `FIXED` | [`trace-ownership/REVALIDATION.md`](trace-ownership/REVALIDATION.md) |
| process-local task continuity/state (Phase 3A-2D/R) | `FIXED` (PR #36/full #63) | [`host-continuity/REMEDIATION.md`](host-continuity/REMEDIATION.md); original [`FAIL diagnosis`](host-continuity/REVALIDATION.md) retained |
| cache-miss Host continuation (Phase 3A-2D, scoped) | `FIXED` | [`host-continuity/cache-miss.receipt.json`](host-continuity/cache-miss.receipt.json) |
| resolver lexical-language assumptions (Phase 3A-3D) | `OPEN` | [`resolver-language/REVALIDATION.md`](resolver-language/REVALIDATION.md), frozen 30-case pure-function diagnosis; 17 PASS/13 FAIL |

The five Phase 2 rows also have a `post-cleanup.receipt.json` bound to the final cleanup Product identity.
These receipts preserve the prior claim statements and coverage levels; they do not replace or
rewrite the diagnosis/remediation evidence.

Phase 3A-1 adds `worker-once/receipt.json` on the same executable Product identity, with source/tests
commit `4b76405f3e3e73ed85713161eb9465e7bbf5cc82`. Its bounded-cycle evidence is SCOPED G9;
the Product manifest does not change and no additional architecture item is promoted to PASS.

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

Phase 3A-2D adds separate native-continuity FAIL and cache-miss PASS receipts without
changing Product executable identity. Phase 3A-2R changes the native guard and adds
its own current-tree remediation receipt; the old receipts remain historical. Original
failure assertions now pass without XFAIL, and real recovery was rerun on the repaired
tree. PR #36/full #63/main fast `35688151840` now close that repair remotely.

Phase 3A-3D keeps the Product executable identity unchanged and adds an OPEN scoped
resolver diagnosis: client compatibility and Runtime interpretation are separate owners.
13 desired-behavior failures remain explicit, including strict XFAIL CI annotations;
none is counted as a pass or proof of actual retrieval, exposure or model benefit.

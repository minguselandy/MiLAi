# Worker `--once` revalidation — 3A-1

Date: 2026-09-22. Decision: `FIXED` (behavior confirmed; operational documentation clarified).
No Product executable, API, schema, permission, Canonical or default behavior changed.
Schema remains `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`.

## Identity and environment

- Source/test commit: `4b76405f3e3e73ed85713161eb9465e7bbf5cc82`;
  Git tree: `56c81a12365c97fd586d5e4900d463bf7f2a71d7`.
- Parent main: `cf149939eea9f184159ebfb6aab1a3e791988250` (PR #27 closed).
- Product manifest: `7927bb6a0cad2ed139a7ce05f34f64cd47e3c0cd75bb77ff431a433b83c0c693`;
  Product tree: `7135d3388f9360ab3acf7b160ad20451da1883a09d10bf7f51ac9a404942f521` (422 files).
- Dedicated container: `milai-3a1-worker-once-20260922`, PostgreSQL 16.14 / pgvector pg16;
  database `milai_worker_once`, loopback port 32789, migrations from empty DB to `0056_host_notes`.
  The owned container was stopped after validation; database storage was retained.
- Separate owner/API/Steward/worker roles; synthetic tenant per test; deterministic hash embedding.
  No model, HTTP embedding, Provider or Judge calls. No shared service or user database used.
- Test source SHA-256: `59999f54da9c008f8101262b697c9e791abf2b99c98d10345f84660b4fbe489e`.
- JUnit: `/cra/memory/mx_memory/evidence/post-cleanup-3a1-worker-once-20260922/worker-once.xml`;
  SHA-256 `c8be8299d61e3020c62c4aa31c9dacac486e7fa11b39a156b468dbed4af06020`.
  Raw local test artifacts stay outside Git; compact reproducible evidence is in `receipt.json`.

## Observed contract

Startup → settings/dependencies → orphan reconciliation → one bounded cycle across four projections
→ watermark reconciliation for each projection with work → database close → exit.

Each projection has its own event limit. A cycle limit of 3 can process up to 12 deliveries, including
explicit routing skips; `processed` is not a count of successful unique source events. A second CLI
process resumes the remaining prefix. An empty/fully drained queue returns without polling sleep.

`--check` warms dependencies and pings PostgreSQL without leasing, processing, watermark advancement
or orphan cleanup. `--check --once` is rejected by the parser.

Missing Blob content is a handled per-item failure: CLI exit 0, durable PENDING or DEAD_LETTER,
nonempty safe error code, no projected document and no watermark crossing the failed sequence.
Unaffected projections may acknowledge their non-applicable delivery. An unhandled DB startup
failure exits nonzero without touching the original queue. This satisfies the Goal's explicit
fail-closed alternative; it does not establish an all-items-success exit-code contract.

## Executed coverage

| Case | Executable proof | Result |
| --- | --- | --- |
| Empty queue | fresh CLI, one cycle, processed=0, zero watermarks, no documents | PASS |
| Queue below limit | 2 items, limit 3, batch 2; all four projections finish exactly once | PASS |
| Queue above limit | 5 items, limit 3; bounded delivered prefix, untouched pending tail; next process drains | PASS |
| Multiple projections | per-projection bounds plus existing real FTS/vector Claim projection test | PASS |
| Orphan exists | aged synthetic orphan retained by check, removed before once-cycle; referenced Blob retained | PASS |
| No projection work | already-drained queue unchanged; process exits within 20 s with poll interval 60 s | PASS |
| Processing failure | missing Blob, max attempts 1/5 → DEAD_LETTER/PENDING, safe error and watermark gap | PASS |
| Check mode | exact queue/watermark/doc snapshot unchanged, orphan retained, no cycle event | PASS |
| Watermark work | four reconcile calls for active cycle, none for empty; correct contiguous positions in DB | PASS |
| Startup failure | nonexistent isolated database, nonzero exit, original queue unchanged | PASS |
| Resource exit | each actual child CLI has zero remaining named PostgreSQL sessions after exit | PASS |

## Validation

With the four `MILAI_MIGRATION_DATABASE_URL` / `MILAI_TEST_{API,STEWARD,WORKER}_DATABASE_URL`
variables pointing to the dedicated instance, from `MiLAi-Product/runtime`:

```bash
.venv/bin/pytest -q tests/integration/test_worker_once.py \
  tests/integration/test_projection_worker.py::test_projection_worker_builds_fts_vector_and_contiguous_watermarks \
  tests/integration/test_projection_worker.py::test_blob_orphan_reconciles_on_real_worker_startup_and_ingest_recovers \
  tests/unit/test_worker.py tests/unit/test_worker_settings.py --tb=short \
  --junitxml=/cra/memory/mx_memory/evidence/post-cleanup-3a1-worker-once-20260922/worker-once.xml
.venv/bin/ruff check tests/integration/test_worker_once.py
```

Result: **20 passed in 12.02 s**, zero skips; Ruff PASS. The first harness development run was
1 passed / 1 failed because the new test used the wrong metric key (`_ms_calls` instead of `_ms`).
The test was corrected; this was an assertion-name error, not a worker failure. Before final execution,
the synthetic orphan helper was also corrected to use the existing BlobStore `write` method.

No full Runtime/PostgreSQL suite, historical replay or full composition was run locally: only tests
and documentation changed, and Product executable identity is unchanged. Root fast CI remains the
PR gate. This receipt provides SCOPED G9 evidence and does not promote another architecture item.

## Limits and follow-up

This verifies one process with an isolated database and deterministic embedding; it does not claim
production performance, HTTP embedding availability, concurrent-worker recovery or full G9 coverage.
The 20 s child timeout proves absence of the configured 60 s polling wait, not a latency SLA.
Process-level session cleanup is observed; every startup exception path's in-process cleanup is not
separately certified. No worker remediation is indicated by this matrix.

Work-package remote completion still requires the tested PR head, merge tree and main fast gate;
those identities are recorded in the Goal journal after merge, independently of this behavioral receipt.

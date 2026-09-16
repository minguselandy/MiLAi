# MILA-PRODUCT-01 S3 local usability

Status: `PASS_S3_PRODUCT_LOCAL_USABILITY`

- Arm kind: `PRODUCT_BLACK_BOX_LOCAL_STACK` with one isolated persistent PostgreSQL deployment.
- Product commit: `126ca08b3b4b15e17f3b5fad777022f0c6a05d0b`.
- Product lock digest: `36fc1680ab93c9b5c25c91009fad6f256ea915852584c5e1ff1d880923f5bd1c`.
- Historical lock: `data/locks/product01-s3-product.lock.json`.
- Final run: `artifacts/product01-s3-20260901-002`.
- Run ID: `product01-s3-20260901T140413Z`.
- Candidate remained default OFF; the selected configuration was enabled only by
  `MILAI_RETRIEVAL_TYPE_DIRECTED_ACQUISITION_ENABLED=true`.

## Result

- Golden capture → searchable Raw Evidence → restart → new-session recall with source → reviewed
  Canonical create → reviewed correction → two-version history → revoke → physical/derived deletion
  → restart persistence: PASS.
- Product scenario success: `23/24` (`0.9583`, required `>=0.90`).
- Warm typed terminal rate: `100/100`.
- Read-after-write searchable P95: `1046.97 ms` (required `<=5000 ms`).
- Retrieval + Context P95: `55.05 ms` (required `<=2000 ms`).
- Warm memory-control P95: `16.54 ms` (required `<=500 ms`).
- Model-outage deterministic fallback: `1.0`.
- Scope/permission/revocation/deletion leaks: `0`.
- Canonical mutations from read path: `0`.
- Four persistent Runtime/worker restarts completed; one restart disabled the single candidate flag
  and proved the enriched probe absent, then restored the selected configuration.

The only unsuccessful scenario was a role-free assistant answer: Raw search returned the correct
source in a typed `HIT`, but grounded relation Binding remained `PARTIAL`, so it was not counted as
task success. This is a bounded quality limitation, not a system failure or leak.

The preceding `-001` run passed but exposed a Lab terminal-classification error: Product correctly
returned `ABSENT / NO_CANDIDATE`, while the scorer recognized only `MISS/ABSTAINED`. The scorer was
repaired and `-002` was executed against a fresh database. No Product behavior changed between the
runs.

Artifact SHA-256: `run.json` `27399355…e68`, `cases.jsonl` `eb3c76cc…80f0`, `metrics.json`
`57c37d2a…5b1b`, `terminal.json` `94f1f283…e093`.

Disposition: Product local usability is established for synthetic local data. This does not grant
production readiness, personal-data use, default feature enablement, or LongMemEval confirmation.

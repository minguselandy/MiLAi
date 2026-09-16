# DG-17 Raw Evidence dense rebuild

The Evidence dense projection is derived and default-disabled. Rebuild it only with the same
128-dimensional embedding identity configured for the candidate retrieval lane.

```bash
runtime/.venv/bin/python scripts/rebuild_dg17_a6_evidence_dense.py \
  --env-file runtime/.env \
  --batch-size 32
```

The command is idempotent and reads only live, readable Evidence documents missing the exact
model/input-projection version. It never mutates Evidence, Claims, or canonical state. A bounded
run can use `--max-batches`; `PARTIAL` means rows remain and must not be treated as projection
readiness.

Before enabling the product flag, call the governed dense search and verify
`source_count == projected_count` for the intended scope. On embedding or database failure, leave
the flag disabled, retain the failure log, fix the cause, and start a new explicit rebuild run.

Rollback requires disabling `MILAI_RETRIEVAL_EVIDENCE_DENSE_ENABLED` first, downgrading migration
0044, and verifying deterministic Evidence FTS remains available. Governed Evidence purge deletes
dense rows through the Evidence document foreign key; do not delete the dense table as a substitute
for revocation or purge.

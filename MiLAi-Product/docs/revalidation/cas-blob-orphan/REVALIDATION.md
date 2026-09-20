# CAS blob-first orphan revalidation

Decision: `FIXED`

The current Product was revalidated against the `2ce622b` baseline with a
real PostgreSQL instance and an isolated tenant. The existing blob-before-DB
write window was forced to fail, then the actual `milai-worker --once`
startup path reconciled the stale orphan. No production mechanism change was
needed.

## Executed behavior

- a durable CAS blob was written before a forced TX-01 repository failure;
- the failed ingest left zero canonical Evidence, ContentBlob, and Outbox
  rows for the tenant;
- after the configured grace window, real worker startup called canonical
  reference discovery and orphan reconciliation, and removed the unreferenced
  blob;
- a normal ingest then succeeded, and the same idempotency key replayed the
  same Evidence and Blob identity;
- the companion TX-01 identity tests passed, including concurrent same-key
  single-side-effect behavior and owner-side capture identity immutability.

The machine-readable execution record is [`receipt.json`](receipt.json).
The `I-02` claim is the only complete architecture-item promotion in this
receipt; the other claims are deliberately scoped to the blob durability and
recovery branch.

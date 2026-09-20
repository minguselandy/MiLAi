# Projection purge/rebuild revalidation

Decision: `FIXED`

The current Product was revalidated against the `2ce622b` baseline with a
real PostgreSQL instance and an isolated tenant. The existing purge, erasure
proof, dead-letter, retry, rebuild, watermark, and canonical-preservation
mechanisms were exercised; no production mechanism change was needed.

## Executed behavior

- revoke followed by worker processing removes derived claim projections and
  the eligible CAS blob, with a verified absence proof;
- a forged erasure proof fails closed into dead-letter and recovery succeeds
  only after the blob is already verified absent;
- rebuilding FTS and vector projections resets derived state and replays the
  outbox without changing canonical claim state;
- rebuilding after evidence revoke does not resurrect revoked material, even
  when the reset outbox is replayed;
- projection watermarks converge to the tenant outbox maximum after recovery.

The machine-readable execution record is
[`receipt.json`](receipt.json). The receipt claims scoped evidence for G6, G9,
I-10, TX-05, and `PROJECTION_WORKER`; those broad frozen items remain
`UNVERIFIED` unless their complete frozen statements are explicitly covered.

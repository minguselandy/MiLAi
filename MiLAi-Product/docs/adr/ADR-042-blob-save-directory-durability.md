# ADR-042: Blob save synchronizes directory publication before Evidence commit

Status: ACCEPTED FOR IMPLEMENTATION / Schema 0.1.x EXPERIMENTAL.

## Failure and decision

The Evidence path writes a content-addressed file before TX-01 commits its metadata and durable
outbox event. The former adapter fsynced the staging file and renamed it, but did not fsync its
containing directory. Linux documents that file fsync alone does not ensure directory-entry
durability: [fsync(2)](https://man7.org/linux/man-pages/man2/fsync.2.html).

Before returning a successful blob write, synchronize the renamed file's directory, tenant
directory, configured blob root and its provisioned parent, in that order. The staging file's
0600 mode and content are synced before rename. Existing verified files are synced too, followed
by the same directory chain: an earlier failed attempt can leave a readable but unconfirmed file.
Do not cache directory existence as proof of durability, including concurrent directory creation.

Any fsync/open failure propagates before TX-01. A failed write may leave an unreferenced blob;
existing orphan reconciliation applies. An explicit replay can verify and sync that blob before
the original operation commits. This does not authorize automatic retries or reinterpret a lost
HTTP response as a failed transaction.

## Scope and limits

The blob root's parent is provisioned storage: its own link and ancestors must already be durable.
Filesystem/device fsync guarantees and PostgreSQL durable-commit configuration remain deployment
requirements. Tests verify syscall ordering, errors, real database boundaries and process restart;
they do not simulate storage-controller power loss or certify arbitrary filesystems.

This tightens the existing save receipt, without changing identity, permissions, encryption
format, CAS, TX-01/outbox schema or Canonical authority. Index readiness remains separate from
durable save and direct readability. No migration is required. No new projection or maintenance
process is added. Erasure and key rotation are separate existing operation contracts.

Additional file/directory sync work is part of capture latency and must remain in measurements.
Rollback restores the former weaker publication boundary and must not retain this stronger claim.
The product remains NO-GO FOR SCHEMA FREEZE.

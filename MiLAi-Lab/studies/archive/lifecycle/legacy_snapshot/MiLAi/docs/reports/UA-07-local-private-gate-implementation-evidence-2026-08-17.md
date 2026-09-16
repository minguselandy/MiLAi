# UA-07 Crypto、Data Mode 与 Import Gate 证据

> Implementation decision: `PASS`  
> Promotion decision: `NO-GO FOR LOCAL PRIVATE BETA` (missing explicit user approval)

Implemented engineering controls include AES-256-GCM per-Blob envelope encryption, per-Blob DEK,
KEK reference, wrong-key/tamper fail-closed behavior, resumable key rotation, encrypted
backup/verify/empty-target restore and deletion reconciliation. `LOCAL_PERSONAL_DATA` startup
requires encryption, a KEK and `backup_key_recovery_confirmed=true`.

Evidence ingest now has `SYNTHETIC/DEIDENTIFIED/PERSONAL` classification. Runtime checks it against
`SYNTHETIC_ONLY/DEIDENTIFIED_ALLOWED/LOCAL_PERSONAL_DATA` before Blob write and records the asserted
classification in the permission snapshot. This is policy enforcement, not automatic PII
detection.

`milai-ops import-dry-run` supports versioned Mem0, Graphiti and Hindsight JSON exports. It is
read-only, rejects symlinks/non-regular/oversized inputs, emits hashes rather than content, requires
source lineage/tenant/Scope/time/permission/retention, quarantines invalid rows, writes a 0600
non-overwriting report and always returns `execution_authorized=false`.

The privacy decision and remaining human approvals are recorded in
`docs/security/UA-07-local-data-privacy-threat-review.md`. Until a user approves exact source,
purpose, records, retention and key-recovery custody and witnesses an independently accepted
recovery/deletion drill, only synthetic/de-identified Agent Integration Beta is eligible.

# ADR-019: Complete Legacy TX-05 Transaction-Time Certification

> Status: `ACCEPTED FOR 1.0.0-candidate.5`  
> Date: `2026-08-17`（Asia/Shanghai）  
> Scope: candidate.1 populated history, candidate.3/0024 compatibility, and already-applied candidate.4/0025 development databases  
> Freeze effect: none; AF-09 remains `PENDING_INDEPENDENT_REREVIEW`

## Context

The same independent reviewer rejected the exact candidate.4 submission in
`docs/reviews/AF-09-independent-rereview-candidate.4-2026-08-17.md` (SHA-256
`ed7f4ff514f8b7c41eb345fe4c2d568b34f6df4260d74c1eaaa33341fe25ec21`). The
review closed AF09-F01 and the exact missing-DeletionRequest AF09-F11
counterexample, but opened P1 AF09-F12.

Candidate.1 public procedure `milai.tx05_revoke_evidence` uses PostgreSQL
`CURRENT_TIMESTAMP` for the Evidence revocation and defaults it for the
DeletionRequest, idempotency record, OperationalEvent, revoke Outbox, and
purge Outbox. PostgreSQL fixes `CURRENT_TIMESTAMP` at the transaction start,
so all six durable time fields are an exact atomicity witness. Candidate.4
proved only `DeletionRequest.requested_at = Evidence.revoked_at`. Independently
shifting any of the other four `created_at` fields by one second still allowed
0024/0025 to synthesize an `APPLIED REVOKE_EVIDENCE` Proposal and a
`STEWARD APPROVE` Decision.

Candidate.4 was never accepted or frozen. Its exact source bytes, manifest,
archive, external receipt, author report, and independent review remain
immutable evidence. Candidate.5 must close the proof gap without treating the
already-applied candidate.4 revision number as proof that its data is valid.

## Decision

### 1. Use one durable transaction-time anchor

For every candidate.1 `EVIDENCE_REVOKED` Outbox row without original
governance links, the offline migration chooses
`DeletionRequest.requested_at` as the transaction-time anchor and requires
exact equality with:

1. `EvidenceRecord.revoked_at`;
2. `IdempotencyRecord.created_at`;
3. the original `EVIDENCE_REVOKED` OperationalEvent `created_at`;
4. the original `EVIDENCE_REVOKED` Outbox `created_at`; and
5. the paired `PURGE_EVIDENCE_DERIVATIVES` Outbox `created_at`.

The existing tenant, request, Evidence/Blob, actor, reason, commit sequence,
state-axis, count, and Outbox-ID predicates remain mandatory. Time proximity,
rounding, ordering, a shared UUID, or agreement among only a subset of legs is
not sufficient.

### 2. Correct both pre-authority proof paths

The live, unaccepted 0024 and 0025 migrations add all four missing time
equalities while their source tables are held under `ACCESS EXCLUSIVE` locks.
Corrected 0024 therefore rejects bad fresh candidate.1 input before creating
legacy ledgers or reconstructed authority and leaves Alembic at
`0023_erasure_sha256_repair`. Corrected 0025 applies the same proof to a
candidate.3-compatible database and leaves invalid input at
`0024_legacy_history_reconcile` with no 0025 residue.

The actual 0024 governance reconstruction query repeats the same timestamp
predicate. The initial proof remains the global fail-closed boundary; the
repeated predicate prevents the write query from silently selecting a weaker
source shape.

### 3. Add a proof-only candidate.4 compatibility head

New forward migration `0026_legacy_tx05_time_guard` is the certification gate
for development databases that already reached candidate.4 revision 0025. It
locks the five source tables and re-runs the complete proof before Alembic may
advance. It creates no table, Proposal, Decision, transition, OperationalEvent,
Outbox, or replacement authority.

An invalid 0025 database remains at 0025. Any governance already reconstructed
by the rejected candidate.4 migration remains forensic prior-state evidence;
0026 neither certifies it nor destructively rewrites it. Such a database must
not serve the candidate.5 runtime and must be restored or repaired from an
independently proven source. A valid database advances to
`0026_legacy_tx05_time_guard`.

All three proof shapes raise the stable error
`AF09_UNPROVABLE_LEGACY_TX05`. Downgrade remains intentionally unsupported:
removing a certification head or deleting governance/audit facts is not a data
repair strategy.

### 4. Make every missing time leg executable evidence

Real PostgreSQL tests must construct the baseline through candidate.1 public
procedures and independently shift exactly one source timestamp by one second.
The four fresh nodes are individually named and source-mapped. Parameterized
compatibility tests replay the same four corruptions from 0024 and 0025, plus
a positive 0025→0026 control that proves all six source timestamps are present
and identical.

Every negative verifies the prior Alembic head and absence of new migration
authority/residue. Test setup failures or hand-built rows cannot substitute
for the public-procedure history.

## Executable evidence

Primary nodes in `runtime/tests/integration/test_runtime_foundation.py`:

- `test_candidate1_tx05_idempotency_timestamp_conflict_rolls_back`;
- `test_candidate1_tx05_operational_event_timestamp_conflict_rolls_back`;
- `test_candidate1_tx05_revoke_outbox_timestamp_conflict_rolls_back`;
- `test_candidate1_tx05_purge_outbox_timestamp_conflict_rolls_back`;
- `test_candidate3_applied_0024_timestamp_conflict_is_blocked_by_0025`;
- `test_candidate4_applied_0025_valid_tx05_time_proof_advances_to_0026`; and
- `test_candidate4_applied_0025_timestamp_conflict_is_blocked_by_0026`.

The earlier missing-row, identity, actor, reason, state, payload, valid
grounding, and real Issue/Context regressions remain required. Passing only the
new timestamp tests cannot close AF-09.

## Consequences

- Alembic head becomes `0026_legacy_tx05_time_guard`; the durable catalog
  remains 32 tables total / 31 tenant-owned because 0026 is proof-only.
- Candidate.3 and candidate.4 compatibility are explicit, separately tested
  input shapes rather than assumptions derived from revision numbers.
- The main forensic development database is not repaired by fabrication or
  forced head advancement. Acceptance gates continue to use a fresh database.
- Candidate.5 remains `0.1.x EXPERIMENTAL`, `CANDIDATE`, and
  `NO-GO FOR SCHEMA FREEZE` until the same independent reviewer accepts the
  exact immutable candidate.5 submission.

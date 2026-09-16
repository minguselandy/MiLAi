# ADR-018: Rejected Grounding Quarantine and Durable TX-05 Provenance Guard

> Status: `ACCEPTED FOR 1.0.0-candidate.4`  
> Date: `2026-08-17`（Asia/Shanghai）  
> Scope: candidate.1 populated database and already-applied candidate.3/0024 development databases  
> Freeze effect: none; AF-09 remains `PENDING_INDEPENDENT_REREVIEW`

## Context

The same independent reviewer rejected the exact candidate.3 submission in
`docs/reviews/AF-09-independent-rereview-candidate.3-2026-08-17.md` (SHA-256
`321883a7b9b695f4727aee99375fbeb3daf9919314c7562f6854d2a826012e9c`). AF09-F02 was
closed and F03–F10 remained closed, but two P1 findings remained:

1. **AF09-F01:** candidate.1 proposal submission created both an Issue transition and a
   `RESOLUTION_CANDIDATE` GroundingRelation before a Decision. Candidate.3 rejected/reversed and
   quarantined only the transition. The rejected relation remained canonical and was returned by
   the Issue and Context consumers.
2. **AF09-F11:** candidate.3 called legacy TX-05 provenance complete when several JSON documents
   repeated the same `deletion_request_id`, without joining the durable
   `milai.deletion_request`. Deleting that row still caused migration 0024 to reconstruct an
   `APPLIED REVOKE_EVIDENCE` Proposal and `STEWARD APPROVE` Decision.

Candidate.3 was never accepted or released as a frozen migration line. Its exact migration bytes
remain preserved by its immutable submission archive and receipt. Candidate.4 must both make a
fresh 0014→head upgrade fail within 0024 (so Alembic remains at 0023 with no partial authority) and
support development databases that already executed the rejected candidate.3 form of 0024.

## Decision

### 1. Correct the rejected candidate-only 0024 and add a compatibility head

Candidate.4 replaces the live, unaccepted 0024 source while retaining candidate.3's original bytes
in `AF-09-candidate.3-6a2f1574-submission.tar.gz`. The corrected 0024 performs all new source proof
before reconstructing governance. Therefore an unprovable candidate.1 database fails inside the
0024 transaction and remains at `0023_erasure_sha256_repair` with no quarantine, Proposal,
Decision, replacement transition, reconciliation event or reconciliation Outbox residue.

New forward migration `0025_legacy_provenance_guard` is the compatibility and release head. It
repeats the source proof and grounding reconciliation for a development database whose Alembic
version already says 0024 because it ran candidate.3. Invalid such databases remain at 0024 and
must be restored or repaired from independently proven source data before serving candidate.4.

Downgrade of either reconciliation revision remains intentionally unsupported. Deleting audit or
governance facts is not a rollback strategy.

### 2. A TX-05 UUID reference is not the referenced object

For every candidate.1 `EVIDENCE_REVOKED` Outbox without governance links, the offline migration
takes `ACCESS EXCLUSIVE` locks and requires one mutually consistent transaction containing:

- the actual tenant-scoped `DeletionRequest` row named by the revoke event;
- the same Evidence and Blob identity, a non-null Evidence revocation, and the same revocation
  reason;
- the same requester/creator actor and transaction timestamp;
- `logical_revocation_status = APPLIED`, `canonical_block_status = APPLIED`, and valid current
  purge/primary/backup/retention states;
- the original idempotency result with the same request ID, Evidence, commit sequence, actor,
  initial statuses, counts and both Outbox IDs;
- the original `EVIDENCE_REVOKED` OperationalEvent with matching reason, IDs, counts and sequence;
  and
- the paired `PURGE_EVIDENCE_DERIVATIVES` Outbox with matching DeletionRequest, Evidence, Blob,
  actor, sequence and initial purge metadata.

Any absent or conflicting leg raises the stable error `AF09_UNPROVABLE_LEGACY_TX05`. Agreement
among JSON references to a missing row is explicitly insufficient. Only this proof permits the
legacy Proposal/Decision reconstruction described by ADR-017.

### 3. Preserve rejected grounding exactly, outside canonical authority

Add tenant-owned `milai.legacy_grounding_relation_quarantine`. For each candidate.1 resolution
submission, the migration first proves that the exact distinct Proposal support set corresponds to
the Issue-owned `RESOLUTION_CANDIDATE` relation set.

When the actual Decision is `REJECT`—including the fixed POLICY rejection used for a still-pending
candidate.1 proposal—the migration atomically:

1. recomputes SHA-256 over every original GroundingRelation field;
2. inserts the exact row, original transition ID and actual reconciliation Decision into the new
   ledger;
3. removes only that exact row from canonical `grounding_relation`; and
4. appends safe OperationalEvent and Outbox reconciliation facts.

The ledger has forced RLS and an UPDATE/DELETE rejection trigger. API and Worker receive no table
privilege; Steward and Audit receive tenant-scoped `SELECT`; only the offline Migration Owner may
insert during reconciliation. The ledger is not queried by EffectiveClaimState, Issue, Context,
retrieval or authority code and is included in the exhaustive backup inventory.

An already-approved resolution remains canonical only if its Proposal is `APPLIED`, the actual
Decision is `APPROVE`, the Decision points to the same Issue, the Proposal patch names that Issue,
and the relation Evidence is in the actual support set. A final database postcondition rejects any
canonical `RESOLUTION_CANDIDATE` without that complete approval chain.

### 4. Compatibility must converge to one head schema

Corrected fresh 0024 and the 0025 compatibility path create the same ledger columns, constraints,
forced-RLS policy, grants, append-only trigger, comment and migration marker. Corrected 0024 may
create the object early so all candidate.1 repairs remain in the same transaction; 0025 creates it
only when an already-applied candidate.3 database lacks it. Both paths converge on
`0025_legacy_provenance_guard` and the same 32-table durable catalog.

## Executable evidence

`runtime/tests/integration/test_runtime_foundation.py` uses real PostgreSQL and candidate.1 public
procedures to cover:

- pending resolution: exact relation/hash quarantine, POLICY rejection, Issue reversal, owner
  append-only rejection, forced RLS/grants, real Issue API absence, real Context absence and later
  normal resolution;
- already-decided `REJECT`: remove/quarantine only the unauthorized relation while retaining a
  continuous three-revision Issue replay;
- already-decided `APPROVE`: retain the relation and link the actual Decision; never quarantine it;
- corrupted/missing resolution grounding: stable failure and whole rollback to 0023;
- valid legacy TX-05: actual DeletionRequest-backed reconstruction and continuous replay;
- nine independent TX-05 corruptions: missing request, requester, reason, canonical/block status,
  idempotency result, Evidence revocation, OperationalEvent, revoke Outbox and purge Outbox; every
  case raises `AF09_UNPROVABLE_LEGACY_TX05` and proves no 0024 residue; and
- an already-applied candidate.3/0024 structural state: 0025 creates the missing ledger and
  converges to the same canonical/quarantine postconditions.

Fresh base→head migration and the full exact-role suite remain separate gates. Candidate.4 cannot
close AF09-F01/F11 by author assertion; the same independent reviewer must replay the exact
receipt-anchored submission.

## Consequences

- The durable catalog increases from 31 to 32 tables: one global metadata table and 31
  tenant-owned tables.
- Backup/restore catalog equality now requires both legacy quarantine ledgers.
- A development database containing intentionally corrupted candidate.3 test residue is expected
  to fail 0025. It must be preserved for forensics or replaced by a clean database, not coerced to
  head by fabricating a DeletionRequest.
- Candidate.4 remains `0.1.x EXPERIMENTAL`, `CANDIDATE`, and `NO-GO FOR SCHEMA FREEZE` until an
  independent `ACCEPT` exists for its exact immutable submission.

# ADR-017: Populated Governance-History Reconciliation

> Status: `ACCEPTED FOR 1.0.0-candidate.3`  
> Date: `2026-08-17`（Asia/Shanghai）  
> Scope: candidate.1 populated database → current experimental head  
> Freeze effect: none; AF-09 remains `PENDING_INDEPENDENT_REVIEW`

## Context

The independent rereview of the exact candidate.2 manifest
`17561675750fa1add9f32f4dbe20f9a7ba6668861e0af2beb41e391dc55329ae`
returned `REVISE`. The immutable review record is
`docs/reviews/AF-09-independent-rereview-candidate.2-2026-08-17.md`
(SHA-256 `50f341f2d460fbca59e12b3a1841894a49dbbeb13405804e007bbb1d53557515`).

Fresh candidate.2 writes were governed, but a populated database created by candidate.1 could still contain:

1. Claim V1 and first OpenIssue rows without their `CREATE` / `ISSUE_CREATED` transition sentinels;
2. a resolution submission that had already changed an Issue to `READY_FOR_REVIEW` before a Decision, leaving
   an `open_issue_transition.decision_id = NULL` row and a pending Proposal that the corrected review procedure
   could no longer apply;
3. candidate.1 TX-05 Issue transitions whose revoke operation had a real Steward call, idempotency result,
   Evidence mutation, OperationalEvent and Outbox fact, but no materialized Proposal/Decision foreign keys; and
4. `ck_issue_transition_governed` present but not validated over existing rows.

An empty-schema migration test cannot prove the deployed-state property. Repair must preserve the original
evidence, must not invent prior authority, and must abort before serving when provenance is insufficient.

## Decision

Add forward-only migration `0024_legacy_history_reconcile` and treat populated candidate.1 data as an explicit
compatibility input. The migration runs under an offline deployment requirement and also acquires
`ACCESS EXCLUSIVE` locks on the governance tables so proof and reconciliation cannot race a writer.

### 1. Prove first, write second

Before any backfill, the migration proves each source class from existing immutable facts:

- V1: its ClaimVersion, `CREATE` Proposal, `APPROVE` Decision, actor, resulting version, canonical sequence and
  original Outbox payload must agree;
- Issue creation: its `CONTRADICT` Proposal, `APPROVE` Decision, actor, resulting Issue, canonical sequence and
  original Outbox payload must agree;
- pre-Decision resolution: Proposal patch, target, expected Issue revision, policy, actor, exact transition shape
  and original Outbox must agree;
- legacy TX-05: the immutable idempotency result, revoked Evidence, deletion request, OperationalEvent and
  original Outbox must all prove the same tenant, actor, Evidence and canonical sequence.

Unknown, conflicting or incomplete shapes raise stable `AF09_*` migration errors and roll back the entire
migration. No sentinel or governance row is synthesized from an ID or timestamp alone.

### 2. Backfill creation history from actual provenance

For every proven V1 without an incoming transition, insert exactly one `CREATE` transition with
`old_claim_version_id = NULL`, reusing the actual Proposal, Decision, actor, Decision time and canonical
sequence. For every proven Issue without a creation sentinel, insert exactly one `ISSUE_CREATED` transition
from `(NULL, revision 0)` to `(OPEN, revision 1)` with the actual creation governance facts.

Unique `(tenant_id, new_claim_version_id)` and `(tenant_id, issue_id, to_revision)` indexes then prevent a
second incoming version transition or duplicate Issue revision.

### 3. Preserve invalid legacy rows outside canonical replay

Create tenant-owned table `milai.legacy_issue_transition_quarantine`. It stores the exact legacy transition
columns, an independently recomputable SHA-256 of those columns, the reconciliation Proposal/Decision and
replacement/reversal IDs, reason, time and migration revision.

The quarantine ledger is evidence about an invalid historical effect; it is not canonical Issue history and
must never be consumed as authority. It has forced RLS, an UPDATE/DELETE rejection trigger and no API/Worker
privileges. Steward and Audit may read tenant-scoped rows; only the offline Migration Owner inserts them.
It is included in backup inventory and restore catalog comparison.

Moving a row means: insert the exact row and hash into quarantine, delete it from the canonical transition
table, then insert its governed classification/replacement in the same PostgreSQL transaction. Any failure
rolls back both sides, so the source is neither erased nor duplicated partially.

### 4. Reconcile, never retroactively approve

For a pending candidate.1 resolution effect, migration policy
`af09-candidate1-reconciliation-v1` creates a `POLICY REJECT` Decision with fixed non-user actor
`00000000-0000-4024-8024-000000000024` and reason `LEGACY_PREDECISION_EFFECT_REJECTED`. The original
Proposal becomes `REJECTED`; a governed classification records the observed legacy move; an immediate CAS
reversal restores the prior Issue status at the next revision. This actor cannot approve or elevate the
Proposal. The migration therefore removes an unauthorized effect rather than laundering it into authority.

If a real Decision already exists and its downstream transition proves the outcome, the classification links
that actual Decision and does not create a replacement decision.

For legacy TX-05, only the four-way immutable proof above permits reconstruction. A normalized
`REVOKE_EVIDENCE` Proposal and `STEWARD APPROVE` Decision reuse the original actor, fingerprint, Evidence and
canonical sequence; the exact null-governance Issue row is quarantined and replaced with the same semantic
transition linked to those facts. Missing proof aborts with `AF09_UNPROVABLE_LEGACY_TX05`.

### 5. Make completion a database postcondition

The migration flushes deferred constraints, validates `ck_issue_transition_governed`,
`ck_issue_transition_revision` and `ck_version_transition_creation`, and aborts unless:

- every ClaimVersion has exactly one incoming VersionTransition and V1 uses `CREATE` with no old version;
- every Issue has one continuous transition per revision, starting at 0 and ending at its current revision;
- every Issue has exactly one governed `ISSUE_CREATED` sentinel; and
- no canonical Issue transition has a NULL Proposal, Decision, policy or canonical sequence.

Downgrade is intentionally unsupported: deleting reconciliation Decisions, provenance sentinels or the
quarantine ledger would erase audit facts. Recovery is forward repair or restore from a verified pre-migration
backup, never destructive downgrade.

## Executable evidence

`runtime/tests/integration/test_runtime_foundation.py` contains real PostgreSQL, public-procedure regressions:

- `test_candidate1_populated_governance_state_is_reconciled_forward` creates a real 0014 V1, conflict and
  pending legacy resolution, upgrades to head, verifies source-linked sentinels, exact quarantine hash,
  owner-level append-only rejection, policy rejection/reversal, validated constraint and a subsequent normal
  review to `RESOLVED`;
- `test_candidate1_legacy_tx05_history_is_reconciled_from_four_way_proof` creates an approved resolution and
  candidate.1 TX-05 revoke at 0014, then proves reconstructed Proposal/Decision linkage, continuous replay and
  reconciliation Outbox at head; and
- `test_candidate1_unprovable_creation_history_fails_upgrade_closed` corrupts a source provenance link and
  proves that upgrade rolls back at 0023 without creating the quarantine table or partial history.

Fresh base-to-head replay remains a separate test. The exact test nodes, migration and this ADR are source
locked in candidate.3; reports are navigation only and do not replace independent execution.

## Consequences

- AF09-F01/F02 now have a forward migration and populated-state negative evidence, but only the same
  independent reviewer may close them.
- The durable catalog increases from 30 to 31 tables: one global metadata table and 30 tenant-owned tables.
- Backup/restore inventory must include the quarantine ledger; omission or an extra catalog entry fails closed.
- Deployments must stop serving during 0024 because the migration takes governance locks and may fail on
  unprovable historical state.
- Schema remains `0.1.x EXPERIMENTAL`, implementation remains `CANDIDATE`, and real personal data, remote
  deployment and schema freeze remain denied by their existing gates.

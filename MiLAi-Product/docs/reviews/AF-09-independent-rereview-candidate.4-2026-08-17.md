# AF-09 Independent Rereview — Logical Architecture 1.0.0-candidate.4

Status: `COMPLETE — DECISION REVISE`

Decision: `REVISE`

## Reviewer record

```text
Reviewer: /root/af09_reviewer_retry
Reviewer role/independence: same independent reviewer as candidate.1/2/3;
  did not author candidate.4, ADR-018, AF09_REMEDIATION, the submission
  receipt/archive, candidate source/tests, manifest, or author evidence reports;
  author preflight/remediation conclusions were not used as proof
Review started: 2026-08-17T01:26:01Z / 2026-08-17T09:26:01+08:00
Review completed: 2026-08-17T01:49:14Z / 2026-08-17T09:49:14+08:00
Candidate manifest SHA-256 before review:
  13d0a948daa0b9907fd8fc6d7142c6565f8afd3672471c1da2ed5814a5af57eb
Candidate manifest SHA-256 at decision:
  13d0a948daa0b9907fd8fc6d7142c6565f8afd3672471c1da2ed5814a5af57eb
Submission archive SHA-256:
  03ca6b686f21afacccb0a31ca9892ca2854a8a395d402adc26fb6374e36ec341
External receipt SHA-256:
  7edc99c4ab4ddd682cd50cc5b49cefe9edb34700c60c7d52bc5474887100dd5f
Decision: REVISE
Decision rationale: candidate.4 closes the rejected-grounding AF09-F01
  counterexample and the exact missing-DeletionRequest AF09-F11 counterexample,
  but its corrected 0024 and compatibility 0025 migrations do not prove the
  transaction timestamp across four claimed legacy TX-05 durable legs. A
  one-second conflict in idempotency_record.created_at, operational_event.created_at,
  EVIDENCE_REVOKED Outbox.created_at, or PURGE_EVIDENCE_DERIVATIVES
  Outbox.created_at is independently accepted and causes reconstruction of an
  APPLIED Proposal plus STEWARD APPROVE Decision. AF09-F12 is open P1; ACCEPT
  is prohibited.
Signature/reference: /root/af09_reviewer_retry candidate.4 independent rereview decision
```

This record is a full independent rereview of the exact candidate.4 submission. It does not amend
the candidate.1, candidate.2, or candidate.3 reviews. No candidate bundle, manifest, source, test,
archive, receipt, author report, or existing review was modified; this new record is the sole
repository write made by the reviewer.

## Submission identity and chain of custody

The trusted manifest digest came only from the bundle-external candidate.4 receipt. I inspected the
archive with Python `tarfile` without extraction and resolved its `MiLAi/` and workspace-sibling
members against their respective live roots.

| Check | Independent result |
| --- | --- |
| External receipt | SHA-256 `7edc99c4ab4ddd682cd50cc5b49cefe9edb34700c60c7d52bc5474887100dd5f`; exact expected object |
| Receipt manifest digest | `13d0a948daa0b9907fd8fc6d7142c6565f8afd3672471c1da2ed5814a5af57eb` |
| Live manifest digest | exact receipt match before review and at decision |
| Receipt archive digest | `03ca6b686f21afacccb0a31ca9892ca2854a8a395d402adc26fb6374e36ec341` |
| Actual archive | exact digest match; 4,767,531 bytes |
| Archive shape | 168 sorted, unique, safe relative regular-file entries; no absolute/traversal path, duplicate, symlink, hardlink, device, or other special member |
| Archive/live identity | archived manifest bytes equal live manifest; all 168 archived bytestrings equal their live project/workspace objects |
| Manifest inventory | 19 required files, 18 bundle locks, 149 source locks, 9 Git locks |
| Manifest drift during review | none |

The manifest remains `1.0.0-candidate.4`, `CANDIDATE`, schema `0.1.x EXPERIMENTAL`, `NO-GO`, and
independent review `PENDING`; this review does not mutate those submitted bytes.

## Validation environment and method

```text
Workspace: /cra/memory/mx_memory/MiLAi
Host: Linux 5.15.0-86-generic x86_64 GNU/Linux
Python: 3.11.13 (runtime/.venv)
uv: 0.8.3
Ruff: 0.16.3
mypy: 1.20.2
pytest: 8.4.2
psql client: PostgreSQL 16.14
PostgreSQL service: milai-lean-v1-postgres-1, healthy, pgvector/pgvector:pg16
PostgreSQL review database: fresh milai_af09_c4_review_clean2, not /milai
Timezone used for record: UTC and Asia/Shanghai
```

All PostgreSQL commands ran from `runtime/`. Migration Owner, API, Steward, Worker, and Audit DSNs
were constructed from the healthy container and passed through the exact
`MILAI_MIGRATION_DATABASE_URL` and `MILAI_TEST_*_DATABASE_URL` variables. No credential or DSN was
printed. I did not use or repair the intentionally contaminated `/milai` candidate.3 forensic
database.

I read the governing contract/goals/design and `AGENTS.md`; all candidate booklets, manifest,
crosswalk and `FREEZE_REVIEW.md`; ADR-001 through ADR-018; the previous independent reviews and exact
submission histories; migrations 0001 through 0025; mapped runtime SQL/application/repository/worker
code and tests; CI/package, backup/recovery, threat/privacy and external-lock material. Candidate.4
author material was navigation only. Candidate.4 was diffed against the immutable candidate.3
archive, and every changed migration, test, backup, architecture and governance artifact was read.
The decision derives from source inspection, exact-role PostgreSQL behavior and independently
constructed negative states.

## Commands and results

### Identity, architecture, and external trust anchor

```text
sha256sum <candidate.4 manifest> <candidate.4 archive> <candidate.4 receipt>
  PASS — exact trusted digests above

[Python tarfile path/type/duplicate/order/archive-live byte audit]
  PASS — entries=168, sorted=true, unique=true, unsafe=0,
         byte_diffs=0, archived_manifest_equal=true

runtime/.venv/bin/ruff format --check \
  architecture/v1.0-candidate/scripts architecture/v1.0-candidate/tests
  PASS — 4 files already formatted
runtime/.venv/bin/ruff check \
  architecture/v1.0-candidate/scripts architecture/v1.0-candidate/tests
  PASS — All checks passed

runtime/.venv/bin/python architecture/v1.0-candidate/scripts/validate_bundle.py
  PASS — MiLAi architecture bundle validation: PASS (candidate, not frozen)

runtime/.venv/bin/python architecture/v1.0-candidate/scripts/verify_lock.py \
  --scope all --mode review --expected-manifest-sha256 \
  13d0a948daa0b9907fd8fc6d7142c6565f8afd3672471c1da2ed5814a5af57eb
  PASS — MiLAi architecture lock verification: PASS (candidate, not frozen)

MILAI_ARCHITECTURE_LOCK_SCOPE=all runtime/.venv/bin/python -m unittest discover \
  -s architecture/v1.0-candidate/tests -v
  PASS — 19 tests, OK (0.794s)
```

The 19 architecture tests directly include missing/mismatched external trust anchor, coordinated
bundle-plus-manifest substitution, path escape, omitted source/bundle lock and source/Git drift
negatives. The external expected digest was supplied from the receipt rather than the manifest.

`crosswalk.json` contains all 12 invariants. An AST/node audit found all declared positive and
negative test nodes present: 32 unique direct nodes, zero missing; per invariant the positive/negative
counts are I-01 `1/1`, I-02 `1/1`, I-03 `1/4`, I-04 `4/3`, I-05 `1/2`, I-06 `1/2`, I-07 `1/2`,
I-08 `1/1`, I-09 `1/1`, I-10 `2/4`, I-11 `1/4`, and I-12 `4/6`. All ran inside the 108-test suite.
Their presence does not cure the omitted timestamp negative demonstrated below.

### Runtime, fresh migration, exact-role PostgreSQL and populated replay

From `runtime/`:

```text
uv sync --frozen --dev --python 3.11
  PASS — Audited 36 packages
uv run ruff format --check .
  PASS — 104 files already formatted
uv run ruff check .
  PASS — All checks passed
uv run mypy
  PASS — Success: no issues found in 57 source files

[fresh review database] uv run alembic upgrade head
  PASS — empty base through 0025_legacy_provenance_guard
[exact-role MILAI_TEST_* environment] uv run pytest -q
  PASS — 108 passed in 49.90s

uv run pytest -q <eight populated migration nodes below>
  PASS — 16 passed in 36.93s (parameterized cases included)
```

The targeted nodes were:

- `test_candidate1_populated_governance_state_is_reconciled_forward`;
- `test_candidate1_unprovable_resolution_grounding_rolls_back_whole_migration`;
- `test_candidate1_decided_reject_quarantines_only_unauthorized_grounding`;
- `test_candidate3_applied_0024_grounding_is_forward_repaired_by_0025`;
- `test_candidate3_applied_0024_missing_deletion_request_is_blocked_by_0025`;
- `test_candidate1_legacy_tx05_history_is_reconciled_from_four_way_proof`;
- `test_candidate1_legacy_tx05_corrupt_proof_leg_rolls_back_whole_migration`; and
- `test_candidate1_unprovable_creation_history_fails_upgrade_closed`.

These tests use candidate.1 public routines on populated revision 0014, not hand-inserted happy-path
head rows. They prove pending exact-support rejection, exact row/SHA quarantine, Issue API and
L0-derived Context absence, later normal review, already-decided REJECT isolation, APPROVE retention,
missing/conflicting relation whole rollback, candidate.3 0024 compatibility, actual DeletionRequest,
the author's nine TX-05 corruptions, V1/Issue creation history, continuous replay and validated
constraints. The official suite is green but does not mutate the four timestamp columns in AF09-F12.

The head catalog independently reported 32 `milai` durable tables, the 31-table backup inventory,
and revision `0025_legacy_provenance_guard`. Both quarantine ledgers reported
`relrowsecurity=true`, `relforcerowsecurity=true`; API/Worker had no table privilege, Steward/Audit
had SELECT only, and each append-only UPDATE/DELETE trigger was enabled. The populated tests exercise
nonempty Migration Owner UPDATE/DELETE denial.

```text
uv run pytest -q \
  tests/integration/test_backup_restore.py::test_consistency_backup_restore_and_deletion_expiry_reconciliation
  PASS — 1 passed in 6.33s
uv run pytest -q tests/security
  PASS — 5 passed in 0.36s
```

The backup drill includes both ledgers in the database count/SHA inventory, verifies archive
integrity, exercises revoke, physical purge, backup obligation/expiry and restore, and compares the
restored inventory. The security suite and full suite cover exact DB-role attestation, RLS,
cross-role/cross-tenant denial, owner/swap negatives, session reset, secrets and log redaction.

### Research, package, CI/Compose and documentation

```text
runtime/.venv/bin/ruff format --check research/ospc
  PASS — 11 files already formatted
runtime/.venv/bin/ruff check research/ospc
  PASS — All checks passed
runtime/.venv/bin/mypy --strict research/ospc
  PASS — 7 source files
runtime/.venv/bin/python -m unittest discover -s research/ospc/tests -v
  PASS — 9 tests, OK (0.194s)

[fresh temporary research copy] generate_fixtures + run_benchmark
  PASS — 40 synthetic fixtures
  fixture SHA-256=8fd9482aacf58d8802a16dbc86a9e8043ffc28123d904f72b7b87a052eaa718a
  decision=ABANDON; novelty_claim=false
  reasons=HF-01_STRONG_TYPED_STATE_EQUIVALENT,
          HF-02_STATIC_OPEN_ISSUE_EQUIVALENT,
          HF-06_VALIDATOR_COST_WITHOUT_MEASURED_GAIN

uv build --out-dir <fresh-temporary-directory>
  PASS — wheel SHA-256
    7e0430cf8aeb05f8e1d880b094ef9ef1fda3d52f8edbc78f2a6f42fd534f012d
  PASS — sdist SHA-256
    19661b7772c9f7f3ccf40f3a3cf3773981107fab5f2ac616bbd301700f94f5a7
  wheel entries=63; safe contents inspection PASS
uv venv <fresh-temporary-venv> --python 3.11
uv pip install --no-deps <fresh-wheel>
  PASS — installed distribution milai-runtime==0.1.0

Ruby YAML.safe_load .github/workflows/ci.yml
  PASS — mapping; job=runtime-and-research
[container-env supplied without printing values] docker compose config --quiet
  PASS
[Markdown fence and root-bounded relative-link audit]
  PASS — 73 source/history files before this review; 1,008 headings;
         21 relative links; zero errors
```

Research remains synthetic-only, makes no production authority claim and has no runtime/external
framework import. External assets are disabled from the core path and their exact source/license/Git
identities passed the all-scope lock. The package check used fresh output and installation locations;
no build artifact was written into the repository.

## Candidate.3 P1 closure replay

### AF09-F01 — closed by exact rejected-grounding reconciliation

The corrected 0024 migration proves that each distinct Proposal support item equals the exact
Issue-owned `RESOLUTION_CANDIDATE` set, then preserves each rejected row and its SQL-computed content
SHA-256 in `legacy_grounding_relation_quarantine` and removes it from canonical grounding
(`0024_legacy_history_reconciliation.py:431-828,1363-1545`). Only an actual `APPLIED` Proposal and
`APPROVE` Decision may retain the canonical relation. Compatibility 0025 applies the same guard to
candidate.3 databases (`0025_legacy_provenance_compatibility.py:306-598`).

Independent real-PostgreSQL replay observed:

- a pending candidate.1 submission ends POLICY `REJECT`, exact relation/hash in immutable
  quarantine, zero rejected relation in canonical Issue and L0-derived Context, followed by a normal
  new review;
- an already-decided `REJECT` relation is quarantined while actual `APPROVE` grounding remains
  canonical and decision-linked;
- a missing or conflicting support relation aborts the whole fresh migration at 0023 without a 0024
  table, Proposal, Decision, transition, relation, event, Outbox or Alembic residue; and
- an old candidate.3 0024 database advances safely through 0025, while its missing-request negative
  remains at 0024 with no 0025 residue.

The original AF09-F01 counterexample is therefore `CLOSED`.

### AF09-F11 — missing durable request repaired, but full provenance gate not closed

Both 0024 and 0025 now lock and join the real tenant-scoped `deletion_request` by request, Evidence
and Blob identity. They verify requester/creator actor, reason, `requested_at = Evidence.revoked_at`,
logical/canonical status, all derived/primary/backup/retention state domains, idempotency payload,
OperationalEvent and the revoke/purge Outbox pair
(`0024_legacy_history_reconciliation.py:277-430,882-1152` and
`0025_legacy_provenance_compatibility.py:160-305`). Deleting the actual request now yields stable
`AF09_UNPROVABLE_LEGACY_TX05`, with fresh state at 0023/no 0024 residue and old candidate.3 state at
0024/no 0025 residue.

Independent mutations also showed that DeletionRequest creator, DeletionRequest requested time,
Evidence identity, Blob identity, and each of logical/canonical/derived/primary/backup/retention state
axes individually fail closed at 0023 with neither quarantine ledger nor reconstructed Proposal,
Decision, event or Outbox. Thus the exact candidate.3 missing-row counterexample is repaired. The
broader candidate.4 closure obligation is nevertheless incomplete because AF09-F12 accepts conflicts
in four other durable time legs.

## AF09-F12 independent TX-05 timestamp counterexample

ADR-018 requires one mutually consistent transaction with “the same requester/creator actor and
transaction timestamp” (`docs/adr/ADR-018-rejected-grounding-and-tx05-provenance-guard.md:47-66`).
The bundle repeats the requester/creator/reason/**time** obligation at
`architecture/v1.0-candidate/TRANSACTIONS.md:154-177`. Both migration predicates compare only
`deletion.requested_at = evidence.revoked_at`; neither compares the timestamps of the idempotency,
OperationalEvent, revoke Outbox or purge Outbox legs
(`0024_legacy_history_reconciliation.py:303-424`, especially `:333`, and
`0025_legacy_provenance_compatibility.py:182-299`, especially `:208`).

Each independent case used a fresh disposable real PostgreSQL database, migrated to candidate.1
revision `0014_query_plan_outbox_sequence`, and constructed a real conflict plus governed resolution
and revoke by calling the public candidate.1 routines as the exact API/Steward roles. As Migration
Owner, exactly one source timestamp was changed, then the unchanged candidate.4 migration was run:

```sql
-- Run as four separate disposable cases, restricted to the created TX-05 row.
UPDATE milai.idempotency_record
SET created_at = created_at + interval '1 second' ...;

UPDATE milai.operational_event
SET created_at = created_at + interval '1 second'
WHERE event_type = 'EVIDENCE_REVOKED' ...;

UPDATE milai.outbox_event
SET created_at = created_at + interval '1 second'
WHERE event_type = 'EVIDENCE_REVOKED' ...;

UPDATE milai.outbox_event
SET created_at = created_at + interval '1 second'
WHERE event_type = 'PURGE_EVIDENCE_DERIVATIVES' ...;
```

All four cases unexpectedly succeeded. Each reached:

```text
('0025_legacy_provenance_guard',
 'milai.legacy_issue_transition_quarantine',
 'milai.legacy_grounding_relation_quarantine',
 reconstructed REVOKE_EVIDENCE Proposal count=1,
 reconstructed STEWARD APPROVE Decision count=1,
 reconstructed governance transition count=1)
```

By contrast, creator, request/evidence timestamp, entity identity and every state-axis mutation
returned stable `AF09_UNPROVABLE_LEGACY_TX05` and the tuple:

```text
('0023_erasure_sha256_repair', NULL, NULL,
 reconstructed Proposal count=0, Decision count=0, transition count=0)
```

Every temporary counterexample database was force-dropped after observation. The accepted states
are not harmless timestamp formatting differences: candidate.1 uses the durable timestamp legs as
evidence that the records came from one atomic TX-05, and candidate.4 uses that claimed transaction
to synthesize an authoritative historical `APPLIED` Proposal and `STEWARD APPROVE` Decision. A proof
predicate that ignores conflicting claimed legs cannot establish that transaction. This is a direct
hard-reject condition, not a test-coverage-only concern.

## AF09-F01 through AF09-F11 closure audit

`CLOSED` means the original behavior was observed in source and direct tests; it is not overall
acceptance.

| Finding | Candidate.4 status | Independent conclusion |
| --- | --- | --- |
| AF09-F01 — submission mutates canonical state before Decision | **CLOSED** | Fresh submission remains noncanonical; populated pending/rejected relation sets are exact-hash quarantined, absent from Issue/Context, and only actual APPROVE grounding remains. Missing/conflicting support rolls back whole. |
| AF09-F02 — missing V1/OpenIssue creation history | **CLOSED; no regression** | Source-linked V1 CREATE and ISSUE_CREATED sentinels, unique incoming history, continuous replay and validated constraints passed positive and corrupted-source rollback nodes. |
| AF09-F03 — normative/legacy state domains | **CLOSED; no regression** | Normative constraints, legacy mapping, exhaustive accepted domains and unknown-value rollback tests passed. |
| AF09-F04 — Gate omits axes / bypasses ECS | **CLOSED; no regression** | ECS-only all-version Gate/Context enforces lifecycle, epistemic, freshness, Scope, valid/system time, authority and confidence independently; all-axis negatives passed. |
| AF09-F05 — indirect crosswalk evidence | **CLOSED for original omissions** | All 32 unique direct positive/negative nodes exist and ran. The newly absent timestamp node/false behavior is AF09-F12. |
| AF09-F06 — TX-05 lacks governed Decision | **CLOSED for current writes** | Current TX-05 remains Steward-only, Proposal/Decision-linked and atomically rolled back across the declared failure classes. AF09-F12 concerns supported legacy reconstruction. |
| AF09-F07 — ERASED lacks durable absence proof | **CLOSED; no regression** | Typed adapter plus SQL identity/SHA absence proof and forged/missing/symlink/crash/retry negatives passed. |
| AF09-F08 — exact DB-role attestation missing | **CLOSED; no regression** | Exact usernames, `session_user=current_user`, unsafe attributes and ownership are checked; exact-role and owner/swapped-role negatives passed. |
| AF09-F09 — no real Outbox causal token/wait/fallback | **CLOSED; no regression** | Tenant-bound HMAC token uses real Outbox position; continuous watermark, bounded wait, dead-letter/timeout fallback and trace tests passed. |
| AF09-F10 — no external manifest trust anchor | **CLOSED; no regression** | Exact external receipt digest, all-scope review verification, archive-live identity and coordinated-substitution rejection passed. |
| AF09-F11 — missing actual DeletionRequest still reconstructs APPROVE | **Exact candidate.3 counterexample CLOSED; broader provenance closure incomplete** | Missing request now rolls back fresh 0024 and compat 0025. Creator/request time/entity/all state axes also fail closed. Four other transaction-time legs remain unchecked and are separately open as AF09-F12. |

## G1-G9 and I-01-I-12 adversarial audit

| Goal | Result | Conclusion |
| --- | --- | --- |
| G1 Source Fidelity | PASS | Evidence identity, immutable capture, lineage, blocks and Gate behavior remain enforced. |
| G2 Governed Canonical Evolution | **FAIL — AF09-F12** | Migration fabricates APPROVE governance from durable records that no longer prove one transaction. |
| G3 Open-State Preservation | PASS | Candidate.4 exact-hash quarantines rejected grounding and preserves Issue identity/open semantics. |
| G4 Applicability Separation | PASS | Typed independent axes and exhaustive ECS/Gate negatives remain executable. |
| G5 Candidate-Safe Retrieval | PASS | L0/L1/Context use canonical Gate; projection/model/external inputs cannot elevate authority. |
| G6 Revocation Propagation | **FAIL — AF09-F12** | Current revoke/purge passes, but supported legacy reconciliation accepts four conflicting time legs. |
| G7 Bounded Traceable Context | PASS | Bounds/trace pass and rejected candidate.1 grounding is absent from real Context. |
| G8 Least-Privilege Local Security | PASS | Exact roles, forced RLS, session reset, loopback, separate secrets and redaction pass. |
| G9 Replaceable and Recoverable | **FAIL — AF09-F12** | Backup/restore mechanics pass, but populated forward repair is not fail-closed for all declared provenance. |

| Invariant | Result | Adversarial conclusion |
| --- | --- | --- |
| I-01 | PASS | Evidence/Claim identities stay separate and API direct collapse is denied. |
| I-02 | PASS | Capture identity is immutable; idempotency conflicts fail closed. |
| I-03 | PASS | Submission is noncanonical, and populated rejected effects are removed outside authority. |
| I-04 | PASS | All four histories and both quarantine ledgers are append-only; V1/Issue replay is complete. |
| I-05 | PASS | Head/Issue CAS races have one winner and full loser rollback. |
| I-06 | PASS | Issue identity/status/revision and candidate.1 rejected-grounding reconciliation pass. |
| I-07 | PASS | L0 consumes ECS-only all-axis Gate. |
| I-08 | PASS | Projection/external candidates cannot bypass Gate; canonical outage abstains. |
| I-09 | PASS | Normative states and all orthogonal applicability axes have direct independent negatives. |
| I-10 | **FAIL — AF09-F12** | Fresh revoke and erasure proof pass; legacy revoke accepts four source timestamp conflicts. |
| I-11 | PASS | Exact role, RLS, cross-role/cross-tenant and owner-swap negatives pass. |
| I-12 | **FAIL — AF09-F12** | Fresh atomicity/causal trace passes, but populated reconciliation creates authority from a non-proven atomic source transaction. |

## Fifteen-item semantic checklist

| Check | Decision | Evidence/finding |
| --- | --- | --- |
| G1-G9 mutually consistent and no circular authorization | **FAIL** | G2/G6/G9 fail: a predicate that omits four transaction timestamps is used to authorize reconstructed APPROVE history. AF09-F12. |
| I-01-I-12 each have executable positive and negative evidence | **FAIL** | Declared direct nodes exist/run, but no negative mutates the four time legs and I-10/I-12 are false for those states. |
| Evidence/Claim/OpenIssue/Context identity boundaries are explicit | PASS | Separate IDs, ownership, pointers and traces remain explicit; rejected grounding no longer leaks. |
| Steward single-writer, CAS, append-only and rollback are complete | **FAIL** | Fresh paths and ledgers pass, but Migration Owner accepts unprovable legacy state instead of entering the required whole rollback. |
| authority/Scope/time/freshness/epistemic are orthogonally matched | PASS | Normative domains, ECS, typed plans and all-axis negatives pass. |
| projection/external/model cannot raise truth/authority | PASS | Canonical Gate is the active boundary; projection/model/external failures only abstain or reduce recall. |
| revoke, Context invalidation, purge, Blob/backup obligations fail closed | **FAIL** | Current flow and backup drill pass; legacy revoke provenance fails open for four time conflicts. AF09-F12. |
| tenant/RLS/roles/network/secrets/log privacy are least privilege | PASS | Exact roles, forced RLS, loopback Compose, secret separation and redaction passed direct tests. |
| dual sequence, watermark, RYW and recovery are unambiguous | PASS | Canonical/Outbox sequences, real tenant-bound token, continuous watermark, wait/fallback and recovery traces pass. |
| external assets can be disabled and license/identity verified | PASS | All-scope source/Git locks pass and no external route is needed for core runtime/build behavior. |
| threat residual and synthetic-only boundary acceptable | **FAIL** | Synthetic/remote/real-data boundaries are explicit, but the declared legacy TX-05 residual omits the demonstrated timestamp states. |
| migration/rollback/legacy/real-data change policy executable | **FAIL** | Fresh, official populated and compat paths pass; four unprovable states incorrectly advance to 0025. |
| populated candidate.1 provenance/quarantine/replay/validated constraints executable | **FAIL** | Grounding, creation history, replay and constraints pass; TX-05 provenance is incomplete under AF09-F12. |
| rejected grounding exact support/hash quarantine and real Issue/Context absence | PASS | AF09-F01 closes under exact candidate.1 pending/decided/missing/conflicting and candidate.3 compat replays. |
| legacy TX-05 actual DeletionRequest, per-leg fail-close and prior-head rollback | **FAIL** | Actual request/entity/creator/request-time/state axes pass, but four durable `created_at` legs can conflict and still reconstruct authority. |

## Hard-reject sweep

| Hard-reject condition | Result | Evidence/conclusion |
| --- | --- | --- |
| Unmapped G/I/MUST or indirect-only evidence | **TRIGGERED — AF09-F12** | The mandatory same-transaction timestamp has no direct negative for four legs, and source behavior contradicts it. |
| API/worker/model/adapter can direct canonical DML | NOT TRIGGERED | Current direct-DML grants/procedures and real-role negatives pass. |
| Cross-tenant/permission/retention/revoke/canonical outage fails open | **TRIGGERED — AF09-F12** | Current runtime negatives pass, but the supported legacy revoke migration fails open for time conflicts. |
| Conflict/Issue auto-closed by summary/retrieval/time/model | NOT TRIGGERED | Only governed Decision paths close; rejected legacy grounding is removed from canonical Issue/Context. |
| Projection/Context/graph/external memory is authority | NOT TRIGGERED | All remain candidates/consumers behind canonical Gate. |
| CAS loser/rollback/outbox/history has partial write | NOT TRIGGERED for exercised current/failing paths | CAS, current TX rollback, relation failures and candidate.3 compat failures leave no residue. |
| Populated migration fabricates authority, omits history, loses source, has mutable quarantine, or fails to abort unprovable state | **TRIGGERED — AF09-F12** | Four conflicting source timestamps still yield an APPLIED Proposal and STEWARD APPROVE Decision. |
| Rejected Proposal grounding remains canonical or lacks exact-hash preservation | NOT TRIGGERED | Exact pending/REJECT rows are immutable-hash quarantined; only actual APPROVE remains canonical. |
| Legacy TX-05 proof leg missing/conflicting still reconstructs, or failed migration leaves residue | **TRIGGERED — AF09-F12** | Four conflicting `created_at` proof legs reconstruct successfully. |
| Manifest/source/Git drift is not rejected | NOT TRIGGERED | Archive/live identity and all-scope lock pass; manifest did not drift. |
| External trust anchor absent or coordinated substitution accepted | NOT TRIGGERED | Exact receipt anchor and coordinated-tamper negative pass. |
| Real-data/remote gate or residual risk hidden | NOT TRIGGERED for declared deployment boundary | Real/remote boundaries remain explicit; this review records the new migration residual. |
| Candidate banner removed before freeze | NOT TRIGGERED | Candidate/experimental/no-go banners remain present. |

## Open finding and required change

| ID | Severity | Artifact/line | Finding | Required change/evidence |
| --- | --- | --- | --- | --- |
| AF09-F12 | P1 | `docs/adr/ADR-018-rejected-grounding-and-tx05-provenance-guard.md:47-66`; `architecture/v1.0-candidate/TRANSACTIONS.md:154-177`; `runtime/migrations/versions/0024_legacy_history_reconciliation.py:303-424`; `runtime/migrations/versions/0025_legacy_provenance_compatibility.py:182-299`; `runtime/tests/integration/test_runtime_foundation.py:1613-1767` | Candidate.4 claims a mutually consistent legacy TX-05 transaction timestamp but verifies only DeletionRequest `requested_at = Evidence.revoked_at`. Independently shifting `created_at` by one second on idempotency, OperationalEvent, revoke Outbox, or purge Outbox is accepted by both proof shapes and reconstructs authoritative APPLIED/APPROVE governance. The official nine-corruption parameter set does not exercise these four fields. | In both corrected 0024 and compatibility 0025, choose the original TX-05 transaction timestamp from durable candidate.1 semantics and require exact agreement by DeletionRequest/Evidence, idempotency record, OperationalEvent and both Outbox legs. Any absent or conflicting leg must raise stable `AF09_UNPROVABLE_LEGACY_TX05`, leave fresh state at 0023 or old-compatible state at 0024, and leave no ledger/Proposal/Decision/transition/event/Outbox/Alembic residue. Add four independent public-procedure populated negative nodes (plus a valid control), map/source-lock them, and submit a new immutable candidate/manifest/archive/external receipt. |

## Residual gates and decision

Before another candidate can be accepted:

1. Corrected 0024 and compatibility 0025 must prove the timestamp across every durable TX-05 source
   leg, not only DeletionRequest and Evidence.
2. Four direct public-procedure negative replays must demonstrate stable error and whole rollback at
   both supported prior heads, alongside the valid control and existing entity/actor/reason/state
   mutations.
3. A new immutable candidate must rerun external-anchor/all-scope lock, exact-role PostgreSQL,
   fresh/populated/compat migration, backup/security, research, package, CI/Compose, documentation
   and final drift gates.

Candidate.4 substantively closes AF09-F01 and the actual-missing-request AF09-F11 counterexample,
and F02-F10 remain closed. The full ordinary and official populated suites are green. Nevertheless,
AF09-F12 is a real PostgreSQL counterexample to an explicit MUST and triggers the populated-migration
and legacy-TX05 hard-reject conditions. Under `FREEZE_REVIEW.md:84-110`, a P1 finding prohibits ACCEPT.

```text
Decision: REVISE
Architecture: 1.0.0-candidate.4 — NOT FROZEN
Schema: 0.1.x EXPERIMENTAL
Implementation: CANDIDATE
Freeze: NO-GO
Open P1 finding: AF09-F12
Manifest before/at decision:
  13d0a948daa0b9907fd8fc6d7142c6565f8afd3672471c1da2ed5814a5af57eb
Signature/reference: /root/af09_reviewer_retry candidate.4 independent rereview decision
```

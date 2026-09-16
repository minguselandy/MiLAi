# AF-09 Independent Rereview — Logical Architecture 1.0.0-candidate.3

Status: `COMPLETE — DECISION REVISE`

Decision: `REVISE`

## Reviewer record

```text
Reviewer: /root/af09_reviewer_retry
Reviewer role/independence: same independent reviewer as candidate.1/candidate.2;
  did not author candidate.3, ADR-017, AF09_REMEDIATION, the submission
  receipt/archive, candidate code/tests, manifest, or evidence reports;
  author preflight/remediation conclusions were not used as proof
Review started: 2026-08-16T18:05:18Z / 2026-08-17T02:05:18+08:00
Review completed: 2026-08-16T18:16:58Z / 2026-08-17T02:16:58+08:00
Candidate manifest SHA-256 before review:
  6a2f1574511f53614d558d663b0792c79b26c1b43a62ab746bfe10f367f15620
Candidate manifest SHA-256 at decision:
  6a2f1574511f53614d558d663b0792c79b26c1b43a62ab746bfe10f367f15620
Submission archive SHA-256:
  1c57041803db46ff90e74e9fcb305c72fe72aa85ac1f3946a747a65f2fb8a8bd
External receipt SHA-256:
  0c3ddfc9b86c66df296b1c2b43554b7af713ac9884e0c431be5837007c4e520a
Decision: REVISE
Decision rationale: candidate.3 repairs V1/Issue creation history and the
  legacy OpenIssue transition, but leaves the candidate.1 resolution
  submission's pre-Decision RESOLUTION_CANDIDATE GroundingRelation in the
  canonical aggregate after policy rejection. Independently, migration 0024
  accepts a legacy TX-05 whose actual DeletionRequest is absent and fabricates
  a REVOKE_EVIDENCE Proposal plus STEWARD APPROVE Decision from agreeing JSON
  references. AF09-F01 and AF09-F11 are open P1 findings; ACCEPT is prohibited.
Signature/reference: /root/af09_reviewer_retry candidate.3 independent rereview decision
```

This is a full rereview of the exact candidate.3 submission. It does not amend either earlier
independent review. No candidate, manifest, source, test, archive, receipt, existing review, or
evidence-report file was modified during this review; this new record is the sole review write.

## Submission identity and chain of custody

The trusted manifest digest came from the bundle-external candidate.3 receipt, not from candidate
metadata. I inspected the archive with Python `tarfile` without extracting it or trusting member
paths.

| Check | Independent result |
| --- | --- |
| External receipt | SHA-256 `0c3ddfc9b86c66df296b1c2b43554b7af713ac9884e0c431be5837007c4e520a`; exact expected object |
| Receipt manifest digest | `6a2f1574511f53614d558d663b0792c79b26c1b43a62ab746bfe10f367f15620` |
| Live manifest digest | exact receipt match before review and at decision |
| Receipt archive digest | `1c57041803db46ff90e74e9fcb305c72fe72aa85ac1f3946a747a65f2fb8a8bd` |
| Actual archive | exact digest match; 2,367,005 bytes |
| Archive shape | 161 sorted, unique, safe relative regular-file entries; no absolute/traversal path, symlink, hardlink, device, or duplicate |
| Archive/live identity | archived manifest bytes equal live manifest; every one of the 161 archived bytestrings equals its live workspace object |
| Manifest inventory | 19 required files, 18 bundle locks, 142 source locks |
| Manifest drift during review | none |

The manifest retains `1.0.0-candidate.3`, `CANDIDATE`, schema `0.1.x EXPERIMENTAL`, and `NO-GO`.

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
Timezone used for record: UTC and Asia/Shanghai
```

All PostgreSQL tests ran from `runtime/`. Migration Owner, API, Steward, Worker, and Audit DSNs were
constructed from the healthy service and passed through the exact `MILAI_MIGRATION_DATABASE_URL` and
`MILAI_TEST_*_DATABASE_URL` variables. No credential or DSN is printed here.

I read the governing contract/goals/design, `AGENTS.md`, all candidate booklets, manifest/crosswalk,
`FREEZE_REVIEW.md`, ADR-001 through ADR-017, prior independent reviews, candidate.3 remediation and
DG-00 completion material, migrations 0001 through 0024, relevant runtime SQL/application/repository/
worker code, every mapped direct test node, backup runbook/implementation/tests, CI/package material,
and locked external identities. Author reports were navigation only. The decision derives from source,
real PostgreSQL behavior, and independently constructed negative states.

## Commands and results

### Identity, architecture, and external trust anchor

```text
sha256sum <candidate.3 manifest> <candidate.3 archive> <candidate.3 receipt>
  PASS — exact trusted digests above

[Python tarfile member/path/type/duplicate/content audit]
  PASS — 161/161 safe archive members byte-equal live objects

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
  6a2f1574511f53614d558d663b0792c79b26c1b43a62ab746bfe10f367f15620
  PASS — MiLAi architecture lock verification: PASS (candidate, not frozen)

MILAI_ARCHITECTURE_LOCK_SCOPE=all runtime/.venv/bin/python -m unittest discover \
  -s architecture/v1.0-candidate/tests -v
  PASS — 19 tests, OK (0.680s)
```

The 19 tests include missing external anchor, digest mismatch, path/source drift, and coordinated
bundle-plus-manifest substitution rejection. The trusted digest was supplied independently.

### Runtime, exact-role PostgreSQL, and populated migration

Run from `runtime/`:

```text
uv sync --frozen --dev --python 3.11
  PASS — Audited 36 packages
uv run ruff format --check .
  PASS — 103 files already formatted
uv run ruff check .
  PASS — All checks passed
uv run mypy
  PASS — Success: no issues found in 57 source files
[exact-role MILAI_TEST_* environment] uv run pytest -q
  PASS — 95 passed in 28.88s

uv run pytest -q \
  tests/integration/test_runtime_foundation.py::test_candidate1_populated_governance_state_is_reconciled_forward \
  tests/integration/test_runtime_foundation.py::test_candidate1_legacy_tx05_history_is_reconciled_from_four_way_proof \
  tests/integration/test_runtime_foundation.py::test_candidate1_unprovable_creation_history_fails_upgrade_closed
  PASS — 3 passed in 5.71s
```

The 95-test suite includes fresh empty base-to-0024 migration, real-role RLS/direct-DML negatives,
fresh proposal non-mutation, V1/Issue histories, normalized state constraints, all-axis ECS Gate,
governed TX-05 rollback, SQL-verified durable absence, exact-role attestation, real Outbox causal
tokens/wait/fallback, quarantine/backup/restore/revoke/purge, and the three populated tests above.
Those green tests do not cover the independently demonstrated states below.

An additional real populated quarantine drill observed:

```text
quarantine catalog: relrowsecurity=true; relforcerowsecurity=true
API SELECT=false; API INSERT=false; Worker SELECT=false
Steward SELECT=true; Audit SELECT=true; append-only trigger enabled=true
nonempty backup inventory: row_count=1
  content_sha256=c076e1420a2b323acb16939853f4e22cb614ea08bfe54652b081cfe55af9b5a3
restored row: byte/field equal; status=RESTORED_AND_RECONCILED
  revision=0024_legacy_history_reconcile
```

The official populated test also proves Migration Owner UPDATE of quarantine raises
`APPEND_ONLY_VIOLATION`. Thus quarantine mechanics and backup inventory pass; the findings concern
data that migration 0024 never quarantines and an insufficient proof predicate.

### Research, package, CI/Compose, and documentation

```text
runtime/.venv/bin/ruff format --check research/ospc
  PASS — 11 files already formatted
runtime/.venv/bin/ruff check research/ospc
  PASS
runtime/.venv/bin/mypy --strict research/ospc
  PASS — 7 files
runtime/.venv/bin/python -m unittest discover -s research/ospc/tests -v
  PASS — 9 tests, OK (0.194s)

[fresh temporary copy] generate_fixtures + run_benchmark
  PASS — 40 synthetic fixtures; generated fixture/manifest byte-equal locks
  fixture SHA-256=8fd9482aacf58d8802a16dbc86a9e8043ffc28123d904f72b7b87a052eaa718a
  decision=ABANDON; novelty=false; reasons=HF01,HF02,HF06

uv build --out-dir <fresh-temporary-directory>
  PASS — wheel SHA-256
    253fb6ede6b22fe142972990c78b71b59ad0083c9723cbaef8429a3d83bf714d
  PASS — sdist SHA-256
    93d9f6bd9eef48b0d50512241a352aed6134ba8d0bcd80885d22248e9ef90273
  wheel entries=63; unzip/contents inspection PASS

Ruby YAML.safe_load .github/workflows/ci.yml
  PASS — mapping with one job
docker compose config --quiet
  PASS
[locked Markdown fence/relative-link audit]
  PASS — 59 files; 625 headings; 20 relative links
```

Research remains synthetic-only and cannot authorize product behavior. External assets remain off by
default and are not imported by the core runtime/build path.

## Independent populated-state counterexamples

Each harness used a disposable real PostgreSQL database, migrated it to
`0014_query_plan_outbox_sequence`, constructed state through candidate.1 public API/Steward routines,
then upgraded the same populated database to head. Temporary databases were force-dropped after the
queries. No fixture, migration, source, or candidate artifact was edited.

### AF09-F01 — rejected legacy resolution leaves canonical grounding

Reproduction shape:

1. Use the helpers/public procedures at `test_runtime_foundation.py:186-272` to create Claim V1,
   CONTRADICT/OpenIssue, resolution Evidence, and a pending SUPERSEDE resolution at 0014.
2. Confirm candidate.1 submission inserted one `RESOLUTION_CANDIDATE` relation whose
   `created_from_proposal_id` is that pending proposal.
3. Upgrade to head and query `grounding_relation`, proposal/Decision, and OpenIssue.

Observed result:

```text
before upgrade: RESOLUTION_CANDIDATE count=1; created_from_proposal_id=legacy proposal
after upgrade:
  (RESOLUTION_CANDIDATE count=1,
   relation still linked to legacy proposal=true,
   proposal.status='REJECTED', decision='REJECT',
   issue.status='OPEN', revision migration='0024_legacy_history_reconcile')
```

Candidate.1 inserts that canonical relation before any Decision at
`runtime/migrations/versions/0005_canonical_procedures.py:304-405`, specifically `:376-383`.
Candidate.3 repairs/quarantines only `open_issue_transition`; migration 0024 has no
`grounding_relation` reference. Its pending-state reconciliation rejects the Proposal and reverses
the Issue at `0024_legacy_history_reconciliation.py:869-1026`, but leaves the rejected Proposal's
canonical resolution branch behind.

This directly violates `architecture/v1.0-candidate/OBJECTS.md:69-74`: submission must not alter
grounding, only an APPROVE transaction may materialize it, and REJECT must preserve the Issue's
original state. It is observable, not inert: the canonical Issue repository returns every relation
as a branch (`runtime/src/milai/persistence/canonical_repository.py:259-299`), and Context aggregates
all relations for live Issues (`runtime/src/milai/persistence/context_repository.py:105-124`). The
fresh negative test at `runtime/tests/integration/test_canonical_api.py:246-255` correctly protects
new submissions, but the populated test at `test_runtime_foundation.py:317-621` never counts the
legacy relation. AF09-F01 therefore remains open.

### AF09-F11 — missing DeletionRequest still yields reconstructed APPROVE authority

Reproduction shape:

1. At 0014 create a real conflict, submit and approve a resolution, then call public
   `milai.tx05_revoke_evidence` as the exact Steward role (`test_runtime_foundation.py:631-718`).
2. As Migration Owner, delete the resulting `milai.deletion_request` row while retaining the legacy
   idempotency record, revoked Evidence, OperationalEvent, Outbox and null-governance TX-05 Issue row.
3. Upgrade to head. ADR-017 requires `AF09_UNPROVABLE_LEGACY_TX05` and whole rollback.

Observed result:

```text
deletion_request before corruption=1; after corruption=0
migration outcome=unexpected-success
post-upgrade state:
  ('0024_legacy_history_reconcile',
   actual deletion_request count=0,
   reconstructed REVOKE_EVIDENCE Proposal count=1,
   reconstructed STEWARD APPROVE Decision count=1,
   governed replacement transition count=1)
```

ADR-017 requires the deletion request itself to agree with the other immutable facts
(`docs/adr/ADR-017-populated-governance-history-reconciliation.md:35-49,88-91`). The implementation's
proof at `runtime/migrations/versions/0024_legacy_history_reconciliation.py:390-435,588-675` only
checks that JSON contains a `deletion_request_id` and that three JSON copies agree. It never joins
`milai.deletion_request`. It then creates an `APPLIED` Proposal and `STEWARD APPROVE` Decision at
`:714-751`. Agreement among references to a missing object is not proof of the required object.

The positive TX-05 test at `test_runtime_foundation.py:631-826` covers only a valid request. The
unprovable negative at `:829-893` corrupts V1 creation provenance, not any TX-05 proof leg. This is a
new P1 finding, AF09-F11.

## AF09-F01 through AF09-F10 closure audit

`CLOSED` means the original required behavior was observed in SQL/code and direct tests; it is not an
overall acceptance.

| Finding | Candidate.3 status | Independent conclusion |
| --- | --- | --- |
| AF09-F01 — proposal submission mutates canonical state before Decision | **OPEN P1** | Fresh candidate.3 submission is noncanonical and migration 0024 quarantines/reverses the legacy Issue transition, but the same legacy submission's canonical `RESOLUTION_CANDIDATE` grounding survives POLICY REJECT and remains exposed in Issue/Context branches. The original finding expressly included pre-Decision grounding. |
| AF09-F02 — missing V1/OpenIssue creation history | **CLOSED** | Migration 0024 proves source Proposal/Decision/actor/sequence/Outbox, backfills `CREATE old=NULL` and `ISSUE_CREATED NULL/0→1`, enforces unique incoming revisions, validates constraints, and asserts continuous replay. The official real populated positive and corrupted V1 rollback tests passed; rollback remained at 0023 with no quarantine or partial sentinel. |
| AF09-F03 — normative/legacy state domains | **CLOSED** | Normalization migration, normative constraints, exhaustive allowed-domain and unknown-value rollback nodes passed. |
| AF09-F04 — Gate omits axes / bypasses ECS | **CLOSED** | ECS-only all-version Gate and Context delegation enforce lifecycle, epistemic, freshness, Scope, valid/system time, authority and confidence independence; direct all-axis negatives passed. |
| AF09-F05 — indirect crosswalk evidence | **CLOSED for original omissions** | Direct Evidence/Claim separation, all four append-only histories, every Gate axis, and full rollback residue tests exist and ran. The distinct missing populated negatives are recorded as AF09-F01/F11. |
| AF09-F06 — TX-05 lacks governed Decision | **CLOSED for current writes** | Current TX-05 has Steward-only Proposal/Decision, linked history/event/outbox, and six-class rollback. AF09-F11 concerns unsafe legacy reconstruction, not the current transaction. |
| AF09-F07 — ERASED lacks durable absence proof | **CLOSED** | Typed adapter proof plus SQL identity/SHA recomputation and forged/missing/symlink/crash/retry negatives passed. |
| AF09-F08 — exact DB-role attestation missing | **CLOSED** | Exact usernames, `session_user=current_user`, unsafe attributes and ownership are checked at startup/borrow; owner/swapped role negatives and exact-role integration passed. |
| AF09-F09 — no real Outbox causal token/wait/fallback | **CLOSED** | Tenant-bound HMAC token over real Outbox position, continuous watermark, bounded wait, dead-letter/timeout fallback and trace tests passed. |
| AF09-F10 — no external manifest trust anchor | **CLOSED** | Exact external receipt digest matched; review mode required it; missing/mismatch/coordinated substitution negatives and independent all-scope verify passed. |

AF09-F03 through F10 remain closed. AF09-F02 is closed by populated behavior, not by the remediation
claim. AF09-F01 is only partially repaired and stays open.

## G1-G9 and I-01-I-12 adversarial audit

| Goal | Result | Conclusion |
| --- | --- | --- |
| G1 Source Fidelity | PASS | Evidence identity, immutable capture, lineage, blocks and Gate behavior remain enforced. |
| G2 Governed Canonical Evolution | **FAIL — AF09-F01/F11** | A rejected legacy proposal retains its pre-Decision canonical grounding; an incomplete TX-05 proof fabricates APPROVE governance. |
| G3 Open-State Preservation | **FAIL — AF09-F01** | Issue identity/status/replay are repaired, but its canonical branch set retains evidence introduced by a rejected resolution proposal. |
| G4 Applicability Separation | PASS | Typed independent axes and exhaustive ECS/Gate negatives remain executable. |
| G5 Candidate-Safe Retrieval | PASS | L0/L1/Context use canonical Gate; projections/models/external assets cannot elevate authority. |
| G6 Revocation Propagation | **FAIL — AF09-F11** | Current revoke/purge is safe, but supported legacy reconciliation does not require the durable DeletionRequest it claims to prove. |
| G7 Bounded Traceable Context | **FAIL — AF09-F01** | Bounds and trace pass, but Context aggregates the rejected proposal's lingering canonical resolution branch. |
| G8 Least-Privilege Local Security | PASS | Exact roles, forced RLS, session reset, loopback, separated secrets and redaction pass. |
| G9 Replaceable and Recoverable | **FAIL — AF09-F01/F11** | Backup/recovery mechanics pass, but the populated forward repair is semantically incomplete and not fail-closed. |

All test nodes named by `crosswalk.json` exist and ran. Direct assertion inspection gives:

| Invariant | Result | Adversarial conclusion |
| --- | --- | --- |
| I-01 | PASS | Evidence and Claim identities cannot collapse; API direct insert is denied. |
| I-02 | PASS | Capture identity is immutable and idempotency conflicts fail closed. |
| I-03 | **FAIL — AF09-F01** | Current grants/procedures pass, but the supported populated head retains canonical grounding created by pre-Decision API submission. |
| I-04 | PASS | All four histories plus quarantine are append-only; V1/Issue sentinels and continuous replay are now complete. |
| I-05 | PASS | Head/Issue CAS races have one winner and full loser rollback. |
| I-06 | **FAIL — AF09-F01** | Stable Issue identity and status survive, but a rejected resolution candidate remains a canonical branch. |
| I-07 | PASS | L0 consumes ECS-only all-axis Gate. |
| I-08 | PASS | Projection/external candidates cannot bypass Gate; canonical outage abstains. |
| I-09 | PASS | State domains and all orthogonal axes have direct independent negatives. |
| I-10 | **FAIL — AF09-F11** | Fresh revoke and erasure proof pass, but legacy TX-05 reconciliation treats a missing DeletionRequest as provable. |
| I-11 | PASS | Real exact-role/RLS/owner-swap negatives pass. |
| I-12 | **FAIL — AF09-F01/F11** | Fresh atomicity/causal trace passes; populated reconciliation leaves a rejected canonical branch and can synthesize an APPROVE chain from incomplete provenance. |

## Thirteen-item semantic checklist

| Check | Decision | Evidence/finding |
| --- | --- | --- |
| G1-G9 mutually consistent and no circular authorization | **FAIL** | G2/G3/G6/G7/G9 fail under AF09-F01/F11. The migration classifies a rejected effect without removing all canonical effects and elevates incomplete TX-05 references into APPROVE facts. |
| I-01-I-12 each have executable positive and negative evidence | **FAIL** | All mapped nodes execute, but no direct node checks residual legacy grounding or missing/corrupt TX-05 DeletionRequest. I-03/I-06/I-10/I-12 are false for those states. |
| Evidence/Claim/OpenIssue/Context identity boundaries are explicit | PASS | Separate identities and pointer/trace boundaries remain explicit; AF09-F01 is lifecycle/governance leakage, not identity collapse. |
| Steward single-writer, CAS, append-only and rollback are complete | **FAIL** | Fresh paths pass, but Migration Owner leaves an unauthorized canonical relation and creates authoritative TX-05 facts without the required source object. |
| authority/Scope/time/freshness/epistemic are orthogonally matched | PASS | Normative domains, ECS, typed plans and direct all-axis negatives pass. |
| projection/external/model cannot raise truth/authority | PASS | Canonical Gate remains the sole active authority boundary; failures only reduce recall/abstain. |
| revoke, Context invalidation, purge, Blob/backup obligations fail closed | **FAIL** | Current flow passes, but legacy TX-05 migration succeeds when its durable DeletionRequest is absent. AF09-F11. |
| tenant/RLS/roles/network/secrets/log privacy are least privilege | PASS | Real exact-role and cross-role/cross-tenant negatives, forced RLS, loopback and redaction pass. |
| dual sequence, watermark, RYW and recovery are unambiguous | PASS | Real tenant-bound Outbox tokens, continuous watermarks, wait/fallback and traces pass. |
| external assets can be disabled and license/identity verified | PASS | All-scope lock and identity pass; core remains independent and external routes off. |
| threat residual and synthetic-only boundary acceptable | **FAIL** | Synthetic/remote/real-data gates are explicit, but TM claims do not account for the two demonstrated populated migration states. |
| migration/rollback/legacy/real-data change policy executable | **FAIL** | Empty and official populated tests pass, but AF09-F01/F11 disprove complete, fail-closed forward repair. |
| populated candidate.1 provenance/quarantine/replay/validated constraints executable | **FAIL** | Quarantine, exact row hash, backup, replay and validation work for covered rows; resolution grounding is omitted and TX-05 provenance proof does not include the actual DeletionRequest. |

## Hard-reject sweep

| Hard-reject condition | Result | Evidence/conclusion |
| --- | --- | --- |
| Unmapped G/I/MUST or indirect-only evidence | **FAIL** | Mandatory residual-grounding and incomplete-TX05 negative states lack direct mapped nodes and produce source counterexamples. |
| API/worker/model/adapter can direct canonical DML | PASS for current runtime | Current roles cannot direct DML. The migrated residue is separately caught by the populated-migration condition. |
| Cross-tenant/permission/retention/revoke/canonical outage fails open | **FAIL — AF09-F11** | Runtime checks pass, but legacy revoke provenance fails open when the durable request is absent. |
| Conflict/Issue auto-closed by summary/retrieval/time/model | PASS | Only governed Decision paths close; neither counterexample is model/projection closure. |
| Projection/Context/graph/external memory is authority | PASS | These remain candidates/consumers behind canonical Gate. |
| CAS loser/rollback/outbox/history has partial write | **FAIL — AF09-F01** | Migration repairs Issue transitions but leaves the same rejected proposal's canonical resolution grounding, a partial aggregate reconciliation. |
| Populated migration fabricates authority, omits history, retains NULL governance, loses source, has mutable quarantine, or fails to abort unprovable state | **FAIL — AF09-F01/F11** | It omits a canonical legacy effect from quarantine and reconstructs APPROVE authority when the actual DeletionRequest is missing. |
| Manifest/source/Git drift is not rejected | PASS | Archive/live identity and all-scope lock pass; no manifest drift occurred. |
| External trust anchor absent or coordinated substitution accepted | PASS | Exact external receipt anchor and direct coordinated-tamper rejection pass. |
| Real-data/remote gate or residual risk hidden | PASS | Boundaries remain explicit; this review records the newly found migration residuals. |
| Candidate banner removed before freeze | PASS | Candidate/experimental/no-go banners remain present. |

## Open findings and required changes

| ID | Severity | Artifact/line | Finding | Required change/evidence |
| --- | --- | --- | --- | --- |
| AF09-F01 | P1 | `runtime/migrations/versions/0005_canonical_procedures.py:304-405` (especially `:376-383`); `runtime/migrations/versions/0024_legacy_history_reconciliation.py:869-1026`; `architecture/v1.0-candidate/OBJECTS.md:69-84`; `runtime/src/milai/persistence/canonical_repository.py:259-299`; `runtime/src/milai/persistence/context_repository.py:105-124`; `runtime/tests/integration/test_runtime_foundation.py:317-621` | Candidate.3 rejects and reverses the candidate.1 pending resolution's Issue transition but never removes or quarantines the `RESOLUTION_CANDIDATE` GroundingRelation inserted by the same pre-Decision submission. The relation remains canonical and visible in Issue/Context after Proposal=`REJECTED` and Decision=`REJECT`. Proposal submission therefore still has a surviving canonical effect on the supported populated path. | From actual Proposal support references, prove the exact legacy relation set; preserve exact rows and hashes in an append-only, non-authoritative quarantine (or an equally audit-preserving representation); remove them atomically from canonical grounding on POLICY REJECT/reversal. For already-decided proposals, retain/link only effects justified by the actual Decision. Add public-procedure populated tests that query canonical Issue branches and Context before/after migration and prove rejected Proposal grounding is absent, exact evidence is preserved, and rollback is whole. Submit a new immutable candidate/manifest/archive/receipt. |
| AF09-F11 | P1 | `docs/adr/ADR-017-populated-governance-history-reconciliation.md:35-49,88-91`; `runtime/migrations/versions/0024_legacy_history_reconciliation.py:390-435,588-675,714-751`; `runtime/tests/integration/test_runtime_foundation.py:631-893`; `architecture/v1.0-candidate/TRANSACTIONS.md:154-177,204-216` | Migration 0024 calls legacy TX-05 provable when idempotency, Evidence, OperationalEvent and Outbox JSON agree on a `deletion_request_id`, but never verifies the referenced `milai.deletion_request` exists or agrees. Deleting the real request before upgrade still produces an `APPLIED REVOKE_EVIDENCE` Proposal, `STEWARD APPROVE` Decision, replacement transition, and successful 0024 revision. This fabricates authoritative governance from incomplete provenance and violates the declared fail-closed protocol. | Lock/join the actual DeletionRequest by tenant and UUID and verify Evidence, requester/actor, reason, canonical/block/purge status and relevant provenance. Any missing or conflicting proof leg must raise stable `AF09_UNPROVABLE_LEGACY_TX05` and roll the entire migration back to 0023 with no quarantine/Proposal/Decision/replacement/event/outbox residue. Add public-procedure negative tests that independently delete/corrupt every TX-05 proof leg and assert whole rollback. Submit a new immutable candidate/manifest/archive/receipt. |

## Residual gates and decision

Before another candidate can be accepted:

1. Candidate.1 pending-resolution migration must reconcile every unauthorized canonical effect,
   including `GroundingRelation`, without erasing its audit evidence or laundering it into authority.
2. Legacy TX-05 proof must require the actual durable DeletionRequest and fail the whole migration for
   every absent/conflicting proof leg.
3. Direct populated public-procedure negatives for both states must be mapped, source-locked, and run
   alongside valid pending, already-decided, TX-05, quarantine, continuous-replay and backup drills.
4. A new immutable candidate must repeat external-anchor, all-scope lock, exact-role PostgreSQL,
   fresh/populated migration, research, package, CI/Compose, documentation and final drift gates.

Candidate.3 substantively closes AF09-F02 and preserves the candidate.2 closure of AF09-F03 through
AF09-F10. The complete ordinary and official populated suites are green. Nevertheless, two direct
real-PostgreSQL counterexamples leave P1 findings open, and two hard-reject classes are present.
Under `FREEZE_REVIEW.md:82-103`, ACCEPT is forbidden.

```text
Decision: REVISE
Architecture: 1.0.0-candidate.3 — NOT FROZEN
Schema: 0.1.x EXPERIMENTAL
Implementation: CANDIDATE
Freeze: NO-GO
Open P1 findings: AF09-F01, AF09-F11
Manifest before/at decision:
  6a2f1574511f53614d558d663b0792c79b26c1b43a62ab746bfe10f367f15620
Signature/reference: /root/af09_reviewer_retry candidate.3 independent rereview decision
```

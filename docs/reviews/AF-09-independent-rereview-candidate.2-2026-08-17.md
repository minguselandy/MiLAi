# AF-09 Independent Rereview — Logical Architecture 1.0.0-candidate.2

Status: `COMPLETE — DECISION REVISE`

Decision: `REVISE`

## Reviewer record

```text
Reviewer: /root/af09_reviewer_retry
Reviewer role/independence: same independent reviewer as candidate.1; did not author
  candidate.2, AF09_REMEDIATION, the submission receipt, candidate code/tests,
  manifest, or evidence reports; author preflight/remediation conclusions were not
  used as proof
Review started: 2026-08-16T16:50:23Z / 2026-08-17T00:50:23+08:00
Review completed: 2026-08-16T17:11:18Z / 2026-08-17T01:11:18+08:00
Candidate manifest SHA-256 before review:
  17561675750fa1add9f32f4dbe20f9a7ba6668861e0af2beb41e391dc55329ae
Candidate manifest SHA-256 at decision:
  17561675750fa1add9f32f4dbe20f9a7ba6668861e0af2beb41e391dc55329ae
Submission archive SHA-256:
  03bf746775beb60a0910f0bbec2539a62a4aa656e3d3de7cb82d667eca0c9544
Decision: REVISE
Decision rationale: two P1 candidate.1 findings remain open on the supported,
  populated candidate.1-to-candidate.2 forward-migration path. Migration 0015
  neither backfills V1/OpenIssue creation history nor reconciles the canonical
  pre-Decision OpenIssue mutation produced by candidate.1. The latter survives
  upgrade and is no longer reviewable by candidate.2. P1 findings prohibit ACCEPT.
Signature/reference: /root/af09_reviewer_retry candidate.2 independent rereview decision
```

This record is a full rereview of the exact candidate.2 submission. It does not amend the immutable
candidate.1 review. No candidate, manifest, source, test, archive, receipt, or evidence-report file
was modified during this review.

## Submission identity and chain of custody

The digest was taken from the external receipt, not derived from the candidate's own claims. The
receipt identifies the candidate and trust anchor at
`docs/reviews/submissions/AF-09-candidate.2-submission-receipt.md:1-21,40-56`.

| Check | Independent result |
| --- | --- |
| External receipt SHA-256 | `5474b8c05d2a8abd938523a85d241a7baa7f93452692151b1fc099c3765c10a6` |
| Receipt manifest digest | `17561675750fa1add9f32f4dbe20f9a7ba6668861e0af2beb41e391dc55329ae` |
| Live manifest digest | exact match before review, before decision, and after all dynamic work |
| Receipt archive digest | `03bf746775beb60a0910f0bbec2539a62a4aa656e3d3de7cb82d667eca0c9544` |
| Actual archive digest | exact match |
| Archive shape | 1,165,262 bytes; 154 sorted, safe relative regular-file entries; no duplicate, absolute, traversal, link, or device entry |
| Archive/live identity | archive manifest bytes equal live manifest; all 154 archived entries byte-equal their live workspace objects |
| Prior review digest | `b12c64be6aea41cfb62ba9d8501a4cfc31f73dda0a50146de7d2367ae98f4707`, matches receipt |
| Candidate.2 remediation digest | `096bdc1ad4de4ca8a320583f307d138e2072ce2922b8b283c46a19a4fbcaf6a9`, matches receipt |
| Candidate.2 DG-00 digest | `fd82f571b4005c780b195377fcef76116ced4a172a6b74c6586cb3243bf61175`, matches receipt |
| Manifest drift during review | none |

The archive audit used Python `tarfile` to inspect members without trusting extraction paths and to
compare each regular member with its resolved live file. The manifest identifies the submission as
`1.0.0-candidate.2`, `CANDIDATE`, schema `0.1.x EXPERIMENTAL`, and `NO-GO`
(`architecture/v1.0-candidate/architecture_manifest.json:1-10`).

## Validation environment

```text
Workspace: /cra/memory/mx_memory/MiLAi
Host: Linux 5.15.0-86-generic x86_64 GNU/Linux
Python: 3.11.13 (runtime/.venv)
uv: 0.8.3
Ruff: 0.16.3
mypy: 1.20.2
pytest: 8.4.2
psql client: PostgreSQL 16.14
Docker Compose: v2.35.1
PostgreSQL service: milai-lean-v1-postgres-1, healthy, pgvector/pgvector:pg16
Timezone used for record: UTC and Asia/Shanghai
```

The real PostgreSQL suite was invoked from `runtime/`, as required. The owner, API, Steward, Worker,
and Audit DSNs were constructed from the existing healthy service and supplied through the exact
`MILAI_MIGRATION_DATABASE_URL` / `MILAI_TEST_*_DATABASE_URL` variables. Credentials and DSNs are
intentionally omitted from this record.

## Materials and review method

I read `AGENTS.md`, the implementation contract, design/development goals, root logical-architecture
design, GOALS completion audit, candidate.2 DG-00 report, all candidate bundle booklets,
`crosswalk.json`, `architecture_manifest.json`, `FREEZE_REVIEW.md`, ADR-001 through ADR-016, both the
candidate.1 review and candidate.2 remediation record, migrations 0001 through 0023, the relevant
runtime domain/application/persistence/API/worker code, direct test nodes, runbooks, packaging and CI
configuration, and all locked external identities. Reports were used only as navigation; decisions
below come from SQL/code/test behavior and independent execution.

The most important adversarial distinction is between a fresh empty database and the supported
forward migration of populated candidate.1 state. Candidate.2's ordinary tests exercise the former
(`runtime/tests/integration/test_runtime_foundation.py:43-68`) but not candidate.1 governance facts
through 0014.

## Commands and independent results

### Architecture identity and bundle gates

```text
sha256sum architecture/v1.0-candidate/architecture_manifest.json
  PASS 17561675750fa1add9f32f4dbe20f9a7ba6668861e0af2beb41e391dc55329ae

sha256sum docs/reviews/submissions/AF-09-candidate.2-17561675-submission.tar.gz
  PASS 03bf746775beb60a0910f0bbec2539a62a4aa656e3d3de7cb82d667eca0c9544

runtime/.venv/bin/ruff format --check \
  architecture/v1.0-candidate/scripts architecture/v1.0-candidate/tests
  PASS — 4 files already formatted

runtime/.venv/bin/ruff check \
  architecture/v1.0-candidate/scripts architecture/v1.0-candidate/tests
  PASS — All checks passed

runtime/.venv/bin/python architecture/v1.0-candidate/scripts/validate_bundle.py
  PASS — MiLAi architecture bundle validation: PASS (candidate, not frozen)

runtime/.venv/bin/python architecture/v1.0-candidate/scripts/verify_lock.py \
  --scope all --mode review \
  --expected-manifest-sha256 \
  17561675750fa1add9f32f4dbe20f9a7ba6668861e0af2beb41e391dc55329ae
  PASS — MiLAi architecture lock verification: PASS (candidate, not frozen)

MILAI_ARCHITECTURE_LOCK_SCOPE=all runtime/.venv/bin/python -m unittest discover \
  -s architecture/v1.0-candidate/tests -v
  PASS — 19 tests, OK (final repeat: 0.615s)
```

The 19 tests include missing-anchor, digest-mismatch, and coordinated bundle-plus-manifest tamper
rejection at `architecture/v1.0-candidate/tests/test_bundle.py:237-297`. The verifier requires and
compares the external digest before trusting the manifest at
`architecture/v1.0-candidate/scripts/verify_lock.py:179-208`.

### Runtime static, database, migration, and package gates

Run from `runtime/`:

```text
uv sync --frozen --dev --python 3.11
  PASS — Audited 36 packages

uv run ruff format --check .
  PASS — 102 files already formatted

uv run ruff check .
  PASS — All checks passed

uv run mypy
  PASS — Success: no issues found in 57 source files

[exact-role MILAI_TEST_* environment] uv run pytest -q
  PASS — 92 passed in 21.86s

[fresh temporary database] uv run pytest -q \
  tests/integration/test_runtime_foundation.py::test_full_forward_migration_chain_on_empty_database
  PASS — 1 passed in 2.42s; head 0023_erasure_sha256_repair; destructive downgrade rejected

uv build --out-dir <fresh-temporary-directory>
  PASS — fresh wheel and sdist built
```

Fresh package inspection:

```text
wheel SHA-256: 30cceb2a1101138601e6a46bcde40d089faf185382a99be2a622a97b8ce7c951
sdist SHA-256:  93310c3f37be9b9767f2855779f1aa05a9606417080cb5806c4e90456c3c144a
wheel unzip test: PASS
wheel entries: 63
contents: complete milai package, py.typed and candidate/no-go metadata present
Requires-Python: <3.13,>=3.11
```

The 92-test PostgreSQL run includes real-role RLS/direct-DML negatives, proposal/Decision/CAS,
creation history on fresh writes, TX-05 rollback, Outbox/watermark/RYW, backup/restore, revoke,
Context invalidation, purge, typed erasure proof and recovery. A green suite does not supersede the
populated-upgrade counterexample below.

### Isolated research, CI, Compose, and documentation gates

```text
runtime/.venv/bin/ruff format --check research/ospc
  PASS — 11 files already formatted
runtime/.venv/bin/ruff check research/ospc
  PASS
runtime/.venv/bin/mypy --strict research/ospc
  PASS — 7 files
runtime/.venv/bin/python -m unittest discover -s research/ospc/tests -v
  PASS — 9 tests in 0.197s

[fresh temporary research copy] generate_fixtures + run_benchmark
  PASS — fixture_count=40; synthetic_only=true; equal_budget=true
  fixture SHA-256=8fd9482aacf58d8802a16dbc86a9e8043ffc28123d904f72b7b87a052eaa718a
  generated pilot/manifest byte-equal locked objects
  decision=ABANDON; novelty=false; reasons=HF-01,HF-02,HF-06

Ruby YAML.safe_load runtime CI workflow
  PASS — valid mapping, one job
docker compose config --quiet
  PASS — configuration parses (secrets supplied but not printed)
```

The research decision remains an isolated synthetic evaluation result. It does not authorize a
canonical product behavior or relax the real-data/remote boundary.

## Adversarial populated-forward-migration tests

I ran two disposable-database harnesses against the locked migrations. Each harness created a fresh
temporary PostgreSQL database, upgraded only to `0014_query_plan_outbox_sequence`, created real
candidate.1 canonical state through its public procedures, upgraded that same populated database to
`head`, queried the authoritative tables/constraint catalog, and dropped the database. No candidate
source or fixture was changed.

### Counterexample A — creation histories are not repaired

Before upgrade, a candidate.1 CREATE and first CONFLICT produced a real Claim V1 and OpenIssue without
their required creation sentinels. After candidate.2 upgrade:

```text
candidate1 pre-upgrade creation histories: (0, 0)
candidate2 post-upgrade creation histories: (0, 0)
governed transition constraint validated: False
migration revision: 0023_erasure_sha256_repair
```

This is explained directly by migration 0015. It changes constraints and defines an AFTER INSERT
trigger on future `steward_decision` rows (`runtime/migrations/versions/0015_governed_proposals_and_complete_history.py:104-223`),
but contains no backfill for already approved V1 or existing OpenIssue rows. The new governance
constraint is deliberately installed `NOT VALID` (`:142-149`) and no later migration validates it.
The fresh-database migration test starts empty and therefore cannot expose this (`runtime/tests/integration/test_runtime_foundation.py:43-68`).

### Counterexample B — a candidate.1 pre-Decision mutation survives and becomes stuck

The second harness created a conflict and submitted a candidate.1 resolution proposal before
upgrading. Candidate.1's API-executable submission procedure performs the canonical mutation at
`runtime/migrations/versions/0005_canonical_procedures.py:304-419`, including an IssueTransition with
`decision_id=NULL` at `:394-405`.

Observed result:

```text
before upgrade: ('READY_FOR_REVIEW', 2, 1)
  # tuple = (OpenIssue status, revision, count of transitions with decision_id IS NULL)
after upgrade:  ('READY_FOR_REVIEW', 2, 1, 'PENDING_REVIEW')
  # proposal remains PENDING_REVIEW
candidate.2 review attempt: ISSUE_REVISION_CONFLICT
head revision: 0023_erasure_sha256_repair
```

Migration 0015 replaces the public submission/review routines for future work and correctly keeps a
fresh proposal non-canonical (`0015...py:249-426`). It does not reconcile already mutated issues or
pending proposals. The candidate.2 review routine only accepts issue status `OPEN`,
`WAITING_EVIDENCE`, or `WAITING_USER` at the expected revision (`0015...py:510-523,568-571`), so the
surviving `READY_FOR_REVIEW` state cannot be completed by the new governed transaction. The old
canonical mutation and null-Decision history therefore remain both authoritative and stranded.

These are release-relevant counterexamples because the baseline expressly characterizes migrations
0015-0023 as forward repair (`architecture/v1.0-candidate/BASELINE.md:108-117`) and the candidate is a
successor to candidate.1, not a fresh-install-only design.

## AF09-F01 through AF09-F10 closure audit

`CLOSED` below means the original finding's required behavior was independently observed in
SQL/code and direct tests. It does not mean candidate.2 as a whole is accepted.

| Finding | Rereview status | Direct evidence and adversarial conclusion |
| --- | --- | --- |
| AF09-F01 — proposal submission mutates canonical Issue before Decision | **OPEN P1** | Fresh candidate.2 submission is correctly non-canonical: the wrapper writes only Proposal, OperationalEvent and Outbox (`0015...py:249-426`), and `test_resolution_submission_is_noncanonical_and_rejection_preserves_issue` asserts Issue remains `OPEN`, revision 1, with only `ISSUE_CREATED` (`runtime/tests/concurrency/test_canonical_transactions.py:405-433`). However the populated-upgrade counterexample proves a candidate.1 pre-Decision mutation and null-Decision transition survive to head and become unreviewable. The required architecture property is not restored for supported deployed state. |
| AF09-F02 — missing V1/OpenIssue creation history | **OPEN P1** | Fresh candidate.2 decisions trigger `CREATE old=NULL` and `ISSUE_CREATED NULL/0→1` (`0015...py:104-223`; fresh tests at `test_canonical_transactions.py:405-484`). The trigger is future-only. The populated-upgrade test retains `(0,0)` creation histories at head, so I-04 remains false for existing candidate.1 objects. |
| AF09-F03 — normative/legacy state-domain mismatch | **CLOSED** | Migration 0015 normalizes legacy lifecycle/epistemic values and installs normative constraints (`0015...py:29-101`). Direct exhaustive positive and unknown-value rollback tests are at `test_canonical_transactions.py:488-566`; both executed against PostgreSQL. |
| AF09-F04 — Gate omits axes / bypasses ECS | **CLOSED** | Migration 0017 exposes the authoritative all-version ECS and the only public eleven-argument Gate reads it; non-current and every independent axis have reasoned rejection (`runtime/migrations/versions/0017_authoritative_effective_claim_state.py:154-318`). Context delegates to that Gate in migration 0021. The all-axis test independently changes lifecycle, epistemic, freshness, Scope, valid/system time, authority and confidence (`runtime/tests/integration/test_retrieval_api.py:633-699`). Projection failures do not raise authority. |
| AF09-F05 — indirect crosswalk test evidence | **CLOSED for the original omissions** | All declared nodes exist and executed. New direct tests attempt Evidence→Claim collapse (`test_canonical_transactions.py:729-751`), mutate ClaimVersion/VersionTransition/StewardDecision/IssueTransition (`:677-724`), independently reject all Gate axes (`test_retrieval_api.py:633-699`), and count mutation/Deletion/Proposal/Decision/Outbox/OperationalEvent rollback residue (`test_canonical_transactions.py:855-894`). The separate missing populated-migration evidence is recorded under F01/F02 and checklist item 2. |
| AF09-F06 — TX-05 has no governed Decision | **CLOSED** | Migration 0016 implements Steward-only governed revoke with Proposal, Decision, linked Issue/history/event/outbox. Direct positive and role-denial test is `test_canonical_transactions.py:756-851`; forced rollback asserts all six residue classes are zero at `:855-894`. |
| AF09-F07 — ERASED without durable-absence proof | **CLOSED** | Adapter returns a typed `ErasureProof` after filesystem/URI/hash/non-regular checks (`runtime/src/milai/adapters/blob_store.py:29-35,83-155`). Worker passes the proof to SQL. Migrations 0019/0022/0023 verify identity and recompute SHA-256 inside PostgreSQL before ERASED (`runtime/migrations/versions/0019_verified_blob_erasure.py:71-210`). Missing, forged, symlink/non-regular, crash/retry cases execute, including `test_forged_erasure_proof_dead_letters_then_verified_absence_recovers` (`runtime/tests/integration/test_projection_worker.py:384-449`). |
| AF09-F08 — runtime exact database-role attestation missing | **CLOSED** | Settings/worker require exact URL login names; `Database` rejects wrong names at construction and verifies `session_user=current_user=expected_role`, unsafe cluster attributes, and MiLAi ownership on pool open, ping and every borrow (`runtime/src/milai/persistence/database.py:39-166`). Worker pings before leasing (`runtime/src/milai/workers/main.py:54-69`). API readiness pings both API and Steward pools (`runtime/src/milai/api/app.py:162-195`). Real-role attributes and owner/role-swap denial execute at `runtime/tests/security/test_tenant_roles.py:119-153`; unit negatives cover owner/swapped API/Steward/Worker URLs. A process may bind its loopback listener before readiness is called, but no ready or database-backed request can execute a query before attestation; this is not a credential bypass. |
| AF09-F09 — no real Outbox causal token/wait/fallback | **CLOSED** | `/causal-tokens` resolves actual tenant Outbox IDs, the HMAC codec binds tenant and position, retrieval waits on continuous projection state, and timeout/dead-letter/snapshot advance use canonical fallback with trace (`runtime/src/milai/domain/causality.py:12-78`; `runtime/src/milai/application/retrieval.py:62-142,186-299`; `runtime/src/milai/persistence/retrieval_repository.py:108-146`). Direct reached, missing/forged/wrong-key/cross-tenant/future, timeout, dead-letter and concurrent snapshot tests execute at `runtime/tests/integration/test_retrieval_api.py:347-521`. |
| AF09-F10 — no external manifest trust anchor | **CLOSED** | External receipt exists and independently matches. Review mode requires a supplied external digest and rejects mismatch (`verify_lock.py:179-208`). Bundle tests exercise missing anchor, mismatch and coordinated content+manifest substitution (`test_bundle.py:237-297`). Independent all-scope review-mode verification with the receipt digest passed repeatedly. |

## G1-G9 consistency audit

| Goal | Decision | Direct conclusion |
| --- | --- | --- |
| G1 Source Fidelity | PASS | Evidence identity/immutability, lineage, revocation and Gate checks are enforced and directly tested. |
| G2 Governed Canonical Evolution | **FAIL — AF09-F01/F02** | Fresh candidate.2 writes are governed, but populated candidate.1 state at head can retain pre-Decision canonical mutation, a null-Decision transition and absent creation history. |
| G3 Open-State Preservation | **FAIL — AF09-F01** | A migrated Issue can remain `READY_FOR_REVIEW` with a pending proposal that the new review procedure cannot decide. Identity is preserved but the governed state machine is stranded. |
| G4 Applicability Separation | PASS | Normative typed domains and independent ECS/Gate comparisons are executable. Confidence never compensates another axis. |
| G5 Candidate-Safe Retrieval | PASS | L0/L1/Context consume the canonical Gate; L2 remains disabled; projection outage degrades recall and canonical outage abstains. |
| G6 Revocation Propagation | PASS | Governed synchronous revoke/block/invalidation and proof-bound asynchronous purge/backup obligations fail closed. |
| G7 Bounded Traceable Context | PASS | Protected items, fixed budgets, pointer invalidation, action confirmation and payload-free replay trace are directly exercised. |
| G8 Least-Privilege Local Security | PASS | Exact roles, forced RLS/session context, loopback, independent secrets, redaction and negative permissions are enforced. |
| G9 Replaceable and Recoverable | **FAIL — AF09-F01/F02** | External assets are removable and backup/projection recovery works, but the advertised forward repair does not recover candidate.1 governance/history state. |

There is no new circular-authorization path for fresh candidate.2 proposals. The failure is that the
candidate claims a forward migration while preserving a state produced by candidate.1's circular,
pre-Decision authorization path.

## I-01-I-12 direct node and behavior audit

Every node named in `crosswalk.json` exists and ran inside the 92-test suite. I inspected assertions,
not only node names.

| Invariant | Declared positive / negative nodes and direct result | Decision |
| --- | --- | --- |
| I-01 | `test_tx02_create_is_versioned_grounded_and_idempotent` / `test_i01_evidence_cannot_be_collapsed_directly_into_claim_version`; distinct tables and API-role INSERT denial are real. | PASS |
| I-02 | `test_tx01_api_replay_conflict_blob_dedup_and_lineage` / `test_evidence_capture_identity_is_immutable_even_for_owner`; fingerprint conflict and owner mutation rejection are real. | PASS |
| I-03 | `test_proposal_review_claim_conflict_and_lineage_api` / `test_canonical_tables_deny_direct_dml_and_history_is_immutable`; current grants/procedures pass, but the populated upgrade retains a pre-Decision API-caused mutation at candidate.2 head. | **FAIL — AF09-F01** |
| I-04 | `test_tx02_create_is_versioned_grounded_and_idempotent` / append-only test; fresh creation and four-history immutability pass, but existing V1/Issue creation sentinels are not repaired. | **FAIL — AF09-F02** |
| I-05 | exact-head and Issue-revision race nodes each produce one winner and full loser rollback. | PASS |
| I-06 | `test_tx04_conflict_preserves_head_and_structured_branches` / fresh noncanonical-resolution/rejection node preserve identity and branches. | PASS |
| I-07 | L0 positive and exhaustive all-axis negative use the ECS-only SQL Gate. | PASS |
| I-08 | L1 positive and vector/canonical outage negative prove projection is candidate-only and canonical outage abstains. | PASS |
| I-09 | exhaustive normative/legacy domain node plus all-axis Gate node independently test the orthogonal axes. | PASS |
| I-10 | governed TX-05 positive/rollback plus forged durable-erasure proof negative exercise sync and async boundaries. | PASS |
| I-11 | real API role ping and API/Steward/Worker/Audit/RLS/owner/role-swap tests execute with exact role DSNs. | PASS |
| I-12 | Fresh candidate.2 TX-05 atomicity, Context lineage, real Outbox token and RYW negatives pass. The migrated candidate.1 transition with `decision_id=NULL` violates the same atomic governance/history invariant at head. | **FAIL — AF09-F01** |

Because the crosswalk has no populated 0014-to-head governance/history test, its I-03/I-04/I-12
evidence is sufficient for fresh candidate.2 transactions but not for the supported migration policy.

## Twelve-item semantic checklist

| Check | Decision | Evidence/finding |
| --- | --- | --- |
| G1-G9 goals are mutually consistent and contain no circular authorization | **FAIL** | G2/G3/G9 fail for populated forward migration. Candidate.1's pre-Decision mutation survives even though fresh candidate.2 removed the authorization path. AF09-F01/F02. |
| I-01-I-12 each have executable positive and negative evidence | **FAIL** | All named nodes execute, but none creates candidate.1 governance/history data at 0014 and proves repair at head. I-03/I-04/I-12 are false under the independent counterexamples. AF09-F01/F02. |
| Evidence/Claim/OpenIssue/Context identity boundaries are explicit | PASS | Separate immutable Evidence/ClaimVersion identities, structured Issue identity/branches and Context pointer/invalidation boundaries are enforced and traced. |
| Steward single-writer, CAS, append-only and rollback are complete | **FAIL** | Current procedures/grants/CAS/rollback pass, but migrated canonical history contains a null-Decision transition and missing creation sentinels; `ck_issue_transition_governed` remains unvalidated. AF09-F01/F02. |
| authority/Scope/time/freshness/epistemic are orthogonally matched | PASS | Normative domains, ECS, typed request/plan and the all-axis/bitemporal Gate test independently reject mismatches. |
| projection/external/model cannot raise truth/authority | PASS | All active retrieval/Context paths use the Gate; L2/external routes remain disabled and credential-isolated; failures only reduce recall. |
| revoke, Context invalidation, purge, Blob and backup obligations fail closed | PASS | Governed TX-05, rollback, proof-bound ERASED, purge dead-letter/recovery and backup/restore obligations execute. |
| tenant/RLS/roles/network/secrets/log privacy are least privilege | PASS | Exact role attestation, forced RLS/session reset, loopback-only configuration, secret separation and redaction negatives pass. |
| dual sequence, watermark, RYW and recovery semantics are unambiguous | PASS | Canonical commit and real Outbox positions remain distinct; continuous watermarks, HMAC token, bounded wait, precise trace and canonical fallback are tested. |
| external assets can be disabled and license/identity are verifiable | PASS | All-scope lock verifies local/Git/hash identities; external routes are disabled by default and core runtime/build/tests do not import them. |
| threat residual risk and synthetic-only boundary are acceptable | **FAIL** | The synthetic/remote/real-data boundaries are disclosed and accepted as candidate limits, but the threat/residual inventory marks governance/history as passed while omitting the populated forward-migration state demonstrated here. That P1 residual is not acceptable for freeze. |
| migration/rollback/legacy/real-data change policy is executable | **FAIL** | Empty base-to-head replay passes, but advertised candidate.1 forward repair leaves invalid/stuck governed state and unvalidated historical rows. AF09-F01/F02. |

## Hard-reject sweep

`PASS` means the prohibited condition was not observed. `FAIL` means the hard-reject condition is
present and independently blocks acceptance. Candidate.2's template contains ten conditions
(`architecture/v1.0-candidate/FREEZE_REVIEW.md:77-90`).

| Hard-reject condition | Result | Evidence/conclusion |
| --- | --- | --- |
| Unmapped G/I/MUST, or positive/negative evidence is only indirect | **FAIL** | The crosswalk has no executable populated candidate.1-to-head governance/history repair node; I-03/I-04/I-12 and migration MUSTs fail under direct SQL counterexamples. |
| API/worker/model/adapter can direct canonical DML | PASS | Direct table DML is denied to runtime roles; fresh proposal submission is noncanonical; Steward procedures revalidate and own mutation. |
| Cross-tenant, permission/retention unknown, revoke, or canonical outage fails open | PASS | Real RLS, Gate, revoke and outage negatives abstain/reject. |
| Conflict/Issue is closed by summary, retrieval omission, time, or model | PASS | Only governed Decision paths close; projection/Context/model cannot commit. The migrated Issue is stranded open-like, not silently closed. |
| Projection, Context, graph, or external memory is authority | PASS | All remain candidate/projection inputs behind ECS/Gate. |
| CAS loser, rollback, outbox, or history has partial write | **FAIL** | Fresh loser/rollback behavior is atomic, but supported migrated history remains partial: absent creation transitions and an IssueTransition with `decision_id=NULL`. AF09-F01/F02. |
| Manifest/source/Git drift is not rejected | PASS | Archive/live identity and all-scope lock pass; drift/path/Git tests pass; manifest did not drift during review. |
| Review/release lacks external trust anchor or accepts coordinated substitution | PASS | External receipt digest is independently matched; review mode and coordinated-tamper negatives pass. |
| Real-data/remote gate or residual risk is hidden | PASS | Boundaries remain explicit; no production certification is claimed. The newly discovered migration residual is recorded here rather than hidden. |
| Candidate banner is removed before freeze decision | PASS | Manifest/runtime/docs remain `CANDIDATE`, `0.1.x EXPERIMENTAL`, `NO-GO`. |

## Open findings and required changes

| ID | Severity | Artifact/line | Finding | Required change/evidence |
| --- | --- | --- | --- | --- |
| AF09-F01 | P1 | `runtime/migrations/versions/0005_canonical_procedures.py:304-419`; `runtime/migrations/versions/0015_governed_proposals_and_complete_history.py:225-246,249-426,510-523,568-571`; `runtime/tests/integration/test_runtime_foundation.py:43-68` | Candidate.2 correctly prevents new pre-Decision canonical mutation, but migration does not identify or reconcile candidate.1 pending resolution proposals whose submission already moved an Issue to `READY_FOR_REVIEW` and wrote a null-Decision transition. Such state survives at head and candidate.2 review rejects it with `ISSUE_REVISION_CONFLICT`. | Add a forward-only, audit-preserving reconciliation migration. It must either complete each legacy state through an explicitly governed Decision/CAS transaction or fail/quarantine upgrade before serving; it must not fabricate authority or erase history. Add a real populated-0014 regression that creates the legacy resolution state, upgrades to head, proves no ungoverned/null-Decision canonical transition remains, and proves the proposal has a defined review/reconciliation outcome. Create a new candidate, manifest, archive and receipt. |
| AF09-F02 | P1 | `runtime/migrations/versions/0015_governed_proposals_and_complete_history.py:104-223` (especially `:142-149`); `runtime/tests/integration/test_runtime_foundation.py:43-68`; `architecture/v1.0-candidate/BASELINE.md:108-117` | The creation-history trigger applies only to future Decision inserts. Existing candidate.1 Claim V1 and first OpenIssue retain no `CREATE`/`ISSUE_CREATED` sentinel after upgrade. `ck_issue_transition_governed` is added `NOT VALID` and remains `convalidated=false` at head. | Backfill every existing V1/OpenIssue from its actual Proposal/Decision/provenance with the defined sentinels and canonical sequence, or fail closed when provenance cannot be proven. Reconcile all legacy null-governance transitions, then `VALIDATE CONSTRAINT ck_issue_transition_governed` (and any equivalent history constraints). Add populated candidate.1-to-head tests for clean CREATE/conflict and legacy pending resolution, with complete replay counts and Decision/outbox linkage. Create a new candidate, manifest, archive and receipt. |

No separately numbered new finding is needed: both independently discovered counterexamples are the
unclosed deployed-state forms of the original AF09-F01 and AF09-F02 requirements. AF09-F03 through
AF09-F10 are closed as described above; their closure does not waive these P1 findings.

## Residual gates and final decision

The following must be true before a future candidate can be accepted:

1. A populated candidate.1 database containing both ordinary V1/first-conflict rows and the legacy
   pre-Decision resolution state is migrated without missing or null-Decision governance history.
2. The migrated pending proposal has a documented, executable, authority-safe outcome; no Issue is
   stranded in a state rejected by the new review state machine.
3. Governance/history constraints are validated over existing data, not merely enforced for new
   rows.
4. Direct regression nodes are added to the crosswalk/migration evidence, then architecture review
   lock, 19 bundle tests, the full exact-role PostgreSQL suite, fresh migration, research isolation,
   package, backup/revoke/purge/restore and external-anchor gates are rerun against a new immutable
   candidate submission.

The full current automated suite is green, and AF09-F03 through AF09-F10 show substantive remediation.
Nevertheless, the freeze protocol expressly forbids ACCEPT while a P1 is open and treats partial
history as a hard reject. The independent decision for exact submission
`17561675750fa1add9f32f4dbe20f9a7ba6668861e0af2beb41e391dc55329ae` is therefore:

```text
Decision: REVISE
Architecture: 1.0.0-candidate.2 — NOT FROZEN
Schema: 0.1.x EXPERIMENTAL
Implementation: CANDIDATE
Freeze: NO-GO
Open P1 findings: AF09-F01, AF09-F02
Signature/reference: /root/af09_reviewer_retry candidate.2 independent rereview decision
```

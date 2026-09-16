# AF-09 Independent Rereview — Logical Architecture 1.0.0-candidate.5

Status: `COMPLETE — DECISION ACCEPT`

Decision: `ACCEPT`

## Reviewer record

```text
Reviewer: /root/af09_reviewer_retry
Reviewer role/independence: same independent reviewer as candidate.1–4;
  did not author candidate.5, ADR-019, AF09_REMEDIATION, the submission
  receipt/archive, candidate source/tests, manifest, or author evidence reports;
  author preflight/remediation conclusions were not used as proof
Review started: 2026-08-17T02:35:35Z / 2026-08-17T10:35:35+08:00
Review completed: 2026-08-17T02:53:09Z / 2026-08-17T10:53:09+08:00
Candidate manifest SHA-256 before review:
  ece90366e5e3e3647af729351d8ae80310c8f6c30db1cf85b5a74ccb4168ed64
Candidate manifest SHA-256 at decision:
  ece90366e5e3e3647af729351d8ae80310c8f6c30db1cf85b5a74ccb4168ed64
Submission archive SHA-256:
  aa56033be8380eee9289baec11c7839cbaa9bde4d66f69c6757fd9fb651ff668
External receipt SHA-256:
  2f8189339b6ee5b45107cee93c67005c1051171810913014631b1bd8c9aed680
Decision: ACCEPT
Decision rationale: candidate.5 closes P1 AF09-F12. Corrected 0024 and 0025
  require all six candidate.1 TX-05 timestamps to equal the durable
  DeletionRequest anchor before reconstructing authority; proof-only 0026
  re-certifies already-applied candidate.4 state without writing authority.
  Independent real-PostgreSQL replay of four fresh, four candidate.3-compatible,
  and four candidate.4-compatible single-leg conflicts produced the stable
  error, retained 0023/0024/0025 respectively, and produced no migration
  residue. A six-equal-time control alone advanced 0025→0026 without changing
  schema, authority, event, or Outbox counts. AF09-F01 through F12 are closed,
  all semantic/hard-reject gates pass, and no P0/P1 finding remains.
Signature/reference: /root/af09_reviewer_retry candidate.5 independent rereview acceptance
```

This record is a full independent rereview of the exact candidate.5 submission. It does not amend
any candidate.1–4 history. No candidate bundle, manifest, source, test, archive, receipt, author
report, remediation record, prior review, or submission history was modified; this new review is the
sole repository write made by the reviewer.

`ACCEPT` applies to the immutable candidate.5 bytes identified below. It does not itself rewrite the
submitted manifest or publish `1.0.0 FROZEN`; those are subsequent, separately locked release steps
under `FREEZE_REVIEW.md:117-126`.

## Submission identity and chain of custody

The trusted manifest digest came only from the bundle-external candidate.5 receipt. I inspected the
archive with Python `tarfile` without extraction and resolved `MiLAi/` and workspace-sibling members
against their respective live roots.

| Check | Independent result |
| --- | --- |
| External receipt | SHA-256 `2f8189339b6ee5b45107cee93c67005c1051171810913014631b1bd8c9aed680`; exact expected object |
| Receipt manifest digest | `ece90366e5e3e3647af729351d8ae80310c8f6c30db1cf85b5a74ccb4168ed64` |
| Live manifest digest | exact receipt match before review and at decision |
| Receipt archive digest | `aa56033be8380eee9289baec11c7839cbaa9bde4d66f69c6757fd9fb651ff668` |
| Actual archive | exact digest match; 9,558,914 bytes |
| Archive shape | 175 sorted, unique, safe relative regular-file entries; no absolute/traversal path, duplicate, symlink, hardlink, device, or other special member |
| Archive/live identity | archived manifest bytes equal live manifest; all 175 archived bytestrings equal their live project/workspace objects |
| Manifest inventory | 19 required files, 18 bundle locks, 156 source locks, 9 Git locks |
| Manifest drift during review | none |

The submitted manifest remains `1.0.0-candidate.5`, `CANDIDATE`, schema `0.1.x EXPERIMENTAL`,
`NO-GO`, and independent decision `PENDING`; preserving those submitted bytes is required for this
review's identity. The accepted review is external to the candidate bundle.

## Validation environment and scope

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
PostgreSQL review database: fresh milai_af09_c5_review_clean1, not /milai
Timezone used for record: UTC and Asia/Shanghai
```

All PostgreSQL commands ran from `runtime/`. Migration Owner, API, Steward, Worker, and Audit DSNs
were built from the healthy local container and passed through the exact
`MILAI_MIGRATION_DATABASE_URL` and `MILAI_TEST_*_DATABASE_URL` variables. No credential or DSN was
printed. The intentionally contaminated `/milai` forensic database was neither used nor repaired.

I read the governing contract/goals/design and `AGENTS.md`; all candidate booklets, manifest,
crosswalk and freeze template; ADR-001 through ADR-019; candidate.1–4 independent reviews and exact
submission histories; candidate.5 delta/remediation material; migrations 0001 through 0026; mapped
runtime SQL/application/repository/worker code and tests; threat/privacy, runbooks, backup/recovery,
CI/package, research and external-lock material. Author documents were navigation only.

The 168-entry candidate.4 archive was compared with the 175-entry candidate.5 archive. Candidate.5
adds ADR-019, migration 0026 and its immutable history/report records. In runtime behavior, the only
changes to 0024/0025 are the missing timestamp predicates (plus explanatory comments); no F01 or
F02–F11 predicate was weakened. All changed architecture and test artifacts were read directly.

## Commands and results

### Identity, architecture and external trust anchor

```text
sha256sum <candidate.5 manifest> <candidate.5 archive> <candidate.5 receipt>
  PASS — exact trusted digests above

[Python tarfile path/type/duplicate/order/archive-live byte audit]
  PASS — entries=175, sorted=true, unique=true, unsafe=0,
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
  ece90366e5e3e3647af729351d8ae80310c8f6c30db1cf85b5a74ccb4168ed64
  PASS — MiLAi architecture lock verification: PASS (candidate, not frozen)

MILAI_ARCHITECTURE_LOCK_SCOPE=all runtime/.venv/bin/python -m unittest discover \
  -s architecture/v1.0-candidate/tests -v
  PASS — 19 tests, OK (0.968s)
```

The 19 tests exercise missing/mismatched external anchors, coordinated bundle-plus-manifest
substitution, source/Git/required-lock drift, path escape and candidate/review-state negatives. The
expected digest was supplied from the external receipt rather than candidate metadata.

An AST/node audit of `crosswalk.json` found all 12 invariants and every declared direct node present:
39 unique positive/negative nodes, zero missing. Per-invariant positive/negative counts are I-01
`1/1`, I-02 `1/1`, I-03 `1/4`, I-04 `4/3`, I-05 `1/2`, I-06 `1/2`, I-07 `1/2`, I-08 `1/1`, I-09
`1/1`, I-10 `3/10`, I-11 `1/4`, and I-12 `5/12`. All nodes ran in the 121-test suite; the timestamp
nodes were additionally replayed with reviewer-owned assertions below.

### Runtime, fresh migration and exact-role PostgreSQL

From `runtime/`:

```text
uv sync --frozen --dev --python 3.11
  PASS — Audited 36 packages
uv run ruff format --check .
  PASS — 105 files already formatted
uv run ruff check .
  PASS — All checks passed
uv run mypy
  PASS — Success: no issues found in 57 source files

[fresh exact-role review database] uv run alembic upgrade head
  PASS — base through 0026_legacy_tx05_time_guard
[exact-role MILAI_TEST_* environment] uv run pytest -q
  PASS — 121 passed in 86.26s
uv run pytest -q tests/integration/test_runtime_foundation.py
  PASS — 33 passed in 63.86s
```

The foundation file directly executes candidate.1 public routines at 0014, F01 exact grounding and
real Issue/Context absence, creation-history/replay/constraints, exact missing DeletionRequest,
identity/state/payload proof legs, all three timestamp prior-head shapes and the valid control. I read
the actual assertions and SQL; green status alone was not treated as proof.

Catalog and operational gates:

```text
head                                  0026_legacy_tx05_time_guard
milai durable tables                  32
backup tenant inventory tables        31
both quarantine relrowsecurity        true
both quarantine relforcerowsecurity   true
API/Worker ledger privilege           none
Steward/Audit ledger privilege         SELECT only

uv run pytest -q \
  tests/integration/test_backup_restore.py::test_consistency_backup_restore_and_deletion_expiry_reconciliation \
  tests/security
  PASS — 6 passed in 5.22s
```

The backup drill covers both ledgers in count/SHA inventory, archive verification, revoke, physical
purge, backup obligation/expiry and restore. Populated migration tests exercise nonempty Migration
Owner UPDATE/DELETE denial. Security/full-suite tests cover exact DB role attestation, unsafe role
attributes and ownership, RLS, cross-role/cross-tenant denial, session reset, secrets and redaction.

### Independent AF09-F12 three-generation replay

This was a separate reviewer harness, not an invocation of author test assertions. For setup only, I
called the inspected candidate.1 fixture helper that invokes the real public API/Steward procedures at
revision 0014. The reviewer harness independently selected exactly one durable row, applied the
one-second SQL mutation, ran the unchanged migration, queried prior head/schema/authority/event/outbox
state and force-dropped each disposable database in `finally`.

The four independently mutated legs were:

```sql
idempotency_record.created_at = created_at + interval '1 second'
operational_event.created_at  = created_at + interval '1 second'
EVIDENCE_REVOKED Outbox.created_at = created_at + interval '1 second'
PURGE_EVIDENCE_DERIVATIVES Outbox.created_at = created_at + interval '1 second'
```

The reviewer snapshot tuple is:

```text
(Alembic head, issue-ledger regclass, grounding-ledger regclass,
 target REVOKE_EVIDENCE Proposal count, linked Decision count,
 governed replacement-transition count,
 LEGACY_TX05_GOVERNANCE_RECONCILED event count,
 EVIDENCE_REVOCATION_GOVERNANCE_RECONCILED Outbox count,
 durable-table count)
```

| Input/prior head | Independent cases | Result and exact stable snapshot |
| --- | ---: | --- |
| candidate.1 at 0014, then fresh → head | 4 | Every leg raised `AF09_UNPROVABLE_LEGACY_TX05`; `('0023_erasure_sha256_repair', NULL, NULL, 0,0,0,0,0,30)` |
| candidate.3-compatible applied 0024 → 0025 | 4 | Every leg raised the stable error; before/after snapshots byte-value equal at `('0024_legacy_history_reconcile', issue-ledger, NULL, 1,1,1,1,1,31)` |
| candidate.4-compatible applied 0025 → 0026 | 4 | Every leg raised the stable error; before/after snapshots equal at `('0025_legacy_provenance_guard', issue-ledger, grounding-ledger, 1,1,1,1,1,32)` |
| valid six-equal timestamp 0025 → 0026 | 1 | `count=6`, `distinct timestamps=1`; advanced to `0026_legacy_tx05_time_guard`; every field after the head in the snapshot stayed identical `(ledgers,1,1,1,1,1,32)` |

The `1` counts in compatibility negatives are forensic authority already committed at the prior
candidate.3/candidate.4 head; the equality of before/after snapshots proves that failed 0025/0026 did
not add or replace authority. Fresh failures have zero authority and no 0024 ledger. In total:

```text
INDEPENDENT_REPLAY_PASS cases=13 invalid=12 control=1
```

An additional independent exact AF09-F11 replay deleted the real DeletionRequest after candidate.1
public TX-05 and observed:

```text
('0023_erasure_sha256_repair', NULL, NULL,
 Proposal=0, Decision=0, governed transition=0,
 reconciliation OperationalEvent=0, reconciliation Outbox=0)
```

It raised `AF09_UNPROVABLE_LEGACY_TX05`; the disposable database was dropped.

### TX-05 source-field audit

Candidate.1 uses PostgreSQL `CURRENT_TIMESTAMP`, fixed at transaction start, for the six durable time
facts. Direct inspection of each proof shape found the following predicates before authority or head
advancement:

| Required source fact | Corrected 0024 | Corrected 0025 | Proof-only 0026 | Dynamic evidence |
| --- | --- | --- | --- | --- |
| tenant + actual DeletionRequest UUID | `0024:323-329` | `0025:198-204` | `0026:63-69` | missing-row custom + foundation negatives |
| Evidence/Blob identity | `0024:323-327` | `0025:198-202` | `0026:63-67` | identity corruption rollback and unchanged candidate.4 predicate |
| requester and creator actor | `0024:330-333` | `0025:204-207` | `0026:69-72` | actor/creator negatives and exact-role replay |
| DeletionRequest requested time = Evidence revoked time | `0024:334` | `0025:208` | `0026:73` | request/Evidence-time negative and six-time control |
| logical/canonical/derived/primary/backup/retention state axes | `0024:335-349` | `0025:209-223` | `0026:74-88` | state/unknown-domain rollback nodes; predicates unchanged from independently reviewed candidate.4 |
| idempotency identity/payload/counts/actor/time | `0024:350-377` | `0025:224-251` | `0026:89-116` | payload negative plus independent timestamp leg |
| OperationalEvent IDs/reason/counts/actor/time | `0024:378-402` | `0025:252-275` | `0026:117-140` | payload negative plus independent timestamp leg |
| revoke Outbox IDs/actor/sequence/time | `0024:311-321,414-425` | `0025:187-196,287-299` | `0026:52-61,154-164` | payload negative plus independent timestamp leg |
| purge Outbox IDs/Evidence/Blob/state/actor/sequence/time | `0024:403-413` | `0025:267-286` | `0026:141-153` | payload negative plus independent timestamp leg |

The initial proof is under `ACCESS EXCLUSIVE` locks and is the global fail-closed boundary. Corrected
0024 repeats the selected-row idempotency, OperationalEvent and revoke-Outbox time predicates in the
governance reconstruction query (`0024:887-967`); the complete purge proof already ran under the same
locks. Migration 0026 contains only source locks and this proof; source inspection and the valid
control show no DDL, Proposal, Decision, transition, OperationalEvent, Outbox or canonical write.

### F01 and F02–F11 no-regression replay

Candidate.4 independently closed F01 and the exact missing-request F11 state. A byte diff of the
candidate.4 and candidate.5 0024/0025 migrations shows only the four missing time equalities and their
repeated selected-row predicates; rejected-grounding, creation-history, RLS, append-only, replay,
constraint and existing TX-05 checks are unchanged.

Direct populated nodes nevertheless ran again. At 0014, proposal submission creates the legacy
`RESOLUTION_CANDIDATE` relation before Decision. After candidate.5 migration, the actual pending/
rejected support set and SQL-recomputed exact row SHA are in forced-RLS append-only quarantine, the
relation is absent from canonical Issue branches and L0-derived Context, and a later normal review
works. Already-decided REJECT quarantines only unauthorized grounding; actual APPROVE remains linked.
Missing/conflicting relation support rolls the whole migration back. V1/Issue creation histories,
continuous replay and validated constraints also pass.

## Research, package, CI/Compose and documentation

```text
runtime/.venv/bin/ruff format --check research/ospc
  PASS — 11 files already formatted
runtime/.venv/bin/ruff check research/ospc
  PASS — All checks passed
runtime/.venv/bin/mypy --strict research/ospc
  PASS — 7 source files
runtime/.venv/bin/python -m unittest discover -s research/ospc/tests -v
  PASS — 9 tests, OK (0.216s)

[fresh temporary research copy] generate_fixtures + run_benchmark
  PASS — 40 synthetic fixtures
  fixture SHA-256=8fd9482aacf58d8802a16dbc86a9e8043ffc28123d904f72b7b87a052eaa718a
  decision=ABANDON; novelty_claim=false
  reasons=HF-01_STRONG_TYPED_STATE_EQUIVALENT,
          HF-02_STATIC_OPEN_ISSUE_EQUIVALENT,
          HF-06_VALIDATOR_COST_WITHOUT_MEASURED_GAIN

uv build --offline --out-dir <fresh-temporary-directory>  # run twice
  PASS — two builds byte-identical
  wheel SHA-256 45e61f9376aa7bd7cd2b06f27cfeeb850bc4be278638285d4ae97f631bf64365
  sdist SHA-256 d17b910229004700876f845d7d885d4b34260e7ebafa7f0dfd498d12c280acbf
  wheel entries=63; sdist entries=120; unique/safe contents PASS
uv venv <fresh-temporary-venv> --python 3.11
uv pip install --offline --no-deps <fresh-wheel>
  PASS — installed milai-runtime==0.1.0

Ruby YAML.safe_load .github/workflows/ci.yml
  PASS — mapping; job=runtime-and-research
[container values supplied without printing] docker compose config --quiet
  PASS
[Markdown fence and root-bounded relative-link audit before this review]
  PASS — 78 source/history files; 1,055 headings; 21 relative links; zero errors
```

The first online-isolated `uv build` attempt waited on its external build environment and exited
without artifacts; it did not touch the repository. Two subsequent fresh offline builds used the
available locked cache, completed immediately, were byte-identical, installed successfully and are
the package gate reported above. This environmental retry is not a candidate finding.

Research remains synthetic-only and cannot authorize product behavior. External assets are fully
disabled from the core path; their declared version/license/source/Git identities pass the all-scope
lock. Plaintext Blob support keeps real personal data denied, and remote/model routes remain opt-in
candidate inputs behind the canonical Gate.

## AF09-F01 through AF09-F12 closure audit

`CLOSED` means the required behavior was observed in source and executable evidence; it is not an
inference from remediation prose.

| Finding | Candidate.5 status | Independent conclusion |
| --- | --- | --- |
| AF09-F01 — proposal submission mutates canonical state before Decision | **CLOSED** | Fresh submission is noncanonical; populated pending/REJECT grounding is exact-hash quarantined and absent from real Issue/Context; only actual APPROVE remains canonical. |
| AF09-F02 — missing V1/OpenIssue creation history | **CLOSED** | Source-linked CREATE/ISSUE_CREATED sentinels, unique incoming history, continuous replay, validated constraints and corrupted-source rollback pass. |
| AF09-F03 — normative/legacy state domains | **CLOSED** | Normative constraints, legacy mappings, exhaustive allowed domains and unknown-value rollback pass. |
| AF09-F04 — Gate omits axes / bypasses ECS | **CLOSED** | ECS-only all-version Gate/Context independently enforce lifecycle, epistemic, freshness, Scope, valid/system time, authority and confidence. |
| AF09-F05 — indirect crosswalk evidence | **CLOSED** | 39 unique direct nodes exist and ran; F12 fresh/compat legs are explicitly mapped rather than inferred. |
| AF09-F06 — TX-05 lacks governed Decision | **CLOSED** | Current TX-05 remains Steward-only, Proposal/Decision-linked and atomically rolled back; legacy reconstruction is separately proven. |
| AF09-F07 — ERASED lacks durable absence proof | **CLOSED** | Typed adapter plus SQL identity/SHA absence proof and forged/missing/symlink/crash/retry negatives pass. |
| AF09-F08 — exact DB-role attestation missing | **CLOSED** | Exact usernames, `session_user=current_user`, unsafe attributes and ownership are enforced; exact-role negatives pass. |
| AF09-F09 — no real Outbox causal token/wait/fallback | **CLOSED** | Tenant-bound HMAC token uses the real Outbox position; continuous watermark, wait, dead-letter/timeout fallback and traces pass. |
| AF09-F10 — no external manifest trust anchor | **CLOSED** | Exact external receipt, archive-live identity, review-mode all-scope verification and coordinated-tamper rejection pass. |
| AF09-F11 — missing durable DeletionRequest reconstructs APPROVE | **CLOSED** | Independent deletion of the actual request raises the stable error at 0023 with zero ledger/authority/event/outbox residue; creator/identity/reason/state/payload legs remain enforced. |
| AF09-F12 — four durable TX-05 timestamps unproved | **CLOSED** | Twelve independent conflicts stay at 0023/0024/0025 with no new residue; six-equal control alone reaches proof-only 0026 without state changes. |

No new finding was discovered.

## G1-G9 and I-01-I-12 adversarial audit

| Goal | Result | Independent conclusion |
| --- | --- | --- |
| G1 Source Fidelity | PASS | Evidence identity, immutable capture, lineage, blocks and source-bound migration proofs are enforced. |
| G2 Governed Canonical Evolution | PASS | Submission is noncanonical; only Decision commits, and legacy authority requires complete source proof. |
| G3 Open-State Preservation | PASS | Issue identity/replay stay stable; rejected grounding is preserved outside authority and absent from consumers. |
| G4 Applicability Separation | PASS | Typed axes remain independent with direct ECS/Gate negatives. |
| G5 Candidate-Safe Retrieval | PASS | L0/L1/Context use canonical Gate; projection/model/external inputs cannot elevate authority. |
| G6 Revocation Propagation | PASS | Current TX-05, actual-request legacy reconstruction, six-time proof, purge and backup obligations fail closed. |
| G7 Bounded Traceable Context | PASS | Bounds/trace pass and no rejected candidate.1 branch reaches real Context. |
| G8 Least-Privilege Local Security | PASS | Exact roles, forced RLS, reset, loopback, separate secrets and redaction pass. |
| G9 Replaceable and Recoverable | PASS | Fresh and both compatibility paths are explicit; backup/restore and prior-head rollback are executable. |

| Invariant | Result | Independent conclusion |
| --- | --- | --- |
| I-01 | PASS | Evidence and Claim identity cannot collapse; API direct insertion is denied. |
| I-02 | PASS | Capture identity is immutable and idempotency conflicts fail closed. |
| I-03 | PASS | Proposal submission is noncanonical; only actual APPROVE retains canonical grounding. |
| I-04 | PASS | All four histories and both exact quarantine ledgers are append-only and complete. |
| I-05 | PASS | Head/Issue CAS races have one winner and full loser rollback. |
| I-06 | PASS | Issue identity/status/revision and rejected-grounding reconciliation remain stable. |
| I-07 | PASS | L0 consumes ECS-only axis-complete Gate. |
| I-08 | PASS | Projection/external candidates cannot bypass Gate; canonical outage abstains. |
| I-09 | PASS | State domains and orthogonal applicability axes have direct independent negatives. |
| I-10 | PASS | Fresh and legacy revoke, erasure proof, six timestamps and three prior-head failures are complete. |
| I-11 | PASS | Exact role/RLS/cross-role/cross-tenant/owner-swap negatives pass. |
| I-12 | PASS | Atomic writes, causal trace, populated reconciliation and no-residue rollback are directly executable. |

## Sixteen-item semantic checklist

| Check | Decision | Evidence/conclusion |
| --- | --- | --- |
| G1-G9 mutually consistent and no circular authorization | PASS | Source proof precedes reconstruction under locks; 0026 is proof-only and no projection/model is authority. |
| I-01-I-12 each have executable positive and negative evidence | PASS | All 39 direct nodes exist/run; reviewer-owned F11/F12 negatives and control agree. |
| Evidence/Claim/OpenIssue/Context identity boundaries are explicit | PASS | Separate IDs, ownership, pointers, histories and traces are enforced. |
| Steward single-writer, CAS, append-only and rollback are complete | PASS | Current writes, CAS losers, both ledgers and all three prior-head failures pass. |
| authority/Scope/time/freshness/epistemic are orthogonally matched | PASS | Normative domains, ECS, typed plans and direct all-axis negatives pass. |
| projection/external/model cannot raise truth/authority | PASS | Canonical Gate is the only active authority boundary; failures abstain/reduce recall. |
| revoke, Context invalidation, purge, Blob/backup obligations fail closed | PASS | Exact current/legacy revoke, verified absence, purge, expiry and restore drill pass. |
| tenant/RLS/roles/network/secrets/log privacy are least privilege | PASS | Real exact-role tests, forced RLS, Compose loopback and redaction pass. |
| dual sequence, watermark, RYW and recovery are unambiguous | PASS | Canonical/Outbox sequences, tenant token, continuous watermark, wait/fallback/recovery traces pass. |
| external assets can be disabled and license/identity verified | PASS | Core is independent; all-scope external source/Git locks pass. |
| threat residual and synthetic-only boundary acceptable | PASS | TM-27 and real/remote gates are explicit; research stays synthetic and novelty is abandoned. |
| migration/rollback/legacy/real-data change policy executable | PASS | Fresh base, populated 0014, 0024/0025 compatibility, proof-only 0026 and prior-head rollback pass. |
| populated candidate.1 provenance/quarantine/replay/validated constraints executable | PASS | Creation, grounding, actual-request TX-05, exact ledgers, replay and constraints pass. |
| rejected grounding exact support/hash quarantine and real Issue/Context absence | PASS | F01 direct populated storage/API/Context and continuation assertions pass. |
| legacy TX-05 actual DeletionRequest, per-leg fail-close and prior-head rollback | PASS | Exact F11 custom replay plus identity/actor/reason/state/payload negatives pass. |
| six durable TX-05 timestamps exact; 0024/0025/0026 conflicts retain prior head | PASS | Independent 12 negatives and six-equal control provide direct evidence. |

## Hard-reject sweep

| Hard-reject condition | Result | Evidence/conclusion |
| --- | --- | --- |
| Unmapped G/I/MUST or indirect-only evidence | NOT TRIGGERED | All mappings and direct nodes exist; F11/F12 have reviewer-owned SQL outcomes. |
| API/worker/model/adapter can direct canonical DML | NOT TRIGGERED | Grants, procedures and real-role negatives deny direct canonical mutation. |
| Cross-tenant/permission/retention/revoke/canonical outage fails open | NOT TRIGGERED | Direct negatives and fallback behavior pass. |
| Conflict/Issue auto-closed by summary/retrieval/time/model | NOT TRIGGERED | Only governed Decision closes; omission and model/projection have no authority. |
| Projection/Context/graph/external memory is authority | NOT TRIGGERED | They remain consumers/candidates behind canonical Gate. |
| CAS loser/rollback/outbox/history has partial write | NOT TRIGGERED | Current failures and all migration negatives show whole rollback/no new residue. |
| Populated migration fabricates authority, omits history, loses source, has mutable quarantine, or fails to abort unprovable state | NOT TRIGGERED | Complete source proofs, creation histories, exact immutable ledgers and prior-head failures pass. |
| Rejected Proposal grounding remains canonical or lacks exact-hash preservation | NOT TRIGGERED | Rejected rows are exact-hash quarantined and absent from Issue/Context. |
| Legacy TX-05 proof leg missing/conflicting reconstructs, or failed migration leaves residue | NOT TRIGGERED | Exact F11 and payload/identity/actor/state failures retain the prior head. |
| Any durable TX-05 timestamp conflict gains a head or reconstructs/certifies authority | NOT TRIGGERED | All 12 single-leg conflicts are blocked; 0026 control is read-only. |
| Manifest/source/Git drift is not rejected | NOT TRIGGERED | Archive/live identity, all-scope lock and direct drift negatives pass. |
| External trust anchor absent or coordinated substitution accepted | NOT TRIGGERED | Exact receipt anchor and coordinated-tamper rejection pass. |
| Real-data/remote gate or residual risk hidden | NOT TRIGGERED | Plaintext-real-data denial, remote opt-in and residuals are explicit. |
| Candidate banner removed before freeze | NOT TRIGGERED | Candidate/experimental/no-go banners remain present in submitted bytes. |

## Findings and decision

| ID | Severity | Finding | Resolution evidence |
| --- | --- | --- | --- |
| — | — | No open finding | AF09-F01 through AF09-F12 closed; no new P0/P1/P2 finding recorded |

The external identity chain, full exact-role runtime suite, independent three-generation provenance
counterexamples, real Issue/Context behavior, backup/security, research, package, documentation and
final drift gates all pass. The remaining boundaries—experimental schema, plaintext-Blob real-data
denial, synthetic-only research, optional remote/model adapters, and a separate immutable frozen
release—are explicit and acceptable for this logical-architecture decision.

```text
Decision: ACCEPT
Accepted submission: MiLAi Logical Architecture 1.0.0-candidate.5
AF-09: ACCEPTED FOR THE EXACT EXTERNAL-RECEIPT-IDENTIFIED CANDIDATE BYTES
Schema at review: 0.1.x EXPERIMENTAL
Implementation at review: CANDIDATE
Submitted freeze banner: NO-GO (preserved; frozen release is a subsequent step)
Open P0/P1/P2 findings: none
Manifest before/at decision:
  ece90366e5e3e3647af729351d8ae80310c8f6c30db1cf85b5a74ccb4168ed64
Signature/reference: /root/af09_reviewer_retry candidate.5 independent rereview acceptance
```

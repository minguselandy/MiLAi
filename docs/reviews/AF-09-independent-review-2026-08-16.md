# AF-09 Independent Review Record

Status: `COMPLETE — DECISION REVISE`

Decision: `REVISE`

## Reviewer record

```text
Reviewer: /root/af09_reviewer_retry
Reviewer role/independence: separate no-history sub-agent; did not author candidate
Review started (UTC): 2026-08-16T14:04:47Z
Review started (Asia/Shanghai): 2026-08-16T22:04:47+0800
Review completed (UTC): 2026-08-16T14:37:28Z
Review completed (Asia/Shanghai): 2026-08-16T22:37:28+0800
Candidate submission manifest SHA-256: e7f12a5f5832adc49e9c73cb6374ca66ac3c524cdbfe53709862f0155c45aab7
Candidate final-recheck manifest SHA-256: e7f12a5f5832adc49e9c73cb6374ca66ac3c524cdbfe53709862f0155c45aab7
Decision: REVISE
Signature/reference: /root/af09_reviewer_retry phase-3 decision
```

## Validation environment

```text
Host/kernel: Linux ligong-old 5.15.0-86-generic #96-Ubuntu SMP Wed Sep 20 08:23:49 UTC 2023 x86_64
System Python: Python 3.10.12
Runtime virtualenv Python: Python 3.11.13
PostgreSQL client: psql (PostgreSQL) 16.14 (Ubuntu 16.14-1.pgdg22.04+1)
Alembic: alembic 1.19.1
Git: git version 2.34.1
SHA-256 implementation: sha256sum (GNU coreutils) 8.32
Workspace: /cra/memory/mx_memory/MiLAi
```

The workspace root is not itself a Git worktree; `git status` therefore returned
`fatal: not a git repository`. Git identities declared inside the candidate were checked by the
all-scope lock verifier below.

## Candidate identity and command results

Commands were run from `/cra/memory/mx_memory/MiLAi` before this checkpoint was created.

```text
$ sha256sum architecture/v1.0-candidate/architecture_manifest.json
e7f12a5f5832adc49e9c73cb6374ca66ac3c524cdbfe53709862f0155c45aab7  architecture/v1.0-candidate/architecture_manifest.json

$ runtime/.venv/bin/python architecture/v1.0-candidate/scripts/validate_bundle.py
MiLAi architecture bundle validation: PASS (candidate, not frozen)

$ runtime/.venv/bin/python architecture/v1.0-candidate/scripts/verify_lock.py --scope all
MiLAi architecture lock verification: PASS (candidate, not frozen)
```

Submission identity for subsequent phases is the manifest digest recorded above. These automated
results establish candidate identity/consistency only; they are not an independent semantic review
or freeze decision.

Phase 2A identity recheck at `2026-08-16T14:19:46Z`
(`2026-08-16T22:19:46+0800` Asia/Shanghai) returned the same SHA-256:
`e7f12a5f5832adc49e9c73cb6374ca66ac3c524cdbfe53709862f0155c45aab7`.
No manifest drift was observed.

Phase 2B identity recheck at `2026-08-16T14:26:33Z`
(`2026-08-16T22:26:33+0800` Asia/Shanghai) again returned the submission SHA-256
`e7f12a5f5832adc49e9c73cb6374ca66ac3c524cdbfe53709862f0155c45aab7`.
No manifest drift was observed before or during the static review.

Phase 3 pre-gate identity recheck at `2026-08-16T14:34:07Z`
(`2026-08-16T22:34:07+0800` Asia/Shanghai) and final recheck at
`2026-08-16T14:37:28Z` (`2026-08-16T22:37:28+0800` Asia/Shanghai) both returned
`e7f12a5f5832adc49e9c73cb6374ca66ac3c524cdbfe53709862f0155c45aab7`.
The final all-scope lock verification also passed. Submission identity did not drift across the
review.

## Static-review method and scope

Phase 2A was a static adversarial review of checklist items 1–6. `AUTHOR_PREFLIGHT.md` and author
reports were used only as navigation and not as proof. The reviewer compared the normative bundle,
root design, `crosswalk.json`, ADRs, SQL migrations, runtime application/repository code, grants,
triggers, and test bodies.

All 20 unique positive/negative test nodes named by I-01 through I-12 in `crosswalk.json:91-223`
exist as Python test functions. Existence is not treated as semantic coverage: the function bodies
were inspected against the mapped invariant. Runtime execution of the test suite remains outside
this static phase.

For checklist items 7–12 the reviewer directly inspected the revoke/purge SQL and worker/Blob
implementation, Context and retrieval paths, backup/restore implementation and test, RLS/role
migration, authentication/settings/network/logging code, outbox/watermark/rebuild SQL and tests,
external source/Git locks and local asset identities, threat boundaries, migration tests and the
legacy/real-data ADRs. Author reports were not accepted as evidence. The hard-reject sweep below
uses the same direct artifacts.

## Semantic checklist checkpoint

| Check | Phase status | Evidence/finding |
| --- | --- | --- |
| G1–G9 目标相互一致且没有循环授权 | FAIL | G2/G4/G5/G8 are contradicted by implementation. The API proposal path accepts caller-selected `requested_authority` (`runtime/src/milai/domain/proposals.py:20-35`) and, although CommitPolicy says `USER_REVIEW` (`runtime/src/milai/application/derivation.py:109-121`), changes canonical OpenIssue state before a Decision (`runtime/migrations/versions/0005_canonical_procedures.py:304-419`). The runtime also accepts elevated/misassigned DB credentials (AF09-F08). See AF09-F01 through F04, F06 and F08. |
| I-01～I-12 每项含可执行正/负向证据 | FAIL | All named nodes exist, but several assertions are indirect or incomplete, and I-03/I-04/I-07/I-08/I-09/I-11/I-12 have source counterexamples. See the invariant audit and AF09-F01 through F06 plus AF09-F08. |
| Evidence/Claim/OpenIssue/Context identity 边界明确 | PASS_STATIC | Separate typed identities/tables are specified at `architecture/v1.0-candidate/OBJECTS.md:20-40` and implemented at `runtime/migrations/versions/0003_evidence_plane.py:35-119`, `0004_canonical_state_schema.py:49-358,412-568`, and `0009_context_chat.py:29-105`. Composite tenant FKs bind lineage (`0004_canonical_state_schema.py:412-470`). Behavioral nodes preserve separate Evidence/Claim lineage and stable issue/context IDs: `test_tx01_api_replay_conflict_blob_dedup_and_lineage` (`runtime/tests/integration/test_evidence_api.py:78-147`), `test_tx04_conflict_preserves_head_and_structured_branches` (`runtime/tests/concurrency/test_canonical_transactions.py:329-377`), and `test_chat_builds_fixed_capsule_trace_and_recoverable_pointer` (`runtime/tests/integration/test_context_chat_api.py:201-240`). No identity collapse was found statically. |
| Steward single-writer、CAS、append-only 与 rollback 完整 | FAIL | Direct table DML is revoked (`runtime/migrations/versions/0004_canonical_state_schema.py:719-725`) and exact-head/issue CAS is structurally present (`0005_canonical_procedures.py:684-694,835-844`; tests at `runtime/tests/concurrency/test_canonical_transactions.py:266-299,405-443`). However an API-executable proposal procedure mutates OpenIssue before Decision (AF09-F01), required creation history is absent (AF09-F02), TX-05 has no Decision (AF09-F06), and mapped rollback coverage does not assert outbox/event absence (AF09-F05). |
| authority/Scope/time/freshness/epistemic 正交匹配 | FAIL | The normative enum contract (`architecture/v1.0-candidate/OBJECTS.md:105-121`) disagrees with the schema (`runtime/migrations/versions/0004_canonical_state_schema.py:313-320`), and the Gate checks authority/scope/valid-time but not epistemic/freshness (`runtime/migrations/versions/0008_retrieval_gate.py:230-291`). See AF09-F03 and AF09-F04. |
| projection/external/model 不能提升 truth/authority | FAIL | L0/L1 candidates do converge on `gate_and_hydrate` (`runtime/src/milai/application/retrieval.py:159-166`), canonical outage abstains (`runtime/src/milai/application/retrieval.py:239-250`; `runtime/tests/integration/test_retrieval_api.py:438-483`), L2 is disabled (`runtime/src/milai/application/retrieval.py:54-60`), and the external-import guard exists (`runtime/tests/unit/test_external_dependency_boundary.py:6-31`). Nevertheless the shared Gate admits candidates without epistemic/freshness matching and bypasses the named ECS view, so these controls cannot prove the normative no-elevation property. See AF09-F04. |
| revoke、Context invalidation、purge、Blob/backup obligation fail closed | FAIL | Logical revoke, GroundingBlock and Context invalidation are synchronous (`runtime/migrations/versions/0006_evidence_revocation.py:300-437`), purge dead letters remain explicit (`runtime/migrations/versions/0007_projection_outbox.py:434-525`), and backup inventory/restore reconciliation is fail-closed (`runtime/src/milai/operations/backup.py:68-203,206-286,319-411`; `runtime/tests/integration/test_backup_restore.py:176-326`). However the purge worker ignores the false result of a missing Blob and then records `ERASED` without passing physical evidence to SQL (`runtime/src/milai/adapters/blob_store.py:74-88`; `runtime/src/milai/workers/main.py:95-112`; `runtime/migrations/versions/0007_projection_outbox.py:794-849`). See AF09-F07; the governance gap in revoke remains AF09-F06. |
| tenant/RLS/roles/network/secrets/log privacy 最小权限 | FAIL | Forced RLS and real-role negatives exist (`runtime/migrations/versions/0002_tenant_security_boundary.py:21-104`; `runtime/tests/security/test_tenant_roles.py:34-153`), bearer auth derives tenant/actor only from fixed settings (`runtime/src/milai/api/auth.py:13-30`), loopback is enforced (`runtime/src/milai/config/settings.py:67-78`; `runtime/compose.yaml:15-27`), and log payloads are omitted (`runtime/src/milai/observability/logging.py:14-58`; `runtime/tests/unit/test_logging_redaction.py:12-30`). But settings accept any two distinct DB usernames and the worker accepts any DSN; neither startup nor `milai-db-check` verifies the expected non-owner login/attributes. An owner credential is therefore an accepted API/worker configuration. See AF09-F08. |
| dual sequence、watermark、RYW、recovery 语义无歧义 | FAIL | Separate outbox sequence/delivery/watermark and contiguous-gap rules are implemented (`runtime/migrations/versions/0007_projection_outbox.py:43-143,276-427`) and exercised by `test_projection_worker_builds_fts_vector_and_contiguous_watermarks`, `test_dead_letter_blocks_watermark_until_explicit_retry`, and `test_search_projection_rebuild_replays_outbox_without_canonical_mutation` (`runtime/tests/integration/test_projection_worker.py:154-310,481-568`). But ADR-009 requires waiting for a causal `minimum_outbox_sequence`; the request has no such input and the planner always writes null, while runtime instead compares against the current tenant snapshot (`docs/adr/ADR-009-canonical-sequence-model.md:15-24`; `runtime/src/milai/domain/retrieval.py:14-28,44-59`; `runtime/src/milai/application/query_planner.py:31-43`; `runtime/src/milai/application/retrieval.py:126-193`). See AF09-F09. |
| external assets 可完全关闭且 license/identity 可验证 | PASS_STATIC | ADR-010 keeps L2 and all named frameworks disabled/removable and credential-free (`docs/adr/ADR-010-l2-and-external-adapter-gate.md:6-25`); runtime import scanning forbids them (`runtime/tests/unit/test_external_dependency_boundary.py:6-31`). Direct inspection matched Graphiti/Mem0 and all seven benchmark commits to `architecture_manifest.json:563-602`, and the four recorded license hashes matched the local ReMe/Hindsight/Graphiti/Mem0 files (`architecture/v1.0-candidate/BASELINE.md:33-112`). `verify_lock.py --scope all` also passed. The manifest trust-anchor defect is separately recorded as AF09-F10 and prevents treating the verifier alone as release identity proof. |
| threat model residual risk 与 synthetic-only boundary 可接受 | PASS_STATIC | The static boundary is explicit, not silently accepted for broader use: local/single-user/loopback/synthetic only (`architecture/v1.0-candidate/THREAT_MODEL.md:3-15`), plaintext Blob is a P0 real-data blocker and remote deployment is unapproved (`:68-77`), and encryption/key, privacy authorization, remote-security and performance gates remain open (`:112-125`; `docs/adr/ADR-012-blob-encryption-key-and-real-data-gate.md:24-28`). `PASS_STATIC` here means the limitation is sufficiently explicit for continued synthetic review; it is not approval of real data, production, remote access or final residual-risk acceptance. |
| migration/rollback/legacy/real-data change policy 可执行 | PASS_STATIC | Every revision has a downgrade; the integration node performs empty-database `base -> head -> base -> head`, and a populated 0013 trace is upgraded/downgraded without sequence loss (`runtime/tests/integration/test_runtime_foundation.py:43-69,71-160`). Unsafe post-revoke downgrade is explicitly stopped rather than deleting deletion history (`runtime/migrations/versions/0006_evidence_revocation.py:570-584`). ADR-014 requires read-only inventory, dry run, Evidence lineage, Proposal/Steward review and quarantine, and blocks any real import on ADR-012/privacy/backup/deletion/user-authorization gates (`docs/adr/ADR-014-legacy-and-real-data-migration.md:7-29`). Dynamic migration/restore execution remains pending. |

`PASS_STATIC` means only that no static counterexample was found in the inspected artifacts. It is
not a dynamic gate result or final AF-09 disposition.

## Hard-reject static sweep

These rows answer whether the prohibited condition is present in the inspected static candidate;
`PASS_STATIC` is not a substitute for the pending dynamic gates.

| Hard-reject condition (`FREEZE_REVIEW.md:75-83`) | Static result | Adversarial evidence |
| --- | --- | --- |
| Unmapped G/I/MUST or indirect positive/negative evidence | FAIL | I-01/I-04/I-09/I-12 evidence is indirect or incomplete, and implementation counterexamples remain for I-03/I-04/I-07/I-08/I-09/I-11/I-12. See the invariant audit and AF09-F01–F06, AF09-F08–F09. |
| API/worker/model/adapter can direct canonical DML | FAIL | Named runtime roles are denied literal table DML, but the API-executable security-definer proposal path performs pre-Decision OpenIssue mutation (AF09-F01), and accepted runtime configuration can assign an owner DSN to the API or worker without role verification (AF09-F08). |
| Cross-tenant, permission/retention unknown, revoke, or canonical outage fails open | PASS_STATIC | Forced RLS/cross-tenant and pool-reset nodes are `runtime/tests/security/test_tenant_roles.py:34-113`; permission/retention, shared-reference and legal-hold negatives are `runtime/tests/integration/test_canonical_api.py:448-493`; stale/revoked candidates and canonical outage are rejected/abstained at `runtime/tests/integration/test_retrieval_api.py:328-422,438-483`. AF09-F07 concerns physical-erasure attestation, not revival of authority. |
| Conflict/issue auto-closes through summary, omission, time or model | PASS_STATIC | Conflict Head remains unchanged with both branches (`runtime/migrations/versions/0005_canonical_procedures.py:888-970`; `runtime/tests/concurrency/test_canonical_transactions.py:329-377`), and Context construction revalidates every live issue (`runtime/migrations/versions/0009_context_chat.py:264-285`; `runtime/tests/integration/test_context_chat_api.py:307-335`). No automatic close path was found. |
| Projection/Context/graph/external memory is treated as authority | PASS_STATIC | Search candidates converge on canonical gate/hydration (`runtime/src/milai/application/retrieval.py:159-166`), Context is a bounded copy, external imports are absent, and L2 is disabled. AF09-F04 still fails the wider checklist because the canonical Gate omits two normative axes, but no origin-based authority grant was found. |
| CAS loser, rollback, outbox or history partially writes | FAIL | SQL transaction boundaries and CAS predicates are present, but required creation history is absent (AF09-F02), rollback evidence does not assert outbox/event residue (AF09-F05), and revoke canonical/history mutations lack the required Decision (AF09-F06). |
| Manifest/source/Git drift is not rejected | FAIL | The current review catches post-checkpoint drift by comparing the separately recorded submission digest, and no such drift occurred. However `manifest_self_lock` is false (`architecture_manifest.json:8-10`), `verify_lock.py` trusts hashes read from that same mutable manifest (`scripts/verify_lock.py:173-233`), and tests mutate a locked file without coordinating its manifest entry (`tests/test_bundle.py:170-185`). A copied bundle with `OBJECTS.md` and its manifest hash changed together returned no errors from either collector. See AF09-F10. |
| Real-data/remote gates or residual risks are hidden | PASS_STATIC | The threat model explicitly rejects real personal data, production and remote deployment and lists plaintext Blob, root/host and performance residuals (`architecture/v1.0-candidate/THREAT_MODEL.md:68-77,112-125`); ADR-012 and ADR-014 preserve those gates. |
| Candidate banner removed before the actual freeze decision | PASS_STATIC | Manifest remains `CANDIDATE`/`NO-GO` (`architecture/v1.0-candidate/architecture_manifest.json:3-10`), runtime constants remain experimental/candidate/no-go (`runtime/src/milai/__init__.py:1-7`), and health/foundation tests assert those strings (`runtime/tests/contract/test_health.py:36-42`; `runtime/tests/integration/test_runtime_foundation.py:30-40`). |

## G1–G9 static consistency audit

| Goal | Static result | Adversarial evidence |
| --- | --- | --- |
| G1 Source Fidelity | PASS_STATIC | Evidence identity immutability is enforced by `runtime/migrations/versions/0003_evidence_plane.py:237-268`; Claim grounding uses typed tenant-composite relations at `runtime/migrations/versions/0004_canonical_state_schema.py:412-470`. The Evidence replay/lineage node is `runtime/tests/integration/test_evidence_api.py::test_tx01_api_replay_conflict_blob_dedup_and_lineage` (`:78-147`). |
| G2 Governed Canonical Evolution | FAIL | The normative requirement is `architecture/v1.0-candidate/INVARIANTS.md:13`. API proposal submission changes OpenIssue with no Decision (AF09-F01); CREATE/CONTRADICT omit required initial history (AF09-F02); TX-05 mutations omit Decision (AF09-F06). |
| G3 Open-State Preservation | PASS_STATIC | CONTRADICT preserves Head, stable issue, both branches and discharge rule in `runtime/migrations/versions/0005_canonical_procedures.py:888-970`; the mapped node asserts Head/version/branches/ECS at `runtime/tests/concurrency/test_canonical_transactions.py:329-377`. The separate missing creation-transition defect remains AF09-F02. |
| G4 Applicability Separation | FAIL | Normative/schema vocabulary conflicts (AF09-F03), and request/Gate cannot match epistemic or freshness (AF09-F04). |
| G5 Candidate-Safe Retrieval | FAIL | Projection and canonical candidates converge on a canonical function, but that function omits required axes and independently reads canonical tables rather than the named ECS decision entry (AF09-F04). |
| G6 Revocation Propagation | PASS_STATIC | Synchronous revoke updates Evidence, creates blocks and invalidates Context in `runtime/migrations/versions/0006_evidence_revocation.py:300-437`; the mapped nodes inspect blocked authority and invalid pointers at `runtime/tests/integration/test_canonical_api.py:339-383` and `runtime/tests/integration/test_context_chat_api.py:338-368`. Governance/Decision completeness is separately failed under G2/I-12 (AF09-F06). |
| G7 Bounded Traceable Context | PASS_STATIC | Capsule creation revalidates trace candidates, all live issues, and Evidence (`runtime/migrations/versions/0009_context_chat.py:185-344`); mapped positive/negative behavior is at `runtime/tests/integration/test_context_chat_api.py:201-304,307-335,372-418`. |
| G8 Least-Privilege Local Security | FAIL | Forced RLS/session context and named-role DML denial are present (`runtime/migrations/versions/0002_tenant_security_boundary.py:21-104`; `runtime/src/milai/persistence/database.py:27-100`; `runtime/tests/security/test_tenant_roles.py:34-153`), but API/Steward settings accept any distinct usernames, Worker accepts any DSN, and startup never checks the connected role. See AF09-F08. |
| G9 Replaceable and Recoverable System | PASS_STATIC | External runtime imports are prohibited by `runtime/tests/unit/test_external_dependency_boundary.py:6-31`; ADR-010 requires disabled/removable adapters at `docs/adr/ADR-010-l2-and-external-adapter-gate.md:6-25`. Recovery execution remains a later phase. |

The goal graph itself (`MiLAi_Logical_Architecture_v1_设计文档.md:236-248`) has no formal graph
cycle. The authorization flow does contain a semantic self-authorization defect: API-controlled
`requested_authority` is used to satisfy an issue's required authority before Steward review; this
is AF09-F01.

## I-01–I-12 test-node and behavior audit

| Invariant | Node resolution and behavior match | Static result |
| --- | --- | --- |
| I-01 | Both mapped nodes exist (`crosswalk.json:98-100`). `test_tx02_create_is_versioned_grounded_and_idempotent` (`runtime/tests/concurrency/test_canonical_transactions.py:201-237`) proves a governed ClaimVersion with grounding. The designated negative node `test_tx01_api_replay_conflict_blob_dedup_and_lineage` (`runtime/tests/integration/test_evidence_api.py:78-147`) tests Evidence replay/conflict and empty pre-claim lineage, but never attempts or rejects treating Evidence as ClaimVersion. | PARTIAL — AF09-F05 |
| I-02 | `test_tx01_api_replay_conflict_blob_dedup_and_lineage` asserts same-key replay and changed-fingerprint conflict (`runtime/tests/integration/test_evidence_api.py:83-108`); `test_evidence_capture_identity_is_immutable_even_for_owner` asserts the owner trigger rejects source mutation (`:313-323`). | PASS_STATIC |
| I-03 | The negative node denies ClaimHead DML for all runtime roles and ClaimVersion mutation even to owner (`runtime/tests/concurrency/test_canonical_transactions.py:564-588`). The positive API node also demonstrates the counterexample: proposal submission alone transitions OpenIssue to `READY_FOR_REVIEW` (`runtime/tests/integration/test_canonical_api.py:220-250`). | FAIL — AF09-F01 |
| I-04 | Append-only triggers are installed on all four named history objects (`runtime/migrations/versions/0004_canonical_state_schema.py:608-635`), but the mapped negative node mutates only ClaimVersion (`runtime/tests/concurrency/test_canonical_transactions.py:582-588`). Required creation history is absent and tests encode zero/missing transitions. | FAIL — AF09-F02, AF09-F05 |
| I-05 | Head race has one winner and final counts (`runtime/tests/concurrency/test_canonical_transactions.py:266-299`); issue revision race has one winner and rejected resolution reopens (`:405-443`). SQL uses row locking plus exact predicates (`runtime/migrations/versions/0005_canonical_procedures.py:684-694,835-844,720-730`). | PASS_STATIC |
| I-06 | CONTRADICT preserves Head and both branches (`runtime/tests/concurrency/test_canonical_transactions.py:329-377`); the resolution race/rejection node preserves the same issue identity and reopens (`:405-443`). | PASS_STATIC |
| I-07 | Both nodes exist (`crosswalk.json:163-166`), but they prove use of `evaluate_canonical_candidates`, not that `effective_claim_state` is the sole current/authority entry. The Gate directly reads ClaimVersion/Head/Evidence/Issue (`runtime/migrations/versions/0008_retrieval_gate.py:199-291`) and never queries the named ECS view. | FAIL — AF09-F04 |
| I-08 | L1 FTS/vector candidates are merged then gated (`runtime/tests/integration/test_retrieval_api.py:220-298`), and projection outage degrades while canonical outage abstains (`:438-483`). The external import node exists (`runtime/tests/unit/test_external_dependency_boundary.py:16-31`). The common Gate is incomplete for required axes, so the mapped tests cannot establish the full no-elevation claim. | FAIL — AF09-F04 |
| I-09 | The mapped “stale” negative node supersedes a version and checks stale Head, revoke, Scope, authority and valid time (`runtime/tests/integration/test_retrieval_api.py:328-422`). It has no epistemic, freshness, confidence-independence, or system-time negative case. The implementation omits two axes. | FAIL — AF09-F03, AF09-F04, AF09-F05 |
| I-10 | Revoke creates synchronous blocks/Context invalidation (`runtime/migrations/versions/0006_evidence_revocation.py:300-437`); mapped nodes verify blocked retrieval, invalid pointer and retention/legal-hold behavior (`runtime/tests/integration/test_canonical_api.py:339-383,448-493`; `runtime/tests/integration/test_context_chat_api.py:338-368`). | PASS_STATIC |
| I-11 | The mapped real-login nodes exercise RLS cross-tenant denial and pool reset (`runtime/tests/security/test_tenant_roles.py:34-113`), and the positive node opens PostgreSQL using the intended API role (`runtime/tests/integration/test_runtime_foundation.py:164-183`). They do not test role substitution: accepted settings/worker DSNs can supply owner/elevated credentials and startup does not verify `current_user` or attributes. | FAIL — AF09-F08 |
| I-12 | The positive context/chat node records ClaimVersion, Evidence and trace IDs (`runtime/tests/integration/test_context_chat_api.py:201-240`). The mapped rollback node is named for idempotency/outbox/event but only asserts idempotency and Evidence counts (`runtime/tests/integration/test_evidence_api.py:238-281`). TX-05 is absent from the I-12 implementation/test map and creates no Decision. | FAIL — AF09-F05, AF09-F06 |

## Static-review findings

| ID | Severity | Artifact/line | Finding | Required change/evidence | Resolution evidence |
| --- | --- | --- | --- | --- | --- |
| AF09-F01 | P1 | `architecture/v1.0-candidate/INVARIANTS.md:13,28,37`; `architecture/v1.0-candidate/PERMISSIONS.md:11-12,21-22,65-75`; `runtime/migrations/versions/0005_canonical_procedures.py:167-201,304-419,1071-1077`; `runtime/src/milai/application/derivation.py:109-121`; `runtime/tests/integration/test_canonical_api.py:220-250` | API Runtime is granted the proposal function. Despite CommitPolicy requiring review, that function inserts resolution grounding and revision-CAS changes canonical OpenIssue to `READY_FOR_REVIEW`; its IssueTransition has `decision_id = NULL`. It authorizes this using caller-selected `requested_authority`. This is a pre-Decision canonical mutation and a semantic self-authorization path, contrary to G2/I-03/I-12 and the single-writer contract. | Make proposal submission non-canonical: persist only proposal/candidate evidence until the Steward review transaction, then perform OpenIssue CAS/transition with a non-null Decision. Add a real API-role negative test showing proposal submission cannot change OpenIssue/revision/history, plus atomic review/rollback assertions. If a pre-review canonical state is intended, an ADR and synchronized G/I/schema/crosswalk change must define its governance fact without weakening authority safety. | PENDING |
| AF09-F02 | P1 | `architecture/v1.0-candidate/TRANSACTIONS.md:49-56,84-90`; `runtime/migrations/versions/0004_canonical_state_schema.py:361-409`; `runtime/migrations/versions/0005_canonical_procedures.py:623-678,900-947`; `runtime/tests/concurrency/test_canonical_transactions.py:201-237,329-377,431-443` | The normative TX-02 contract requires a VersionTransition and TX-04 requires an OpenIssueTransition. CREATE inserts no VersionTransition and its test explicitly expects zero. First CONFLICT inserts OpenIssue revision 1 but no creation transition; only later conflict updates append one, and the resolution test's history starts at revision 1→2. The VersionTransition schema also requires a non-null old version, so it cannot represent creation as written. Replay/history is incomplete relative to the frozen candidate text. | Define explicit creation-history semantics. Either add creation transition forms/sentinels and atomic inserts for Claim/OpenIssue creation, or revise the normative transaction/object/replay contract through ADR and synchronized crosswalk. Add tests asserting a complete revision-0/creation-to-current replay and Decision/outbox linkage. | PENDING |
| AF09-F03 | P1 | `architecture/v1.0-candidate/OBJECTS.md:105-121`; `MiLAi_Logical_Architecture_v1_设计文档.md:338-350`; `runtime/migrations/versions/0004_canonical_state_schema.py:313-320`; `runtime/migrations/versions/0005_canonical_procedures.py:658-660,817-823` | Normative ClaimVersion enums are lifecycle `ACTIVE/SUPERSEDED/ARCHIVED/DELETED`, epistemic `PROVISIONAL/VERIFIED/CHALLENGED/UNPROVABLE`, freshness `CURRENT/STALE`. The schema accepts lifecycle `ACTIVE/RETIRED`, epistemic `SUPPORTED/WEAKENED/UNCERTAIN`, and extra freshness `UNKNOWN`; procedures default to the implementation-only vocabulary. No compatibility mapping is specified. G4/I-09 therefore do not map to the locked schema. | Align schema/procedures/domain/API with the normative values, or publish a lossless, reviewed mapping and update the normative architecture via ADR. Add migration compatibility and exhaustive enum positive/negative tests; refresh crosswalk/manifest after review. | PENDING |
| AF09-F04 | P1 | `architecture/v1.0-candidate/RETRIEVAL_CONTEXT.md:64-82`; `architecture/v1.0-candidate/INVARIANTS.md:32-34`; `runtime/src/milai/domain/retrieval.py:14-28,44-59`; `runtime/src/milai/application/retrieval.py:159-166`; `runtime/src/milai/persistence/retrieval_repository.py:258-307`; `runtime/migrations/versions/0008_retrieval_gate.py:199-291`; `runtime/tests/integration/test_retrieval_api.py:328-422` | Canonical Gate requires lifecycle, epistemic and freshness to independently satisfy the request, and ECS is declared the sole current/authority entry. QueryPlan/request has no epistemic/freshness requirement; the Gate checks Head/lifecycle/scope/time/authority/block/issue/lineage but never epistemic or freshness, and directly recomputes from canonical tables rather than consuming the named ECS view. The mapped negative test's “stale” case is stale Head after supersede, not `freshness=STALE`. Thus a current Head with unacceptable epistemic/freshness can be accepted from L0/L1. | Define typed per-request matching semantics for every axis; pass them through QueryPlan/repository; enforce them in the authoritative ECS/Gate boundary without duplicated divergent logic. Add independent negative combinations including current-Head + `STALE`, `CHALLENGED`/`UNPROVABLE` (or the final aligned enums), confidence changes that do not alter authority, and valid-time vs system-time. | PENDING |
| AF09-F05 | P1 | `architecture/v1.0-candidate/crosswalk.json:93-100,126-133,181-188,214-221`; `runtime/tests/integration/test_evidence_api.py:78-147,238-281`; `runtime/tests/concurrency/test_canonical_transactions.py:564-588`; `runtime/tests/integration/test_retrieval_api.py:328-422` | Every mapped node exists, but required positive/negative evidence is partly indirect: I-01's negative node never attempts Evidence→Claim collapse; I-04's negative node mutates only ClaimVersion, not all four named histories; I-09 omits epistemic/freshness/confidence/system-time; I-12's rollback node does not count OutboxEvent or OperationalEvent despite its name. This meets the review template's “indirect evidence” insufficiency condition. | Add targeted executable negative tests for each omitted invariant behavior, including all append-only tables and full transaction residue counts (mutation, Decision, history, OperationalEvent, Outbox). Correct crosswalk mappings only after inspecting test assertions, not just node names. | PENDING |
| AF09-F06 | P1 | `architecture/v1.0-candidate/TRANSACTIONS.md:6-18,93-110`; `architecture/v1.0-candidate/INVARIANTS.md:13,37`; `architecture/v1.0-candidate/crosswalk.json:214-221`; `runtime/migrations/versions/0006_evidence_revocation.py:210-552` (especially `:403-418,483-527`) | TX-05 performs Evidence revoke, GroundingBlock creation, canonical OpenIssue revision/status changes, transitions, Context invalidation, events and outboxes but creates no OperationProposal or StewardDecision. Reopened IssueTransitions explicitly store null proposal/decision IDs. I-12's crosswalk omits migration 0006 and any revoke atomicity/Decision test. This contradicts TX-05's required synchronous `decision` and G2/I-12. | Represent revoke authorization as a governed proposal/StewardDecision or a separately specified append-only governance decision that satisfies G2/I-12; link affected IssueTransitions and operational/outbox facts to it in one transaction. Extend I-12/TX-05 crosswalk and add success, forced-failure rollback, idempotency and replay tests that assert the Decision/history/event/outbox set. | PENDING |
| AF09-F07 | P1 | `architecture/v1.0-candidate/DELETION_RECOVERY.md:6-9,57-61,140-151`; `runtime/src/milai/adapters/blob_store.py:74-88`; `runtime/src/milai/workers/main.py:95-112`; `runtime/src/milai/persistence/projection_repository.py:132-137`; `runtime/migrations/versions/0007_projection_outbox.py:794-849`; `runtime/tests/integration/test_projection_worker.py:316-372` | `LocalContentAddressedBlobStore.erase` returns `False` when the expected file is absent. The worker discards that result and unconditionally calls `complete_blob_erasure`; the SQL then records both Blob and every clear deletion request as `ERASED` without receiving a physical result/hash. The only success test begins with an existing file and asserts it is later absent; no missing-file/result-attestation negative exists. Thus the deletion record cannot distinguish a performed durable erase from a pre-existing loss or an unverified absence, contrary to the declared per-layer deletion proof. | Make the adapter return a typed, auditable postcondition (performed erase versus verified already-absent versus integrity failure), require the worker/SQL transition to consume that proof, and record a safe result/proof hash. Add missing file, symlink/non-regular target, hash/URI mismatch, retry and crash-boundary tests; only mark `ERASED` after the defined durable absence condition is verified. | PENDING |
| AF09-F08 | P1 | `architecture/v1.0-candidate/PERMISSIONS.md:16-24,61-75`; `MiLAi_Lean_V1_实施合同.md:1053-1061,1331-1332`; `runtime/src/milai/config/settings.py:48-57,87-95`; `runtime/src/milai/workers/main.py:159-170,184-192`; `runtime/src/milai/persistence/cli.py:7-14`; `runtime/tests/unit/test_settings.py:10-64`; `runtime/tests/unit/test_worker_settings.py:11-40` | The role/grant migration defines least-privilege named logins, but runtime configuration verifies only that the API and Steward URL usernames differ. It does not require `milai_api`/`milai_steward`, reject owner/superuser/`BYPASSRLS`, or check the connected role. `_worker_dsn` accepts any non-empty URL and `milai-db-check` only pings. Consequently a syntactically valid configuration can run the API or worker with the Migration Owner (or another elevated login), making the direct-DML/DDL prohibition depend on operator discipline rather than a fail-closed process boundary. Existing settings tests do not cover role substitution. | At API/worker/Steward startup, connect and verify the exact expected `session_user/current_user`, role attributes, ownership and `BYPASSRLS` state; reject owner/elevated/misassigned credentials before serving or leasing work. Parse/validate the worker DSN without exposing it. Add unit and real-login integration negatives for owner, swapped API/Steward/Worker, inherited/elevated roles and a positive dedicated-role startup path. | PENDING |
| AF09-F09 | P1 | `docs/adr/ADR-009-canonical-sequence-model.md:7-24`; `runtime/src/milai/domain/retrieval.py:14-28,44-59`; `runtime/src/milai/application/query_planner.py:13-43`; `runtime/src/milai/application/retrieval.py:126-193`; `runtime/tests/integration/test_retrieval_api.py:220-246,300-324`; `runtime/migrations/versions/0014_query_plan_outbox_sequence.py:1-86` | ADR-009 says `READ_YOUR_WRITES` waits for a caller's `minimum_outbox_sequence` and falls back on timeout. The request has no causal-minimum field, QueryPlanner always emits `minimum_outbox_sequence=None`, and retrieval never reads the plan field or waits; it conservatively compares projection watermarks with the current tenant-wide snapshot and immediately uses canonical search when behind. The tests codify null and projection-lag fallback. This is safe against stale projection answers but is not the locked causal RYW contract, makes the renamed plan field inert, and cannot express or trace the client's write token. | Add a typed, authenticated/validated causal outbox token to the request or define a server-side session token; populate QueryPlan, wait/bound it against each required projection watermark, fall back canonically on timeout, and persist the minimum/outcome in the trace. Add reached, timeout, dead-letter, invalid/future/cross-tenant token and concurrent-snapshot tests. Alternatively revise ADR/bundle/crosswalk to specify the conservative tenant-snapshot semantics before re-locking. | PENDING |
| AF09-F10 | P1 | `architecture/v1.0-candidate/architecture_manifest.json:8-10,30-94`; `docs/adr/ADR-011-architecture-bundle-lock.md:8-18`; `architecture/v1.0-candidate/scripts/validate_bundle.py:292-336`; `architecture/v1.0-candidate/scripts/verify_lock.py:173-233`; `architecture/v1.0-candidate/tests/test_bundle.py:170-185` | The manifest intentionally excludes itself and ADR-011 says its digest is recorded separately, but neither validator accepts or authenticates that external digest. `verify_lock.py` reads expected hashes from the same mutable manifest as the candidate. In an isolated copy, changing `OBJECTS.md` from “30 durable tables” to “999 durable tables” and updating only its manifest hash yielded `[]` from both `collect_errors` and all-scope `collect_hash_errors`; the forged manifest digest was `3b4955c0b6038fdcc434192507efa3edbe19d41c563f9a74d1f13cee7f636204`. The existing drift test changes only the file. This review's pre-edit digest protects the current submission from later drift, but the advertised verifier alone accepts coordinated bundle/manifest substitution and no pre-acceptance authenticated receipt is present. | Require the verifier/review gate to consume an externally authenticated expected manifest digest (signed/immutable submission or release receipt), fail if it is absent/mismatched, and add a coordinated bundle+manifest tamper negative test. Preserve the reviewer-captured submission digest and independently republish/verify it after any authorized revision. | PENDING |

No static-review finding was closed before Phase 3. Checklist items 1–12 and all nine hard-reject
conditions received a static result.

## Phase 3 dynamic gates

All commands below ran against the unchanged submission manifest. Database passwords were read
inside the test shell from the already-running healthy `milai-lean-v1-postgres-1` container, checked
for URL-safe characters, used to construct owner/API/Steward/Worker/Audit DSNs in process, and never
printed. The full runtime test used the four dedicated runtime/audit login roles plus Migration
Owner only where the migration/backup tests require it.

### Architecture candidate

```text
$ runtime/.venv/bin/ruff format --check \
    architecture/v1.0-candidate/scripts architecture/v1.0-candidate/tests
3 files already formatted

$ runtime/.venv/bin/ruff check \
    architecture/v1.0-candidate/scripts architecture/v1.0-candidate/tests
All checks passed!

$ runtime/.venv/bin/python architecture/v1.0-candidate/scripts/validate_bundle.py
MiLAi architecture bundle validation: PASS (candidate, not frozen)

$ runtime/.venv/bin/python architecture/v1.0-candidate/scripts/verify_lock.py --scope all
MiLAi architecture lock verification: PASS (candidate, not frozen)

$ MILAI_ARCHITECTURE_LOCK_SCOPE=all runtime/.venv/bin/python \
    -m unittest discover -s architecture/v1.0-candidate/tests -v
Ran 14 tests in 0.449s — OK
```

The verifier was run again after all dynamic gates and again returned
`PASS (candidate, not frozen)`. These green tests do not exercise the coordinated content+manifest
substitution in AF09-F10.

### Runtime static checks and real PostgreSQL suite

```text
$ cd runtime && uv sync --frozen --dev --python 3.11
Audited 36 packages in 1ms

$ uv run ruff format --check .
90 files already formatted

$ uv run ruff check .
All checks passed!

$ uv run mypy
Success: no issues found in 55 source files

$ uv run pytest -q
74 passed in 19.22s
```

The 74-test invocation was unfiltered: migration `base -> head -> base -> head`, populated 0014
compatibility migration, real login/RLS and role denial, concurrency/CAS/rollback, retrieval/outage,
revoke/Context invalidation, purge/dead-letter/rebuild, and backup/expiry/empty-target restore were
all included. The PostgreSQL service was healthy before the run. A first orchestration attempt was
rejected before process creation by the execution safety guard because its temporary-directory
cleanup trap used a recursive removal command; it ran no test and changed no candidate artifact.
The safe rerun above omitted that cleanup and is the reported gate result.

### Fresh package build

The build used a new temporary output directory, so no repository distribution artifact was
created or overwritten.

```text
$ cd runtime && uv build --out-dir <new-temporary-directory>
Successfully built milai_runtime-0.1.0.tar.gz
Successfully built milai_runtime-0.1.0-py3-none-any.whl

$ sha256sum <temporary>/milai_runtime-0.1.0-py3-none-any.whl
1632908d11d63b2f6db57a8bfd6f9f32eacf01de95f548d22077d4beab5fbb4a

$ sha256sum <temporary>/milai_runtime-0.1.0.tar.gz
4dd2b56b1867d43754ecb4408c939d267f2ae3d555a7e3f433cbb4b44e0ab269

$ unzip -t <temporary>/milai_runtime-0.1.0-py3-none-any.whl
No errors detected in compressed data
```

Wheel inspection found 61 entries, the complete `milai` package, templates/static assets,
`py.typed`, console-entry metadata and version `0.1.0`. Its METADATA retained
`0.1.x EXPERIMENTAL / CANDIDATE / NO-GO FOR SCHEMA FREEZE` and Python `>=3.11,<3.13`.

### Isolated OSPC research gates

```text
$ runtime/.venv/bin/ruff format --check research/ospc
11 files already formatted

$ runtime/.venv/bin/ruff check research/ospc
All checks passed!

$ runtime/.venv/bin/mypy --strict research/ospc
Success: no issues found in 7 source files

$ runtime/.venv/bin/python -m unittest discover -s research/ospc/tests -v
Ran 9 tests in 0.201s — OK
```

Fixture generation and the benchmark ran in a temporary copy so the locked research artifacts were
not rewritten:

```text
$ python -m research.ospc.generate_fixtures
$ python -m research.ospc.run_benchmark
fixture_count: 40
fixture SHA-256: 8fd9482aacf58d8802a16dbc86a9e8043ffc28123d904f72b7b87a052eaa718a
generated pilot.jsonl and manifest.json: byte-identical to locked inputs
synthetic_only: true
equal_budget: true
decision: ABANDON
novelty_claim: false
reasons:
  HF-01_STRONG_TYPED_STATE_EQUIVALENT
  HF-02_STATIC_OPEN_ISSUE_EQUIVALENT
  HF-06_VALIDATOR_COST_WITHOUT_MEASURED_GAIN
```

This is an OSPC novelty decision only and neither changes product policy nor repairs an AF-09
finding.

### CI and Compose parsing

```text
$ ruby -e '<safe YAML load and jobs mapping assertion>' .github/workflows/ci.yml
CI YAML parse: PASS (1 job)

$ MILAI_*_DB_PASSWORD=<parse-only placeholders> \
    docker compose -f runtime/compose.yaml config --quiet
Docker Compose config: PASS
```

## Dynamic resolution audit

No new dynamic failure or additional finding AF09-F11 was observed. Green regression tests do not
close a semantic counterexample or absent assertion, so all ten P1 findings remain open:

| Finding | Phase 3 status | Why the green suite does not close it |
| --- | --- | --- |
| AF09-F01 | OPEN P1 | `test_canonical_api.py` passes while affirmatively expecting proposal submission to move the issue to `READY_FOR_REVIEW`; it encodes rather than refutes the counterexample. |
| AF09-F02 | OPEN P1 | Existing transaction tests pass while expecting zero CREATE VersionTransitions and omit first-conflict creation history. |
| AF09-F03 | OPEN P1 | Type/lint/migration success does not reconcile the locked normative and schema enum vocabularies. |
| AF09-F04 | OPEN P1 | Retrieval tests cover stale Head/scope/time/authority but still do not pass or reject epistemic/freshness requirements or prove ECS is the sole entry. |
| AF09-F05 | OPEN P1 | All named nodes execute, but their assertions still omit the invariant-specific negatives and full rollback residue counts identified statically. |
| AF09-F06 | OPEN P1 | Revoke/purge tests pass without a TX-05 Proposal/StewardDecision or Decision-linked issue transition. |
| AF09-F07 | OPEN P1 | Purge success/dead-letter tests do not exercise `erase() == False` or require a physical-erasure proof before SQL records `ERASED`. |
| AF09-F08 | OPEN P1 | The suite deliberately used correct dedicated roles; it has no startup negative proving an owner/elevated/swapped DSN is rejected. |
| AF09-F09 | OPEN P1 | The RYW test passes while QueryPlan explicitly contains `minimum_outbox_sequence=None`; no causal minimum/wait/timeout path exists. |
| AF09-F10 | OPEN P1 | The 14 bundle tests cover uncoordinated file drift, path escape and Git drift, not coordinated bundle+manifest substitution or an authenticated expected digest. |

## Final decision

```text
Decision: REVISE
AF-09: COMPLETE_WITH_REVISE_DECISION
Freeze: NO-GO
Candidate status: retain CANDIDATE / NO-GO FOR SCHEMA FREEZE
Reviewer: /root/af09_reviewer_retry
Independence: separate no-history sub-agent; did not author candidate
Signature/reference: /root/af09_reviewer_retry phase-3 decision
Submission manifest SHA-256: e7f12a5f5832adc49e9c73cb6374ca66ac3c524cdbfe53709862f0155c45aab7
Final manifest SHA-256: e7f12a5f5832adc49e9c73cb6374ca66ac3c524cdbfe53709862f0155c45aab7
Completed UTC: 2026-08-16T14:37:28Z
Completed Asia/Shanghai: 2026-08-16T22:37:28+0800
```

Rationale: every requested dynamic gate passed and no P0 was found, so the candidate is not rejected
as irreparable. It nevertheless has ten unresolved P1 findings, eight of twelve semantic checklist
rows are `FAIL`, and four hard-reject conditions are present (unmapped/indirect evidence, canonical
mutation boundary, partial history/Decision evidence, and manifest trust). `FREEZE_REVIEW.md:98-99`
forbids ACCEPT unless every checklist item passes and all P0/P1 findings are closed. The required
outcome is therefore `REVISE`: preserve the candidate/no-go banner, repair each finding through the
synchronized ADR/design/crosswalk/migration/code/test/manifest process, then submit a new immutable
candidate identity for an independent re-review.

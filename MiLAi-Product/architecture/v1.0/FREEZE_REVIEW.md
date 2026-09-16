# AF-09 Independent Freeze Acceptance

> Architecture：`1.0.0 FROZEN`  
> Review status：`COMPLETE_INDEPENDENT_REVIEW`  
> Decision：`ACCEPT`  
> Release status：`FROZEN LOGICAL ARCHITECTURE`  
> Schema `0.1.x EXPERIMENTAL` · Implementation `CANDIDATE` · `NO-GO FOR SCHEMA FREEZE`

本文件把 bundle 外的独立 candidate.5 acceptance 纳入 frozen release lineage。它不改写
candidate.1–5 的任何提交、receipt、archive 或 review，也不把 logical architecture freeze 扩大为
Schema、production、remote、真实个人数据或加密门的批准。

## 1. Independent record

```text
Reviewer: /root/af09_reviewer_retry
Reviewer role/independence: same independent reviewer as candidate.1–4;
  did not author candidate.5 or this promotion
Accepted candidate: 1.0.0-candidate.5
Accepted candidate manifest SHA-256:
  ece90366e5e3e3647af729351d8ae80310c8f6c30db1cf85b5a74ccb4168ed64
Accepted candidate archive SHA-256:
  aa56033be8380eee9289baec11c7839cbaa9bde4d66f69c6757fd9fb651ff668
Accepted candidate external receipt SHA-256:
  2f8189339b6ee5b45107cee93c67005c1051171810913014631b1bd8c9aed680
Independent review record:
  docs/reviews/AF-09-independent-rereview-candidate.5-2026-08-17.md
Independent review SHA-256:
  8ddf9e8a302b46404319ef2b27d99403f73b4d71127b4483c3b333d27230d1f3
Decision: ACCEPT
Findings: AF09-F01 through AF09-F12 CLOSED; no open P0/P1/P2
```

The independent review recorded the candidate manifest before and after review as the same digest.
Its sole repository write was the review record. The release source locks include that record, the
accepted candidate manifest, archive and receipt, so promotion cannot substitute a different
candidate.

## 2. Accepted evidence

| Check | Independent result |
| --- | --- |
| Candidate archive safety and live identity | PASS — 175 sorted, unique, safe regular files; zero byte differences |
| Architecture validator / external all-scope lock / tests | PASS — 19 tests |
| Fresh exact-role PostgreSQL base → 0026 | PASS — 121 tests |
| Migration foundation | PASS — 33 tests |
| F12 fresh timestamp conflicts | PASS — four cases remain 0023, stable error, zero residue |
| F12 candidate.3-compatible conflicts | PASS — four cases remain 0024, unchanged prior state |
| F12 candidate.4-compatible conflicts | PASS — four cases remain 0025, unchanged prior state |
| Six-equal-time control | PASS — only valid control advances to 0026; no authority/schema/event/outbox delta |
| Exact F11 missing DeletionRequest | PASS — remains 0023; zero new authority/residue |
| F01 rejected grounding / real Issue and Context absence | PASS |
| F02–F10 regression audit | PASS |
| Backup/security/catalog/RLS | PASS — 6 tests; 32 durable / 31 tenant tables |
| Research/package/install/CI/Compose/docs | PASS |
| Residual synthetic-only and real-data boundary | ACCEPTED AS DECLARED |

## 3. Frozen gate matrix

| Gate | Decision | Evidence boundary |
| --- | --- | --- |
| AF-00 Baseline | PASS_FROZEN | versions, licenses, source/Git identity |
| AF-01 Objects | PASS_FROZEN | identity, owner, mutability, authority |
| AF-02 Invariants | PASS_FROZEN | G1–G9 and I-01–I-12 machine mapping |
| AF-03 Permissions | PASS_FROZEN | exact roles, grants, RLS, credential isolation |
| AF-04 Transactions | PASS_FROZEN | TX/EP, CAS, atomic history/outbox, populated migrations |
| AF-05 Retrieval/Context | PASS_FROZEN | ECS Gate, OpenIssue protection, lineage |
| AF-06 Delete/Recovery | PASS_FROZEN | governed revoke, proof-bound purge, backup/restore |
| AF-07 Isolation | PASS_FROZEN | external/model/audit cannot gain canonical authority |
| AF-08 Operations | PASS_FROZEN | runbooks, forward repair, privacy boundary, locks |
| AF-09 Lock Review | ACCEPTED_INDEPENDENT_REVIEW | exact candidate.5 review above |

## 4. Findings disposition

Candidate.1 opened AF09-F01–F10. Candidate.2 closed F03–F10; candidate.3 closed F02 but exposed F11;
candidate.4 closed F01 and exact F11 but exposed F12. Candidate.5 closed F12 without weakening any
prior predicate. The same reviewer independently replayed the exact counterexamples and closed
F01–F12. No deferred P2 exists.

## 5. Release trust and immutability

The release manifest does not self-lock. A bundle-external release receipt supplies its trusted
SHA-256 and deterministic release archive identity. Verification MUST run:

```bash
runtime/.venv/bin/python architecture/v1.0/scripts/validate_bundle.py
runtime/.venv/bin/python architecture/v1.0/scripts/verify_lock.py \
  --scope all --mode release \
  --expected-manifest-sha256 "$TRUSTED_RELEASE_MANIFEST_SHA256"
MILAI_ARCHITECTURE_LOCK_SCOPE=all runtime/.venv/bin/python -m unittest discover \
  -s architecture/v1.0/tests -v
```

Missing/mismatched external digest, source/Git drift, coordinated bundle+manifest substitution,
candidate lineage mismatch, or loss of independent ACCEPT invalidates the release verification.

After publication, `architecture/v1.0/` is immutable. Any change to G/I, object identity, roles,
permissions, transaction semantics or locked evidence requires a new architecture version and a new
independent review; this directory must not be edited in place.

## 6. Current result

```text
Reviewer: /root/af09_reviewer_retry
Decision: ACCEPT
AF-09: ACCEPTED_INDEPENDENT_REVIEW
Logical architecture: 1.0.0 FROZEN
Schema: 0.1.x EXPERIMENTAL
Implementation: CANDIDATE
Schema freeze: NO-GO
```

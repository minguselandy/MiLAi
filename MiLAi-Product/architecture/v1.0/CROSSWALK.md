# MiLAi Architecture Crosswalk

> Architecture `1.0.0 FROZEN`  
> Schema `0.1.x EXPERIMENTAL` · Implementation `CANDIDATE` · `NO-GO FOR SCHEMA FREEZE`

本文件是便于评审的人类视图；`crosswalk.json` 是机器真源。验证器要求每个 G/I 都至少映射到
design、schema/code、test 和 report，且引用路径存在。

## 1. Goal summary

| Goal | Primary implementation evidence | Primary test/report evidence |
| --- | --- | --- |
| G1 Source Fidelity | migrations 0003–0005；Evidence service；canonical repository | Evidence/API tests；DG-03/DG-04 |
| G2 Governed Evolution | migrations 0004–0005/0015–0016/0024–0026；proposal/Steward procedures | fresh + populated creation history、legacy pre-Decision/TX-05 reconciliation、six-time certification、rejected-grounding removal、noncanonical proposal、CAS/rollback/fail-closed tests；candidate.5 remediation |
| G3 Open-State Preservation | migrations 0005/0015/0024–0025；OpenIssue repository/procedures | issue create/reject/resolve/reopen/race、populated continuous replay、real Issue/Context rejected-branch absence tests；DG-05/remediation |
| G4 Applicability Separation | migrations 0004/0008/0015/0017/0021；ECS-only Gate | exhaustive domain mapping、all-axis/bitemporal Gate tests；remediation |
| G5 Candidate-Safe Retrieval | migrations 0007/0008/0012/0014/0017/0018/0020/0021；retrieval/causality | projection、all-axis Gate、causal wait/fallback/snapshot tests；remediation |
| G6 Revocation Propagation | migrations 0006/0010/0016/0019/0021–0026；deletion/backup | governed + actual-DeletionRequest-backed legacy TX-05、identity/state/nine-leg + four timestamp rollback、0026 certification、purge/erasure-proof/restore tests；remediation |
| G7 Bounded Traceable Context | migrations 0009/0013；context/chat | context budget/pointer/confirmation tests；DG-08 |
| G8 Least Privilege | migrations 0002/0020；database exact-role/session boundary | owner/role-swap/unsafe-attribute/RLS/Outbox denial tests；DG-02/remediation |
| G9 Replaceable/Recoverable | migrations 0001/0007/0010/0024–0026；worker/backup/adapters | fresh/candidate.3/candidate.4 compatible forward migration、prior-head fail-close、two-ledger backup、worker/isolation tests；DG-01/DG-09/candidate.5 |

## 2. Invariant ownership

| Invariant | Owner plane | Main enforcement |
| --- | --- | --- |
| I-01 | Evidence/Canonical | separate tables and governed create/revision procedures |
| I-02 | Evidence | immutable capture + idempotency fingerprint |
| I-03 | Security/Governance | grants/RLS + Steward execute boundary + offline provenance-only migration boundary |
| I-04 | Canonical/Governance | append-only grants/validated constraints/procedures + fresh/populated sentinels + immutable non-authoritative quarantine |
| I-05 | Canonical/OpenIssue | exact-head and expected-revision CAS |
| I-06 | OpenIssue | conflict procedure and preserved branch grounding |
| I-07 | Retrieval/Canonical | ECS as sole source for every Gate/Context decision fact |
| I-08 | Retrieval/Adapters | canonical ID resolution + Gate |
| I-09 | Domain/Gate | typed orthogonal fields and explicit matching |
| I-10 | Deletion/Context | governed synchronous block/invalidation + proof-bound purge workflow |
| I-11 | Security | tenant column, forced RLS, exact runtime roles, scoped sessions |
| I-12 | Transactions/Trace | atomic governance/event/outbox, populated-repair transaction, causal position and answer lineage |

## 3. Transaction coverage

| Protocol | Primary implementation |
| --- | --- |
| TX-01 | migration 0003；evidence application/repository/API |
| TX-02/03/04/06 | migrations 0004–0005/0015/0024–0025；canonical repository/proposal routes and populated history/grounding reconciliation |
| TX-05 | migrations 0006/0016/0019/0021–0026；deletion application/repository/API/worker and actual-request/six-time multi-leg proof |
| EP-01/02 | migration 0011；episode application/repository/API |

## 4. Freeze gate snapshot

| Gate | Frozen status | Meaning |
| --- | --- | --- |
| AF-00 Baseline | PASS_FROZEN | inputs and local dependency identity captured |
| AF-01 Objects | PASS_FROZEN | object/owner/mutability catalog present |
| AF-02 Invariants | PASS_FROZEN | machine crosswalk present and validated |
| AF-03 Permissions | PASS_FROZEN | role/grant/RLS contract and current tests mapped |
| AF-04 Transactions | PASS_FROZEN | TX/EP/CAS/rollback/outbox mapped |
| AF-05 Retrieval/Context | PASS_FROZEN | QueryPlan/Gate/protected context/trace mapped |
| AF-06 Delete/Recovery | PASS_FROZEN | sync block, purge, backup and restore mapped |
| AF-07 Isolation | PASS_FROZEN | external/model credential boundary mapped |
| AF-08 Operations | PASS_FROZEN | runbooks/reports/manifest evidence mapped |
| AF-09 Lock Review | ACCEPTED_INDEPENDENT_REVIEW | candidate.5 exact bytes independently ACCEPTED；F01–F12 closed；no P0/P1/P2 finding |

`PASS_FROZEN` 表示该 gate 已进入本 release 的锁定证据；AF-09 的 `ACCEPTED_INDEPENDENT_REVIEW`
来自 bundle 外的 exact candidate.5 review，不由作者或 validator 自签。

## 5. Usage

```bash
python architecture/v1.0/scripts/validate_bundle.py
python architecture/v1.0/scripts/verify_lock.py --scope all --mode release \
  --expected-manifest-sha256 "$TRUSTED_RELEASE_MANIFEST_SHA256"
python -m unittest discover -s architecture/v1.0/tests -v
```

变更任何规范、ADR、映射或被锁定源文件后都必须刷新 `architecture_manifest.json`，并重跑以上命令
以及对应 runtime regression gates。

# DG-00 — MiLAi Logical Architecture Candidate.4 Gate Report

> Architecture：`1.0.0-candidate.4`  
> Date：`2026-08-17`（Asia/Shanghai）  
> Author gate：`PASS — READY FOR INDEPENDENT REREVIEW`  
> AF-09：`PENDING_INDEPENDENT_REVIEW`  
> Freeze：`NO-GO FOR SCHEMA FREEZE`

## Scope

本报告记录 candidate.3 独立复审后 AF09-F01/F11 的 candidate.4 作者门禁。它不修改 candidate.1–3
的 review/archive/receipt，也不构成独立 ACCEPT。Candidate.4 的规范差异由 ADR-018、corrected
0024、compatibility head 0025、第二个 immutable legacy ledger 及直接 populated/adversarial tests
组成。

本报告是作者证据快照，不关闭 finding。精确 submission identity 只能在本报告也被 source-lock
之后由 bundle 外 receipt 记录，避免 candidate 自我声明成为 trust anchor。

## Candidate.4 semantic delta

1. rejected candidate.1 resolution grounding 在 exact support-set proof 后全字段/hash 隔离并从
   canonical Issue/Context 路径移除；真实 APPROVE 链才允许保留；
2. legacy TX-05 reconstruction 必须 join durable DeletionRequest 和其余八类一致 provenance；
3. fresh bad 0014 input 在 corrected 0024 内整体回滚到 0023；already-applied candidate.3 开发库由
   0025 兼容，无法证明则保持 0024；
4. durable catalog 为 32 tables（31 tenant-owned），两个 legacy quarantine ledger 均进入 backup
   inventory；
5. Candidate 仍是 synthetic-only、experimental、NO-GO，等待同一独立 reviewer。

## Gate results

```text
runtime Ruff format/check                                  PASS (104 files)
runtime strict mypy                                        PASS (55 source files)
runtime real exact-role PostgreSQL suite                   PASS (108 tests; clean database)
fresh empty database base → 0025                           PASS
populated candidate.1 resolution grounding                PASS (pending/reject/approve/fail-close)
populated candidate.1 legacy TX-05                         PASS (valid + nine corrupt proof legs)
candidate.3-compatible 0024 → 0025                         PASS (valid + missing-request block)
catalog/head/RLS                                           PASS (32 durable / 31 tenant / forced RLS)
backup/restore exhaustive inventory                       PASS (both quarantine ledgers)
runtime wheel/sdist double build                           PASS (byte-identical; 63 / 119 entries)
locked dependency install / Compose interpolation          PASS
research Ruff / strict mypy / unittest                     PASS (8 Python files / 7 source / 9 tests)
research deterministic equal-budget fixture                PASS (40 fixtures; novelty ABANDONED)
critical Markdown links/fences                             PASS (74 documents)
architecture validator / all-scope lock / bundle tests     RECORDED IN EXTERNAL RECEIPT AFTER FINAL LOCK
```

Package identities from either independent `uv build` output:

```text
wheel SHA-256  d00a624777e3876a499610356b319481599e418db07b5afe5d991e2ba4c33652
sdist SHA-256  3b3663aaead040ef3a855f42eb1ccae0382d4c760dff9338cc6d59ee777ad26e
wheel entries  63
sdist entries  119
duplicate paths / absolute paths / parent traversal  NONE
```

## Development-database boundary

The pre-existing `milai` development database is intentionally retained as a forensic negative sample. It
is at candidate.3 revision `0024_legacy_history_reconcile` and contains 134 candidate.1-style revoke events,
four of which have no actual DeletionRequest because earlier adversarial tests deleted them. Candidate.4 0025
correctly refuses that source with `AF09_UNPROVABLE_LEGACY_TX05`; no row was fabricated or deleted to make the
upgrade green. All acceptance gates ran on fresh `milai_candidate4_gate_20260817b`, which reached 0025 and
reported 32 durable / 31 tenant-owned tables. The forensic database is supplementary evidence, not the clean
gate environment.

## Submission identity

```text
Manifest SHA-256: supplied only by bundle-external candidate.4 receipt
Archive identity: supplied only by bundle-external candidate.4 receipt
External receipt: generated after final manifest/source lock
Independent reviewer: same reviewer assigned
Independent decision: PENDING
```

The author does not convert `PENDING_INDEPENDENT_REVIEW` to ACCEPT. Review mode must receive the external
manifest digest, reproduce archive/live/source identity, rerun the gates, replay F01/F11 counterexamples and
audit F02–F10 for regression.

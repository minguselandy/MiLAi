# DG-00 MiLAi Logical Architecture candidate.3 Evidence Report

> Date：2026-08-17（Asia/Shanghai）  
> Architecture：`1.0.0-candidate.3`  
> Schema：`0.1.x EXPERIMENTAL`  
> Implementation：`CANDIDATE`  
> Freeze：`NO-GO / AF-09 PENDING_INDEPENDENT_REREVIEW`

## Scope

This is the candidate.3 author evidence snapshot. It preserves the immutable candidate.1 review and
candidate.2 submission/rereview, whose exact decision was `REVISE` with AF09-F01/F02 still open. It covers
the populated candidate.1 governance-history reconciliation added in migration
`0024_legacy_history_reconcile`; it does not constitute independent acceptance.

## New evidence plane

- provenance-first, fail-closed V1/OpenIssue creation-history backfill;
- immutable, tenant-scoped quarantine of exact candidate.1 pre-Decision Issue rows with recomputable SHA-256;
- policy-REJECT and CAS reversal of pending pre-Decision resolution effects without fabricated approval;
- linkage to an actual Decision for already-decided legacy resolution effects;
- four-way immutable proof and normalized governance reconstruction for candidate.1 TX-05;
- validated Issue governance/revision and Version creation constraints, continuous replay postconditions and
  per-version/per-Issue-revision uniqueness;
- quarantine table added to least-privilege permissions and backup/restore catalog.

ADR-017 defines the normative semantics. The three populated migration tests use public candidate.1
procedures at revision 0014, not hand-inserted happy-path rows.

## Verification snapshot

```text
runtime Ruff format/check                              PASS (103 files)
runtime mypy strict                                    PASS (57 source files)
runtime real exact-role PostgreSQL suite               PASS (95 tests)
fresh empty database base → 0024                       PASS
populated candidate.1 0014 → 0024                      PASS (3 direct regressions)
architecture validation/full lock/tests                PASS (19 tests)
research Ruff/strict-mypy/isolated suite               PASS (11 files / 7 sources / 9 tests)
research equal-budget fixtures                         PASS (40)
runtime wheel/sdist reproducibility                     PASS (two fresh builds byte-identical)
locked dependency install / Compose interpolation      PASS
critical Markdown link/fence audit                     PASS (24 documents)
```

Package identities from either reproducible build:

```text
wheel  SHA-256 253fb6ede6b22fe142972990c78b71b59ad0083c9723cbaef8429a3d83bf714d
sdist  SHA-256 93d9f6bd9eef48b0d50512241a352aed6134ba8d0bcd80885d22248e9ef90273
wheel entries 63; sdist entries 118; unique/safe-path/content checks PASS
```

The exact manifest digest, deterministic archive digest and final commands belong in the external
candidate.3 submission receipt. Review/release mode must fail without that external trust anchor.

## Observed nonempty development migration

The existing nonempty local development database upgraded from 0023 to 0024 with these postconditions:

```text
canonical OpenIssue transitions                 210
canonical transitions with NULL governance       0
quarantined exact legacy transitions             55
quarantine rows whose SHA-256 recomputes          55
ck_issue_transition_governed validated          true
Issues with incomplete revision replay             0
```

This observation is supplementary. Temporary-database populated regressions are the repeatable acceptance
evidence and the same independent reviewer must rerun them.

## Decision boundary

Candidate.3 remains synthetic-local only. Plaintext Blob/real-data, remote/public deployment, host-root and
performance gates are unchanged. No report, author preflight or passing automated test may change AF-09 from
`PENDING_INDEPENDENT_REVIEW`; only an independent decision on the exact receipt-anchored bytes can do so.

# DG-00 Architecture Candidate.5 Gate Report

> Status: `AUTHOR GATE PASS — NOT AF-09 ACCEPTANCE`  
> Architecture: `1.0.0-candidate.5`  
> Date: `2026-08-17`（Asia/Shanghai）  
> Freeze: `NO-GO FOR SCHEMA FREEZE`

## Outcome

Candidate.5 is the bounded remediation for independent P1 AF09-F12. It does
not expand the Lean V1 product surface or add an external memory dependency.
It completes legacy TX-05 transaction-time proof and adds a compatibility
certification head for development databases already at candidate.4/0025.

The complete author engineering gate passed. The manifest, archive and
external receipt are generated only after this report is source-locked, and
the same reviewer must still reproduce the evidence. Author PASS is not an
AF-09 decision.

## Implemented delta

1. ADR-019 defines one exact durable TX-05 transaction-time anchor.
2. Corrected 0024/0025 prove all six time fields before authority
   reconstruction and retain the earlier actual-request/identity/state proof.
3. 0024's reconstruction selector repeats the time predicate.
4. New proof-only `0026_legacy_tx05_time_guard` validates already-applied
   candidate.4 state without creating tables or replacement authority.
5. Four named fresh negatives plus 0024 and 0025 compatibility matrices use
   candidate.1 public procedures and one-second single-leg corruption.
6. Design, contracts, runbooks, bundle, threat model, and crosswalk are updated
   without modifying immutable candidate.1–4 submission history.

## Current direct evidence

```text
runtime Ruff format/check                                    PASS (105 files)
runtime strict mypy                                          PASS (57 source files)
fresh base -> 0026 exact-role PostgreSQL suite               PASS (121)
new timestamp/compatibility PostgreSQL nodes                 PASS (13)
complete migration foundation PostgreSQL file               PASS (33)
backup/security/catalog/RLS                                  PASS (6; 32 / 31 tables)
research Ruff/mypy/tests/reproduction                        PASS (7 / 9 / 40)
runtime wheel/sdist double build                             PASS (63 / 120 entries)
locked wheel install / CI YAML / Compose                     PASS
Markdown relative-link/fence audit                           PASS (79 files; 0 errors)
architecture final lock/archive/external receipt             RECORDED EXTERNALLY
same independent reviewer                                    PENDING
```

The byte-identical package identities are wheel
`149eb1ec203cb3c9751e351a2a4c18be1609c9e53598bdc55c05e25965d9a8ff`
and sdist
`d454cdd6ee4d65aec58566debec6a0023524bde5ef8ee96172021d91eae8a59b`.
The clean acceptance database was `milai_candidate5_gate_20260817a`; the
forensic `/milai` database was not reset or repaired.

## Compatibility and data policy

Bad fresh, candidate.3-compatible, and candidate.4-compatible inputs remain at
0023, 0024, and 0025 respectively. No migration fabricates a missing
DeletionRequest or rewrites the four timestamps to make them agree. The
existing main development database remains forensic input and is not reset to
obtain a green gate; candidate.5 acceptance uses a fresh exact-role database.

Migration 0026 creates no durable table, so the expected head catalog remains
32 durable / 31 tenant-owned tables. Both quarantine ledgers remain covered by
backup inventory, forced RLS, and append-only controls.

## Remaining independent gate

The explicitly reviewed source-lock set is finalized after this report, then
the deterministic candidate.5 archive and bundle-external receipt identify
the frozen candidate bytes. The same independent reviewer must independently
replay AF09-F12 and every prior closure. Only an exact `ACCEPT` permits a
separate `architecture/v1.0/` frozen release.

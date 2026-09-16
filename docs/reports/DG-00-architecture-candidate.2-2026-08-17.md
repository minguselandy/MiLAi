# DG-00 MiLAi Logical Architecture candidate.2 Evidence Report

> Date：2026-08-17（Asia/Shanghai）  
> Architecture：`1.0.0-candidate.2`  
> Schema：`0.1.x EXPERIMENTAL`  
> Implementation：`CANDIDATE`  
> Freeze：`NO-GO / AF-09 PENDING_INDEPENDENT_REREVIEW`

## Scope

This report supersedes the candidate.1 author evidence snapshot for the candidate.2 submission; it does not
alter the immutable candidate.1 independent review. It covers AF09-F01–F10 remediation, migration head 0023,
the architecture crosswalk and external manifest trust-anchor protocol.

## Implemented evidence planes

- governed proposal/review and complete creation history (`0015`);
- governed TX-05 (`0016`);
- authoritative, axis-complete ECS/Gate (`0017`, `0021`);
- persistent causal wait facts and narrow position API (`0018`, `0020`);
- verified Blob absence proof and forward SHA-256 repair (`0019`, `0021`–`0023`);
- exact API/Steward/Worker database-role attestation;
- candidate.2 external trust-anchor and coordinated-substitution negative tests.

## Verified snapshot before bundle submission

```text
PostgreSQL 16 / pgvector runtime suite             PASS (92 tests)
runtime Ruff format/check                          PASS (101 files)
runtime mypy strict                                PASS (55 source files)
fresh empty database forward migration to 0023    PASS
deployed candidate.1 forward repair to 0023        PASS
architecture bundle validation/full lock/tests      PASS (19 tests; pre-final receipt)
research Ruff/strict-mypy/isolated suite            PASS (8 source files / 9 tests)
Markdown link/fence audit                           PASS (19 critical documents)
```

Two consecutive package builds were byte-stable:

```text
wheel  SHA-256 30cceb2a1101138601e6a46bcde40d089faf185382a99be2a622a97b8ce7c951
sdist  SHA-256 93310c3f37be9b9767f2855779f1aa05a9606417080cb5806c4e90456c3c144a
```

The final manifest SHA-256, archive SHA-256, exact commands and post-lock results belong in the external
candidate.2 submission receipt. Review/release verification without that external digest must fail.

## Decision boundary

The architecture candidate is ready for independent re-review only after its final lock passes. Architecture
freeze is not schema freeze: plaintext Blob/real-data and remote-access gates remain denied under ADR-012 and
the threat model. No line in this report authorizes real personal data or production deployment.

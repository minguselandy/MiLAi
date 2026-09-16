# AF-09 Remediation — Candidate.5

> Status: `AUTHOR REMEDIATION COMPLETE — READY FOR INDEPENDENT REREVIEW`  
> Candidate: `1.0.0-candidate.5`  
> Date: `2026-08-17`（Asia/Shanghai）  
> Schema: `0.1.x EXPERIMENTAL`  
> Freeze: `NO-GO FOR SCHEMA FREEZE`

## Immutable predecessor identity

Candidate.4 remains identified by:

- manifest SHA-256:
  `13d0a948daa0b9907fd8fc6d7142c6565f8afd3672471c1da2ed5814a5af57eb`;
- archive SHA-256:
  `03ca6b686f21afacccb0a31ca9892ca2854a8a395d402adc26fb6374e36ec341`;
- external receipt SHA-256:
  `7edc99c4ab4ddd682cd50cc5b49cefe9edb34700c60c7d52bc5474887100dd5f`;
- independent rereview SHA-256:
  `ed7f4ff514f8b7c41eb345fe4c2d568b34f6df4260d74c1eaaa33341fe25ec21`.

The independent decision is `REVISE`. This record does not alter that decision
or any candidate.1–4 review, archive, receipt, remediation, or report.

## Finding addressed

| Finding | Independent counterexample | Candidate.5 change | Required outcome |
| --- | --- | --- | --- |
| AF09-F12 (P1) | Shifting `created_at` by one second on the candidate.1 TX-05 idempotency record, original OperationalEvent, revoke Outbox, or purge Outbox still let 0024/0025 reconstruct `APPLIED` Proposal + `STEWARD APPROVE` Decision | ADR-019; exact six-time predicate in corrected 0024/0025; same predicate in 0024 reconstruction query; proof-only compatibility migration 0026; four named fresh negatives and two four-case compatibility sets | Any missing/conflicting time leg raises `AF09_UNPROVABLE_LEGACY_TX05`; fresh, candidate.3-compatible, and candidate.4-compatible inputs remain at 0023, 0024, and 0025 respectively, with no new migration authority/residue |

Candidate.4's independent review closed AF09-F01 and confirmed the exact
missing-DeletionRequest AF09-F11 counterexample was repaired. Candidate.5 does
not ask the author to reopen or self-close those findings; the same reviewer
must confirm there is no regression.

## Normative implementation

Candidate.1 `milai.tx05_revoke_evidence` uses PostgreSQL
`CURRENT_TIMESTAMP`, which is fixed at transaction start. The durable source
time is therefore:

```text
DeletionRequest.requested_at
= EvidenceRecord.revoked_at
= IdempotencyRecord.created_at
= EVIDENCE_REVOKED OperationalEvent.created_at
= EVIDENCE_REVOKED OutboxEvent.created_at
= PURGE_EVIDENCE_DERIVATIVES OutboxEvent.created_at
```

Corrected 0024 and 0025 require exact equality while holding source tables
under `ACCESS EXCLUSIVE` locks. Time proximity, ordering, rounding, or shared
UUIDs do not qualify. Migration 0026 repeats the complete proof for a database
already at candidate.4/0025 and performs no table or authority write.

All paths use stable `AF09_UNPROVABLE_LEGACY_TX05`. An invalid 0025 database
keeps its prior candidate.4 reconstructed facts only as forensic state; it does
not receive the candidate.5 head and must not serve the candidate.5 runtime.

## Direct executable evidence

Real candidate.1 public-procedure fixtures cover:

- four individually named fresh 0014→head timestamp conflicts;
- four candidate.3-compatible 0024→0025 timestamp conflicts;
- four already-applied candidate.4 0025→0026 timestamp conflicts;
- one valid six-leg 0025→0026 control;
- all earlier identity/state/missing-row/grounding/Issue/Context regressions.

Complete author execution:

```text
new F12 timestamp and compatibility nodes              13 passed
complete migration foundation file                     33 passed
fresh base -> 0026 exact-role runtime suite            121 passed
runtime Ruff / strict mypy                              105 / 57 files
backup/security and catalog/RLS                         6 passed; 32 / 31 tables
research isolation                                      7 source / 9 tests / 40 fixtures
double package build                                    byte-identical; 63 / 120 entries
wheel / sdist SHA-256                                   149eb1ec... / d454cdd6...
locked wheel install                                    milai-runtime 0.1.0
CI YAML / Compose / Markdown audit                      PASS; 79 files / 0 errors
```

The exact-role runtime, research, package, Compose, documentation, and
backup/security gates above are actual executions. The final architecture
lock, deterministic archive, and external receipt necessarily follow this
source-locked author record and are recorded in the bundle-external receipt;
they are not inferred here. None of these author results is an AF-09 decision.

## Migration and recovery contract

- Fresh candidate.1 corruption: 0024 transaction rolls back; head remains
  `0023_erasure_sha256_repair`; no 0024 ledger/authority residue.
- Candidate.3-compatible corruption: 0025 transaction rolls back; head remains
  `0024_legacy_history_reconcile`; no 0025 schema/event residue.
- Candidate.4-compatible corruption: proof-only 0026 rolls back; head remains
  `0025_legacy_provenance_guard`; no 0026 authority or certification.
- Valid input: one head `0026_legacy_tx05_time_guard`; durable catalog remains
  32 total / 31 tenant-owned tables.
- Downgrade is intentionally unsupported; fabrication, deletion of forensic
  rows, or forced Alembic advancement is prohibited.

## Independent handoff requirement

Candidate.5 may be submitted only after a new manifest, deterministic archive,
and bundle-external receipt identify its exact bytes. The same independent
reviewer must reproduce F12 across all three proof shapes, replay F01/F11 and
all prior closures, and rerun the complete AF-09 checklist. Until an exact
candidate.5 `ACCEPT` exists:

```text
Implementation CANDIDATE
Schema 0.1.x EXPERIMENTAL
NO-GO FOR SCHEMA FREEZE
```

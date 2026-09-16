# OE-07 candidate.2 remediation evidence

Decision: `IMPLEMENTATION CANDIDATE — LOCAL REMEDIATION GATES PASS; PROVIDER GATE OPEN`  
Date: `2026-08-18` (Asia/Shanghai)  
Boundary: synthetic/de-identified local evaluation; Runtime `0.1.x CANDIDATE`; Schema
`0.1.x EXPERIMENTAL / NO-GO`

## Independent-review findings

This candidate responds to the complete findings in
`docs/reviews/OE-07-independent-review-2026-08-18.md`; it does not reinterpret the shorter
candidate.1 summary as erasing valid findings from the full review.

| Finding | Candidate.2 disposition | Executable evidence |
| --- | --- | --- |
| OE-F01 cache binding/public override | **CLOSED locally** | running lifecycle now uses the Router cache key; Slot binds query/goal/scope/authority/consistency/limit/canonical position/semantic Issue digest/compiler/tokenizer/all budgets/constraints/TTL. Public sync/async `cache_validated` parameters were removed. Old checkpoints fail closed. Independent-leg, expiry, sync, async, Hook and AutoGen tests pass. |
| OE-F02 Hook event policy override | **CLOSED locally** | Hook recall and budget policy is environment-owned; stdin overrides are rejected. Cross-process checkpoint under a changed host Scope performs L1 again. |
| OE-F03 `request_id` cache instability | **CLOSED locally** | validated semantic OpenIssue projection excludes request/transition metadata while retaining governed identity, type, live status, revision, scope, discharge, authority and sorted branches. A changing real-shaped `request_id` now remains CACHE; revision changes do not. |
| OE-F04 weak OpenIssue validation | **CLOSED locally** | compiler rejects resolved status, negative revision, target mismatch, empty discharge/branches, unknown relation and incomplete Issue. Runtime ContextCapsule now supplies Issue revision plus all governed fields at every compression tier. |
| OE-F05 UUID route/transport mismatch | **CLOSED locally** | one explicitly typed Claim UUID carries `exact_claim_id` and uses `recall_exact` in sync, async and AutoGen paths. OpenIssue UUID and ambiguous/multiple UUID input remain governed L1. |
| OE-F06 provider/billing/quality proof | **OPEN — EXTERNAL** | no provider credentials/account or approved target model are present. Offline metrics keep usage, extra model rounds and end-to-end model wall time null/unverified. Candidate is not promoted to Beta. |
| OE-F07 cwd/raw scale reproducibility | **CLOSED locally** | Alembic paths are absolute; unit test and both full scale attempts launch from `/tmp`; raw JSON is retained and inventory-bound. |

## Cross-layer defect found during remediation

The first candidate.2 three-session run failed because Runtime ContextCapsule omitted OpenIssue
`revision`. The SDK integrity gate was not weakened. Runtime's context repository and minimal
projection were corrected to carry `issue_type`, `revision`, `scope_predicate` and
`required_authority` together with identity, branches and discharge. A fresh exact-role Runtime run
and a fresh three-session Agent E2E then passed.

## Current gates

| Gate | Result |
| --- | --- |
| Runtime fresh exact-role PostgreSQL | **152/152 PASS** in 139.04 s; cleanup zero connections and drop PASS; report SHA-256 `dff77550aa6aac51ddfbd4f64500de0166dcc88084bffffd0e1e261a4c4c2464` |
| Agent three-session E2E | **PASS**, three phases, no hard failures, cleanup PASS; report SHA-256 `d3d60da210a096b24d00e62bdff16eb5d5aa3be4a67a4af016fa8da771dbd9ad` |
| Package tests | SDK 76, MCP 9, LangGraph 4, AutoGen 6, Hook 6, offline benchmark 4; Ruff/format/mypy PASS |
| Frozen architecture | validate and release-mode external anchor PASS; 19 adversarial tests PASS with one expected bundle-scope Git skip |
| PostgreSQL scale | first retained contested attempt FAIL; separate no-parallel-MiLAi retry PASS at 10k L0/L1 p95 `20.819/33.596 ms`, 100k measured, cleanup PASS |
| Offline 100-turn regression | 10,280 evaluation tokens versus 70,800 baseline, 85.48% reduction, 20 logical recalls; zero provider calls and provider/model fields remain unverified/null |
| Package artifacts | six wheels/sdists rebuilt; manifest SHA-256 `d31ce50ee96fc7a45087e6a719a3c5aede1eb1b277db1521e1d34ffeaa557e9f` |
| Clean install | six fresh venvs, isolated import and PEP 561 **PASS**; report SHA-256 `92652d09fe7086111cd4401752a63e63db545d517a71c1d6ea0f9cde8815504d` |
| Archive/secret safety | 346 files plus 296 unpacked archive members; zero secret match, forbidden member or unsafe archive; release-safety 8/8 PASS |
| Examples | Generic, MCP, LangGraph and AutoGen smoke **4/4 PASS** |
| OSPC isolation | Ruff/mypy and 9 tests PASS |

## Acceptance boundary

Candidate.2 is ready for an independent code/security re-review of OE-F01–F05/F07. OE-F06 cannot
be closed by local synthetic evidence. A Beta request additionally needs an approved target
provider/model A/B with provider-native request identity and usage, pricing reconciliation, actual
model-round and end-to-end wall time, post-ready first-query measurement, and same-task quality and
safety scoring. Until then the defensible status remains `Optimization Candidate`.

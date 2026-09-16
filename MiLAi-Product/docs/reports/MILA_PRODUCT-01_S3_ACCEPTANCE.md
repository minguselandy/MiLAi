# MiLA Product-01 S3 acceptance

Date: 2026-09-01  
Stage: S3 — local-ready product experience  
Result: **PASS**

## Frozen run identity

- Product behavior commit: `126ca08b3b4b15e17f3b5fad777022f0c6a05d0b`
- Product behavior tree: `c4841be0b637ddf56d35cf2fbab2a9ee15bc26b2a26e46eda7d6e7d38578e30e`
- Lab Product lock digest: `36fc1680ab93c9b5c25c91009fad6f256ea915852584c5e1ff1d880923f5bd1c`
- Final Lab artifact: `MiLAi-Lab/artifacts/product01-s3-20260901-002`
- Run ID: `product01-s3-20260901T140413Z`
- Selected configuration: B1 through one explicit flag; Product default remained OFF.

## Golden flow and exit gate

The isolated persistent stack completed capture, searchable Raw Evidence, Runtime/worker restart,
new-session recall with source, reviewed Canonical create, reviewed correction, two-version history,
logical revoke, derived purge, primary erasure, and post-deletion restart persistence.

| Metric | Required | Observed |
| --- | ---: | ---: |
| Golden flow | PASS | PASS |
| 24-case product task success | >= 0.90 | 23/24 = 0.9583 |
| 100-request typed terminal rate | 1.0 | 100/100 = 1.0 |
| Read-after-write searchable P95 | <= 5 s | 1.047 s |
| Retrieval + Context P95 | <= 2 s | 55.05 ms |
| Warm memory-control P95 | <= 500 ms | 16.54 ms |
| Model-outage deterministic fallback | 1.0 | 1.0 |
| Scope/permission/revocation/deletion leak | 0 | 0 |
| Canonical mutation from read path | 0 | 0 |
| One feature flag restores repaired baseline | 1.0 | 1.0 |

Four persistent restarts ran during the gate. One disabled
`MILAI_RETRIEVAL_TYPE_DIRECTED_ACQUISITION_ENABLED`; the baseline trace had no enriched probe. The
selected configuration was then restored without changing the default.

The sole unsuccessful scenario was a role-free assistant answer: Raw retrieval returned the exact
source in a typed `HIT`, but grounded Binding stayed `PARTIAL`. It is recorded as a bounded recall
limitation, not converted into success, retry, or system failure.

## Artifact integrity

| File | SHA-256 |
| --- | --- |
| `run.json` | `27399355bd18893ab525c77c8d9440a6b111a943187659dccbdb7e413eba8e68` |
| `cases.jsonl` | `eb3c76cc791ef23a46e5eae547fdbe37dc002cee488f3c6497d591be34ff80f0` |
| `metrics.json` | `57c37d2a78863ac254dfc6a4f309e7fef27b1430496f6a817aa53abd46465b1b` |
| `terminal.json` | `94f1f283fab67a9501eaa5b2d46a4be37e910148983834800372cb187c1e0933` |

The preceding `-001` run passed at 22/24 but exposed a scorer mismatch: Product's correct typed
`ABSENT / NO_CANDIDATE` terminal was not recognized. The scorer was repaired and `-002` reran on a
fresh database. No Product behavior changed between those runs.

## Final Product matrix

- Fresh exact-role Runtime: `743 passed, 1 declared optional skip`.
- Runtime Ruff / strict mypy / wheel+sdist: PASS (`161` typed source files).
- Python client / MCP / OpenWorker / hooks / LangGraph / AutoGen:
  `164 / 48 / 102 / 6 / 5 / 6` tests, all builds PASS.
- Frozen Architecture 1.0 validation, release lock, and applicable tests: PASS; frozen bytes unchanged.
- OpenWorker generated/private artifact leakage scan: PASS.

The first full-matrix attempt exposed an outdated Formation test assertion that equated a governed
candidate with an accepted semantic Binding. The test now proves `new_governed_candidate_count=1`
and `new_accepted_binding_count=0` for an ungrounded relation; the fresh full rerun passed.

## Disposition

S3 establishes Product local usability for synthetic local data and permits S4 Lab confirmation.
It does not grant production readiness, personal-data eligibility, public deployment, Schema
freeze, or default candidate enablement. Both S3 Compose volumes and temporary credentials/Blob
roots were destroyed after evidence verification; the generated reports and Lab artifacts remain.

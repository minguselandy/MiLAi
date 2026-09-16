---
document_id: MILA-HOST-COGNITIVE-AFFORDANCE-HC4-EXPERIMENT-TRACKER
version: "0.2"
status: HC4_A1_GUIDED_ADOPTION_PENDING
created_at: "2026-09-04T18:01:27+08:00"
---

# HC-4 A1 Experiment Tracker

## Current state

```text
HC implementation/schema changes             0
codex-full tool catalog                       13 (unchanged)
A0 completed real sessions                    8
A0 completed distinct chains                  2
A0 natural Working State GET/UPDATE           0 / 0
A0 terminal                                   HC4_A0_PASSIVE_ADOPTION_NEGATIVE

A1 treatment                                  instructions + 2 descriptions only
A1 completed genuine sessions                 0 / 4
A1 natural Working State GET/UPDATE           0 / 0 (no runs)
A1 terminal                                   HC4_A1_GUIDED_ADOPTION_PENDING
HC4-C2                                        NOT_EVALUABLE
```

Frozen identities:

```text
Product tree SHA-256       bb1946f8977c55c80c1cbe4ad406a6ae3eac2d7bcb9ca2e0e896b334ac1dc664
MCP interface SHA-256      135ebea00f81b05e56f63b89e174e531acdc479c51dde749ea4a95d27409795e
MCP package tests          92 passed
Ruff / mypy / build        PASS
```

## A0 immutable baseline

| Run | Workstream | Result | Natural GET/UPDATE |
| --- | --- | --- | ---: |
| H4-C1～C4 | retrieval regression diagnosis and repair | real four-session chain complete | 0 / 0 |
| H4-D1～D4 | query-only RecollectionFacade refactor | real four-session chain complete | 0 / 0 |

A0 outcome is sealed as an affordance adoption failure signal. It must not be renamed incomplete
noise or merged with A1 results. Full per-session facts remain in the v0.1 tracker and
`MILA_HOST_COGNITIVE_AFFORDANCE_HC4_EXECUTION_AUDIT_20260904_134043.md`.

## A1 preparation

| Run ID | Purpose | Frozen variant | Status | Evidence |
| --- | --- | --- | --- | --- |
| A1-P0 | Split adoption and usefulness claims; preregister stop rule | Plan v0.2 | COMPLETE | timestamped + fixed plan |
| A1-P1 | Explain natural triggers without mandatory workflow | `GUIDED_AFFORDANCE` | COMPLETE | server instruction test |
| A1-P2 | Make the two tool descriptions task-semantic | same `get/update` | COMPLETE | catalog description assertions |
| A1-P3 | Prove no schema/catalog/package regression | Product tree above | COMPLETE | 92 tests, Ruff, mypy, wheel/sdist |
| A1-P4 | Load frozen treatment in existing HTTP MCP | public backend 7968 | COMPLETE | service active; readyz 200; live 13 tools; both guidance probes true; setup excluded |

## Third genuine chain

The chain is intentionally unassigned until a real, independently authorized, non-trivial coding
workstream appears. Do not count the A1 prompt/document change itself.

| Run ID | Natural phase | Eligibility | Status | GET | UPDATE | Notes |
| --- | --- | --- | --- | ---: | ---: | --- |
| A1-G1 | initial task | fresh Codex; genuine multi-session value | WAITING_GENUINE_TASK | — | — | prompt must not mention State/HC-4 |
| A1-G2 | resume | new process; same TASK ref; no prior conversation | NOT_ENTERED | — | — | prior ACTIVE State not assumed |
| A1-G3 | real decision/failure/blocker/phase change | event must occur naturally | NOT_ENTERED | — | — | do not manufacture failure |
| A1-G4 | resume and complete/handoff | new process; same TASK ref | NOT_ENTERED | — | — | C2 eligible only if prior ACTIVE State exists |

## Analysis gates

| Run ID | Purpose | Entry | Status |
| --- | --- | --- | --- |
| A1-E1 | classify natural invocation and materiality | G1～G4 complete | NOT_ENTERED |
| A1-E2 | apply hard safety gates | any counted A1 run | NOT_ENTERED |
| A1-T1 | apply adoption stop rule | G1～G4 complete | NOT_ENTERED |
| C2-R | resume usefulness measurement | A1 calls >0 and ACTIVE State exists | NOT_ENTERED |

Decision rule:

```text
4 valid A1 sessions + 0 natural calls
→ HC4_A1_GUIDED_ADOPTION_NEGATIVE
→ stop prompt escalation
→ park as manual feature or open separate Host-managed Goal

at least 1 natural call
→ HC4_A1_GUIDED_ADOPTION_OBSERVED
→ not PASS; continue only toward C2 minimum sample
```

## Hard safety counters

| Counter | Required | A0 observed | A1 observed |
| --- | ---: | ---: | ---: |
| CanonicalMutationFromWorkingState | 0 | 0 | NOT_ENTERED |
| WorkingStateAuthorityEscalation | 0 | 0 | NOT_ENTERED |
| CrossTenantStateLeak | 0 | 0 | NOT_ENTERED |
| CrossPrincipalStateLeak | 0 | 0 | NOT_ENTERED |
| CrossProjectStateLeak | 0 | 0 | NOT_ENTERED |
| RevokedEvidenceAcceptedAsValidReference | 0 | 0 | NOT_ENTERED |
| RecallSideWorkingStateMutation | 0 | 0 | NOT_ENTERED |

## Execution rule

Each A1 row is updated only after a genuine user task naturally forms one bounded fresh-Codex
session. Setup calls, tests, probes, wrapper calls and task prompts that prescribe State use are
excluded. Retrieval and Recollection work remain separate; A1 cannot change Runtime, schema,
Working State semantics or retrieval behavior.

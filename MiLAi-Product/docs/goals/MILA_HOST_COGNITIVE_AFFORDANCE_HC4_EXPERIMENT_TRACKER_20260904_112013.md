---
document_id: MILA-HOST-COGNITIVE-AFFORDANCE-HC4-EXPERIMENT-TRACKER
version: "0.1"
status: FROZEN_NOT_STARTED
created_at: "2026-09-04T11:20:13+08:00"
---

# HC-4 Experiment Tracker

## 冻结摘要

```text
Product behavior changes after HC-3       0
Runtime/schema changes authorized          0
target chains                              4
target session-tasks                       16
completed real session-tasks               0
completed continuation sessions            0
current terminal                           PARTIAL_HOST_COGNITIVE_PERSISTENCE_USABLE
```

## Preparation

| Run ID | Milestone | Purpose | System / Variant | Split | Metrics | Priority | Status | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| H4-P0 | H4-0 | Freeze HC-0～HC-3 behavior identity | Product tree `6cfb2418…cc2a1` | Product | manifest, tool catalog, migration head | MUST | COMPLETE | minimal HC-4 instruction sealed; no further Product change authority |
| H4-P1 | H4-0 | Freeze claims, rubric, attribution and terminal precedence | HC4 plan v0.1 | Product docs | contract completeness | MUST | COMPLETE | timestamped + latest plan |
| H4-P2 | H4-0 | Seal minimal instruction and action timestamp collection | frozen `codex-full` | setup | instruction text, trace availability | MUST | PARTIAL | instruction sealed; MCP 74 tests/Ruff/mypy/build PASS; verify action timestamps before A1 |
| H4-P3 | H4-0 | Select historical no-state descriptive references before outcomes | historical Product tasks | reference | task complexity descriptors | MUST | TODO | not a causal control; no retrospective cherry-pick |

## Continuous chains

| Run ID | Milestone | Purpose | System / Variant | Split | Metrics | Priority | Status | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| H4-A1 | H4-1 | Retrieval chain: understand/design and optionally create state | WS-ON minimal instruction | Chain A / S1 | use, update, materiality | MUST | TODO | wait for an authorized real retrieval task |
| H4-A2 | H4-1 | New Session implementation resume | WS-ON minimal instruction | Chain A / S2 | read rate, TTFA, task outcome | MUST | TODO | no prior conversation context |
| H4-A3 | H4-1 | Record or recover from a real failed approach | WS-ON minimal instruction | Chain A / S3 | repeated failure, correction | MUST | TODO | do not manufacture a failure |
| H4-A4 | H4-2 | Repair, completion conditions and handoff | WS-ON minimal instruction | Chain A / S4 | success, useful label | MUST | TODO | Product-11 gates still apply |
| H4-B1 | H4-2 | Schema/migration contract and first working state | WS-ON minimal instruction | Chain B / S1 | use, grounding | MUST | TODO | real feature only |
| H4-B2 | H4-2 | New Session implementation and PostgreSQL verification | WS-ON minimal instruction | Chain B / S2 | read rate, TTFA | MUST | TODO | preserve scope/RLS boundaries |
| H4-B3 | H4-2 | Compatibility failure diagnosis/correction | WS-ON minimal instruction | Chain B / S3 | stale correction, repeated failure | MUST | TODO | classify product vs state failure |
| H4-B4 | H4-2 | Final regression, rollback and state closeout | WS-ON minimal instruction | Chain B / S4 | success, useful label | MUST | TODO | no schema promotion during HC-4 |
| H4-C1 | H4-2 | Regression chain: establish failure facts | WS-ON minimal instruction | Chain C / S1 | use, grounding | MUST | TODO | seal failing command/evidence |
| H4-C2 | H4-2 | New Session root-cause localization | WS-ON minimal instruction | Chain C / S2 | read rate, TTFA | MUST | TODO | retrieval failures separately attributed |
| H4-C3 | H4-2 | Validate repair and clear obsolete blockers | WS-ON minimal instruction | Chain C / S3 | stale correction, material update | MUST | TODO | required stale-correction opportunity |
| H4-C4 | H4-2 | Full regression and handoff | WS-ON minimal instruction | Chain C / S4 | success, harmful rate | MUST | TODO | record unresolved issues honestly |
| H4-D1 | H4-2 | Refactor chain: freeze boundaries/risks | WS-ON minimal instruction | Chain D / S1 | use, decisions | MUST | TODO | small-scope real refactor |
| H4-D2 | H4-2 | New Session execute one bounded refactor | WS-ON minimal instruction | Chain D / S2 | read rate, TTFA | MUST | TODO | no broad rewrite |
| H4-D3 | H4-2 | Respond to failure or counter-evidence | WS-ON minimal instruction | Chain D / S3 | decision consistency | MUST | TODO | natural field discovery |
| H4-D4 | H4-2 | Verify and close chain | WS-ON minimal instruction | Chain D / S4 | success, useful label | MUST | TODO | no automatic primitive promotion |

## Analysis and terminal

| Run ID | Milestone | Purpose | System / Variant | Split | Metrics | Priority | Status | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| H4-E1 | H4-3 | Seal state-entry sample before labels | deterministic SHA-256 ordering | all valid chains | sample identity | MUST | TODO | ≤30 entries, otherwise full population if smaller |
| H4-E2 | H4-3 | Judge state correctness and material updates | human offline audit | sealed sample | grounding, stale, contradiction, materiality | MUST | TODO | Product runtime never sees labels |
| H4-E3 | H4-3 | Judge continuation usefulness and primary attribution | human offline audit | all continuation sessions | USEFUL/NEUTRAL/HARMFUL, attribution | MUST | TODO | one primary attribution per failure |
| H4-E4 | H4-3 | Inventory naturally invented fields | observational | all state versions | usage, persistence, correction, impact | MUST | TODO | recommendation only; promotion count remains 0 |
| H4-T1 | H4-4 | Apply frozen terminal precedence | no new run | HC-4 | sample, safety, usefulness gates | MUST | TODO | no threshold tuning after outcomes |
| H4-F1 | future | Strict paired resume-effect study | WS-ON vs matched WS-OFF | future Goal | calls, tokens, TTFA, success | NICE | NOT_AUTHORIZED | not required for first HC-4 usability terminal |

## Hard safety counters

| Counter | Required | Observed | Status |
| --- | ---: | ---: | --- |
| CanonicalMutationFromWorkingState | 0 | NOT_RUN | TODO |
| WorkingStateAuthorityEscalation | 0 | NOT_RUN | TODO |
| CrossTenantStateLeak | 0 | NOT_RUN | TODO |
| CrossPrincipalStateLeak | 0 | NOT_RUN | TODO |
| CrossProjectStateLeak | 0 | NOT_RUN | TODO |
| RevokedEvidenceAcceptedAsValidReference | 0 | NOT_RUN | TODO |
| RecallSideWorkingStateMutation | 0 | NOT_RUN | TODO |

## Execution rule

每次只在真实用户任务自然形成一个 bounded session-task 时更新一行。不得为了填 tracker 制造任务、
失败或 State 内容；不得把同一 conversation 中的多个命令伪装成多个新 Session。

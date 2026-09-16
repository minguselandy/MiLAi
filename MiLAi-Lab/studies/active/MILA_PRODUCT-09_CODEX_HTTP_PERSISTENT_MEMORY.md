# Product-09 Codex HTTP persistent memory result

Date: `2026-09-03`  
Product terminal: `PASS_PRODUCT09_CODEX_HTTP_PERSISTENT_MEMORY_USABLE`

## What was tested

Product-09 uses Codex as the only reasoning Host and MiLAi as a model-free memory service:

```text
HostAgentEvent
→ fresh PostgreSQL
→ official projection worker
→ authenticated Streamable HTTP MCP
→ memory-evidence-context-v1
→ Codex
```

The model-controlled MCP arguments remained `query` and optional `previous_context_id`. Trusted
environment and bearer binding supplied principal and project scope. MiLAi did not run a Reader,
EvidenceLedger, vLLM or generated sufficiency step.

## Real lifecycle result

The authoritative run is `var/product09/e2e-003.json`.

```text
Host events submitted / unique Evidence       4 / 3
duplicate event created another Evidence      0
Evidence / projection / Canonical rows         3 / 3 / 0
restart recall targets                         2 / 2
design / fix / no-memory / cross-project       PASS / PASS / PASS / PASS
Codex memory calls                              1 / 1 / 0 / 1
cross-project leak                              0
internal Reader / vLLM / semantic retry         0 / 0 / 0
```

The first runner attempt failed before product execution because a subprocess helper supplied both
`input` and `stdin`; the generic harness bug was fixed once and the lifecycle continued. No semantic
operation was automatically retried.

## Opened-development LongMemEval diagnostic

The baseline is `var/product09/lme-002.json`. It used 8 concurrent Host capture workers and 4
concurrent Codex tasks. All 1,772 turns were persisted and projected on a fresh database.

| Capability | Result | Memory calls | Required sessions visible |
| --- | ---: | ---: | ---: |
| ordinary user lookup | PASS | 1 | 1/1 |
| assistant-answer lookup | PASS | 1 | 1/1 |
| multi-session set COUNT | MISS (`2` vs `3`) | 2 | 3/3 |
| state update | PASS | 2 | 2/2 |

Aggregate baseline:

```text
Exact / normalized F1                 0.75 / 0.75
Any required-session recall           1.0
All required-session recall           1.0
Cases with all annotated turns visible 0.75
Canonical mutation                    0
Formal 500 consumed                   false
```

The exact-turn single-case localization in `var/product09/lme-003-count.json` showed 3/4 annotated
turns visible. The omitted turn repeated the already visible blazer fact; the visible evidence also
contained the old/new boots actions. Codex nevertheless collapsed the pending instances and answered
two. This is not a persistence or MCP transport failure, and session recall alone would have hidden
the remaining ambiguity between evidence admission and Host aggregation.

## Rejected repair

`var/product09/lme-004-host-guidance.json` tested a generic longer MCP instruction asking the Host to
enumerate facts before set/count/comparison/change answers. It regressed exact accuracy from 3/4 to
2/4, reduced COUNT answer-turn visibility, and made the state-update answer choose the older value.
The treatment was removed from Product.

This failure supports a simpler product rule: MCP server instructions should state authority and
workflow boundaries, not become a hidden Reader prompt. Future multi-evidence work should improve
retrieval continuation and expose compact, identity-preserving evidence—not add a rigid ledger or
benchmark-shaped counting rule.

## Scope of claim

This study establishes a usable Codex HTTP persistent-memory lifecycle and a four-case diagnostic.
It does not claim LongMemEval leaderboard accuracy, complete EvidenceSet recall, production readiness,
or a Formation effect. No judge was used; scoring was deterministic normalized EM/F1. The formal
500-case holdout was not accessed.


---
document_id: MILA-PRODUCT-11-X0-EXECUTION-AUDIT
version: "0.1"
status: X0_BLOCKED_HUMAN_AND_CONTINUATION_OPPORTUNITY
created_at: "2026-09-04T08:55:58+08:00"
goal: MILA-PRODUCT-11@0.4
formal_holdout_accessed: false
formal_cases_scored: 0
---

# Product-11 X0 execution audit

## Outcome

X0 did not pass. The final source-only A0 trace is operationally valid, but the post-trace
model-assisted proxy join found no continuation opportunity; human adjudication remains `0/24`.
This document does not assert the human-sealed terminal state.

```text
A0 run                           p11-x0-a0-20260904f
source fixture                   product11-opened-dev24.v0.6.json
fixture SHA-256                  c1fee1f4e9f68e7d9a0b082984c4ed5e4952e1e3f72ae009afd264640ba4c709
A0 redacted trace SHA-256        eef498d36c35b102ca6943469c7b203113237b1bf63c3cb17cd8c95f9dd27a95
proxy audit                      p11-x0-proxy-audit-20260904a
proxy case-view SHA-256          5300bacc9d3a39149a12641353c181b0ee23095f3e64255e39790c46b5c7108c
```

## Operational gates

| Gate | Result |
| --- | --- |
| fresh PostgreSQL | `0 evidence / 0 projection / 0 canonical` |
| capture and projection | `238 / 238` |
| Product/MCP trace | `24 / 24` |
| Canonical mutation | `0` |
| cross-case namespace | `0` |
| Product label access | `0` |
| Formal access/scoring | `false / 0` |
| Reader/vLLM/retry/vote | `0 / 0 / 0 / 0` |
| run-owned volume cleanup | PASS |

The trace was written before any proposal file was loaded. MCP public input and Product behavior were
unchanged; this was not an effect run.

## Opportunity audit

The offline join used only `MODEL_ASSISTED_PROPOSAL_ONLY / PENDING` groups and therefore remains
diagnostic:

| Stratum | Observed proxy | Required |
| --- | ---: | ---: |
| continuation opportunity | 0 | >=8 |
| intra-source opportunity | 8 | >=8 |
| control / already complete | 16 | >=8 |

The final continuation candidates had unseen distractor frontier entries, but every required group
was already Host-visible because A0 token-efficient planning retained the short required windows.
Unseen non-required candidates do not satisfy the frozen continuation-opportunity definition.

## Preserved failures

All superseded runs remain immutable in Lab. The append-only failure ledger records:

1. preparation file-vs-semantic digest ambiguity;
2. short source slice with no continuation frontier and widespread zero-candidate retrieval;
3. individually oversized required turns that caused hydration degradation;
4. feasible but too-deep raw frontier;
5. immediate frontier whose total activation remained below 16K;
6. final activation correction whose required groups were still retained by A0.

No Product treatment was run in any attempt, and Formal access/scoring stayed `false/0`.

## Stage disposition

Product behavior and migration remain forbidden before `PASS_PRODUCT11_X0_HUMAN_SEAL`. X1, X2,
X3 and X4 are not entered. A formal insufficient-opportunity terminal requires real annotator and
independent reviewer confirmation; AI/model proposals cannot self-sign it.

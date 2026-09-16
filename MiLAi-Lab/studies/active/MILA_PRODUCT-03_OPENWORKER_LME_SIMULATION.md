# Product-03 OpenWorker LongMemEval simulation

Date: 2026-09-02  
Arm kind: `OPENWORKER_HOST_BLACK_BOX`  
Input: opened-development, deidentified LongMemEval only  
Formal 500-case holdout: `NOT CONSUMED`

## Final result

The real LongMemEval case `ad7109d1` (`F1_DISCOVERY`, `single-session-user`) now passes through the
actual local product composition:

```text
44 source sessions / 466 material turns
→ submitter MCP capture and projection
→ native OpenWorker/OpenCode operation
→ query-first Host
→ reader-lite UDS broker / milai-mcp
→ Runtime resolve and governed MemoryContext
→ local Qwen provider
```

All 466 turns were captured and projected. The final operation made one logical MCP resolve and one
Qwen provider call, with no automatic retry and no Canonical mutation. Runtime used the requested
WIDE plan (`REQUIRED`, 120 candidates, 8192 Context tokens, 2000 ms). The run-local corrective
summary reports 20 selected governed Evidence units and confirms that the answer-bearing Evidence
entered Reader-visible Context; the compacted Host trace independently preserves the count summary
and Context boundary. Host compiled 24,576
bytes / 5,858 tokens of Runtime-owned memory into the prompt. Qwen returned the exact expected
answer using 17,268 prompt tokens and 5 completion tokens.

Runtime deliberately remains `PARTIAL` under the ordinary-recall soft boundary. The fix does not
invent typed `COMPLETE`: Host accepts the Runtime-owned, governance-admitted Context as usable input
while preserving Runtime status and Evidence lineage.

## Corrective sequence

Three retained runs localize the failure and repair:

1. `mila-product03-lme-openworker-20260902T125500-cst`: WIDE was declared by Host, but Runtime
   downgraded the effective plan to 30 candidates, 768 Context tokens and 250 ms. The gold turn was
   not selected and Provider correctly remained uncalled.
2. `mila-product03-lme-openworker-ad7109d1-postfix-20260902T131833-cst`: Runtime accepted the WIDE
   budget, but Host rebuilt Context only from MCP-compacted raw items and discarded the non-empty
   Runtime-owned `memory_context.text`; Provider again remained uncalled.
3. `mila-product03-lme-openworker-ad7109d1-final-20260902T133619-cst`: explicit reads remain
   `REQUIRED`, and the trusted Context bridge preserves the Runtime-owned soft-ranked Context. The
   answer-bearing Evidence became Reader-visible and the native task passed.

The two general repairs are therefore:

```text
explicit read intent owns the WIDE Runtime plan
+
authenticated Runtime MemoryContext survives MCP diagnostic compaction
```

No case ID rule, reference-answer cue, synonym, seed switch, retry, Dense treatment, graph path or
post-outcome route was added.

## Earlier V01 two-case follow-up

Two additional opened-development cases were then run independently against fresh Runtime database
volumes and fresh OpenWorker containers. Together they covered 88 sessions and 923 material turns;
all 923 turns were captured and projected. Each valid task produced one native OpenWorker operation
and one logical MCP resolve, with no automatic retry. Neither task reached Qwen because Runtime
failed closed at sufficiency:

| Case | Type | Turns | Runtime result | Provider | Score |
| --- | --- | ---: | --- | ---: | --- |
| `71a3fd6b` | `single-session-assistant` | 439 | `UNBOUNDED / QUERY_AMBIGUOUS` | 0 | fail |
| `0a995998` | `multi-session` | 484 | `UNSATISFIED / QUERY_AMBIGUOUS` | 0 | fail |

For `71a3fd6b`, the phrase “provided me earlier” was treated as an unbounded temporal request. The
Runtime could not prove `MATCHING_EVENTS_IN_RANGE`, returned `ABSTAINED`, and Host emitted a typed
`MEMORY_INSUFFICIENT / ASK_USER` response. The compiled diagnostic-only Context was 152 bytes / 45
tokens.

For `0a995998`, the cross-session clothing pickup/return count also failed the query-ambiguity
sufficiency gate. Runtime returned `ABSTAINED`; Host emitted the same typed fail-closed action with a
154-byte / 46-token diagnostic-only Context. The originally printed `passed=true` was a scorer false
positive: reference `3` matched an incidental character in the typed JSON trace rather than an
answer. The scorer now rejects typed `MEMORY_INSUFFICIENT` responses and requires reference token
boundaries; regression tests cover both cases.

The fixed WIDE broker profile remained active (`REQUIRED`, 120 candidates, 8192 Context tokens,
2000 ms), but these two requests stopped before a governed answer Context or provider call. They
therefore show that the earlier `ad7109d1` repair did not weaken fail-closed sufficiency behavior;
they do not add two more successful recall examples. One discarded pre-Host invocation for the
second case used incorrect image environment-variable names, reached neither Host nor MCP, and is
excluded from the valid operation counts.

Authoritative follow-up summary:
`var/runs/mila-product03-lme-openworker-two-case-20260902T140859-cst/summary.json`.

## Expanded-budget V02 replay

The next usability pass retained the same opened-development cases and actual Product path, but
explicitly selected `OPENWORKER_USABILITY_WIDE_V02`: 50 results, 120 candidates, 16,384 Runtime
Context tokens and 5,000 ms, with a V02-only 262,144-byte MCP wire ceiling and a 262,144-character
Host ceiling. The profile is default-OFF; scope, revocation, Binding, Sufficiency and Canonical
authority did not change.

| Case | Turns | Product result | Provider | Score |
| --- | ---: | --- | ---: | --- |
| `71a3fd6b` | 439 | `PARTIAL`, governed lookup Context | 1 | pass |
| `ad7109d1` | 466 | `PARTIAL`, governed lookup Context | 1 | pass |
| `0a995998` | 484 | `PARTIAL / UNBOUNDED`, governed best-effort Context | 1 | fail |

All 1,389 turns were already captured and projected in isolated case databases. Each replay created
one native OpenWorker operation, one logical MCP resolve and one Qwen call; automatic retry and
Canonical mutation were zero. The assistant-source lookup returned the requested historical value,
and the prior 500-Mbps lookup remained correct. The shared query-intent repair distinguishes actual
count expressions from compound identifier phrases; it contains no case ID, answer or domain rule.

The multi-session count case progressed from a provider-not-called failure to a full usable chain:
Runtime exposed 49,152 bytes / 11,604 memory tokens, Host marked the governed informational Context
`AVAILABLE`, and Qwen ran once. Runtime correctly preserved
`SUFFICIENCY_UNBOUNDED_QUERY_AMBIGUOUS`; Qwen's answer was still wrong. This is an availability
improvement, not COUNT correctness. The remaining failure concerns general atomic-member extraction,
object-instance/obligation lineage and duplicate-reference resolution, rather than capacity after
V02. No gold count, clothing term, synonym, seed change, retry or post-outcome route was added.

Compact summary:
`var/runs/mila-product03-lme-openworker-v02-replay-20260902T162500-cst/summary.json`.

## Product-04 post-refactor replay

After the QueryTaskContract/Reader-availability refactor, the two original V01 failures were
replayed again against separate fresh Runtime volumes with `OPENWORKER_USABILITY_WIDE_V02`. All 923
turns were freshly captured. Each valid task made one native OpenWorker operation, one logical MCP
resolve and one Qwen call, with no automatic retry or Canonical mutation.

| Case | Original V01 result | Product-04 result | Score |
| --- | --- | --- | --- |
| `71a3fd6b` | `MEMORY_INSUFFICIENT`, Provider 0 | `PARTIAL`, exact phone number | pass |
| `0a995998` | `MEMORY_INSUFFICIENT`, Provider 0 | `PARTIAL`, answer `1` vs reference `3` | fail |

For `71a3fd6b`, Host passed 49,152 bytes / 11,659 tokens of governed Context to Qwen, which returned
the exact Speyer tourism-board phone number. For `0a995998`, Host passed 47,026 bytes / 10,726 tokens.
A separate read-only resolve reproduced the exact Host Context digest and confirmed that both the
navy-blazer/dry-cleaning and Zara/boots facts were Reader-visible. Qwen still answered `1`; the
remaining boundary is therefore Reader counting rather than retrieval visibility. It appears to
count a pair of boots as one item and omit the blazer, but that explanation is an inference from the
answer and benchmark reference, not a typed Runtime conclusion.

This replay supports the narrow Product-04 claim that governed availability is independent of typed
completion: both formerly blocked cases now reach the Reader. It establishes one new exact answer,
not two-case accuracy closure or general LongMemEval accuracy.

Authoritative replay summary:
`var/runs/mila-product04-lme-openworker-two-case-20260902T222138-cst/summary.json`.

The formal 500-case holdout remains unauthorized, unrun and unconsumed.

## Evidence and limits

Authoritative final directory:
`var/runs/mila-product03-lme-openworker-ad7109d1-final-20260902T133619-cst/`

- `summary.json`: compact public corrective result;
- `lme-ad7109d1-final.private.json`: private question, reference and native answer;
- `lme-ad7109d1-final.private.captures.private.json`: idempotent capture receipts;
- `host-trace.jsonl`: operation → MCP → Runtime → provider linkage;
- `provider-ledger.jsonl`: one logical Qwen execution lifecycle.

The original run establishes single-case OpenWorker usability under a large 466-turn haystack; the
V02 replay adds two passing lookup regressions and one explicit semantic count miss. Neither result
establishes general LongMemEval accuracy, COUNT/set correctness, production readiness, remote MCP
behavior, Schema stability or a Formation effect. The formal 500-case holdout remains untouched.

Two residual opportunities are intentionally separate from this correction: the harness currently
mixes response instructions/reference date into the retrieval surface, and the WIDE reranker path is
not exercised by this route. They require matched multi-case evidence before any treatment.

The active replay tooling also consumes a run-owned `openworker.env` created outside the runner.
Network inspection found that two retained files referenced a gateway from an older Docker network;
the replays happened to succeed because the Host was reachable on that other local bridge. A future
runner cleanup should inspect the current case network, bind Host to that exact gateway and generate
the 0600 Worker env for the same run. This is a harness reproducibility issue, not a retrieval result,
and it does not justify widening Host to all interfaces in the product contract.

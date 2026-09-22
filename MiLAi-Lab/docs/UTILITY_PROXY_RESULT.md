# Utility adoption-proxy first batch — KEEP_SIMPLE

Decision: **KEEP_SIMPLE / BENEFIT_NOT_ESTABLISHED**, no Product promotion or next
model allocation. This is a closed finite `RESEARCH_PROTOTYPE` batch, not a resumed
historical study, proof that all Utility methods fail, or a Product result.

The user explicitly authorized historical exact-bundle adoption/rejection as a
proxy, not observed use or causal benefit. The [protocol](UTILITY_PROXY_PROTOCOL.md)
was frozen before the first request. [Machine-readable settlement](../data/manifests/utility-proxy-result-20260922.json)
contains all scheduled pairs, missing arms, exact costs and payload identities.

## Actual result

| Independent development positions | STATIC correct | UTILITY correct | UTILITY − STATIC new tokens |
| --- | ---: | ---: | ---: |
| DB, 12 pairs | 5/12 | 2/12 | +4,783 |
| OS, 12 pairs | 9/12 | 9/12 | −2,632 |
| Total, 24 pairs | 14/24 | 11/24 | +2,151 |

These are descriptive paired observations, not causal estimates. DB selection
never changed; all 20 unchanged-selection independent pairs had identical first
settled request payloads across arms. DB 94/246/256 nevertheless differed in native
correctness. That demonstrates background execution/model variability under the
fixed profile, not causal Utility harm; it also cannot be dropped to declare
quality non-regression. No seed, task, arm order or algorithm was changed in response.

Four OS independent positions changed selection. Only **OS 428** met the frozen
meaningful-alternatives criterion. Its original pair was correct in both arms,
but tokens increased **6,265 → 6,301 (+36)**: prompt tokens fell by 265 while output
tokens grew by 301. Arm wall time fell 12.466 → 9.485 s, while settled generation
time rose 7.112 → 8.211 s; wall time includes native container initialization and
release and is not an established model-latency benefit. Its repeated pair is
incomplete. Neither the primary token-saving criterion nor repeatable benefit holds.

The other changed OS positions (242/355/467) remain in overall costs and quality,
not the mechanism-effect denominator. Their tokens changed −594/+566/+1,225.
Thus the four changed original pairs together used **1,233 more tokens**; the OS
aggregate token reduction cannot be credited to Utility selection. Observable use
is **UNKNOWN** throughout. Exposure receipts and native success are not use proof.

## Exact stopping and costs

Execution retained **54 normally terminated arms (27 complete pairs), one
budget-interrupted arm, and nine unstarted arms**. Complete pairs comprise all
24 independent pairs plus three of the eight fixed repeats. No sample was replaced,
reordered, retried, rerun or added.

- Outbound generation: **199 requests / 341,591 reported tokens**, all actor role.
- Auxiliary solver HTTP: **200 tokenize + 1 model-info**, known zero inference tokens.
- Total outbound: **400 requests**; new embedding **0 / 0 tokens**; rerank **0**.
- New maintenance/controller/extraction/judge inference: **0**.
- New unknown usage and unsettled outbound requests: **0**. Charged text tokens
  equal reported tokens. Shared model-info costs one of the 400 requests.
- Wall time from first auxiliary request: **909.961 s** (15 min 9.961 s), below 4h.
- Shared offline projection/selection preparation: **0.087 s**, recorded separately.

The declared conservative guard counts tokenize/model-info against the 400 text
slots too. It therefore stopped below 400 actual generations and below the user's
528 total ceiling. The token and wall ceilings were not exhausted. **All unused
allocation is closed; it is not permission for makeup or another batch.**

The final dispatched request was tokenize. The following local Provider reservation
`000200-actor` was refused by the transport budget before dispatch; matching the
durable transport ledger proves it was not an unknown or free outbound attempt.
The native adapter wraps this refusal as `agent_unknown_error` for repeated OS428
UTILITY. Its scorer reports `correct` for the already modified environment, but
the arm is explicitly budget-interrupted, not cleanly completed. Repeated STATIC
and all subsequent arms were not started. Original session/error evidence is intact.

Historical materials were not free to create: the two permitted bank-source runs
have gross receipts for **124 generations / 203,778 tokens** and **20 embeddings /
3,528 tokens**. The 21 reused instructed-query receipts report **4,219 tokens**;
these overlap source-run embeddings and **must not be added twice**. They are sunk
historical costs, not new-batch consumption or exact-bundle formation attribution.
Lifecycle amortization and monetary cost remain UNKNOWN; no fresh-retrieval or
full-lifecycle saving is claimed. Three cache misses abstained in both arms.

## Identity, checks and delivery boundary

Base/rollback commit: `ae434539f6b99fd2da0c9ab6e208ff7ce34f9d88` (PR #41); remote main
was checked before execution. Preparation PR #41 exact-head fast `35740683722`,
identical-tree merge and main fast `35741790217` passed.

- Allocation SHA: `90877f1f6506974edb84b773ea356be687e59038136d0801a0b4d299ff392e26`.
- Admission SHA: `a070feaa1b45046ad0369a4fbc65894c58e1aede3e62fbbf7679e1de3a2f8fcd`.
- Terminal SHA: `f9cade14ed740904364c188800c449acc1d64f04cd156c311ab7b05000db32b7`.
- Raw evidence: `/cra/memory/mx_memory/evidence/post-cleanup-utility-proxy-20260922/admitted`.
- All **696 frozen source/input/native/image pins** reverified after execution;
  source hashes and the original allocation were not edited during the batch.
- Sole solver Qwen3.6-35B-A3B-FP8, existing loopback endpoint/M1 profile; frozen
  BGE vectors only, reranker off. Native benchmark commit and Docker IDs are sealed.

Local validation: 11 new method/plan/analysis tests, 22 existing budget/transport
tests PASS (33 distinct); Lab Ruff over src/tests/tools and mypy over 63 source
files PASS; both Lab import boundaries PASS. Pinned native imports and actual
bounded execution provide the runner smoke. No local full suite, Product Runtime/
integration suite, real Product PostgreSQL or full-composition rerun: Lab-only
change, Product executable identity unchanged. Classified PR CI supplies package
tests/build; remote closure is recorded separately once observed.

Schema/API/permissions/Canonical behavior are unchanged. Product remains Runtime
0.1.x CANDIDATE, Schema 0.1.x EXPERIMENTAL / **NO-GO FOR SCHEMA FREEZE**; resolver
C06/C21 remain OPEN. No safety/authority violation was observed within this native
prototype's scope; this is not an independent safety evaluation. Later Revision,
Attention, transfer and second-solver execution have no new model budget from this
batch. The overall development Goal is not complete.

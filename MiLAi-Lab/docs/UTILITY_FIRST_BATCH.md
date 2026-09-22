# First finite Utility batch — authorization and frozen allocation

User authority received on 2026-09-22 supersedes the earlier zero-allocation
preflight **only for this one batch**. Historical allocations remain closed;
historical workers, SUPPORT banks and formal studies are not resumed.
Base main is `3089ee11425f29e889bbc91b93ac1396314af41c`, also verified against
remote main before preparation. Arm kind is `RESEARCH_PROTOTYPE`, not Product.

## Frozen task allocation

The [allocation](../data/manifests/utility-first-batch-allocation-20260922.json)
has SHA-256 `90877f1f6506974edb84b773ea356be687e59038136d0801a0b4d299ff392e26`.
It binds the existing split hash and each existing exposure receipt hash.
Selection uses original DEV-then-VALID order and distinct source clusters, not
scores. Only positions with an existing native execution receipt are eligible.

| Domain | Twelve independent positions, in domain order | Four repeated once |
| --- | --- | --- |
| DB | 33, 62, 94, 134, 159, 163, 175, 223, 240, 246, 248, 256 | 33, 134, 175, 246 |
| OS | 120, 194, 226, 428, 2, 16, 47, 211, 242, 250, 355, 467 | 120, 428, 47, 250 |

DB positions are DEV. OS uses four DEV plus eight already exposed VALID positions;
all are development evidence, not new confirmation evidence. Domains interleave;
the first 24 pairs precede the eight repeats. Arm order alternates by domain and
position, with reverse order for each repeat. The manifest lists all 32 pairs and
64 arm executions explicitly. Repeats are not additional independent samples.
No TEST, main confirmation, Travel, RESERVE, SUPPORT or outcome-based replacements.

## Binding limits

- Solver: only `Qwen3.6-35B-A3B-FP8`, `http://127.0.0.1:7860/v1`, unchanged M1
  profile (seed 213, top-p 1, thinking off, actor temperature 0/output cap 4096;
  historical role-specific temperatures/caps preserved).
- Existing retrieval may use only the existing bge-m3 endpoint/encoding/dimension;
  reranking is off. No new endpoint, model or changed common execution conditions.
- At most 400 text-generation requests / 3,000,000 reported text tokens;
  128 embedding requests / 50,000 embedding tokens; rerank 0; total requests 528.
- Failed requests, retries and maintenance count. Unknown usage occupies its
  known upper bound. No quota resets or free retries.
- Four hours from the first new request; conservatively, the planned guard starts
  even on the first auxiliary solver HTTP call. Stop new requests at the deadline;
  retain completed, failed and unfinished records, without extension or makeup.

## Historical evidence and the authorized proxy

The inspected allowed v0.6 VALID banks contain no `utility_state`. DB's recorded
adoption decisions reject the retrieved bundles; OS has a partial adoption of
`card:4/card:5` on historical task 47. These are decisions/exposures, not causal
utility or observable use. The four v0.7 DEV smoke tasks use H feedback:
`native_result` is null. One DB task exposes `card:1@1`; OS exposures are empty.
This does not establish comparable task-benefit estimates for two alternatives.

Sources inspected (all already exposed DEV/VALID, historical bytes unchanged):

- `experience-optimization-20260916/native-validation-v06/valid-{db_bench,os_interaction}-milai/`
  banks and task memory events, under the external evidence root.
- `evidence-utility-improvement-20260916/d1-native-smoke/d1-{db_bench,os_interaction}/`
  version-bound utility state, under the same root.

The old DB projection comparator loads a SUPPORT bank and is therefore excluded.
No new label is inferred from old H outcomes, no task success is distributed over
individual cards, and candidate provenance must exclude the current task and its
source-group influence before any new model input is built.

The user subsequently explicitly permitted the historical exact-bundle adoption/
rejection proxy, still requiring paired quality and complete costs. The experiment
tests **that proxy**, not an already measured task-benefit utility. The separate
[pre-outcome protocol](UTILITY_PROXY_PROTOCOL.md) fixes the implemented rule,
provenance exclusions, cached-only common retrieval, native conditions, quality/
cost/safety criteria and denominator. Only one independent position has two
established meaningful alternatives; it cannot support generalization or promotion.
The original allocation is unchanged, including its historical preparation status.

## Implemented preparation and validation

`tools/prepare_utility_first_batch.py` creates an allocation exclusively (no
overwrite), verifies split identity, and reads exposure receipts without using
their outcome fields for selection. It sends no requests.

`methods/finite_research_budget.py` provides a durable transactional ledger with
shared request/token reservation, unknown upper bounds, immutable manifest binding,
persisted start/deadline, and permanent stop on bound violation. A reopened ledger
keeps prior usage. The opt-in `tools/finite_budget_transport.py` gate is now connected
to the existing text and embedding Provider constructors. It reserves before sending,
checks allowed endpoints/M1 parameters, caps network timeouts by the batch deadline,
and preserves failed response bodies if its own checks prevent normal Provider
settlement. Unknown/failed requests retain their upper bounds across provider restarts.
No retries are built into the transport. Tokenizer/model-info HTTP requests
conservatively consume text slots too, with **known zero inference tokens**; purpose
counts keep these auxiliary requests distinct from actual generations. This stricter
accounting may stop below 400 generations and does not expand any authorized cap.

`tools/run_utility_proxy_batch.py` now binds one hard-coded batch root and ledger,
verifies frozen source/selection/input/native identities and prevents replay with
exclusive batch/arm markers. Admission SHA before the first external request:
`a070feaa1b45046ad0369a4fbc65894c58e1aede3e62fbbf7679e1de3a2f8fcd`.
The external evidence root is
`/cra/memory/mx_memory/evidence/post-cleanup-utility-proxy-20260922/admitted`.
No new embedding is needed: 21 existing instructed query vectors are verified;
three missing caches abstain in both arms without task replacement. The opt-in
embedding transport still requires a deployment-grounded token bound if used in
a separately authorized run; fixture bounds are not deployment claims.

Targeted validation: 11 budget, 11 transport, 3 allocation, 4 existing Provider and
4 adjacent runtime-policy tests PASS (33 distinct tests across targeted invocations);
changed-file Ruff, budget-module mypy and both Lab import boundaries PASS.
That preparation ran no local full suite, Product tests, benchmark, generation or
endpoint probe. PR #41 closed at main `ae434539f6b99fd2da0c9ab6e208ff7ce34f9d88`:
tested head `883cd7861a2d1b3044a032415ee47c3b9486ba19`, fast `35740683722` PASS,
identical merge tree `bd173eb75f6df156223ada3d02050fcdff2b39cc`, main fast
`35741790217` PASS. Classified Lab CI: 4,682 PASS / 137 SKIP / 4 DESELECTED;
static/build/archive PASS. The remote main baseline was rechecked before this batch.
Product executable/schema/API, permissions and Canonical behavior are unchanged;
resolver C06/C21 remain OPEN.

Preparation ended at zero requests. The separately sealed execution and its actual
consumption are reported in [the batch result](UTILITY_PROXY_RESULT.md), not inferred
from historical authorization or the allocation's unchanged preparation fields.

# First finite Utility batch — authorized, not yet execution-admitted

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

## Admission gap: what Utility means

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

A historical bundle adoption/rejection proxy is a possible first selection rule,
but would test **that proxy**, not an already measured task-benefit utility. This
choice has been put to the user; neither interpretation is silently substituted.
The allocation freezes tasks/arms, **not** an unfinished algorithm or candidate
bank. Method, permissible utility evidence, native pins, primary quality/cost and
safety rules, and pre-outcome opportunity accounting remain to be frozen.

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

The **experiment runner is not yet admitted or connected**. It must pin one ledger
path for all arms, freeze/verify the selection implementation and input provenance,
and prevent extra/replayed arm executions. For embedding, a verified token-upper-bound
function is mandatory: without a bound grounded in the existing deployment/tokenizer
contract, construction fails closed. No deployment bound is inferred from string
length, and the fixture embedding bound used in tests is not a deployment claim.

Targeted validation: 11 budget, 11 transport, 3 allocation, 4 existing Provider and
4 adjacent runtime-policy tests PASS (33 distinct tests across targeted invocations);
changed-file Ruff, budget-module mypy and both Lab import boundaries PASS.
No local full suite, Product tests, benchmark execution,
embedding, generation or endpoint probe was run. Product executable/schema/API,
permissions and Canonical behavior are unchanged. Existing resolver C06/C21 debt
remains OPEN. Remote main identity was checked; preparation PR closure is pending.

Current consumption: **0 text / 0 embedding / 0 rerank requests; clock not started**.
No mechanism-effect, negative-effect or Product-promotion conclusion is available.

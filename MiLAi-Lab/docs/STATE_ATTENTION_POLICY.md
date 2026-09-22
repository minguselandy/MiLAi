# State-guided Attention: zero-model policy seam

Status: **RESEARCH_PROTOTYPE / engineering only / model execution NOT_ADMITTED**.
Capture base/rollback: `1367b2c8aeb7e330bf9f9046a384f1e2b989d92d` (PR #45 main).
No new data scan, experiment allocation, Provider call or Product change.

## Implemented boundary

[state_attention.py](../src/milai_lab/methods/state_attention.py) makes a pure decision
over an **already acquired** source pool and caller-reviewed visible state. It reuses
`SourceUnit` / `SourceSnapshot` exact versions, bytes and scope; it does not call the
old FULL/FOCUS request builder or change that builder's historical decoding profile.
It does not implement a semantic state producer, retriever, Provider or cost ledger.
The separate capture below durably controls a caller-supplied retrieval callback;
these pieces are not a complete live Attention system.

`decide_attention` returns FOCUS, CONFLICT or EXPLORE, with a distinct action:
`CONTEXT`, `RETRIEVE_ONCE` or `ABSTAIN_MEMORY`. The last action means no memory
context from this decision, not a native task failure or a demand that the solver
abstain. The caller must honor the action, not dispatch provisional selection from
an expansion intent as if coverage were sufficient.

## State ownership and freshness

| Input | Owner | Meaning / absence |
| --- | --- | --- |
| Current question | Current authorized task input | Required, exact input hash; not generated from memory |
| Active goal, hypotheses, next actions, memory intentions | Explicit Host/Actor artifact | Absent/unsupported means UNKNOWN, not an inferred goal or relevance |
| Failed approaches, unresolved constraints, recent evidence | Visible tool observation or Host/Actor artifact | No evaluator/hidden-native-result owner; missing means UNKNOWN |
| Uncertainty, open conflicts | Explicit Host/Actor artifact | Fallible assertions, never correctness/confidence inferred from outcomes |
| Coverage review | Caller-authenticated task-visible review | SUFFICIENT/GAP/UNKNOWN over the exact bounded selection, not all acquired evidence |

Every state artifact is bound to task, scope, question hash and the entire candidate
snapshot. Each field declares an artifact reference, producer sequence, expiry and
exact source dependencies; `observed < decision <= expiry` is required. Candidate
change, task reset, changed question, missing provenance, stale/future fields or an
ineligible dependency invalidate the affected control state. A changed pool also
invalidates a previous declaration that no conflict exists.
Because these reviews inspect the whole pool, denial/unknown eligibility of even
an unselected member invalidates derived state/coverage. Only the independently
declared baseline may remain, still excluding every ineligible source.

The policy consumes `memory_intentions.sources` as explicitly reviewed relevance
and `open_conflicts.sources` as **all sides of reviewed current conflicts**.
Known-empty conflict needs a current artifact; absence is not reviewed emptiness.
A single supplied side is UNKNOWN. Other allowed fields are tracked with freshness
but do not acquire hidden weights or automatic semantic interpretations. Multiple
conflicts share a required-source union; their grouping/support remains in the
authenticated review artifact. Automatic conflict detection is not implemented.

## Frozen code policy (not a live experiment protocol)

1. Check every source's current eligibility. DENIED, UNKNOWN, callback failure or
   malformed eligibility is never selectable; recheck again before actual dispatch.
2. Current supported conflict takes priority. Reserve all sides before other relevant
   evidence, then preserve original source order. If all sides cannot fit, abstain
   from memory context; never silently present a one-sided conflict as covered.
3. With reviewed no-conflict and current relevance, FOCUS on those eligible sources.
   Coverage must bind the state, snapshot, exact selected IDs/order, provenance and
   pre-decision sequence. Missing/stale/unknown coverage falls back to the declared
   simple baseline with coverage UNKNOWN, without expansion.
4. A reviewed GAP permits EXPLORE only when the runner's attempt count is zero and
   pool capacity remains. The intent uses the unchanged authorized question/scope,
   excludes acquired IDs, and declares result-count/UTF-8-byte limits. No hidden
   synonyms, gold labels, controller LLM, reranker or item-reward heuristic.
5. The runner must persist/debit the attempt **before** calling its retriever. Failure
   counts too. It must enforce the intent bounds, shared authorized pool and eligibility,
   merge exact whole sources, obtain fresh state/coverage review, then call the policy
   with count 1. Remaining GAP or exhausted capacity stops, with no second expansion.

Both baseline and state selection share limits. Candidate defaults are 8 selected
sources / 8,192 UTF-8 bytes / at most 4 extra results; the reused pool contract caps
32 sources / 65,536 bytes. Remaining pool capacity further limits an expansion.
These are explicit engineering defaults, **not approved live-run settings**. Required
conflict sources are reserved; optional sources use deterministic first-fit in input
order. Byte limits are not token reservations. A real protocol must freeze baseline,
limits, initial retrieval, allowed pool, source order and common solver conditions.

The result hashes policy limits, state/coverage reviews, snapshot, eligibility,
baseline and decision. Artifact refs and source identities must be authentic and
complete; hashes alone do not establish semantic truth, provenance or chronology.
The stateless API cannot prevent a caller resetting `expansion_attempts`; a durable
runner journal is required before live use. A retrieval intent contains the question,
so it is not a redaction API and raw decisions must not be published indiscriminately.

## Durable expansion capture

[attention_expansion.py](../src/milai_lab/methods/attention_expansion.py) supplies that
one-attempt journal, without adding a model client or replacing the existing global
finite-budget ledger. The caller pins one private SQLite path per frozen arm/task.
Admission digest, execution/task identity, scope, question digest, policy and limits
are immutable on reopen. A digest is an identity binding, not execution permission.

`step` commits a singleton reservation with SQLite `synchronous=FULL` before its
mandatory admission/deadline callback, then rechecks source eligibility and the
decision before retrieval. Concurrent instances cannot both claim the attempt.
Pre-dispatch cancellation, failed retrieval, invalid results and uncertain crash
recovery all consume it. There is no reset/retry API; changing journal paths to
evade this is prohibited. An unfinished RESERVED/DISPATCHING row means UNKNOWN,
not proof that its process is still running or that usage was zero.

The retriever must enforce the frozen allowed pool, unchanged query/scope and every
external request's existing global budget guard. Returned source count, UTF-8 bytes,
excluded IDs, exact versions, unique identities, scope and current eligibility are
checked before capturing the merged pool. The backend receipt reference survives
source-validation failure for cost joining. Exceptions without such a receipt remain
UNKNOWN and must be reconciled through the execution-bound global ledger; this
module never estimates them as zero or creates a second request/token allowance.

Successful capture stores exact source bodies privately outside Git. Explicit
`restored_snapshot()` restores bytes, not fresh authority or semantic review. `step`
returns the original retrieval decision plus the new pool, **not Actor-ready context**;
the caller must review the changed pool, call the policy again, and revalidate before
Actor dispatch. Elapsed time covers this capture operation only, not total task cost.
Semantic labels, genuine retrieval integration, full cost settlement and native
quality comparison remain unimplemented here.

## Checks, effect gap and next gate

Local changed-file Ruff/mypy and **74 targeted tests PASS** (new policy plus existing
state_focus). Synthetic tests cover exact bytes/order, mode priority, conflict
reservation, missing/future/stale state, whole-pool and selected-set bindings, denied
sources, capacity exhaustion and the caller-counted one-expansion loop. Initial Ruff
B008 was resolved with a module-level immutable default; no effect result was changed.
Package-wide checks/build belong to classified Lab fast CI, not duplicated locally.
The follow-up capture has **63 targeted tests PASS** together with the pure Attention
policy. These add real local SQLite concurrency/reopen/process-exit tests, failed
dispatch and returned-source admission cases; callbacks use synthetic local sources,
not a live retriever or external model. Changed-file Ruff/mypy pass.

The policy does not estimate unnecessary retrieval, irrelevant exposure or semantic
coverage by itself. These require independent task-visible labels. Nor do these
fixtures measure reported tokens, latency, native quality or causal benefit. Output
use stays UNKNOWN; claim ceiling is `POLICY_DECISION_NOT_EFFECT`.

Before an effect comparison: establish real state/coverage opportunities, predeclare
labels and STATIC baseline, integrate the bounded runner/complete cost settlement,
freeze IDs/order/arms/conditions and finalize a **new finite authorization contract**.
The user's subsequent “授权” authorizes a finite batch in principle; numerical bounds,
joint mechanism allocation and permission to form new state/revisions from existing
feedback still await explicit contract confirmation. No new allocation is opened.
Include initial retrieval, embedding, state formation, review/maintenance, failures, retries,
solver and latency costs. Utility's closed batch and unused quota remain closed.
No TEST/main-confirmation/Travel/RESERVE access, transfer or promotion is authorized.
3C-3 remains IN_PROGRESS with no cost/evidence comparison or KEEP_SIMPLE terminal;
3C-2 and the overall Goal likewise remain incomplete.

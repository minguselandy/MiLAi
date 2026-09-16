# DG-17 Semantic Read operator runbook

Status: opened-development operation guide for local MCP. Runtime and Schema remain
`CANDIDATE / EXPERIMENTAL / NO-GO FOR FREEZE`.

This runbook covers the DG-17 semantic read plane. It does not authorize a formal
holdout run, production rollout, Reader tuning, graph expansion, automatic retry,
or a SemanticRepair product route.

Historical Q0 measurement/oracle receipts remain immutable but non-authoritative
for causal attribution. Their disposition is recorded in
`docs/dg17/q0-receipt-lineage-disposition.v0.1.json`; a corrected multi-seed oracle
now exists at
`var/dg17/q0/dg17-q0-multiseed-20260827-001/receipt.json`. It used sealed actual
compiler IR and 120 fresh Reader calls, but remains provisional while the
answer-bearing annotation manifest has no independent review or adjudication.

## Ownership and data boundary

The product path has one deterministic owner:

```text
ordinary MCP query
→ Runtime QueryPlanner
→ MemoryQueryIR v0.2
→ Evidence requirements
→ bounded Evidence acquisition
→ EvidenceSpan
→ EvidenceInterpretationCandidate
→ RequirementBinding
→ SufficiencyDecision
→ deterministic operator or Runtime MemoryContext
→ frozen Reader once
```

Raw Evidence is primary and lossless. `EvidenceSpan` is only an exact source
pointer, an interpretation is a fallible candidate, and a binding is query-local.
None of them has canonical authority. The eval adapter may consume Runtime output,
but it must not select its own windows, invent operands, or decide completeness.

## Supported behavior

| Family | Completion requirement | Terminal product behavior |
| --- | --- | --- |
| `LOOKUP` | `TOP_K_ACCEPTABLE` | bounded governed Evidence context; no auxiliary model |
| `TEMPORAL_FILTER` | target event binding plus resolved query time axis | deterministic selected event or typed partial |
| `TEMPORAL_ORDER` | both event bindings and compatible event times | deterministic ordering or typed partial |
| `TEMPORAL_DISTANCE` | both event bindings and compatible event times | scalar duration with unit or typed partial |
| `COUNT` | closed-open range, closed source partition, covered watermark, stable event identity | complete count or typed partial; Top-k never proves completeness |
| `DIVIDE` | unique compatible total and count bindings with same entity/purpose | scalar division or typed partial |
| `MULTI_JOIN` | every required binding and declared join compatibility | bounded joined Evidence or typed partial |
| `PREFERENCE_RESOLVE` | user Evidence signals only | `EVIDENCE_ONLY / DERIVED_VIEW`; never canonical current preference |

Unsupported or unsafe surface forms must produce `AMBIGUOUS`, `PARTIAL`, or
`ABSTAINED`. Do not convert them to a safe-looking generic lookup or scalar.

## Time and count rules

- Keep source-observed, event, and system time separate.
- Use source-observed time as the query axis only when the question explicitly asks
  when something was mentioned or observed.
- Relative event time is recalculated from the current request reference time; do
  not cache a previously resolved absolute time.
- Range count uses a closed-open query interval and event-interval overlap.
- A complete bounded scan still returns `PARTIAL / EVENT_TIME_UNRESOLVED` when a
  relevant event lacks usable event time.
- Named siblings such as twins remain distinct event identities. Deduplicate only
  on the declared, versioned event identity rule.
- Planned or cancelled events do not count as completed events. A later planning
  clause must not erase an explicitly completed past event in the same Evidence.

## `EvidenceAtom v0.1` transition disposition

`EvidenceAtom v0.1` is retained only as an internal compatibility DTO in
`runtime/src/milai/application/evidence_atoms.py` and
`runtime/src/milai/domain/memory_query_ir.py`.

Its disposition is fixed:

- it is not a persisted or public MCP object;
- it is not canonical and cannot mutate `ClaimHead`;
- it is projected from v0.2 span/interpretation objects;
- it embeds no final requirement slot or `RequirementBinding` decision;
- new execution code uses `EvidenceSpan`, `EvidenceInterpretationCandidate`, and
  `RequirementBinding` directly;
- the v0.1 QueryIR translator is the only compatibility boundary;
- removal is allowed after the current matched transition has no v0.1 consumer.

Do not add new product semantics, benchmark wording branches, authority, or slot
ownership to `EvidenceAtom v0.1`.

## SemanticQueryHint and SemanticRepair

Q3C is shadow-only. A minimal hint is untrusted and cannot change the product route,
declare Evidence complete, bind requirements, decide authority/currentness, or
answer the user. Each shadow cell allows one call, strict JSON schema, at most 96
completion tokens, temperature 0, disabled reasoning, and zero retries. The
full-plan arm is a negative control and is never consumed by the product.

The Q3C classification prompt receives only the query and reference time; its
missing-requirement list and Evidence previews are empty. A separately labeled
repair lane may receive bounded missing requirements/previews, but that is not
independent classifier evidence. Neither lane may receive the deterministic route,
operator family, gold IR, or any other teacher target. The authored multilingual
fixtures are opened-development diagnostics, not unseen or held-out data.

Do not enable Q3D unless a completed Q3C receipt proves a useful independently
measured parser/coverage mediator, zero wrong promoted hints, and the Semantic
Assist Gate.
If deterministic-only passes Q6 or Q3C has no stable gain, record Q3D as
`PARKED_NOT_NEEDED`.

The completed fixed live shadow is
`var/dg17/q3c/dg17-q3c-shadow-20260827-004/report.json`, SHA-256
`29227f554f941d340bbefcf330b4993ef362815df446fd052e059e5a26bc9cb5`.
It contains 29 minimal calls and 29 full-plan negative controls, zero retries and
zero product-path consumption. The deterministic compiler is correct on 25/25
declared-supported authored fixtures; the minimal hint is correct on 17/25, with
seven wrong promotions and three schema/span rejections. Its provider p95 is
265.404 ms and the full-plan/minimal completion-token ratio is 12.295x. This is an
`AUTHORED_DEV_NO_HELDOUT_CLAIM` characterization, so Q3D is
`PARKED_NOT_NEEDED` and SemanticAssist remains disabled/parked.

## Typed terminal handling

| Condition | Required outcome |
| --- | --- |
| missing required binding | `PARTIAL`; list the missing slot and reason |
| ambiguous interpretation or incompatible join | `PARTIAL` or `AMBIGUOUS`; no guessed value |
| unresolved event time in a relevant bounded count | `PARTIAL / EVENT_TIME_UNRESOLVED` |
| unbounded count domain | no complete scalar |
| source time used without explicit source-axis query | reject the temporal binding |
| preference support without canonical state | `EVIDENCE_ONLY / DERIVED_VIEW` |
| denied, revoked, retained-unreadable, or wrong-scope Evidence | exclude and trace it |
| projection gap or uncovered watermark | `PARTIAL`; no completeness claim |
| invalid semantic hint or timeout | typed rejection; zero retry and no silent route change |
| Reader failure | terminal provider failure; Memory state unchanged |

Every deterministic result must report source Evidence IDs/turn refs,
`canonical_mutation=false`, and `hidden_model_calls=0`.

## Q1R Reader Context and matched-causality boundary

Ordinary Reader prose uses only deterministic local aliases such as `D1`, `C1`,
`E1`, and `I1`. Random Evidence UUIDs, source refs, trace IDs, hashes, and other
execution identity remain in `ContextReceipt.receipt_mapping`; they are not copied
into ordinary Reader prose. The mapping must round-trip every selected Evidence
ID, source turn ref, claim version, and issue revision without loss.

Every Runtime Context records both:

- `semantic_context_digest`, covering evidence prose, speaker/time annotations,
  scope/authority, bindings, sufficiency/status, derived result, and selected order;
- `reader_context_digest`, covering the exact UTF-8 Context bytes sent to the
  Reader.

The Q1R runner accepts only a sealed `milai.dg17.q1r-context-pairs.v0.1` archive.
Each case has one content-addressed immutable Evidence snapshot shared by both
`DG16_ANY_EVIDENCE_STOP` and `DG17_QUERY_SPECIFIC_STOP`; contexts from historical
runs and historical answers are rejected. Main calls for both policies are fresh,
adjacent within one planned run window, use the same model, prompt contract,
generation contract, budget, case order, and arm-independent seed, and have zero
automatic retries.

Same semantic mediators require the same semantic digest, exact Reader bytes, and
exact serialized prompt digest. A policy may change selected sources/order,
evidence prose, speaker/time, scope/authority, binding annotations, status,
sufficiency, derived result, or truncation; every such mediator is recorded. Any
other or unexplained difference is `CONFOUNDED / EXCLUDED FROM CAUSAL CLAIM`.

When a previously-correct case regresses, or semantically equivalent Context
produces different primary answers, the runner performs exactly three independent
diagnostic repeats of each unique frozen prompt. These are diagnostics, not retries;
all answers and agreement are reported, and no repeat may replace the primary
result.

## Failure isolation

Stop a batch at the first failed cell. Select one case and one stage from:

```text
QUERY_COMPILER
ACQUISITION
SPAN_PROJECTION
INTERPRETATION
REQUIREMENT_BINDING
SUFFICIENCY
OPERATOR
CONTEXT_COMPILER
READER
SCORER
```

Inspect the actual IR, candidates, bindings, completeness receipt, context, and
provider receipt. Change one root cause, rerun the focused test, then rerun the
matched slice. Do not change parser, retrieval, Reader prompt, and scorer together.
Do not increase budget, retry, remove a case, or lower a gate to hide a failure.

## Local deterministic verification

These commands do not start a database or call a model:

```bash
cd runtime
uv run pytest -q tests/unit
uv run pytest -q tests/contract
uv run mypy --strict src/milai
uv run ruff check src/milai tests/unit
```

```bash
PYTHONPATH=runtime/src runtime/.venv/bin/python -m pytest -q \
  tests/test_dg17_measurement.py \
  tests/test_dg17_semantic_crosswalk.py \
  tests/test_dg17_semantic_shadow.py \
  tests/test_dg17_product_verticals.py \
  tests/test_dg17_q1r_causality.py \
  tests/test_dg17_q6_preflight.py \
  tests/test_dg17_q6_matched.py \
  tests/test_dg16_reader_stability.py
```

Regenerate deterministic Q4/Q5 and Q6 preflight receipts only with fresh run IDs:

```bash
PYTHONPATH=runtime/src runtime/.venv/bin/python \
  scripts/run_dg17_q4_q5_product_verticals.py \
  --run-id dg17-q4q5-product-YYYYMMDD-NNN

PYTHONPATH=runtime/src runtime/.venv/bin/python \
  scripts/run_dg17_q6_preflight.py \
  --run-id dg17-q6-preflight-YYYYMMDD-NNN \
  --local-gate-receipt \
  var/dg17/local-gate/dg17-local-gate-YYYYMMDD-NNN/receipt.json
```

The current Q4/Q5 product-vertical artifacts are:

```text
Q4 var/dg17/q4/dg17-q4q5-product-20260827-003/report.json
   sha256 e0baf2924f6dd95eebc5d16f17961186db8cf95a35b411d101aa1c15598ca524
Q5 var/dg17/q5/dg17-q4q5-product-20260827-003/report.json
   sha256 6c11309e4f7d99c4fed094a3bb24436b4763f6cae2ecdbbd4630573861123195
```

Q4 is an oracle-required-Evidence operator-isolation trace over seven opened-dev
cases; Q5 includes explicitly synthetic safety boundaries. Treat them as Runtime
mechanism/safety gates, not live-retrieval, Reader-quality, or held-out evidence.

## External matched execution

Run these only when the owner has resumed external experiments and the fixed local
vLLM identity is available. Never restart or reconfigure that service from this
lane.

First produce a sealed same-snapshot Q1R Context archive using the Runtime-owned
Context compiler. Then run the fresh Q1R Reader pair. The archive must not be built
from the old DG16 answer/context receipt:

```bash
PYTHONPATH=runtime/src runtime/.venv/bin/python \
  scripts/run_dg17_q1r_contexts.py \
  --run-id dg17-q1r-contexts-YYYYMMDD-NNN
```

The producer waits for the Evidence, FTS, and vector projection positions before
both budgets are compiled. Its shared validator rejects Reader-visible UUIDs,
SHA-256-like opaque identities, or any true provenance value retained in the
receipt mapping. Only after that archive and its exact SHA-256 pass may the Reader
pair run:

```bash
PYTHONPATH=runtime/src runtime/.venv/bin/python \
  scripts/run_dg17_q1r_matched.py \
  --run-id dg17-q1r-matched-YYYYMMDD-NNN \
  --context-archive var/dg17/q1r/<sealed-context-run>/contexts.json \
  --context-archive-sha256 <exact-context-archive-sha256>
```

The current sealed Q1R inputs are:

```text
Context archive var/dg17/q1r/dg17-q1r-contexts-20260827-004/contexts.json
  sha256 35007cb9c653dff5e792c2e495cf8627c8d89309e18f1958821bf32527a95c1e
Producer receipt var/dg17/q1r/dg17-q1r-contexts-20260827-004/producer-receipt.json
  sha256 1d5cf8c014c915d18c218c648e921a3faa19c9fc13971a135bd6bcc6170ce472
Generation archive var/dg17/q1r/dg17-q1r-matched-20260827-003/generations.json
  sha256 505c4ab7e7fe0a3d7ecce5c520adc9e8307a4493d64af6b5de2585b474b17c9d
Matched receipt var/dg17/q1r/dg17-q1r-matched-20260827-003/receipt.json
  sha256 10a23068424379d0d42842223ce74b1ba98fe8e5a1537299a72e541f946ea2d1
```

The Reader runner seals an execution plan before the first call and rewrites an
unscored `progress.json` after every successful call. A provider failure writes a
`FAILED_NOT_SCOREABLE` failure receipt before labels are loaded. Never resume or
score that partial progress. The preserved pre-instrumentation failure is
`dg17-q1r-matched-20260827-002`; its failed ordinal is explicitly unknown.

Only after the Q1R gate passes, produce an unbiased Q3C shadow receipt. A Q6
preflight must explicitly set `execution_authorized=true`; paused preflights fail
closed. Then pass the exact preflight path/hash and Q3C path to Q6:

```bash
PYTHONPATH=runtime/src runtime/.venv/bin/python \
  scripts/run_dg17_q3c_shadow.py \
  --run-id dg17-q3c-shadow-YYYYMMDD-NNN \
  --model Qwen3.6-35B-A3B-FP8

PYTHONPATH=runtime/src runtime/.venv/bin/python \
  scripts/run_dg17_q6_sealed.py \
  --run-id dg17-q6-sealed-YYYYMMDD-NNN \
  --preflight var/dg17/q6/dg17-q6-preflight-YYYYMMDD-NNN/preflight.json \
  --preflight-sha256 <exact-preflight-sha256> \
  --q1r-context-archive <sealed-contexts.json> \
  --q1r-context-archive-sha256 <exact-sha256> \
  --q1r-context-producer <producer-receipt.json> \
  --q1r-context-producer-sha256 <exact-sha256> \
  --q1r-generation-archive <sealed-generations.json> \
  --q1r-generation-archive-sha256 <exact-sha256> \
  --q1r-matched-receipt <matched-receipt.json> \
  --q1r-matched-receipt-sha256 <exact-sha256> \
  --q3c-shadow-report <shadow-report.json> \
  --q3c-shadow-report-sha256 <exact-sha256>
```

The Q3C shadow may be attached only as a counterfactual cost overlay. Copying the
deterministic arm's F1/coverage into a semantic arm is forbidden; a semantic quality
arm exists only if the product path actually consumes the hint under a separately
authorized matched protocol.

Q6 must seal 20 label-free Runtime contexts and 20 Reader generations before it
opens scoring labels. The 2048 gate remains EM `>=5/10`, normalized F1 `>=0.50`,
RequiredEvidenceSetCoverage `>=0.80`, wrong COMPLETE `=0`, and regression `=0/2`
on the two previously correct cases. The 512 arm remains a constrained-context
diagnostic. Atom coverage requires exact source-turn plus normalized span identity;
the report also keeps unique-span and source-turn denominators separate. A terminal
sufficiency `COMPLETE` with missing required Evidence counts as wrong COMPLETE even
when no derived-result object exists.

The first authoritative sealed characterization is
`var/dg17/q6/dg17-q6-sealed-20260827-002/receipt.json` (sha256
`f89bc33dccb10006938e2f847fc58f0484f8ec64af33550f84adaaf78db72127`).
It is a retained `PARTIAL` negative result: current 2048 EM `2/10`, F1 `0.216`,
RequiredEvidenceSetCoverage `7/23`, and wrong COMPLETE `1`. Do not overwrite it
when scoring a remediated sealed window.

The remediated authoritative characterization is
`var/dg17/q6/dg17-q6-sealed-20260827-003/receipt.json` (sha256
`c0c98a1afc654b9e734657fd57de19abddb4268de4829320e0bb4af1aa02b4df`).
It remains `PARTIAL`: current 2048 EM `2/10`, F1 `0.227338130`,
RequiredEvidenceSetCoverage `7/23`, wrong COMPLETE `0`, answer-path mean
`692.505576 ms`, and quality/s `0.328283464`. This closes the unsafe-completion
defect but locates the remaining failure in acquisition/coverage. Q7 and the final
10-LME comparison remain prohibited while the Q6 quality gate is partial.

## Q8 fixed-control strong retrieval characterization

Q8 is an Evaluation Plane diagnostic, not a product retrieval rollout. It fixes the
current ten-case order, deterministic MemoryQueryIR, TURN Evidence primitive,
2048-token Context, Reader prompt/provider contract, and matched per-case seed. The
five acquisition/ranking arms are `TURN_BM25`, `TURN_BM25_NEIGHBOR`,
`STRONG_DENSE`, `REAL_RERANKER`, and `HYBRID`. The sixth
`TYPED_COMPOSITION_REFERENCE` arm is a cross-mechanism reference and is excluded
from single-factor attribution.

Run from the repository root with the already operator-owned services on 7860,
7861, and 7961; do not restart or reconfigure them:

```bash
set -o pipefail
PYTHONPATH=runtime/src MYPYPATH=runtime/src runtime/.venv/bin/python \
  scripts/run_dg17_q8_retrieval_ablation.py \
  --run-id dg17-q8-retrieval-ablation-YYYYMMDD-NNN \
  --q0-sha256 60cdcc64b8bad73f6a647d3f45560faa7c7b9cff8ace5514072d8bca7e7f1e80 \
  --q6-sha256 c0c98a1afc654b9e734657fd57de19abddb4268de4829320e0bb4af1aa02b4df \
  --q1r-context-sha256 35007cb9c653dff5e792c2e495cf8627c8d89309e18f1958821bf32527a95c1e \
  2>&1 | tee logs/dg17-q8-retrieval-ablation-YYYYMMDD-NNN.log
```

`execution-plan.json` is sealed before retrieval/Reader calls. `contexts.json` and
`generations.json` remain label-free; scoring labels open only after both archives
are sealed. `progress.json` is rewritten after each fresh Reader call. A failure
writes `failure-receipt.json`, performs no automatic retry, and is not scoreable.

The preserved first run is
`var/dg17/q8/dg17-q8-retrieval-ablation-20260827-001/failure-receipt.json`
(sha256 `a8ba78fe1a640364d5034bb41faf1f5a90c0dbea127ac8236a6fd0dfa7b0f931`).
It failed before labels and before any Reader call because one TURN requested 9754
embedding tokens against bge-m3's 8192-token limit. The correction is the frozen
`BGE_M3_TOKEN_PREFIX_7680_V1` index-only projection. It does not truncate the
EvidenceUnit or the Reader-visible selected TURN.

The authoritative successful receipt is
`var/dg17/q8/dg17-q8-retrieval-ablation-20260827-002/receipt.json` (sha256
`ca4c5dde4bd348f7fe860165c6b7ab4136ce776757864b355e8774dd6e8326ef`).
Its context and generation archive hashes are respectively
`6b3a45e1b09b905a6557581063c9892c3bb44279e43f341727d067fa2c03005e`
and `0f51ea0ad897621d5b1aa5885d10a073766f2d6b040b8464cf0fbbe1c20935c4`.
It completed 60/60 fresh Reader calls with zero retry/reuse/label leakage.

The central outcomes are:

```text
method                       coverage  EM      F1          path mean ms
TURN_BM25                    10/23     0/10    0.140259740  505.508433
TURN_BM25_NEIGHBOR           10/23     0/10    0.140259740  561.484888
STRONG_DENSE                 18/23     2/10    0.277685951  505.126364
REAL_RERANKER                10/23     1/10    0.154545455  969.430816
HYBRID                       16/23     1/10    0.172727273  841.753543
TYPED_COMPOSITION_REFERENCE   8/23     2/10    0.215503876  685.209993
```

Q8 coverage means selected full-TURN source-ref acquisition and is deliberately
not the Q6 semantic-binding coverage. Strong Dense's marginal retrieval mean is
89.989727 ms, but cold/context construction was 103046.631395 ms: 92 embedding
calls over 4943 items consumed 86603.888916 ms; 20 reranker calls over 400 pairs
consumed 7627.522760 ms. The 60-call Reader window consumed 23893.178630 ms and
post-seal scoring consumed 9723.079060 ms. Report both lifecycle and marginal cost.

Strong Dense demonstrates that acquisition is materially limiting, but does not
pass Q6: it still misses five atoms, and raw-turn Reader answers `21`, `7`, and
`24` omit the required `days` answer shape despite complete Evidence. Do not turn
this receipt into a production dense default or a completeness proof. A product
integration or new matched Q6 successor requires a separately authorized design.

## Reader / Exact-Match stability boundary

A near-exact answer with high normalized F1 but EM 0 is a scorer/Reader boundary
candidate, not proof of retrieval failure. Keep the frozen scorer unchanged and
report answer variants separately. Do not retry a Q6 cell. A tiny independent
stability diagnostic may repeat a byte-identical payload under a fresh diagnostic
run ID, but its denominator must not be mixed into Q6 and it must not trigger DG16
retrieval rework by itself.

Current historical boundary evidence is
`var/dg16/reader-stability/dg16-reader-stability-20260827-001/receipt.json`. It is
an independent single-case characterization, not a current-10 quality receipt.

## Cleanup and handoff

Every live case uses an isolated namespace, verifies reader-principal write denial,
submits cleanup, waits for Evidence/FTS/vector/purge readiness, verifies no revoked
Evidence remains queryable, stops the isolated Runtime, and preserves failed run
directories. A Q6 quality PASS does not authorize release; governance, cost,
operability, and the single release-boundary review still remain separate gates.

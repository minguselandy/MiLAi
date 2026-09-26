# MiLAi Lab

MiLAi Lab is the independent research, evaluation, and benchmarking repository for
MiLAi. It is intentionally separate from the deployable product.

Latest scoped delivery: [M1 pivot Goal v18](docs/MILA_LANGMEM_M1_PIVOT_GOAL_v18.md), executing
the [v18 plan](docs/MILA_LANGMEM_M1_PIVOT_V18_DEVELOPMENT_PLAN_20260926.md).
Status: `STOPPED_M1_RECHECK_NOT_JUSTIFIED`. Proposition/support roles/completion/persistence
are implemented through the existing adapter; vLLM settings remain unchanged. V0 and decoder
probes passed, but all three small R2 runs stopped before establishing a Basis: two invalid
completion claims and one truncated output. No recheck or business action completed.
Conditional 12/20 and MERIT runs were not started; M2 is not admitted. All costs are preserved:
16 generations / 19237 tokens / 267 embedding tokens, including R1 failure and probes.
See [results](docs/MILA_LANGMEM_M1_PIVOT_V18_RESULTS_20260926.md) and
[reproduction](docs/MILA_LANGMEM_M1_PIVOT_V18_REPRODUCTION_20260926.md). No publication reruns.

Previous scoped delivery: [M1 Goal v17](docs/MILA_LANGMEM_M1_GOAL_v17.md), implementing the complete
[v17 plan](docs/MILA_LANGMEM_M1_V17_DEVELOPMENT_PLAN_20260926.md).
Status: `COMPLETE_WITH_M1_LIMITATIONS`; decision: PIVOT before M2. The opt-in adapter adds one
persistent task-local Basis, exact delivered-evidence adoption and program-owned recheck,
without changing vLLM or adding an independent State call. Final R2 completed the frozen
mechanism, original 12/20 diagnostics and arc0 5/7 without protocol failures. Adoption is 22/22
valid, but the controlled recheck retained a stale action; semantic diagnostics are 5/12,
native MERIT 4/5 and dependent 1/2. Total v17: 101 generations / 101810 tokens / 916 embedding
tokens, including preserved R1 failures and both probes. No M2, new seeds or method-benefit claim.
See [results](docs/MILA_LANGMEM_M1_V17_RESULTS_20260926.md),
[development](docs/MILA_LANGMEM_M1_V17_DEVELOPMENT_20260926.md), and
[reproduction](docs/MILA_LANGMEM_M1_V17_REPRODUCTION_20260926.md).

Previous scoped delivery: [Provenance Goal v16](docs/MILA_LANGMEM_PROVENANCE_GOAL_v16.md),
based on the [v16 development plan](docs/MILA_LANGMEM_V16_DEVELOPMENT_PLAN_20260926.md).
Status: `COMPLETE_WITH_INSTRUMENTED_BASELINE`; G0–G6 passed. B1 adds model-hidden observation,
revision, search return/request inclusion and original business-receipt tracking while preserving
B0 behavior and the original vLLM settings. Same-output raw-wire parity passed for 21 generation
and 5 embedding requests; 18 narrow tests and the required package checks passed.
Final B1 completed the original 12/20 diagnostics (semantic 7/12) and arc0 5/7 (native 4/5,
dependent 1/2), with all observations/revisions/deliveries reconciled. Costs: 55 generations /
40072 tokens, 443 embedding tokens, unknown=0, Judge=0. Baseline semantic failures remain;
there is no method-benefit claim. Decision Basis, adoption, recheck and Attention are later work.
See [results](docs/MILA_LANGMEM_PROVENANCE_V16_RESULTS_20260926.md),
[development](docs/MILA_LANGMEM_PROVENANCE_V16_DEVELOPMENT_20260926.md), and
[reproduction](docs/MILA_LANGMEM_PROVENANCE_V16_REPRODUCTION_20260926.md).

Previous scoped delivery: [LangMem foundation Goal v15](docs/MILA_LANGMEM_FOUNDATION_GOAL_v15.md),
based on the [vNext roadmap](docs/MiLAi_vNext_Development_Roadmap_20260926.md).
Status: `COMPLETE_WITH_BASELINE_FAILURES`; foundation technical gates passed. A pinned public
LangGraph/LangMem baseline now uses a JSON-action adapter with the original vLLM settings,
durable semantic Store, separate thread checkpoint and narrow business recovery.
[Results](docs/MILA_LANGMEM_FOUNDATION_V15_RESULTS_20260926.md) report final-source diagnostics
7/12 and original exposed MERIT arc0 native 4/5, dependent 1/2. Missing initial agreements,
a fabricated 5000-cent refund agreement and stale memory after a correct refund remain failures.
All costs are retained: 108 generations / 76737 charged tokens (71846 known + 4891 unknown
reservation) / 836 embedding tokens, Judge=0. See the
[development record](docs/MILA_LANGMEM_FOUNDATION_V15_DEVELOPMENT_20260926.md) and
[reproduction entry](docs/MILA_LANGMEM_FOUNDATION_V15_REPRODUCTION_20260926.md).
v14 stays frozen; v16 B1 is delivered above. Sparse Basis and State-Attention require later Goals. No new seeds or Product changes.

Previous scoped delivery: [Semantic boundary Goal v14.0](docs/MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v14.0_20260926.md)
and [detailed design](docs/MILA_CONTEXTUAL_USER_MEMORY_V14_SEMANTIC_BOUNDARY_DESIGN_20260926.md).
Status: `IMPLEMENTED_WITH_OPEN_SEMANTIC_FAILURES`. A–D, narrow contract checks, staged V1
diagnostics and final-source V2 are delivered. The frontier, journal-grounded action references
and persistent-prose/literal checks are implemented, but semantic readiness is not met.
[Results](docs/CONTEXTUAL_USER_MEMORY_V14_RESULTS_20260926.md) report native 4/5,
dependent 1/2 and Host 7/7; initial agreements remain unsaved and one successful refund leaves
stale current memory. V1 also retains answer-grounding and task-completion failures.
All costs remain: 80 generations / 317098 generation tokens / 1540 embedding tokens,
unknown=0, Judge=0. V3 was not run because the semantic gate failed; no State-Attention comparison.
See the [development record](docs/CONTEXTUAL_USER_MEMORY_V14_DEVELOPMENT_20260926.md)
and [reproduction instructions](docs/CONTEXTUAL_USER_MEMORY_V14_REPRODUCE.md).

Previous scoped delivery: [Continuous runtime Goal v13.0](docs/MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v13.0_20260925.md).
The current v12 notes template now works through the official preparation and MERIT runner;
write receipts expose existing repair IDs and unresolved attempts before finish. Relevant
core/recovery checks passed 28 tests and preparation/adapter checks passed 10 tests.
[Results](docs/CONTEXTUAL_USER_MEMORY_V13_RESULTS_20260925.md) report final-source native
4/5, dependent 2/2 and Host/maintenance 7/7. First-agreement persistence remains NOT_MET;
an ineffective prompt diagnostic was reverted. Both complete runs and all costs remain:
56 generations / 345375 generation tokens / 2797 embedding tokens, unknown=0, Judge=0.
Status: `COMPLETE_WITH_NEGATIVE_OR_UNCERTAIN_EFFECT`, not full semantic acceptance.
[Development](docs/CONTEXTUAL_USER_MEMORY_V13_DEVELOPMENT_20260925.md) and
[running instructions](docs/CONTEXTUAL_USER_MEMORY_V13_REPRODUCE.md) preserve the scope.
No new memory candidate, sidecar protocol, or Attention comparison is included.

Previous completed scoped engineering: [Write and maintenance repair Goal v12.0](docs/MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v12.0_20260925.md).
Status: `COMPLETE_WITH_SCOPED_ENGINEERING_VALIDATION`. Exact-object visibility, actionable
revision, failed-write handling, snapshot recovery and compact shared tools are implemented.
Selected native suffixes updated the original records; natural and controlled maintenance
recovery repeated no business action. A zero-write completion miss remains preserved in R3;
a generic finish-tool clarification repaired that same isolated message in R4.
The [results](docs/CONTEXTUAL_USER_MEMORY_V12_RESULTS_20260925.md) separate business success,
Host completion and current-record semantics, with all failures and costs: 38 generations /
323992 generation tokens / 2383 embedding tokens, unknown=0, Judge=0.
These exposed, staged diagnostics are not a final-source full arc or a general benefit claim.
Ordinary remains default; Product is unchanged.

Previous completed scoped research: [Sparse decision-basis Goal v11.0](docs/MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v11.0_20260925.md)
and [detailed design](docs/MILA_CONTEXTUAL_USER_MEMORY_V11_SPARSE_BASIS_DESIGN_20260925.md).
The plan reduces state updates, separates change notifications from semantic revisions,
and lets ordinary search consume actionable gaps while respecting explicit queries.
It includes a frozen-selection preparation path for unseen native MERIT instances and a
small three-arm comparison after development. Status: `COMPLETE_WITH_NEGATIVE_OR_UNCERTAIN_EFFECT`.
The [results](docs/CONTEXTUAL_USER_MEMORY_V11_RESULTS_20260925.md) preserve all six R2 trajectories:
A2 scored 5/5 on both instances; arc1 A0/A1 interrupted; arc2 Notes scored 5/5 and A1 4/5.
No gap query or automatic version notice occurred. Notes cost less on the complete second
instance, so no overall or Attention benefit is established. Post-comparison R3 repairs cover
Host read-cache invalidation, search outcome metrics and error-code delivery, with 59 relevant
tests and static checks passing. R3 has no new native comparison. All failures and continuous
costs remain: 238 generations / 2453097 generation tokens / 14274 embedding tokens,
unknown=0, Judge=0. Ordinary and the v10 evidence remain unchanged; no expanded benchmark.

Previous completed scoped research: [Decision-basis Goal v10.0](docs/MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v10.0_20260925.md)
and [detailed design](docs/MILA_CONTEXTUAL_USER_MEMORY_V10_DECISION_BASIS_DESIGN_20260925.md).
V0 keeps one current decision, pins its adopted evidence, and combines state updates
with normal ReAct actions. [Development evidence](docs/CONTEXTUAL_USER_MEMORY_V10_DEVELOPMENT_20260925.md)
records implementation and validation. Ordinary remains the default. The preserved
[R1 comparison](docs/CONTEXTUAL_USER_MEMORY_V10_RESULTS_20260925.md) scored notes 5/5,
basis 3/5 with no actual adoption. The [R2 terminal comparison](docs/CONTEXTUAL_USER_MEMORY_V10_R2_RESULTS_20260925.md)
scored notes 5/5, basis 4/5; both completed 7/7 Host turns, and basis established one
real new-observation recheck and committed memory revision. Basis cost more, and automatic
version-change feedback was not observed. The scoped Goal is
`COMPLETE_WITH_NEGATIVE_OR_UNCERTAIN_EFFECT`; no general benefit is claimed. E2/E3/E4 and
StateMemBench remain NOT_RUN, the latter for lack of verified official data/license/scorer.

Completed work: [Maintenance contract Goal v9.0](docs/MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v9.0_20260925.md),
[design](docs/MILA_CONTEXTUAL_USER_MEMORY_V9_CONTRACT_REFACTOR_DESIGN_20260925.md),
[results](docs/CONTEXTUAL_USER_MEMORY_V9_RESULTS_20260925.md), and
[local reproduction](docs/CONTEXTUAL_USER_MEMORY_V9_REPRODUCE.md).
Semantic maintenance v3, truthful partial review, shared material visibility, explicit delta
basis updates and same-turn recovery are implemented. One final frozen version continuously
completed the original MERIT 5/5 (dependent 2/2, all 7 Host turns) and four document rounds.
The local full/delta comparison completed without another business action; delta was cheaper
in that comparison, but the full continuous run cost more than the v8 baseline.
All failures and charges remain: 119 generations / 966332 generation tokens / 4358 embedding
tokens, unknown=0, Judge=0. No broader benchmark, full suite or Product change; general
reliability and State benefit remain unproven.

Previous completed work: [Usable continuous memory Goal v8.0](docs/MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v8.0_20260925.md).
First writes, current-record revisions, post-action maintenance, durable runtime/recovery,
explicit source delivery and incomplete-run preservation are implemented. A real document
sequence and the same exposed MERIT arc passed scoped criteria after preserved repairs;
the final isolated episode scored 1/1 and updated its original pending card to completed.
This was staged verification, not a continuous five-episode pass on the final source.
[Results and costs](docs/CONTEXTUAL_USER_MEMORY_V8_RESULTS_20260925.md): 137 generations,
948575 generation tokens, 5432 embedding tokens, unknown=0, Judge=0.
[Experiment report](docs/MILA_CONTEXTUAL_USER_MEMORY_V8_EXPERIMENT_REPORT_20260925.md)
separates business success, actual maintenance, staged evidence and remaining costs.
[Usage](docs/CONTEXTUAL_USER_MEMORY_V8_DEVELOPMENT_20260925.md),
[ordinary default](configs/contextual-memory-v8-off.json), and
[optional State](configs/contextual-memory-v8-optional.json) are available.
No full benchmark, full suite or Product migration. General reliability and State benefit remain unproven.

Previous completed work: [Observation-driven memory Goal v7.0](docs/MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v7.0_20260925.md).
Reusable Host sessions, explicit memory/business dispatch, trusted observations, scoped
persistence, genuine revisions, optional State and explicit query projection are implemented.
Development was frozen before selecting one complete exposed native MERIT arc. The final
ordinary/off run scored 5/5 (dependent 2/2) with a real revision-to-later-action chain.
[Results and limitations](docs/CONTEXTUAL_USER_MEMORY_V7_RESULTS_20260925.md) preserve two
failed runs and all costs: 101 generations, 481877 generation tokens, 1273 embedding tokens,
unknown=0. State benefit and general reliability remain unestablished. The model still omitted
one initial write and did not refresh pending-status cards after business execution.
[Usage and generic configs](docs/CONTEXTUAL_USER_MEMORY_V7_DEVELOPMENT_20260925.md) are available.
No full benchmark, full test suite or Product migration; closed v6 evidence is unchanged.

Completed scoped work: [Semantic repair Goal v6.0](docs/MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v6.0_20260924.md).
The final three exposed questions across five fixed paths completed and passed native
scoring. Subject attribution, real revisions without self-dependencies, temporal scope,
new-preference use and State-to-search consumption were exercised; no final answer
persisted task text or advice. The [actual default](configs/contextual-memory-v6-user-scope-default.json)
completed its own small smoke. General semantic reliability remains unestablished:
broad summaries, overinterpretation and all earlier failures remain documented.

The user-requested cumulative budget and verification-count stops are removed; accounting
continues unchanged. Final validation used 43 generations; all v6 development used 243
generations, 969510 generation tokens and 93390 embedding tokens, with zero unknown usage.
The [results](docs/CONTEXTUAL_USER_MEMORY_V6_RESULTS_20260924.md) retain every failure,
source identity and stage cost. Method v10 / write v9 / ingestion v25 / material view v5
share the same source identity across the final paths. Ordinary remains the baseline,
H1–H6 and closed v5 evidence remain unchanged. No full benchmark, full suite or Product work.

The [v6 experiment report and remaining issues](docs/MILA_CONTEXTUAL_USER_MEMORY_V6_EXPERIMENT_REPORT_20260924.md)
separates actual feature execution, scoped native results, complete costs and unresolved
semantic problems, including State initialization and temporary references in stored prose.

Completed scoped engineering work: [Contextual user-memory Goal v5.0](docs/MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v5.0_20260924.md).
Contracts, compact materials, genuine interpretation revisions, and active State-to-search
consumption are implemented and exercised. The final ordinary default completed the
original task without deletion or task reset, but failed native scoring (latest 0,
contamination 1, pass 0). The separate State diagnostic passed after a concrete
initialization-schema repair; its failed attempt and all costs remain recorded.
The sole H2 comparison passed in all three arms without independent quality benefit.
Role attribution, unsupported writes and inappropriate dependencies remain Host semantic
failures; engineering completion does not establish reliable memory or a quality win.
Total use: 114/144 generation requests, 322283/750000 generation tokens and
22445/290000 embedding tokens. User-approved request partitions are default32/online112,
with accumulated use retained. Ordinary remains the baseline and H1–H6 remain frozen.
No further scoped model runs, full benchmark, full suite or Product migration are planned.
[Implementation, frozen evidence and limitations](docs/CONTEXTUAL_USER_MEMORY_V5_RESULTS_20260924.md)
remain separate from the closed v4 results.

Completed scoped Lab Goal: [Contextual user-memory execution repair v4.0](docs/MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v4.0_20260924.md).
Method v7 implements exact ingestion handles, durable local receipts, passive task
conditions and tokenizer capacity checks. The [frozen v4 ordinary configuration](configs/contextual-memory-v4-default.json)
completed a smoke on its frozen source, but an empty forget operation reset
the task context and the answer failed native scoring. One fixed STALE scene completed all 50
history batches, three probes and native scoring (1/3). The authorized C online
replay handled four fixed exposed cases: three received three-arm comparisons; one
stopped after ingestion because the relevant update was not proposed. One H2 chain
reached both actual materials and the answer. All three arms passed that case, while
H2 used 27.6% more answer tokens than ordinary. Benefit remains unestablished and Host
semantic reliability remains limited. The Goal is complete with negative or
inconclusive effect; [v4 results](docs/CONTEXTUAL_USER_MEMORY_RESULTS_20260924.md)
record failures, source identities and cumulative costs. H1–H6 stay frozen, ordinary
stays default, and untouched confirmation cases remain unused. No large tests ran.

The [v7 experiment assessment](docs/MILA_CONTEXTUAL_USER_MEMORY_EXPERIMENT_REPORT_20260924.md)
checks source snapshots, answers and cumulative cost. It distinguishes the current
empty-forget side effect from the first smoke's nonempty deletion, identifies actual
misuse of condition fields, and prioritizes operation contracts and material costs.
This assessment adds no model calls and leaves the closed Goal and frozen scores intact.

Completed Lab development: [Contextual user-memory Goal v3.0](docs/MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v3.0_20260923.md).
The Lab runtime now implements the memory lifecycle and six candidate mechanisms.
Small native comparisons and one fixed H5 confirmation retain negative and incomplete
results. No candidate met the bar for default adoption. The [results](docs/CONTEXTUAL_USER_MEMORY_RESULTS_20260923.md)
record the actual coverage and cost. The [minimal configuration](configs/contextual-memory-v3-default.json)
uses ordinary memory and one exposed case. Host and required LLM Judges use vLLM.
Full benchmarks, full test-suite runs and Product migration remain outside this Goal.

The [development status report](docs/MILA_LAB_DEVELOPMENT_REPORT_20260924.md) independently
checks the current source and frozen results, including mechanism coverage, total
cost and long-history execution limits. The completed v4.0 follow-up records its
repairs separately; the report and its historical evidence remain unchanged.

Previously completed work: [Host memory-control repair Goal](studies/active/MILA_HOST_MEMORY_CONTROL_REPAIR_GOAL_v1.0_20260914.md),
[results](studies/active/MILA_HOST_MEMORY_CONTROL_REPAIR_RESULTS_20260914.md),
[usage](docs/HOST_REVERSIBLE_WORKSPACE.md). Reversible workspace, same-loop ordinary policy and
public SDK recovery implemented. Limited native comparison is complete; benefit not established.
Final regression: 4573 passed / 1 optional SDK skip; engineering complete.
The [current status](docs/LAB_CURRENT_STATUS.md) distinguishes this result from earlier work.

Historical follow-up: [V0222 intent-boundary diagnostic](studies/active/MILA_V0222_BOUNDARY_DIAGNOSTIC_20260912.md)
completed16 HTTP generations: B0 exact4/8, B1 exact8/8; fixed selector INTENT_BOUNDARY_SIGNAL.
568796raw settled,0new unknown/effects;1959tests pass/1optional skip. Final independent result review PASS.
[One full-gate design](docs/V0222_PRESENTATION_FULL_GATE_DESIGN_NOT_ADMITTED.md) is scoped for offline
implementation only; full/finish, execution and Memory are not admitted by the diagnostic.

[Presentation implementation](studies/active/MILA_V0222_PRESENTATION_IMPLEMENTATION_20260912.md):
new-scope complete16+80 offline references and24effect chains verified, including40isolated Worlds;
current independent auditor revalidation PASS. Full Batch Mock16→24 and2388tests/1optional skip PASS.
[Full-gate terminal](studies/active/MILA_V0222_PRESENTATION_FULL_GATE_20260912.md):12P3 PASS,13th stopped at the phase deadline;
13generations/449759raw settled,3P3/24P4 unrun. Independent terminal review PASS; offline engineering follow-up only, no retry.
[Read-scope component](docs/V0222_ADMISSION_READ_SCOPE_OFFLINE_20260912.md):46local tests and independent review PASS;
component baseline2434tests/1optional skip PASS; actual-scale/JSON review PASS.
[Evidence adapter R2](docs/V0222_SCOPED_EVIDENCE_IMPLEMENTATION_20260912.md):64local tests/review and exact5865-file closure PASS;
full regression2498PASS/1skip; [subsequent history adapter](docs/V0222_SCOPED_HISTORY_IMPLEMENTATION_20260912.md)
recomputes57pinned ledgers (full2574PASS/1skip). [Partial scoped Batch core](docs/V0222_SCOPED_BATCH_IMPLEMENTATION_20260912.md)
has a 2707-pass/1-skip core R1 baseline; [new execution wiring](docs/V0222_SCOPED_EXECUTION_WIRING_20260912.md)
now has a 3097-pass/1-skip baseline and independently reconstructed complete Mock16→24 plus negative raw evidence.
[CPU entrypoints](docs/V0222_SCOPED_CPU_REPLAY_IMPLEMENTATION_20260912.md) have192 component passes;
current full regression67617 collected3290 and is running. Actual cold-stage timing remains unproven; no new model admission.

Original bounded execution: [V0222 P1 diagnostic](studies/active/MILA_V0222_P1_STRING_DIAGNOSTIC_20260911.md)
completed24 HTTP generations/4451raw settled; D11 uniquely selected (6/6 exact).
[P2 candidate](docs/V0222_STRING_RULES_RUNTIME_V1_DESIGN.md) admitted;96reference HTTP preflight PASS.
First P3 full output is schema-valid but selects S01 instead of authorized manager_report: permanent stop,
15P3/24P4 unrun,25batch requests/32789raw settled. [Results](studies/active/MILA_V0222_RESULTS_20260911.json).
1812tests pass/1optional skip. vLLM HTTP only, no live effects or device/service changes.
Memory/later gates NOT_TRIGGERED; [one bounded follow-up draft](docs/V0222_RESIDUAL_INTENT_BOUNDARY_DIAGNOSTIC_PLAN.md) is not an online admission.

Historical bounded check: [V0221 HTTP-only execution](studies/active/MILA_V0221_HTTP_ONLY_EXECUTION_20260911.md).
96 full reference requests pass HTTP capacity checks. First live full request returns HTTP200 and
valid full-schema JSON but changes two authorized values;1request/27864raw settled,15W2/24W3 unrun.
Batch stopped, no live business effects or direct device/container calls;1602tests pass/1optional skip.
Live compatibility NOT_MET; Memory remains unadmitted. Old unknown usage remains unknown.

Historical bounded check: [V0221 service readiness stop](studies/active/MILA_V0221_LIVE_COMPAT_AND_EXECUTION_20260911.md).
User execution scope received; container NVML failed and a diagnostic process reported no CUDA
device. W2/W3 not triggered,0model calls; no shared-service changes. No further GPU calls without
specific user agreement. Full W1 integration remains unimplemented/unadmitted.

Latest follow-up: [V02-20 Provider hardening](studies/active/MILA_V0220_PROVIDER_HARDENING_20260911.md).
Full unchanged schemas: 3 rejected/1 CPU pass; exact empty-500 wrapper path reproduced.
Unknown-usage and schema guards verified; no new model requests, no V2 resumption.

Latest completed: [V02-20 bounded validity failure](studies/active/MILA_V0220_FINAL_REPORT_20260911.md):
V0/V1 mechanical calibration passes; first full V2 requestHTTP500,1attempt/23unrun/no business effect.
Two synthetic compatibility requests settled2221raw;1V2 request has unknown usage/28284raw reservation.
V3–V5 not triggered, no Memory readmission or Product/pool/service changes.

Latest completed: [V02-19 decision](studies/active/MILA_V0219_INNOVATION_DECISION_20260911.md):
bounded F2/F3 discovery complete with validity gaps; four roots/three families,
28episodes/448requests/9,820,337raw settled. No qualified Memory regime; current profile paused,
zero candidates, F4–F6 NOT_TRIGGERED. 26reserve candidates protected, C accepted0.
[Baseline](studies/active/MILA_V0219_BASELINE_RESULTS_20260911.md) and
[failure map](studies/active/MILA_V0219_FAILURE_MAP_20260911.md) retain protocol/source/checker limits,
partial successes and semantic disputes. No Product/A0/schema change or novelty claim.

Latest completed research: [V02-18 E5 decision](studies/active/MILA_V0218_INNOVATION_DECISION_20260911.md):
KEEP_SIMPLE_NO_CANDIDATE + ENGINEERING_GAIN_ONLY. T0–T5/E0/E1/E2/E5 complete;
zero qualified mechanism candidates, E3/E4 NOT_TRIGGERED. No unopened C or established novelty.
The adapted testbed has 12 original lineages / 9 coarse families / 49 replayed branches.
[E2 controls](studies/active/MILA_V0218_E2_RESULTS_20260911.md) completed all 32 episodes:
C2 and ordinary review R1 have identical paired outcomes; unresolved/news-update failures remain.
All attempts: 1340 requests / 3,353,114 raw, settled, raw cap null; owned services stopped.
1258 tests / 1 optional skip and Lab gates pass; Product/A0/schema/deployment unchanged.
[Pinned benchmarks](studies/active/MILA_V0218_BENCHMARK_ACQUISITION_20260910.md):
three repositories and all 16,059 WMA data files upstream-hash verified; MemTrap artifact HOLD.

Latest completed admission: [V02-17 benchmark admission](studies/active/MILA_V0217_BENCHMARK_ADMISSION_20260910.md):
B0–B4 bounded audit complete, `VALIDITY_GAPS_RECORDED`; four candidates, 40 native-function
checks / 11 semantic counterexamples, 66 data-boundary/stub checks, zero Agent/model requests.
No full persistent-regulation candidate admitted; A0 unchanged; 777 tests / 1 optional skip.

Previous model experiment: [V02-16 stress discovery](studies/active/MILA_V0216_EXECUTION_20260910.md) and
[failure map](studies/active/MILA_V0216_FAILURE_MAP_20260910.md): 36 deliveries / 28 supported
correct, 118 requests / 581,953 raw; failures concern acquisition, no memory-causality claim.
Keep simple and A0 unchanged; 767 SDK-environment tests and Lab checks pass.

The active package contains only reusable experiment contracts, dataset registries,
scorers, provider configuration, artifact helpers, and public product adapters. It must
not import product internals. Product-faithful experiments run through a pinned public
MCP, OpenWorker, client, or explicitly published testkit interface.

## Repository roles

```text
src/milai_lab/        maintained experiment infrastructure
studies/active/       current and recently completed study contracts
studies/archive/      immutable legacy source snapshots; not importable APIs
configs/              versionable dataset, model, and study configuration
data/                 small fixtures and external-data manifests only
artifacts/            ignored local run output
docs/                 current goals, status, architecture, and result index
```

The pre-reorganization legacy MiLAi tree is preserved by the
`pre-codebase-reorg-v1` Git tag and inventory manifests. Its experimental code and documents are
also copied into `studies/archive/lifecycle/legacy_snapshot` for historical inspection. Those
files are not part of the `milai_lab` package and are not evidence that a current product
path is enabled.

## Quick start

```bash
uv sync --dev
uv run milai-lab-check-boundary
uv run milai-lab-verify-product --lock product.lock.json
uv run pytest
uv run ruff check src tests tools
uv run mypy src/milai_lab
uv build
```

`product.lock.json` pins the exact product tree and public interfaces used by an
experiment. If the product changes, update the lock deliberately before running a new
study; never silently accept a nearby checkout.

The repository CI validates the active Lab package and filtered legacy snapshot. Cross-repository
Product pin verification is an explicit local/release gate and must resolve to the Product identity
recorded by the study manifest.

The [HC-4 A1 guided-adoption study](studies/active/MILA_HOST_COGNITIVE_AFFORDANCE_HC4_A1.md)
completed a third four-session chain with bounded affordance guidance and still observed zero
natural Working State calls. Its preregistered negative terminal parks self-maintained adoption;
HC4-C2 usefulness remains not evaluable.

## Experiment arm kinds

- `PRODUCT_BLACK_BOX`: public product interface only; may support a product-effect claim.
- `PRODUCT_TESTKIT`: published testkit and read-only diagnostics; engineering evidence.
- `RESEARCH_PROTOTYPE`: Lab-owned method; cannot be presented as product behavior.
- `SIMULATION`: synthetic or surrogate execution; mechanism evidence only.

See [Lab architecture](docs/LAB_ARCHITECTURE.md) and
[current status](docs/LAB_CURRENT_STATUS.md). The first
[HC-4 cross-session usability run](studies/active/MILA_HOST_COGNITIVE_AFFORDANCE_HC4.md) stopped at
its frozen sample gate with 8 real sessions, 2 chains, 0 continuation sessions and 0/8 natural
Working State use. This is an invocation/non-adoption signal, but the minimum sample prevents a
PASS/PARKED effect verdict. Its genuine retrieval and recollection coding work completed with a
fresh-PostgreSQL 912-pass Runtime gate and no HC/schema/MCP change. The active
[Product-11 X0 plan](refine-logs/EXPERIMENT_PLAN.md) has completed a label-blind 24-case/238-event A0
trace with fresh DB, Canonical=0, label-access=0 and cleanup gates passing. Its later PENDING proxy
join found `0 continuation / 8 intra-source / 16 control` opportunities; human completion remains
0/24. The [human review runbook](docs/PRODUCT11_X0_HUMAN_REVIEW_RUNBOOK.md) now provides separate
proposal-free annotator/reviewer submissions and a fail-closed exact-agreement merger; opportunity
fields are derived from frozen A0 only after agreement. Product behavior, migration and effect runs
are still stage-gated. Execution is now externally blocked awaiting those two genuine files; this is
not an experiment verdict. Formal access/scoring remains false/0. The completed
[Product-10 instance-preserving continuation diagnostic](../MiLAi-Product/docs/goals/MILA_PRODUCT-10_COMPLETION_AUDIT.md)
measured
distinct historical-instance coverage and tested two same-pool admission repairs. The final repair
gained three groups but lost three and missed the mean-gain threshold, ending
`PARKED_PRODUCT10_INSTANCE_COVERAGE_UNRESOLVED`; too few continuation opportunities prevented X3/X4,
and formal 500 remained unconsumed. All instance labels stayed Lab-only. The completed
[Product-09 persistent Codex HTTP lifecycle](studies/active/MILA_PRODUCT-09_CODEX_HTTP_PERSISTENT_MEMORY.md)
records a bounded local integration smoke and one opened-development normalized EM/F1 `3/4 / 0.75`
diagnostic. A provisional integrity audit limits this to documentary evidence and requires a sealed A0
rerun; the 500-case files were accessed but no formal 500-case scoring run occurred. The completed
[Product-08 Codex HTTP MCP E2E](studies/active/MILA_PRODUCT-08_HOST_REASONING_MCP_E2E.md)
passed required-memory, no-memory and continuation behavior with real Codex over authenticated
Streamable HTTP. It validates the Host/MCP facade, not real-database retrieval quality. The
separate default-OFF
[Product-08 Context repair](studies/active/MILA_PRODUCT-08_CONTEXT_REPAIR.md) publishes a frozen
snapshot C/X/Y testkit and Lab gate runner. Its real-Dense 24-case run is still pending, so it does
not supersede the direct baseline or authorize the formal holdout. The completed
[Product-07 same-pool EvidenceSet selection and reliable consumption](refine-logs/EXPERIMENT_PLAN.md), tracked in
[the Product-07 experiment tracker](refine-logs/EXPERIMENT_TRACKER.md), ended
`PARKED_PRODUCT07_NO_GENERAL_EVIDENCE_GAIN`. B1 passed V0 development but regressed the frozen R3
Context comparison; direct remains selected, H2 was not entered, and formal 500 remains unconsumed.
The preceding completed experiment is
[Product-06 model-native Reader](refine-logs/EXPERIMENT_PLAN_20260903_080031.md), with its final
[tracker](refine-logs/EXPERIMENT_TRACKER_20260903_080031.md).
The earlier Product-02 answer-turn and U3 decision is
[here](studies/active/MILA_PRODUCT-02_ANSWER_TURN_DECISION.md).
Its post-terminal representative-case analysis is
[Product-02 128-case failure families](docs/PRODUCT02_128_FAILURE_FAMILIES.md); this report is a
diagnostic input to Product-03 and does not authorize an experiment by itself.

The latest Product-03 follow-up is the
[real OpenWorker LongMemEval usability replay](studies/active/MILA_PRODUCT-03_OPENWORKER_LME_SIMULATION.md).
Its opt-in V02 budget produced two passing ordinary lookups and one explicit semantic count miss;
the formal 500-case holdout remains unconsumed.

Product-05 finished
`PARTIAL_PRODUCT05_MEMORY_LIFECYCLE_USABLE_READER_CONSUMPTION_UNRESOLVED`. Host-owned capture,
restart persistence and two-tenant isolation passed. Generic fixed-Context evidence-use treatments
did not pass H2 after three bounded repair rounds, so direct Reader remains selected and the gated
24-case S2 was not entered. The formal 500-case holdout remains unauthorized and unconsumed.

2026-09-25：v7 开发和限定原生评估已完成；实际能力及限制见上方结果。

# MiLAi Lab

MiLAi Lab is the independent research, evaluation, and benchmarking repository for
MiLAi. It is intentionally separate from the deployable product.

Current work: [Host memory-control repair Goal](studies/active/MILA_HOST_MEMORY_CONTROL_REPAIR_GOAL_v1.0_20260914.md),
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

The legacy MiLAi repository remains untouched. Its experimental code and documents are
copied into `studies/archive/lifecycle/legacy_snapshot` for historical inspection. Those
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
Product pin verification remains an explicit local/release gate until the first Product commit and
remote repository identity are established.

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

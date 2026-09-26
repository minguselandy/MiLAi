# MiLAi Lab agent instructions

## Scope

This repository owns experiments, evaluation contracts, benchmark adapters, scoring,
analysis, and historical research source. It does not own MiLAi product behavior or
canonical memory state.

## Hard boundaries

1. `src/milai_lab` must never import `milai`, `milai_client`, `evals`, `scripts`, or any
   legacy source module.
2. A `PRODUCT_BLACK_BOX` arm uses only interfaces pinned by `product.lock.json`.
3. A `PRODUCT_TESTKIT` arm may use only a separately published public testkit or
   read-only trace contract. Private product helpers remain forbidden.
4. `RESEARCH_PROTOTYPE` and `SIMULATION` results must not be described as product
   behavior.
5. Benchmark corpora, model weights, venvs, caches, raw Provider transcripts, and run
   artifacts stay outside Git. Git stores manifests and compact terminal results.
6. Archived code is historical evidence, not an active dependency. Do not add archive
   paths to `sys.path`.
7. The Lab never writes canonical product tables directly. Stateful product experiments
   use isolated instances through published interfaces.
8. Preserve failed experimental evidence, but prefer one compact failure record over
   duplicating environments or source trees per attempt.

## Efficient development

- Start with the smallest falsifiable slice, then scale only after execution validity.
- Fail a case, not the whole development program, when a local repair is safe and
  generalizable.
- Diagnose infrastructure failures separately from semantic misses.
- Do not add case IDs, gold terms, benchmark-specific synonyms, or post-outcome routing.
- Use parallel execution only within declared service and database capacity.
- Keep product and research claims tied to the declared `ExperimentArmKind`.

## Required checks

The user activated the full [long-horizon master plan](docs/MILAI_LONG_HORIZON_MASTER_DEVELOPMENT_PLAN_20260926.md),
tracked by [the execution Goal](docs/MILAI_LONG_HORIZON_EXECUTION_GOAL.md).
This supersedes prior closed-stage restrictions for the new research scope; preserve their
historical artifacts and conclusions. Follow P0–P12 without declaring the master Goal done
after a narrow slice. Start with [v20 SER](docs/MILAI_SER_V20_GOAL.md): request-level ordinary
assistant lineage and request-copy demotion, then original controls and non-temperature
generalization. Failure requires first-broken-link localization, competing hypotheses and a
minimal general repair/counterexample; do not stop merely because the first candidate fails.
One existing Sol xhigh owns source/config/CI and necessary narrow checks; Root owns docs,
fixtures/rubrics, freezes, all real model/embedding calls (concurrency 1), analysis and cost;
Luna high owns authorized publication and any needed downloads. Keep vLLM unchanged during
primary development. Avoid defensive platform growth, redundant audits/tests and benchmark
heuristics. Method freeze precedes unseen matched evaluation and sensitivity. Product, old
contextual runtime, M1 and structured ODR remain outside the active method. Conditional
capsule/action grounding/Attention/Jev require the evidence described in the master plan.

P3 original controls pass 3/3; P4 non-temperature controls pass 5/5 mechanism/final-action
checks. Preserve the assistant-only intermediate false search claim and all 41 generations /
36834 tokens / 589 embedding tokens / 18 exact reads. P4 mapping is
`7de0f597d54ddce43f77448bdb4aba093a90f4dec1c3ff6975b23e0f6b57d20b`;
do not rewrite the executed P4 lock when starting P5. The 31 affected tests and static/boundary
checks pass. The cumulative necessary build is deferred to the P5 source freeze, including
the known sdist `/data/diagnostics` inclusion fix; do not claim that packaging item is done.
Proceed to configurable rank-bounded refresh with preserved A4 comparator, then P6/P7.
Eight development controls are not formal/unseen efficacy and do not complete the master Goal.

P5 R1 now has the configurable A5 rank/count policy and matched A4. Preserve strict 2/6:
the four failures shorten target `item` references despite correct current numeric values;
irrelevant passes both arms, with gets 3 -> 0 but tokens 5161 -> 5213. See
[P5 R1 failure analysis](docs/MILAI_SER_V21_P5_R1_RESULTS_20260927.md). Next diagnose the
generic full-reference tool contract on only the two affected cases, not a SER semantic rule.
Mapping `142ce5dfcc5ecf0f79166cff0c1ad710daeff5e8aac3010ee74db50ad8de70e2` has 11 necessary
checks/static/boundary passes and one successful cumulative build including all diagnostics.
No need to repeat that build/test group for fixture/docs-only changes. Continuous SER costs
are 71 generations / 65327 tokens / 1035 embedding tokens / 33 exact reads.

P5 R2's two generic target-description repairs pass 4/4 without source changes. P6 R1
passes 8/9 new controls, giving explicitly variant-labeled 11/12 same-source development
coverage. Preserve [the current-conflict failure](docs/MILAI_SER_V21_P6_R1_RESULTS_20260927.md):
both CURRENT bodies are intact, but the model infers source priority from later Store
created_at, then executes despite unresolved conflict. Next independently freeze a minimal
source-authority protocol clarification and test conflict/no-stale/explicit-priority controls;
no semantic truth gate, source-value rule or vLLM change. Cumulative SER costs now include
136 generations / 128447 tokens / 1908 embedding tokens / 57 exact reads. Old P5/P6 failures
remain; the master Goal and the authority repair are active, not completed by archival.

P6 is now complete as development controls: [final P6R2/confirmation results](docs/MILAI_SER_V21_FINAL_RESULTS_20260927.md)
pass 13/13 on mapping `7ee904cba80c0facf0f513fe7607b15ea4fa5a61fc1a0553c1ef4e85144411e9`.
The only repair after P6 R1 is a generic source-authority protocol clause, adding 39 tokens
per generation; report it as model-visible intervention. Continuous SER costs are 202
generations / 195740 tokens / 2837 embedding tokens / 75 exact reads. All old failures remain.
P5's successful cumulative build closed the old v20 packaging item; the new P6R2 lock will
join the P7 CLI/config/lock in one necessary package build. Luna publishes this checkpoint,
then the same Sol implements a thin v22 exposed-regression CLI reusing original runners and
scorers. Method recipe/transport stay v21; actual B1 and A5 run identities remain distinct.
Root runs matched B1/A5 original 12-case/20-session and MERIT arc0/5-episode/7-message inputs,
with fresh namespaces and one continuous ledger. The native MERIT memory checker sees
checkpoint history; actual Provider delivery must be reported separately. P7–P12 and the
master Goal remain active. No publication-only reruns or changes to vLLM settings.

P7 R1 wiring/build and four frozen attempts are complete, but exposed regression is not:
[R1 results](docs/MILAI_SER_V22_P7_R1_RESULTS_20260927.md) show B1 diagnostic 8/12 versus A5 7/12;
both MERIT runs hit the original 12-generation per-message capacity at episode 2 after no
memory was formed. Full arc scores are unavailable. Preserve all 104 new generations /
78617 tokens / 852 embedding tokens; continuous SER is 306 / 274357 / 3689, exact reads75.
Next, after Luna checkpoint, Sol adds opt-in episode-local capacity isolation with default
false. Keep the native world-checker formula, report Host failure and skipped messages
separately, retain side effects, and stop on service/Store/instrumentation faults. Root freezes
and runs only the two affected MERIT arms first. Do not raise capacities or simultaneously
change authority. A5 has 48/52 requests with no memory items yet still adds authority; its
conditional inclusion is a separate candidate after the coverage repair. P8 remains pending.

P7 R2 [results](docs/MILAI_SER_V22_P7_R2_RESULTS_20260927.md) confirm local capacity isolation:
A5 continues to episode 3 after episode 2 failure, but native is B1 4/5 versus A5 3/5.
Preserve wrong B1 5000 refund, absent early formation, A5 null create/delete, all failures and
360 continuous generations / 332460 tokens / 3902 embedding tokens / 75 exact reads.
After Luna checkpoint, Sol makes the separate minimal authority predicate: actual projected
items or derived rebases. Empty requests return to the B1 system contract; current conflict
and assistant-only stale retain authority. No benchmark-dependent predicate or vLLM change.
Narrow offline counterexamples precede Root's new frozen matched small regression. P8–P12
remain active; lifecycle failures are separate research, not SER successes.

P7 R3/P8 are complete for method freeze, not efficacy: [R3](docs/MILAI_SER_V22_P7_R3_RESULTS_20260927.md)
has diagnostic 7/12 and MERIT4/5, dependent1/2, Host7/7. All twenty actual first diagnostic
requests equal fixed B1 reference wires, yet d11 still misses retrieval. Authority is omitted
on 49/55 actual requests; preserve all 415 generations / 373013 tokens / 4370 embedding tokens
and 75 exact reads. The [P8 freeze](docs/MILAI_SER_V22_P8_METHOD_FREEZE.md) allows one small
unseen same-source B1/a3_exact_refresh/a4_selective_rebase comparison after new selection
pre-registration and thin v23 entrypoint freeze. Keep stage v21 methods and parameters fixed,
reuse the original loop/scorer, preserve old exposed loader behavior. No task-driven method
changes, new model, vLLM adjustment or A5 efficacy claim. P9–P12/master remain ACTIVE.

P9 [v23 Goal](docs/MILAI_SER_V23_GOAL.md) now pre-registers unopened MERIT base_seed3/4,
one original 5-episode/7-message arc each, b1/a3/a4 in that order per ascending seed.
The thin entrypoint, generic frozen loader and shared original loop/scorer pass five necessary
zero-model checks and one build. Source mapping is
`1b90bad524f7ff041fb5484b95fdd91b7f18f9d6240d460ad69afc7ff8f21e07`.
Inputs were generated only after source freeze; no method or prompt change. Root owns all
six serial real runs and full cost/semantic review. Preserve all failures, no task replacement
or post-outcome tuning. Source remains frozen through this comparison; master stays active.

P9 [results](docs/MILAI_SER_V23_RESULTS_20260927.md) complete the six pre-registered runs:
B1 6/10, A3/A4 each7/10, but zero exact refresh/demotion. Keep source and all unseen outcomes
frozen; the extra point follows different capacity/formation paths, not demonstrated SER
causality. Continuous costs are 568 generations / 530611 tokens / 5057 embedding tokens /
75 exact reads. All 21 early agreement observations were unpersisted; successful later
actions leave pending prose unchanged. After Luna result checkpoint, prioritize independent
P11 Formation/Reconciliation with generic mechanisms and temporary/no-op/failure counterexamples.
Do not modify the P9 prompt or rerun seeds3/4 to improve scores. A separate second-model
endpoint question is pending; continue independent work, keep P10/P12/master unfinished.

The user reopened work with [v19 repair](docs/v19修复.md), tracked in
[the repair Goal](docs/MILA_FRESHNESS_PROJECTION_V19_REPAIR_GOAL.md). This supersedes the
old V5 restriction for this new scope: run the existing freshness_only on the three frozen
fixtures before editing source. If insufficient, implement request-copy item-level stale
quarantine; only if that is insufficient proceed to selective exact-version refresh.
One Sol xhigh owns source/config/tests/CI; Root owns docs/freeze/environment/all real requests
(concurrency 1)/cost/evaluation; Luna high retains authorized publication. Preserve old ODR/M1
methods and old results/locks/ledgers. No vLLM setting changes, reconstruction candidate,
semantic truth gate, new benchmark expansion, reviewer or State-Attention. Treat the old M1
test mismatch separately as expectation drift without changing M1 runtime semantics.
Use the smallest necessary offline checks and three-case sequential gates; stop escalating
when a simpler arm succeeds. New source-authority text must be reported as part of the
quarantine intervention, not a pure renderer-only causal comparison.

Repair development and sequential evaluation are now complete:
`COMPLETE_WITH_FRESHNESS_LIMITATIONS`; see [results](docs/MILA_FRESHNESS_PROJECTION_V19_REPAIR_RESULTS_20260926.md)
and [reproduction](docs/MILA_FRESHNESS_PROJECTION_V19_REPAIR_REPRODUCTION_20260926.md).
A1=1/3, A2=1/3, A3=2/3. A3 actually delivers X@2, yet changed still executes 4 C;
do not promote any arm as passing all controls. Retained reacquires X@2; irrelevant
keeps current X unchanged but incurs three exact Y reads, so it is not zero intervention.
Preserve all 45 generations / 41457 tokens / 808 embedding tokens and 9 exact reads;
unknown/Judge/truncation=0. Final 59-file mapping:
`bfc5c27631a9c41625446bc6cc6617e7a30417b39e23229a2ec6e85fc4105555`.
27 affected checks and the one necessary package build pass; old M1 expectation drift
is a separate test-only commit. vLLM settings, old methods/results/ledgers and plan bytes
remain unchanged. Luna's publication authorization persists; do not rerun models/tests/build
for publication or infer a new semantic rescue, reviewer, Attention or benchmark expansion.

The user explicitly authorized full execution of the 1391-line
[v19 ODR plan](docs/MILA_ON_DEMAND_RECONSTRUCTION_V19_DEVELOPMENT_PLAN_20260926.md).
[Goal v19](docs/MILA_ON_DEMAND_RECONSTRUCTION_GOAL_v19.md) is
`STOPPED_STRUCTURED_RECONSTRUCTION_NOT_JUSTIFIED`; engineering and scoped evaluation are
complete. Preserve [results](docs/MILA_ON_DEMAND_RECONSTRUCTION_V19_RESULTS_20260926.md) and
[reproduction](docs/MILA_ON_DEMAND_RECONSTRUCTION_V19_REPRODUCTION_20260926.md). The three-arm
ODR adapter, V0, five deployment probes and three small controls are delivered. Final mapping:
`1f22b6b7b032a647e360c140c61467763f7ce71b0a1fdd481d1c00ede88fbfaa`.
All 9 public messages completed; 15 responses were null reconstruction. Changed received exact
stale notices yet recorded old 4 C; retained did not read the current revision; irrelevant
behavior was undisturbed. Do not equate all-null with selective success or 0/0 grounding with
perfect support. V5/V6/V7 are NOT_RUN_GATE_NOT_MET; F-only efficacy is unknown. Preserve all
20 generations / 20360 tokens / 274 embedding tokens; unknown/Judge/truncation=0. There are
zero persistent semantic-state bytes, but factual/history/analysis storage is reported.
No further semantic rescue, automatic search, hard truth gates, M2/Attention or new data under
this completed scope. Original vLLM settings, plan bytes, old M1 methods and 16 old artifacts
are unchanged. One Sol xhigh owned source/config/tests/CI; Root owns all real requests and
evidence; Luna high retains authorized publication. No model/test/build reruns for publication.
The required new V0/static/boundary/packaging checks passed; retain the reported pre-existing
old M1 assertion mismatch (17 affected checks pass, 1 fails), without claiming the old group
was all green. Future work requires its own explicit scope; this result does not establish
that freshness-only is sufficient or that automatic retrieval is necessary.

The user-authorized [v18 pivot plan](docs/MILA_LANGMEM_M1_PIVOT_V18_DEVELOPMENT_PLAN_20260926.md)
is delivered with [Goal v18](docs/MILA_LANGMEM_M1_PIVOT_GOAL_v18.md)
`STOPPED_M1_RECHECK_NOT_JUSTIFIED`; preserve the [results](docs/MILA_LANGMEM_M1_PIVOT_V18_RESULTS_20260926.md)
and [reproduction entry](docs/MILA_LANGMEM_M1_PIVOT_V18_REPRODUCTION_20260926.md).
Proposition/support roles/completion/persistence are implemented and V0/probes passed.
Final mapping is `657b0060d8c31385fc6bbe99fdb1a42b9d4815376103983348b4038d9ef6533e`.
All three R2 small runs failed on their second public message: two no-pending completion
claims and one 4096-token truncation. No search, accepted Basis/adoption, recheck trigger,
or business execution occurred. Do not treat zero triggers as selective success, undefined
0/0 grounding as perfect, or earlier interruption as improvement. V4/V5 are NOT_RUN_GATE_NOT_MET;
M2 is not admitted. The precise section35 notified-stale-action criterion did not occur.
Preserve R1's schema-combination failure and every cost: 16 generations / 19237 tokens /
267 embedding tokens, unknown=0, Judge=0, truncation=1. No further semantic rescue runs,
fields, longer prompts, automatic search, reviewer or Attention under this completed scope.
One existing Sol xhigh owned code/config/tests/CI; Root owns all real requests and evidence;
Luna high retains authorized publication. All vLLM settings and old v17 locks/results/ledger
remain unchanged. Do not rerun models/tests/build for publication. Raw artifacts remain ignored.

The user explicitly requested execution of the full 1553-line
[v17 M1 plan](docs/MILA_LANGMEM_M1_V17_DEVELOPMENT_PLAN_20260926.md).
Current [Goal v17](docs/MILA_LANGMEM_M1_GOAL_v17.md): `COMPLETE_WITH_M1_LIMITATIONS`.
This new authorization supersedes the completed v16 B1-only restriction for this scoped work.
V17 development and full R2 small runs are complete: 12/20 diagnostics semantic 5/12, arc0
5/7 native 4/5 and dependent 1/2. Source mapping is
`392c14287062a92465f74b31e402ea65099a55cb5136a1c3939b05dd1655b66f`.
Adoption validity is 22/22; one controlled revision trigger reached two actual requests but
Host ignored it, did not acknowledge and executed stale 4 C. Preserve this and the label-like
Basis, missing memories, stale pending prose and all R1 schema failures. Decision is PIVOT
before M2, not method efficacy. Costs: 101 generations / 101810 tokens / 916 embedding tokens,
unknown=0, Judge=0. See the v17 results/reproduction docs before newly authorized work.
No automatic new runs, Attention, semantic tuning or tests/models/build for publication.
The following ownership/scope rules describe the completed v17 execution; they do not reopen it.
One existing Sol xhigh owns all M1/adapter/runner code and narrow checks. Root owns docs,
reference/lock/freeze, diagnostic inputs and scoring, unchanged environment, every real
model request (concurrency 1), continuous costs and reporting; Luna high retains publication.
Implement one task-local Basis slot, explicit adoption of actually delivered exact evidence,
program-owned selective recheck, and persistence/replay through the existing ReAct loop.
State delta and calls/answer must use the same generation. No independent State/reflection
call, hard action gate, automatic memory/retrieval policy, M2/Attention, old contextual method
reuse, Product/Archive change or new benchmark seed consumption. Keep all vLLM settings.
Preserve the user plan bytes, v16 locks/results/ledger; shared changes get a new v17 lock.
Follow reference -> implementation/necessary decoder probe -> V0 -> final freeze -> frozen
controlled mechanism diagnostic -> original 12/20 diagnostics -> original arc0 5/7 -> report.
All failed attempts and costs persist. Narrow problem-driven verification only; no full suite,
benchmark expansion or reruns for publication. A negative mechanism result remains valid
research evidence, but missing implementation/run requirements cannot be redefined as done.

The user explicitly requested execution of the updated
[provenance Goal v16](docs/MILA_LANGMEM_PROVENANCE_GOAL_v16.md), based on the
[development plan](docs/MILA_LANGMEM_V16_DEVELOPMENT_PLAN_20260926.md).
Status: `COMPLETE_WITH_INSTRUMENTED_BASELINE`; implementation superseded the historical planning-only restriction.
One Sol xhigh owns instrumentation/Store/agent/provider/runner code and narrow checks;
root owns reference and new locks/freezes, environment, real model calls (concurrency 1),
continuous costs and reporting. Luna high retains authorized publication; no standing reviewer.
A -> B–E -> F/V0 -> final freeze -> V1 -> V2 -> results is complete; G0–G6 passed.
Preserve the [v16 results](docs/MILA_LANGMEM_PROVENANCE_V16_RESULTS_20260926.md) and
[reproduction entry](docs/MILA_LANGMEM_PROVENANCE_V16_REPRODUCTION_20260926.md).
The frozen 27-file mapping is `ae089f8a1583bf4ef730b0415f4ebd782a722c72398d47ca93af4da9a7d6caea`.
18 narrow tests and original MERIT same-output raw-wire parity (21 generation / 5 embedding
requests) passed. Final B1 completed the original 12/20 diagnostics (semantic 7/12) and arc0
5/7 (native 4/5, dependent 1/2): 55 generations / 40072 tokens, 443 embedding tokens,
unknown=0, Judge=0. All 39 observations, 10 inserts, 8 searches and 62 request-material
links were reconciled. Preserve null insert, omitted memory, fabricated 5000-cent refund
and stale pending content. No natural UPDATE/DELETE occurred; source_refs remain unknown.
No M1/Basis/recheck/Attention or new seeds have started. No models/tests/build for publication.
The current scope is B1 model-hidden instrumentation only:
actual observations, memory revisions, search return/request inclusion and existing action
receipts. Preserve B0 semantics and prove same-output parity before the exposed small runs.
Do not fix baseline semantic failures or add Basis/adoption/recheck/Attention in this Goal;
the older roadmap placing M1 inside v16 is superseded by this narrower scope. Preserve
v15 locks/results, use a new source identity for B1, and keep all original vLLM settings.
Documentation checks need no pytest/build/model calls. Existing Luna high publication
authorization persists.

The user-authorized [v15 foundation Goal](docs/MILA_LANGMEM_FOUNDATION_GOAL_v15.md),
based on the [vNext roadmap](docs/MiLAi_vNext_Development_Roadmap_20260926.md), is
`COMPLETE_WITH_BASELINE_FAILURES`. A–F and G0–G5 technical gates are delivered; preserve the
[results](docs/MILA_LANGMEM_FOUNDATION_V15_RESULTS_20260926.md) and use the
[reproduction entry](docs/MILA_LANGMEM_FOUNDATION_V15_REPRODUCTION_20260926.md) for future authorized runs.
Final source mapping is `99fba610b55237aa31de8ad7f25312dc65e847d944b44b3bde1cde572b3e5ef9`.
Final R2 completed 12 diagnostics / 20 sessions (manual semantic 7/12) and the full original
arc0 / 5 episodes / 7 messages (native 4/5, dependent 1/2), without interruption.
Preserve the missing initial agreements, fabricated 5000-cent agreement and actual refund
instead of 1774, and stale pending memory after the correct 6595-cent refund.
All 108 generations / 76737 charged tokens (71846 known + 4891 unknown reservation) /
836 embedding tokens remain; Judge=0. Earlier R1 interruption and all repair costs are retained.
Eight narrow tests plus relevant static, boundary and packaging checks passed; do not rerun
models/tests for publication. Technical GO does not imply semantic readiness or start v16.
The following ownership rules apply to future authorized work:
One Sol xhigh owns adapter/graph/provider implementation and narrow checks; root owns
reference and foundation locks, environment identity, all actual model calls (concurrency 1),
continuous costs, freezes and reporting. Luna high handles required reference downloads and
authorized publication; no standing reviewer. Follow A -> B -> C -> D -> freeze -> E -> F.
Use the actual pinned upstream manage/search tools with their default contract, effective
semantic index, durable public Store, separate thread checkpoint and minimal action recovery.
The latest user instruction forbids vLLM setting changes: retain the original service
configuration and implement the explicit JSON-action adapter with its own recipe identity.
Do not use an in-memory Store to claim cold persistence, or change B0 prompts for semantic misses.
The roadmap freezes v14 as a reference and starts a
separate public LangGraph/LangMem baseline. Do not extend the old contextual runtime or port
its frontier/finish policies into B0. v15 covers foundation and exposed-set characterization;
v16/v17 instrumentation/Basis/Attention require separate scoped Goals and gates.
The old v14 semantic-readiness failure remains a historical result, not a requirement to keep
repairing that baseline before a valid public foundation can be studied. Preserve all old
results/costs and keep seeds 3/4 unconsumed in v15. Documentation checks require no pytest,
build or model calls. Existing Luna high publication authorization persists.

The user now explicitly authorizes execution of [Goal v14.0](docs/MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v14.0_20260926.md)
and its [semantic boundary design](docs/MILA_CONTEXTUAL_USER_MEMORY_V14_SEMANTIC_BOUNDARY_DESIGN_20260926.md).
Historical planning-only wording is superseded. Execution delivery is complete with status
IMPLEMENTED_WITH_OPEN_SEMANTIC_FAILURES; preserve the
[results](docs/CONTEXTUAL_USER_MEMORY_V14_RESULTS_20260926.md). Final runtime mapping is
`944cda954858d7181624fc25c72ada717d3bd973e5231b29ecab85751e7f66ab` (47 files).
A-D, V0, staged V1 and final-source original-world/empty-memory V2 were delivered.
V2 is native 4/5, dependent 1/2, Host/maintenance 7/7, but initial agreement retention is
0/2 and the successful final refund leaves a stale CURRENT card. V1 d11 still loses the
future reminder; d02 unsupported-location and d04 task-format failures remain open.
Do not combine favorable results from different V1 source rounds or call this baseline ready.
V3 is NOT_RUN because semantic gates failed; no new seeds were generated/read.
Preserve all 80 generations / 317098 generation tokens / 1540 embedding tokens,
unknown=0, Judge=0, including all failed diagnostics. Do not repeat models/tests for publication
or restart State-Attention research. Read the reproduction entry before any newly authorized run.
The following execution rules remain relevant to future authorized work:
Keep v13's runtime/results as the sealed baseline. One Sol xhigh owns core/Host integration;
root owns freezes, diagnostic inputs, continuous costs and all real model requests (concurrency 1).
Reuse existing pending/frontier/journal. A source citation is not complete semantic handling,
a valid successful-action-ref subset is not truthful prose, and issued handles can collide
with genuine literal text; keep these limits visible in tests and real diagnostic review.
Implement A-D before freezing V1's nine matrix cases and at most three controls. Then V2
uses the exposed original arc0 from empty memory. V3's two new original arcs are conditional
on V1/V2 semantic gates; exclude actually exposed seeds/duplicate hashes prospectively,
never read samples to cherry-pick them. No State-Attention comparison or broad test suite.
Use independent v14 notes configuration/new maintenance identity, unchanged native data/scoring,
no Product work, source cleanup, new database or semantic review agent. Keep G1-G4 separate
from native score and Host complete. Preserve all v13 failures and 56 generations / 345375
generation tokens / 2797 embedding tokens. V14 gets a continuous ledger with null cumulative
caps; failures/repairs count and per-workflow capacity remains. Narrow affected tests/static
checks; decoder probes for changed schema, no build/boundary suite without relevant changes.
Existing user authorization for Luna high publication persists.

The user-authorized [Goal v13.0](docs/MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v13.0_20260925.md)
is `COMPLETE_WITH_NEGATIVE_OR_UNCERTAIN_EFFECT`; preserve the
[results](docs/CONTEXTUAL_USER_MEMORY_V13_RESULTS_20260925.md). The current v12 notes template
now has an official prepare/run path, and Host receipts expose existing unresolved repair
IDs without auto-clearing failed writes. Relevant checks passed 38 tests plus static checks.
Final runtime mapping is `5c92005f5e7f2b36c6716dcd8cf5ce1c05091f06fe47141c9f37474c6ff9a773`:
all 46 files match R1's complete original-world/empty-memory run. Native 4/5, dependent 2/2
and Host/maintenance 7/7 do not establish semantic acceptance: first-agreement persistence
is NOT_MET, R1 claimed escalation without a receipt, and durable prose retained session aliases.
R2's first-agreement prompt clarification did not fix the omission and was reverted;
its 4/5 result and distinct, more careful approval wording remain diagnostic evidence.
Do not combine R1 and R2's favorable parts, claim live repair-guidance savings (no natural
write rejection), or present this exposed arc as unseen validation. Preserve all 56 generations /
345375 generation tokens / 2797 embedding tokens, unknown=0, Judge=0, truncations=0.
Ordinary/notes/off, thinking=false, action/maintenance schemas and disk format remain unchanged.
No Product change, new candidate, Attention comparison or package move. Do not add model
runs or repeat tests for publication; prior Luna high publication authorization persists.
Raw transcripts, databases, model files and the rejected R2 source snapshot stay ignored.

The user-authorized [Goal v12.0](docs/MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v12.0_20260925.md)
is `COMPLETE_WITH_SCOPED_ENGINEERING_VALIDATION`; preserve the
[results](docs/CONTEXTUAL_USER_MEMORY_V12_RESULTS_20260925.md). Final R4 mapping is
`f39d8170f168a56d21057a3079fdaed21a5cb6d32e852687544dd740df8955d0`.
Implementation covers exact resident visibility, actionable revisions, failed-write repair or
reasoned abandonment, unchanged-format snapshot recovery and compact shared tools.
R1 corrected both original amounts and consumed the current amount, then maintenance
truncated; R2 zero-model preparation failed on tuple/list binding spans. R3 repaired the
snapshot representation and completed natural/controlled maintenance without repeating
business actions. R3 also preserved a zero-write semantic miss; R4's single generic finish
purpose clarification passed that same isolated native message and updated the original card.
Do not relabel mixed v11 prefixes and R1/R3/R4 suffixes as a final-source full arc, unseen
validation or general reliability. Preserve all 38 generations / 323992 generation tokens /
2383 embedding tokens, unknown=0, Judge=0, including earlier failures. Final same-schema
shared tool text is 4080 -> 1915 tokens; this does not prove total task savings. Ordinary and
thinking=false remain the delivered default; no Attention comparison or sidecar change.
No new compatibility format, Product API/schema/permission/Canonical change or package move.
Do not restart completed diagnostics or broaden tests merely for publication. Existing user
authorization for Luna high publication persists. New development, if authorized, retains
one Sol xhigh core owner, one real model controller/concurrency 1, narrow checks and
continuous accounting; no standing reviewer. Raw transcripts, databases and models stay ignored.

The user explicitly authorized execution of [Goal v11.0](docs/MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v11.0_20260925.md)
and its [sparse-basis design](docs/MILA_CONTEXTUAL_USER_MEMORY_V11_SPARSE_BASIS_DESIGN_20260925.md).
The scoped Goal is `COMPLETE_WITH_NEGATIVE_OR_UNCERTAIN_EFFECT`; preserve the
[results](docs/CONTEXTUAL_USER_MEMORY_V11_RESULTS_20260925.md). All six R2 trajectories use
mapping `2a95dcd0fde0e90a4eff053b5875d0f6d07a3ec61961fd158201c312102d1cf4`: A2 scored 5/5 on
both instances; arc1 A0/A1 interrupted; arc2 Notes 5/5 and A1 4/5. No automatic gap query or
version notice occurred; ordinary stays default. R3 fixes Host read-cache invalidation,
search outcome metrics and error-code projection under mapping
`666344907d0ef59f171431ebc7e572b92bf68fae2378f82fc32dc8df4fff7c12`, with 59 related tests and
static checks passing, no new model calls. Do not represent R2 as R3 unseen validation.
Keep exposed-arc failures, all F interruptions and continuous v11 charges of 238 generations /
2453097 generation tokens / 14274 embedding tokens, unknown=0, Judge=0. Do not restart
completed arms, substitute seeds, expand the benchmark or promote an unobserved mechanism.
Keep ordinary default, v10 evidence sealed and native scoring unchanged.

The user explicitly authorized execution of [Goal v10.0](docs/MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v10.0_20260925.md)
and its detailed design. Planning-only wording is historical. Follow A → B–D implementation
and narrow checks → E frozen original small selection → F staged real comparisons. Keep one
Sol xhigh owner for the core/Host/session integration; Luna high handles official downloads
and user-authorized publication. No standing review agent. One model controller, concurrency 1.
StateMemBench availability is a separate evidence question; do not invent or rename data.
Keep ordinary default, old State/H1–H6 frozen, Lab-only scope, existing identity/permission/
lifecycle/recovery guarantees, and continuous new v10 accounting that cites sealed v9 costs.
No full suite or benchmark, no Product migration. No fresh model run before development freeze.
Preserve [R1](docs/CONTEXTUAL_USER_MEMORY_V10_RESULTS_20260925.md) as a historical failed
comparison: notes 5/5, basis 3/5, basis all null, 51 generations / 452656 generation
tokens / 3955 embedding tokens. [R2](docs/CONTEXTUAL_USER_MEMORY_V10_R2_RESULTS_20260925.md)
on the same exposed original arc scored notes 5/5, basis 4/5, both 7/7 Host complete;
basis established one exact-adoption → new-observation → recheck → committed-revision chain,
but no automatic version notice. Basis cost more. The scoped Goal is
`COMPLETE_WITH_NEGATIVE_OR_UNCERTAIN_EFFECT`; ordinary remains default. Continuous v10
charges are 122 generations / 1216124 generation tokens / 8148 embedding tokens,
unknown=0, Judge=0. E2/E3/E4 and StateMemBench remain NOT_RUN. Do not force a State ritual,
alter tasks or rerun to replace negative evidence. Keep all raw artifacts ignored.

[Goal v9.0](docs/MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v9.0_20260925.md)
completed A–E and scoped final continuous validation. Preserve its
[results](docs/CONTEXTUAL_USER_MEMORY_V9_RESULTS_20260925.md), first failed attempt,
final source identity and all charges: 119 generations / 966332 generation tokens /
4358 embedding tokens, unknown=0, Judge=0. Final original MERIT 5/5 (dependent 2/2,
7/7 Host turns) and document 4/4 use the same frozen implementation from initial states;
local full/delta branches both completed with no new business action. Delta was cheaper
locally, but the full continuous trajectory was more expensive than v8. Do not claim
general reliability, State benefit or overall efficiency. Do not expand the benchmark or
rerun merely to clear truncation counts. Keep raw model/runtime artifacts ignored.
The user explicitly authorized Luna high to commit and push all development to GitHub;
this supersedes old no-commit/push and Luna-download-only restrictions for publication.
Ordinary development remains Sol xhigh; Astra xhigh only for concrete difficult issues.
One model controller, concurrency 1, continuous accounting with null cumulative caps,
Lab-only scope and narrow problem-driven checks remain. No Product migration or full suite.
Documentation-only changes need no pytest, build or model calls.

The user-authorized [Goal v8.0](docs/MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v8.0_20260925.md)
completed A–E development and scoped, staged validation. Durable runtime/recovery, first
writes, same-record updates, post-action maintenance, explicit source-body delivery and
incomplete-run preservation are implemented. The final isolated original MERIT episode
passed 1/1 with current original-card completion, after two full native 5/5 runs whose
maintenance failures remain preserved. Do not describe this as final-source continuous
five-episode success, general reliability, State benefit or Product readiness.
Preserve [results](docs/CONTEXTUAL_USER_MEMORY_V8_RESULTS_20260925.md), all source snapshots
and continuous v8 charges: 137 generations / 948575 generation tokens / 5432 embedding
tokens, unknown=0, Judge=0. Cumulative and verification caps stay null; closed historical
stages do not block new user-authorized repairs. Luna high only downloads, Sol xhigh
ordinary development, Astra xhigh concrete difficult issues. Keep verification narrow;
do not automatically expand the benchmark or run full suites. Documentation checks need
no pytest, build or model calls. No commit/tag/push or Product migration was performed.

The [Goal v7.0](docs/MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v7.0_20260925.md)
completed P0–P7 development before E0 selection, followed by E1/E2 on one complete exposed
MERIT arc. The final ordinary/off run scored 5/5 (dependent 2/2) and exercised durable
CREATE → REVISE → later-session memory → native business action. Preserve both earlier
3/5 failures, the continuous v7 ledger, and the [limits in the results](docs/CONTEXTUAL_USER_MEMORY_V7_RESULTS_20260925.md).
Method v11 / write v10 / ingestion v27 / view v8 / operation v2 are the final runtime;
State benefit and reliable post-execution maintenance remain unproven. Do not describe
this single exposed unit as general quality or a comparative win. Do not automatically
expand the benchmark or reopen v6. Keep ordinary, H1–H6 frozen, vLLM Host/Judge,
continuous accounting without cumulative/verification hard stops, and Lab-only boundaries.
Documentation checks need no pytest/build/model calls; implementation checks stay narrow.

For the contextual user-memory
[Goal v6.0](docs/MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v6.0_20260924.md),
the user's current scope takes precedence over the general handoff commands below:

- Keep ordinary as the baseline, freeze H1–H6, and preserve the closed v3/v4/v5
  Goals and results. v5 completed its required execution wiring but retained semantic
  failures and no independent H2 benefit. Its 114 requests and budget stay closed.
- v6's scoped repairs are validated on the three exposed questions across five final
  paths, with general semantic quality unestablished. Method v10/write v9/ingestion v25/
  material view v5 are frozen in the final `v6-user-scope-*` runs. Preserve all previous
  failures, scores and costs: 243 generations, 969510 generation tokens and 93390
  embedding tokens, unknown=0. Final validation accounted for 43 of those generations.
- The user explicitly removed local-verification-count and cumulative request/token
  stopping restrictions. Caps may be null for accounting-only runs; never reset charges
  or block authorized repair because a previous verification was already used. Keep
  per-workflow capacity limits and problem-driven small verification.
- Keep the three exposed native cases and unchanged data/scoring. Ordinary and State
  histories have different identities; do not bypass ownership validation. Additional
  local verification is authorized and is not another independent sample. Do not
  reopen v5, rerun H2 effects, add candidates, expand benchmarks, consume untouched
  confirmation cases, run full STALE or run the full test suite. Keep real sources,
  creation/revision, independent dependencies and State consumption working.
- New schema branches must remain expressible in the deployed generation backend;
  JSON Schema validation alone is insufficient. Reuse the narrow grammar checks.
  Actual subject/source and dependency failures are semantic repair failures even when
  the calls settle; do not close v6 merely because its interfaces are implemented.
- For documentation/manifests, check paths, JSON, selection counts and source hashes;
  no pytest, model calls or package build is needed.
- For implementation, run affected static checks and the narrow existing tests
  relevant to the change. Add only necessary deterministic checks for semantics a
  benchmark cannot observe. Run the boundary check when moving package code and a
  build only when changing packaging.
- Host and any LLM Judge use vLLM. Gold annotations stay outside method inputs.
- Run the delivered default configuration's own smoke; distinguish source receipt,
  committed operations and unfinished maintenance. Verify real mechanism reachability
  before comparing scores, and keep failed or unscored attempts in the cost record.
- Keep refactoring incremental, separate structural moves from behavior changes,
  and avoid repeated validators, silent fallbacks and new review/approval stages.

For other work requiring the general package handoff, run:

```bash
uv run milai-lab-check-boundary
uv run pytest
uv run ruff check src tests tools
uv run mypy src/milai_lab
uv build
```

The product pin verifier is required before any product-backed effect run.

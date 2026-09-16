# Active studies

Current Goal: [Evidence- and utility-driven experience improvement](MILA_EVIDENCE_AND_UTILITY_DRIVEN_IMPROVEMENT_GOAL_v1.0_20260916.md).
[Problems/results](MILA_EVIDENCE_UTILITY_RESULTS_20260916.md) · [implementation](../../docs/EVIDENCE_UTILITY_METHOD.md).
D0 review is complete; v0.7-dev has four real functional runs. D1-D5 remain in progress,
including MemRL, shared usability, selector calibration and new-source confirmation.
The original [read-only basis](../../data/manifests/evidence-utility-improvement-goal-basis-20260916.json)
remains a historical design snapshot, separate from the new execution manifest.

Current work: [Optimization results](MILA_OPTIMIZATION_RESULTS_20260916.md).
The current Goal continuation resumed the new optimization study after the concise report
handoff. The same frozen configurations continue; the new formal comparison is incomplete.
The [concise paused report](MILA_EXPERIMENT_RESULTS_BRIEF_20260916.md) remains a dated snapshot.

**Prior experiments are PAUSED_BY_USER (2026-09-16 00:19:15 Asia/Shanghai).**
[Problems and experiment results — concise summary](MILA_EXPERIMENT_RESULTS_BRIEF_20260916.md).
Drivers, workers and the automatic handoff watcher are stopped. Do not resume or launch recovery
without a new explicit user instruction. Full research remains incomplete.

Current research: [ReasoningBank transfer and multisession Goal](MILA_REASONINGBANK_TRANSFER_AND_MULTISESSION_RESEARCH_GOAL_v1.0_20260915.md).
Single solver by user instruction; DB/OS four-method DEV pairs and real bank recovery completed,
Travel DEV and four-method v0.3 VALID completed; v0.4 is selected. Sources/data and source-grouped splits are pinned.
[DB formal main and verified-history results](MILA_REASONINGBANK_DB_RESULTS_20260916.md) are terminal:
820 native records; MiLAi correct F/O 81%/82%, RB 76%/77%, Native 90%/88%.
The paired intervals do not establish the required gain, and no natural revision occurred in these DB main runs.
OS formal evaluation and travel support are incomplete and paused.
[Development results](MILA_REASONINGBANK_DEVELOPMENT_RESULTS_20260915.md),
[source/protocol](MILA_REASONINGBANK_SOURCE_AND_PROTOCOL_20260915.md),
[execution manifest](../../data/manifests/reasoningbank-transfer-20260915.json).
The full held-out study, support formation and required contribution/resource comparisons remain incomplete and paused.

Experiment report: [Adaptive Memory v0.1](MILA_ADAPTIVE_MEMORY_EXPERIMENT_REPORT_v1.0_20260915.md).
The closed first-release report covers setup, native results, role-level costs, the fixed-input
diagnostic, engineering failures/repairs and evidence limits. 13 generations / 103,103 tokens;
keep OM at this workpoint. Report preparation added no experiments or allocations.

Latest closed first release: [Adaptive Memory development results](MILA_ADAPTIVE_MEMORY_DEVELOPMENT_RESULTS_20260915.md),
[complete Goal](MILA_ADAPTIVE_MEMORY_DEVELOPMENT_AND_CONTRIBUTION_GOAL_v1.0_20260915.md),
[master design](../../docs/MILA_ADAPTIVE_MEMORY_MASTER_DESIGN_AND_ROADMAP_v1.0_20260915.md).
Core v0.1 / adapter v0.7 engineering complete; 147 adjacent tests and public fresh-process recovery pass.
Full regression: 4628 passed / 1 optional SDK skip, exit 0; static/build checks pass.
E1 all native rewards 1; one E2 pair finds no reminder increment.
13 generations / 103,103 tokens settled; allocations closed. Keep OM at this workpoint;
Adaptive remains a functional baseline without established special-policy or transfer benefit.

Latest closed development: [RWC v0.4 real use and diagnostics](MILA_RWC_V04_DEVELOPMENT_RESULTS_20260915.md),
[plan](../../docs/MILA_RWC_v0.4_后续开发与创新验证规划_v1.0_20260915.md),
[manifest](../../data/manifests/rwc-v04-development-20260915.json).
CLOSED_BOUNDED_DISCOVERY: keep OM at the single exposed workpoint; no trial RWC policy promoted.
80 generations / 358,729 tokens settled, unused positions closed. Improved-version pairing,
transfer and continuation unrun. Architecture and formal policies remain unchanged.
72 nearby tests and static/build checks pass; full regression was not rerun.

Previous development: [memory-control repair Goal](MILA_HOST_MEMORY_CONTROL_REPAIR_GOAL_v1.0_20260914.md),
[results](MILA_HOST_MEMORY_CONTROL_REPAIR_RESULTS_20260914.md),
[usage](../../docs/HOST_REVERSIBLE_WORKSPACE.md).
Deduplication, independent cards, control routes, same-loop ordinary policy and public checkpoint
recovery implemented. Real public fresh-process/CAS/revocation checks pass. Four native attempts,
41 generations / 135,952 settled tokens; one scored pair ties, two attempts unscored.
Frequent rejected control outputs and no natural recall remain material limits.
Model allocation closed; engineering complete: 4573 passed / 1 optional SDK skip,
all 4574 final test identities covered, boundary/ruff/mypy/build pass.

Previous development: [integrated Host workspace control](MILA_HOST_WORKSPACE_CONTROL_DEVELOPMENT_RESULTS_20260914.md).
One authorized CONTROL_0 native trajectory passed all 6 checks (reward 1), with 26 generations
and 71,708 settled tokens. Working-set selection, receipt readback, feedback maintenance,
fresh-Host handoff and bounded delivery review observed; no natural branch return or benefit claim.
75 targeted tests and static/build checks passed; full regression ended with 4520 passed / 1 skip.
Remaining model allocation closed. This is development progress, not a new KEEP_SIMPLE verdict.

Previous research: [HiAgent evidence-maintenance results](MILA_HIAGENT_EVIDENCE_MAINTENANCE_DISCOVERY_RESULTS_20260914.md),
[execution Goal](MILA_HIAGENT_EVIDENCE_MAINTENANCE_DISCOVERY_GOAL_20260914.md).
KEEP_SIMPLE_SPECIAL_POLICY_NOT_SUPPORTED: 8 attempts, 60 generations / 434,611 tokens,
all settled. Incremental summary ties EVIDENCE_1; all valid native rewards are zero.
Transfer unavailable. Full regression: 4497 passed / 1 optional skip; boundary, ruff, mypy,
and build passed. Allocations closed; owned trial/test processes exited.

Prior execution: [HiAgent single-task results](MILA_HIAGENT_BASELINE_EXECUTION_20260914.md),
following the [baseline and fidelity note](MILA_HIAGENT_BASELINE_IMPLEMENTATION_20260914.md).
Real subgoals and summary inputs observed; native verifier 5/6 passed, reward 0; retrieval unused.
57 generations / 50,153 tokens including the first interface failure; all usage settled,
unused 7 of the independent 64-call allocation closed. No product change or old Goal quota reuse.
86 targeted tests and static/build checks passed. Full regression: 4473 passed / 1 optional SDK skip,
exit 0; with the 5 new budget tests, all 4479 current cases have terminal coverage
(4478 passed / 1 skipped). Engineering acceptance is complete; all trial/test processes exited.

Latest completed: [complex-task experiment summary](MILA_HOST_COMPLEX_TASK_POLICY_DISCOVERY_SUMMARY_20260914.md),
[full report](MILA_HOST_COMPLEX_TASK_POLICY_DISCOVERY_RESULTS_20260914.md),
[closed Goal v1.1](MILA_HOST_COMPLEX_TASK_POLICY_DISCOVERY_GOAL_20260914.md).
COMPLETED_BOUNDED_DISCOVERY / KEEP_SIMPLE: 16 trajectories, 337 generations, 5,754,068 raw tokens;
all generation usage settled. Three roots attempted, two with valid native scores; no transferable net policy gain.
One workspace update, no active selection/readback in the common Host; database scoring and ClawMark transfer incomplete.
Initial full regression: 4443 PASS / 1 FAIL / 1 optional SKIP; unchanged module recheck: 10 PASS.
Other checks passed; preserve the initial failure, not an all-green full-suite claim.
Unused allocation closed. This summary update adds no experiment, service operation or new Goal.

Previous completed: [interpretation replication and handoff ablation Goal](MILA_HOST_INTERPRETATION_AND_HANDOFF_GOAL_20260914.md), [experiment results](MILA_HOST_INTERPRETATION_AND_HANDOFF_RESULTS_20260914.md).
Two counterbalanced R/EXPLAIN waves, same-artifact FULL/NO_HANDOFF consumers; full sources retained.
Completed model work: 12 generations / 73,119 tokens, 7 valid final deliveries and one action rejection; no unknown usage.
No stable EXPLAIN or net handoff benefit; no new State, restricted-window claim or independent lineage.
Full regression complete: 4439 PASS/1 optional SDK SKIP; 4440 items exactly covered. Other checks/build PASS; no further sends.

Previous completed continuation Goal v1.1: [natural-context execution and results](MILA_HOST_CONTINUATION_RESULTS_20260914.md).
Completed: natural-context N/R/S and one interpretation diagnostic, 10 generations / 56,547 known raw tokens.
Full regression: 4433 passed / 1 optional SDK skip; all 4434 items covered. Other required checks/build pass.
Keep simple references and only a local interpretation hypothesis; prior restricted 6 calls / 24,196 tokens remain separate.

Historical planning snapshot (now completed above): [continuation formation and use Goal](MILA_HOST_WORKSPACE_续接材料形成与使用_后续GOAL_v1.0_20260914.md).
v1.1 starts with a common consumer and available task history within verified runtime capacity;
no fixed 8k/16k input gate, hard 512-token handoff or default K eviction. At most one follow-up;
restricted-context results are separately labeled, not a prerequisite or normal-context benefit claim.
Explicit stage handoff, not spontaneous Note writing or persistent-memory validation; planned, not started.
Proposed maximum 52 generations, zero allocation. Documentation only; runtime defaults and prior results unchanged.

Previous managed follow-up: [implementation, comparisons and engineering status](MILA_HOST_WORKSPACE_MANAGED_RESULTS_20260914.md).
Managed v4 three-arm and NOTE retention ablation complete; 51 generations / 234,134 known raw tokens,
including preserved scheduling/capacity failures. All work records stayed empty. Keep simple NOTE and
opt-in managed capability; no stable policy or short-record benefit claim. The frozen-source test now
passes; full regression is terminal: 4423 passed / 1 optional SDK skip, with all 4424 items covered.
The original exit-139 run is preserved; fixed-inventory shards both exited 0, and other required
engineering checks pass. This development follow-up is complete; cross-source validation remains incomplete.

Current development: [Host workspace A three-arm results](MILA_HOST_WORKSPACE_DEVELOPMENT_RESULTS_20260913.md).
The [execution Goal](MILA_HOST_WORKSPACE_开发与行为探索_GOAL_v1.0_20260913.md) now has a real
Provider/task connection and complete NOTE / REVIEW / REGULATED trajectories: 10 generations,
44,209 known raw tokens, no unknown usage. All three left the optional work record empty.
Keep the simple NOTE reference and pause extra candidate trials; no persistent-memory claim.
B is [bounded unavailable](MILA_HOST_WORKSPACE_B_DISPOSITION_20260913.md), so only one source was compared.
[Semantic annotations](MILA_HOST_WORKSPACE_A_LABELS_20260913.md) preserve the actual diagnosis errors.
The [original prototype record](MILA_HOST_WORKSPACE_PROTOTYPE_20260913.md) and its zero-call/full-test
incomplete snapshot remain historical evidence; current checks are listed in the results report.
[Design revision 4](MILA_HOST_WORKSPACE_POLICY_DESIGN_v0.1_20260913.md) remains an opt-in research
prototype, not a Product default or schema freeze. No A–E or WMA rerun follows from this result.

Frozen prior planning entry: [V0224 Goal v0.4: functional closure and minimal native benchmark](MILA_V0224_功能GateA收口与原生Benchmark最小实验_GOAL_v0.4_20260913.md).
Current report: [V0224 development and native WMA experiment](MILA_V0224_NATIVE_WMA_DEVELOPMENT_REPORT_20260913.md).
`GATE_A_FUNCTIONAL_PASS_UNDER_R03_R04_USER_PRIORITY / NATIVE_WMA_PARTIAL / JUDGE_TIMEOUT_USAGE_UNKNOWN / MEMORY_EFFECT_INCONCLUSIVE`.
Actual WMA run:165 answers/164 valid scores; five primary answer units and all review runs unrun.
Latest v4 batch stopped at a600-second Judge ReadTimeout;511 generations have13,520,967 known raw tokens, one additional generation has unknown usage.
One paired root has identical recorded question/retrieval/image inputs; four same-answer Judge disagreements preclude a Memory effect claim.
Current review implementation adds a call after the M draft, unlike the planned same-call policy; it has not run.
Frozen Goal NOT_STARTED/zero-allocation labels describe its original planning snapshot, not this separately contracted execution.
[Functional certificate](/cra/memory/mx_memory/evidence/v0224/20260913-cpu-completion-segment-v1/functional-gate-a.json):
complete 16+80 references, CPU P3 16/16 and P4 24/24; 40 successes / 41 attempts with the old timeout retained.
Six engineering checks passed (4285 tests, one existing optional skip); composed functional acceptance is complete, efficiency nonblocking.
No real-model result follows from this CPU certificate itself; subsequent native results are documented separately above.
Historical unknown usage remains accounting work; the new design does not resume scoring or
the unfinished WMA comparison, and does not make their completion a policy-exploration prerequisite.
Old B–E is paused; this report update starts no experiment, service change, new allocation or full regression.
[Execution history](MILA_V0224_EXECUTION_STATE_20260913.md), [v0.3](MILA_V0224_Gate_A至E最新执行与研究_GOAL_v0.3_20260913.md),
[v0.1](MILA_V0224_Gate_A至E执行有效性与持久记忆研究_总GOAL_20260913.md), adopted deltas and V0222 stopped evidence remain intact.

Historical predecessor synthesis: [V0222 experiment report](MILA_V0222_EXPERIMENT_REPORT_20260913.md),
[execution state](MILA_V0222_EXECUTION_STATE_20260912.md).
BLOCKED_UNFINISHED / EXECUTION_VALIDITY_INFRA_TOO_HEAVY / GATE_A_NOT_PASSED / MEMORY_NOT_ADMITTED.
Current3329 PASS/1optional skip; actual reference preparation stopped before first P4 generation because97.161s of admissions exceeded60s.
All40 formal CPU positions remain PENDING; real P3/P4 unadmitted. V0222:54 real generations/1051344 settled raw;
old unknown usage remains separate. This synthesis adds no experiment or execution authority. Older entries below are historical evidence.

Latest follow-up: [V0222 residual boundary](MILA_V0222_BOUNDARY_DIAGNOSTIC_20260912.md),
[compact results](MILA_V0222_BOUNDARY_RESULTS_20260912.json):16HTTP requests,B0 exact4/8,B1 exact8/8,
568796raw settled,0new unknown/effects; fixed INTENT_BOUNDARY_SIGNAL, final independent review PASS.
The earlier presentation full-gate design had offline-only scope review; subsequent stops are recorded above, Memory remains unadmitted.

[Presentation implementation](MILA_V0222_PRESENTATION_IMPLEMENTATION_20260912.md): complete new-scope
16+80 offline references/24effect chains/40Worlds verified; current-auditor revalidation PASS.
Full Mock16→24 integration and2388tests/1optional skip PASS; sole new instance offline preparation completed,
scope and capacity passed. [Full-gate terminal](MILA_V0222_PRESENTATION_FULL_GATE_20260912.md):12P3 PASS,
13th stopped at phase deadline;449759raw settled,3P3/24P4 unrun. Independent terminal audit PASS; offline engineering follow-up only, no retry.
[Read scope](../../docs/V0222_ADMISSION_READ_SCOPE_OFFLINE_20260912.md):46local tests/review and2434-test/1skip component baseline PASS; scale/JSON and explicit V2 design reviewed;
subsequent [evidence adapter R2](../../docs/V0222_SCOPED_EVIDENCE_IMPLEMENTATION_20260912.md)64local tests/review and exact5865-file coverage PASS,
its own full pytest89818 completed2498PASS/1skip; subsequent
[history adapter](../../docs/V0222_SCOPED_HISTORY_IMPLEMENTATION_20260912.md) has2574PASS/1skip full baseline;
[partial Batch core](../../docs/V0222_SCOPED_BATCH_IMPLEMENTATION_20260912.md) has a 2707-pass/1-skip R1 baseline;
[new execution wiring](../../docs/V0222_SCOPED_EXECUTION_WIRING_20260912.md) has3097PASS/1skip and complete Mock raw review PASS.
[CPU entrypoints](../../docs/V0222_SCOPED_CPU_REPLAY_IMPLEMENTATION_20260912.md) preserve the earlier192-component checkpoint;
current measured230-component version has full3329 PASS/1skip, but actual reference preparation failed.
Complete cold-stage timing remains unproven; no new model authorization.

Historical execution: [V0222 decoder semantics and intent fidelity Goal](MILA_V0222_解码语义与意图保真改进_GOAL_20260911.md)
with [detailed execution/Memory roadmap](../../docs/V0222_后续执行与Memory再准入规划.md).
HTTP-only [P1](MILA_V0222_P1_STRING_DIAGNOSTIC_20260911.md) completed24generations/4451raw;
D11 uniquely selected. P2 admitted,96full-reference HTTP capacity PASS,1812tests pass/1skip.
First P3 output is schema-valid but chooses S01 instead of manager_report; permanent stop,
25batch requests/32789raw settled,15P3/24P4 unrun. [Results](MILA_V0222_RESULTS_20260911.json).
Recovery/natural tasks/Memory NOT_TRIGGERED; a new bounded intent-boundary draft is not yet admitted.
Stopped V0221 and historical unknown usage retained; no service/device changes.

Latest bounded check: [V0221 HTTP-only execution](MILA_V0221_HTTP_ONLY_EXECUTION_20260911.md).
Full96-reference capacity PASS; first full HTTP200/schema PASS but authorized values not faithful.
1request/27864raw settled,0new unknown/live effects/direct device calls;15W2/24W3 unrun.
1602pass/1optional skip; LIVE_COMPAT_NOT_MET, Memory not admitted, old unknown retained.

Historical bounded check: [V0221 service readiness stop](MILA_V0221_LIVE_COMPAT_AND_EXECUTION_20260911.md).
Execution scope received; container NVML failure and diagnostic CUDA_ERROR_NO_DEVICE stop early W1.
0model calls;16W2 positions/24W3 chains not triggered; full generation coordinator/capacity not admitted.
1571pass/1skip; no service/Product/State/pool change or further GPU operation without separate agreement.

Latest repair: [V0220 explicit dual-contract wire compatibility](MILA_V0220_WIRE_COMPAT_FIX_20260911.md).
Business schema unchanged;8/8wire CPU variants,25full record roundtrips/negative controls,
40new tests;1545pass/1optional skip. Historical unknown usage still blocks; no generation or V2
resumption, State/ Product/service changes or protected-pool opening. Live compatibility unverified.

Latest follow-up: [V02-20 Provider hardening](MILA_V0220_PROVIDER_HARDENING_20260911.md).
All four full schemas checked: 3 rejected/1 CPU pass; empty HTTP500 wrapper reproduced.
32 offline safety tests; old usage unknown retained; zero new model calls; DO_NOT_RESUME_V2.
Earlier summaries below retain their original knowledge state.

Latest completed: [V02-20 bounded validity failure](MILA_V0220_FINAL_REPORT_20260911.md).
V0/V1 mechanically calibrated; V2 first full requestHTTP500,1attempt/23unrun/no business effect.
Three Provider requests:2synthetic compatibility/2221raw settled,1V2 usage unknown/28284raw reservation.
V3–V5 not triggered; no root admitted and no Memory inference. Full-schema uniqueItems incompatibility
confirmed on CPU; exact HTTP500 cause unknown. No Product/pool/shared-service changes; C=0.

Latest completed: [V02-19 final decision](MILA_V0219_INNOVATION_DECISION_20260911.md),
FAILURE_REGIMES_RECORDED / KEEP_SIMPLE_NO_QUALIFIED_REGIME / VALIDITY_GAPS_RECORDED.
[Baseline](MILA_V0219_BASELINE_RESULTS_20260911.md), [failure map](MILA_V0219_FAILURE_MAP_20260911.md)
and [execution ledger](MILA_V0219_EXECUTION_20260911.md): four roots/three families,
28episodes/448requests/9,820,337raw settled and source/chain audited. F4–F6 NOT_TRIGGERED;
zero candidates/pilots,26reserve protected,C accepted0,candidate57 unopened.
Judge0/rawcapnull/active allocation0; owned services stopped, no Product/A0/schema/deployment change.

Latest completed: [V02-18 E5 decision](MILA_V0218_INNOVATION_DECISION_20260911.md),
WHOLE_GOAL_COMPLETE / KEEP_SIMPLE_NO_CANDIDATE + ENGINEERING_GAIN_ONLY.
T0–T5/E0/E1/E2/E5 complete; zero qualified mechanism candidates, E3/E4 NOT_TRIGGERED.
[T5](MILA_V0218_T5_REVIEW_20260911.md): 12 adapted lineages / 9 coarse families / 49 branches;
all exposed D, unopened C=0. Testbed contribution remains a candidate requiring external review.
[E0](MILA_V0218_E0_V4_20260911.md): standard 42 episodes plus 20 separate probes, S*=N1.
[E1](MILA_V0218_E1_DISCOVERY_20260911.md): two candidates, two roots, 28 episodes/two cold runs.
[E2](MILA_V0218_E2_RESULTS_20260911.md): complete 32-episode matrix with matched full public
information, actual cold Note and request-byte audit. C2/R1 paired results identical (3/6);
N1/C1/P1 each 2/6, all Stable pass, unresolved and news-update failures retained.
All attempts: 1340 requests / 3,353,114 raw, settled, raw cap null; no active allocation.
1258 tests / 1 optional SDK skip and Lab gates pass; owned services stopped, evidence retained.
[Downloads](MILA_V0218_BENCHMARK_ACQUISITION_20260910.md) upstream-hash verified, MemTrap artifact HOLD.
No mechanism novelty, independent confirmation, Product/A0/schema/deployment or protected-pool change.

Latest admission: [V02-17 Goal v0.3](MILA_V0217_Benchmark_Discovery与行为真值准入_GOAL_20260910.md),
[B0–B4 report](MILA_V0217_BENCHMARK_ADMISSION_20260910.md): `VALIDITY_GAPS_RECORDED`.
Four candidates, 40 native-function checks / 11 semantic counterexamples; 66 data-boundary/stub
checks pass. No native Agent task or P Lane admission; generation/Judge requests remain zero.
777 tests / 1 optional SDK skip and Lab gates pass. Original preflight and superseded v0.1 code preserved.
No mechanism development, protected-pool access, A0/public deployment or Schema NO-GO change.

Latest model experiment: [V02-16 execution](MILA_V0216_EXECUTION_20260910.md),
[failure map/cards](MILA_V0216_FAILURE_MAP_20260910.md),
[Goal v0.2](MILA_V0216_简单记忆压力探索与失败图谱_GOAL_20260910.md): `FAILURE_MAP_RECORDED`.
Two roots, 0 → 32 → 8 distractors; 36 deliveries, 28 supported correct, 8 acquisition-layer
failures; 118 requests/581,953 raw, all settled. Zero model-selected notes, no persistent-memory
use/causality claim. Keep simple, no new mechanism; A0/public/Schema NO-GO unchanged; 767 tests.

Previous: [V02-15 execution](MILA_V0215_EXECUTION_20260910.md) and
[mechanism/selection memo](MILA_V0215_MECHANISMS_AND_SELECTION_20260910.md):
`NO_PROMISING_CANDIDATE_IN_THIS_BATCH / KEEP_SIMPLE`, 88 requests/458,071 raw including failures;
R0/R1/R2 complete, zero candidate selected; R3–R5 not triggered, no confirmation/deployment claim.

Historical pre-execution design: [V02-15 open Persistent Memory Regulation exploration](MILA_V0215_持续记忆调控与联想不污染_GOAL_20260910.md),
`PLANNED_OPEN_EXPLORATION_NOT_STARTED`. Goal v0.2 separates discovery from confirmation:
explore tasks, State policies and bundles freely within authorized bounds, preserve every run,
then select minimal candidates for frozen independent validation. A–E have no prerequisite order.
Host engineering is supporting infrastructure. No new run or protected-pool access is allocated.

[2026-09-10 progress and innovation synthesis](MILA_V02_实验进度与创新探索总结_20260910.md)
summarizes the experiment history, current SDK/Host evidence, unresolved State hypotheses,
version boundaries and separately accounted costs. It allocates no new run or deployment.

Historical: [V02-14 SDK Host follow-up](MILA_V0214_SDK_HOST_FOLLOWUP_20260910.md),
`SDK_HOST_DEVELOPMENT_PASS_KEEP_A0`: actual SDK wheel in the local Host, 16/16 development
phases, 29 requests/194,079 raw, 752 tests with SDK. No external Host/deployment or new confirmation.
The [original D0–D7 report](MILA_V0214_HOST_RESULTS_20260909.md) retains its historical allocation.

Historical: [V02-13 Host cold recheck](MILA_V0213_HOST_RECHECK_20260909.md),
`HOST_COLD_RECHECK_VERIFIED_KEEP_A0`: v1 failure retained, v2 public-source pagination and
typed delivery pass original two tasks in both cold rounds. 30 requests/276,265 raw; 685 tests.
No A0 replacement, State, new samples, or retrieval/population benefit claim.

Historical: [V02-13 P3 results](MILA_V0213_P3_RESULTS_20260909.md),
`COMPLETED_BOUNDED_DECOMPOSITION_KEEP_A0`: remaining fixed pair processed, both Oracles
insufficient before generation; 8 requests/71,781 raw, combined 16/145,220. Zero P3 parameter
denominators; task/clarification contract is next candidate. 676 tests pass; no State/deployment.

First-wave historical close: [V02-13 results](MILA_V0213_RESULTS_20260909.md),
`COMPLETED_BOUNDED_DECOMPOSITION_PROPOSE_HOST_FIX`: exact P0 replay; first two Mem2Act clusters,
8 generations/73,439 raw; acquisition and action-format gaps separated, R1/O each 2 correct.
Empty business-plan completion classification fixed, 669 tests pass; keep 0.1.15/A0, no State.

Predecessor: [V02-12 results](MILA_V0212_RESULTS_20260909.md), bounded Horizon diagnosis complete,
keep A0. Seal A/B,4 clusters/8 attempted queries,10 local generations/69,325 raw;
2 correct/4 incorrect/2 budget stops;no new independent recurrence;609 tests/checks pass.

Predecessor: [V02-11 admission](MILA_V0211_ADMISSION_20260909.md) stopped at qualification;
A0 external diagnosis is incomplete. All69 positions retained, benchmark generations0,
first-wave source near-duplicate rejected, later candidates not substituted. Full Small
sources and ten offline evaluation contracts are preserved; public MCP scope isolation
and source transport pass with zero generations; owned services stopped; 601 tests/checks pass.

Historical: [V02-10 v0.5 pilot](MILA_V0210_V05_RESULTS_20260909.md) is
`COMPLETED_BOUNDED_STATE_CONTROL_PILOT`: 12 local generations / 10,346 raw; real mechanical
recovery passes its core scope, dynamic prompt net gain unproved, cold full sufficiency 0/4.
Keep 0.1.15/A0. Owned services stopped, generation allowance zero, 598 tests/checks pass.

Historical v0.4: [V02-10 terminal results](MILA_V0210_CONTROL_RESULTS_20260908.md) are
`COMPLETED_DIAGNOSED_KEEP_BASELINE`: E1+B2 completed 10 local generations / 43,656 raw tokens.
C2 showed no qualified gain; P2/E2 and P3/E3 are NOT_ENTERED. Current generation allowance is zero.
Older studies below retain their own scope.

The separately authorized [local vLLM simulation](MILA_V02_LOCAL_VLLM_SIMULATION_20260906.md)
completed one synthetic G/A/B chain with 3 sessions, 7 local requests and 21,880 raw tokens;
paid requests were zero. Public State save/cold restore worked, but State-first used 67.23% more
tokens than prefetch in this example. Mechanical decision fields passed; full action sequences
were incomplete. This is `SIMULATION`, not native paid-Host equivalence or D3–D5 completion.
The isolated services are stopped, data retained, shared/public services unchanged.

The [MILA-V02-05 development Goal](../../../MiLAi-Product/docs/goals/MILA_V02_05_端到端通用记忆开发与泛化验证_GOAL_20260906.md)
is `IN_PROGRESS / PARTIAL_PRODUCT_AND_LAB_ENGINEERING`. Version 0.8 preserves the local simulation
and [v0.5–v0.7 engineering evidence](MILA_V02_E2E_ENGINEERING_20260906.md): revocation repair,
deadline/presentation controls, full-source forks and representation chains are not model-effect evidence
or a D0–D5 stage PASS. State-first remains a candidate, not a proven cost improvement.
Next are P1 concurrent reads and P2 durable-save/processing separation, then P4 bounded mixed-load,
overload and recovery checks before another real Agent chain. P3 is optional source-code mechanism
study feeding MiLAi-owned implementations, not third-party Memory backend integration. MiLAi keeps
its own runtime, SDK/MCP, persistence and projection code; reference repositories are not dependencies.
Service latency/throughput targets are proposed, not benchmarked achievements.
Experimental model single-in-flight limits do not serialize Memory service or independent tool calls.
The already opened LME source audit/forks are reused; another local chain requires a separate allocation.
The full D3 gate is incomplete; formal D4/D5 and paid experiments remain unentered.
New local and paid model allocations are zero; the completed simulation's unused cap does not roll over.

The [MILA-V02-04 v0.2 cost-first plan](MILA_V02_CONFIRMATION_COMPLETION_PLAN.md) is
`COMPLETED_NON_MODEL_INCREMENT` for C0–C2; see its [execution report](MILA_V02_COST_FIRST_RESULTS_20260906.md).
The +1M-token N5 supplement and later +2M-token pilot proposals are withdrawn, with zero new
experimental model allocations or tokens authorized. All 24 historical failed commands replayed
successfully in 12 isolated containers, with full source recovery and 180 Lab tests passing.
Task-cost control remains unverified, so C3 stays unentered. The original N5
confirmation stays incomplete and parked; historical usage, terminal and sealed task order remain.
No new experiment, public deployment or automatic maintenance has started.

MILA-V02-03 is `COMPLETED_KEEP_BASELINE` following its
[payload fidelity correction and continuation](MILA_V02_PAYLOAD_FIDELITY_CORRECTION_20260906.md).
N4's two histories and one N5 history passed their individual quality/cost gates; the fourth history
has no followup results because the original cumulative token launch gate stopped the next launch.
All 17 allocations / 16 actual model sessions are terminal, with 2,402,257 known tokens. Full A0
remains selected; the exact-note candidate is a Lab tool, not fully confirmed or automatically enabled.
The [original plan](MILA_V02_LOW_COST_REUSE_PLAN.md) and failed evidence remain historical records.

The [MILA-V02-02 LME incremental plan](MILA_V02_LME_INCREMENTAL_PLAN.md) is
`COMPLETED_KEEP_BASELINE`. Its [development Goal](../../../MiLAi-Product/docs/goals/MILA_V02_02_LME复杂任务驱动的增量开发_GOAL_20260905.md)
keeps full A0 and uses opened-development complex LME cases for a small repair, a frozen development
recheck, and a separately gated actual-update U/V probe. The [execution record](MILA_V02_LME_INCREMENTAL.md)
preserves an invalid source-ID annotation leak, its pre-Host cancellation and both repaired diagnostics.
Three controlled imports verified the Lab speedup; no QA candidate entered L2/L3. Two actual updates
and four U/V pairs produced eight correct followups, but both histories failed net cost payback.
All14 allocations are terminal, Lab133 tests/gates passed, and own services stopped with data retained.
Retrieval, current-task utility and saved-memory value remain separate claims; Formal scoring is zero.

The [MILA-V02-01 usability-first development and experiment Goal](../../../MiLAi-Product/docs/goals/MILA_V02_通用Agent记忆_可用性优先增量开发与实验_GOAL_20260905.md)
is `COMPLETED_KEEP_BASELINE`. Its dedicated pin and real Host runner completed G0–G4, including
eight A0/A1 pairs, three normal-use Host pairs, saved-memory U/V and all planned followups,
then four new planning/writing tasks plus two continuations. A0 is retained; no candidate net
gain or automatic maintenance claim is made. See the [execution and results](MILA_V02_MEMORY_FLOW.md);
historical studies below retain their original status.

The current opened-development LME behavior simulation ran fresh zero-Skill Codex processes against
the single-tool MiLA HTTP MCP. With D1 enabled, every first result advertised an available frontier
but natural continuation use was 0/4. A guided COUNT replay made a valid same-query successor call
and received 20 novel turn refs, yet none of the three missing answer turns. This localizes separate
activation and fine-coverage failures without making a Product effect or Formal claim. See
[LME Codex behavior simulation](MILA_LME_CODEX_BEHAVIOR_SIMULATION_20260905.md).

The same study then scored D2 SHADOW across the four LME families. Public first Contexts covered
6/7 exact answer turns; D2 found 7/7 and recovered the sole missing turn at intra-session rank 2
and global rank 53, while changing neither Context nor frontier. This is a mechanism diagnostic,
not authorization to publish 120 fine candidates or enable D2 integration.

A selection rule derived from that probe was frozen before a disjoint 21-case S2 validation. The
public Context missed 9/32 required turns; D2 contained two of the misses, but the presealed
first-novel-per-source/global-cap-20 rule recovered 0/9. The selector is rejected and D2 stays
SHADOW. A separate timing probe showed capture `21.916s` versus only `0.951s` projection tail wait
for 484 Events, localizing performance work to capture rather than removing the required retrieval
projection.

The same report includes a seven-case guided D1 follow-up using real fresh Codex processes with only
the resolve MCP tool. Every case consumed a valid second page and collectively received 152 novel
turn refs, but same-run required-turn gain was `0/6`; Call-1 and cumulative completeness both stayed
`2/7`. More persisted frontier alone therefore does not repair the known gaps.

HC4-A1 subsequently completed a third, four-session public-IP HTTPS/OAuth engineering chain under
bounded non-mandatory guidance. Natural Working State use again remained zero (`0/4`), so the
preregistered terminal is `HC4_A1_GUIDED_ADOPTION_NEGATIVE`: the self-maintained route is parked,
prompt escalation stops, and cross-session usefulness is still not evaluable. See
[HC-4 A1 guided adoption](MILA_HOST_COGNITIVE_AFFORDANCE_HC4_A1.md).

HC4-A0 executed 8 genuine fresh-Codex sessions across retrieval-regression and architecture-refactor
chains, then stopped at the preregistered minimum-sample gate as `HC4_INCOMPLETE`. Natural Working
State use was 0/8 despite a reachable frozen `codex-full` MCP, so continuation usefulness could not
be scored. The negative invocation signal, raw artifact hashes, failure repairs and completed coding
outcomes are recorded in
[HC-4 Codex cross-session cognitive usability](MILA_HOST_COGNITIVE_AFFORDANCE_HC4.md).

Product-09 completed the real persistent Codex HTTP lifecycle and a four-case opened-development
LongMemEval diagnostic. See
[Product-09 Codex HTTP persistent memory](MILA_PRODUCT-09_CODEX_HTTP_PERSISTENT_MEMORY.md). The
lifecycle passed; the LME baseline was 3/4 exact, and a longer Host instruction regressed to 2/4 and
was removed. Formal 500 remains unconsumed.

Product-01 completed S1-S3, then its matched 128-case S4 ended
`FAIL_S4_REPAIR_OR_KEEP_BASELINE`; strict Wrong COMPLETE remained and the 500-case confirmation was
not entered. The Product-01 study files remain here as execution history, not current authorization.

MiLAi Product-02 subsequently completed U0–U3 as
`PASS_LEAN_MEMORY_USABLE_KEEP_SIMPLER_BASELINE`. Its local Product gate passed, and its fresh sealed
128-case run passed all hard gates but decisively rejected the B2 EvidenceSet treatment on exact
answer-turn, required-role and Qwen Judge outcomes. B2 remains default OFF, the B0/B1-equivalent
baseline is selected, and the 500-case formal holdout was not consumed.

- [Product-02 answer-turn and U3 decision](MILA_PRODUCT-02_ANSWER_TURN_DECISION.md)
- [Product-03 OpenWorker LongMemEval V01/V02 usability replay](MILA_PRODUCT-03_OPENWORKER_LME_SIMULATION.md)

Product-03 V02 retained the simple product path and expanded only the explicit, default-OFF local
budget. Two ordinary lookup regressions passed; one collection/count case reached Qwen but remained
semantically partial and incorrect. This is a usability result, not a LongMemEval accuracy claim.
The formal 500-case holdout remains unconsumed.

Future work needs a new, explicit authority and must again declare Product identity, dataset,
primary metrics, budget, and permitted claim before execution.

Product-11's user-authorized [subagent-sealed X0](MILA_PRODUCT11_X0_SUBAGENT_SEAL_20260905.md)
completed 24/24 exact model review but derived only `0 continuation / 8 intra-source / 16 control`
opportunities from frozen A0. The current slice is parked for insufficient opportunity; X1--X4 were
not entered and Formal 500 remains unconsumed.

The completed Product-08 study is the
[Codex Streamable HTTP Host-reasoning MCP E2E](MILA_PRODUCT-08_HOST_REASONING_MCP_E2E.md). Codex
passed three authenticated HTTP Host behaviors. Claude is not a P08 gate; live capture and real
coding-memory retrieval are successor work.

The earlier Product-08 Context-only repair contract is retained as a default-OFF prebase study:
[frozen acquisition, informational admission, and additive FTS+Dense](MILA_PRODUCT-08_CONTEXT_REPAIR.md).
Its runner and Product testkit are ready, but the 24-case opened R3 comparison has not run because a
frozen real embedding model was not supplied. Candidate flags remain default OFF; this readiness
record is not a method-effect result or formal-holdout authorization.

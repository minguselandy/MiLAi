# MiLAi Lab current status

> As of: 2026-09-22
> Coordinating Goal: `MILAI-POST-CLEANUP-DEVELOPMENT-01`
> Current execution: `ACTIVE / 3A-0_PASS / 3A-1_PASS / 3B-1_PASS / 3A-2D_DIAGNOSED / 3A-2R_PASS / 3A-3D_DIAGNOSED / 3A-3R_IN_PROGRESS`
> New experiment allocations: `0`
> New model requests: `0`

## Current coordinated mainline

PR #34 is merged (`9474c63`, main fast `35683815988` PASS), closing scoped 3B-1.
The [trace receipt](../../MiLAi-Product/docs/revalidation/trace-ownership/REVALIDATION.md)
covers v2 joins of current authorized cache invocations to observed fresh origins, with
18 real Host attempts, 47 Product tests and 76 Lab tests passed. Trace debt is FIXED;
active work is Product Resolver remediation. No research budget opens.
The [local Host result](../../MiLAi-Product/docs/revalidation/host-continuity/REVALIDATION.md)
finds retired-instance replay OPEN, while real restart/cache-miss reacquisition passes.
Diagnosis PR #35 is merged (`e760434`, main fast `35685136321` PASS). Separate
retired-instance remediation closed in PR #36 (`3eab81c`). The
[repaired tree](../../MiLAi-Product/docs/revalidation/host-continuity/REMEDIATION.md)
passes 24 native tests and 2 real PG recovery cases; full #63 (`35685753906`)
passed all 17 jobs, candidate/merge tree matched, main fast `35688151840` PASS.
[3A-3D](../../MiLAi-Product/docs/revalidation/resolver-language/REVALIDATION.md)
records client 11 PASS/11 FAIL and Runtime 6 PASS/2 FAIL on a corpus frozen first.
Resolver debt is OPEN; diagnosis PR #37/main fast `35688919530` closed at `87aa53c`.
Separate 3A-3R remediation starts with no repair proof yet. Diagnosis ran no Lab source,
model, retrieval or database execution and made no resolver behavior change.
The Product identity changed; prior research pins remain historical.

The [post-cleanup development Goal](../../MiLAi-Product/docs/cleanup/MILA_POST_CLEANUP_DEVELOPMENT_GOAL_v1.0_20260922.md)
is now the cross-bundle coordination contract. Its immediate work is Product behavioral closure and
measurement foundations; it does not resume a Lab experiment merely because historical code, frozen
inputs or incomplete work exist.

The user resumed this Goal. PR #27 is merged at `cf149939eea9f184159ebfb6aab1a3e791988250`;
exact-head CI, candidate/merge tree identity and main fast run `35673403788` passed.
Worker `--once` revalidation completed through PR #28; main fast `35674495200` passed.
The completed [Trace Ownership v1](../../MiLAi-Product/docs/reference/trace-ownership-v1.md) package began
with a content-free offline joiner. Synthetic contract tests are not real-run evidence;
the later scoped receipt adds actual owner exports and real-chain proof. Historical research remains paused.
PR #30's offline slice is merged (main fast `35676214359` PASS). An explicitly imported
[Host producer testkit](../../MiLAi-Product/docs/reference/host-trace-testkit.md) merged in
PR #31 (main fast `35677115118` PASS); the Runtime producer merged in PR #32 (main fast
`35677932965` PASS). The new
[same-execution candidate](../../MiLAi-Product/docs/reference/trace-ownership-chain.md)
joins eight real MCP/HTTP/PostgreSQL attempts through a controlled in-process Provider
fixture. Fresh exact-version/Context and failure dispatch facts are bound. The later v2
proof adds five genuine cache validations and governed Claim supersession; PR #34 completes
remote closure. No model-backed effect run or actual use is claimed.

Current interpretation of the active research record:

- Evidence/Utility is `IMPLEMENTATION_IN_PROGRESS / UNPROVEN` at its latest recorded execution
  snapshot. Functional paths and DEV observations exist, but no matched benefit, independent
  confirmation or Product-promotion claim is established.
- ReasoningBank and the v0.6 optimization study are historical, partially executed records. Their
  paused or unstarted jobs have no automatic resume authority under the new Goal.
- Adaptive Memory v0.1 is engineering-complete for its recorded scope; special-policy benefit and
  transfer remain unestablished. Its closed allocations stay closed.
- The repository-level `product.lock.json` is a historical pin. Every new Product-backed effect run
  must create and verify a run-specific lock against the selected Product baseline.
- No Lab policy enters Product defaults. The bounded native replay repair above is separate.
  Lab owns experimental Utility, Revision, Attention, policy
  adaptation and transfer until the explicit Product Promotion Gate is satisfied.

The sections below retain dated execution snapshots and historical evidence. Terms such as
“current” inside those snapshots describe their recorded date, not authorization to resume them.

## 2026-09-16 Evidence/Utility execution snapshot

Snapshot Goal: **EVIDENCE_UTILITY_IMPROVEMENT / IMPLEMENTATION_IN_PROGRESS / SINGLE_SOLVER**.
[Goal](../studies/active/MILA_EVIDENCE_AND_UTILITY_DRIVEN_IMPROVEMENT_GOAL_v1.0_20260916.md),
[problems/results](../studies/active/MILA_EVIDENCE_UTILITY_RESULTS_20260916.md),
[stage report](../studies/active/MILA_EVIDENCE_UTILITY_EXPERIMENT_REPORT_20260916.md),
[implementation and remaining work](EVIDENCE_UTILITY_METHOD.md).
Seven prior revisions have been audited and MemRL source pinned. The v0.7-dev
candidate completed four functional DEV tasks: DB 0/2, OS 2/2; 22 generations,
47,177 text tokens, no unknown usage. Real empty adoption, request/version receipts,
hidden-label isolation, fresh-process bank recovery and a v0.7 revision-1 later-use
trace are verified. Fifty-two adjacent tests and static/build checks pass; the integrated
full regression and new confirmation experiments remain pending.

OM capacity v0.3.1 now uses bounded paged omission catalogs, capacity-limited
maintenance batches, exact coverage and request-based retry identities. The saved
travel-31 overflow is reproduced; the new projection fits. Four real maintenance
calls cover 183 pages and cost 208,981 tokens; 325 pages remain explicitly pending.
Fresh-process recovery verifies all 1,603 ranges and 88 old source references.
This is an exposed-material diagnostic, with no new native travel score. Shared
group16 now has Native/v0.6/v0.7 results; the OM arm failed before the first
session at tokenize HTTP 400. The group is diagnostic only.

MemRL LLB v0.1 is now implemented and verified on six native DEV units: O-R DB
1/2, OS 2/2; F-R DB 0/1, OS 1/1. This is functional evidence without a matched
benefit comparison. Twenty actual Actor requests, two native-bit Q updates,
four fresh-process bank restores and two fully frozen bank evaluations are
verified. Usage: 24 generations / 66,302 text tokens; 8 embeddings / 592 embedding
tokens, no unknowns. MemRL source-function differential checks and 52 nearby
tests pass. Shared group16 added 241 model requests and 3,990,780 text tokens;
the active goal remains unproven pending A2, new-source confirmation, H/R comparison
and full regression.

## Prior v0.6 optimization study

Current research: **EXPERIENCE_OPTIMIZATION / FORMAL_EXPERIMENTS_RUNNING / SINGLE_SOLVER**.
[Current optimization results](../studies/active/MILA_OPTIMIZATION_RESULTS_20260916.md).
The current Goal continuation resumed the same new-study processes after the concise report
handoff. Frozen sources, budgets and planned coverage are unchanged; interrupted job timings
are identified separately. Earlier study processes remain paused. Projection, action-policy,
DB/OS/four-group travel validation and frozen/online revision comparisons are complete.
Formal DB/OS F/O comparisons are complete with all 1,600 TEST records scored. MiLAi
correct rates are DB F/O 80%/80% and OS F/O 71%/66%; no predeclared useful gain is met.
Travel remains incomplete: at 08:27 Asia/Shanghai, Native has completed 30 groups,
RB 24 and MiLAi 4. OM has terminated six TEST groups with OM_NATIVE_CONTEXT_CAPACITY;
three travel SUPPORT groups have the same failure. Preserve incomplete coverage in analysis.
Engineering checks pass: 4,662 tests passed and one
optional SDK test skipped. One test hit its episode deadline during the user pause, then
passed unchanged on an isolated rerun; the original failure is retained. All three completed
DB support banks pass fresh-process recovery; OM provenance and original events read back exactly.

## Prior paused study

[Problems and experiment results — concise summary, 2026-09-16](../studies/active/MILA_EXPERIMENT_RESULTS_BRIEF_20260916.md).
The user paused experiments at 00:19:15 Asia/Shanghai. Experiment drivers, workers and the automatic
handoff watcher are stopped. No automatic resume, restart or recovery is authorized; the full study
is incomplete. Shared inference services are retained. The read-only pause snapshot records
14,454 settled generations / 144,488,913 tokens and 9 unresolved requests (upper bound 134,213 tokens).
[Complete Goal](../studies/active/MILA_REASONINGBANK_TRANSFER_AND_MULTISESSION_RESEARCH_GOAL_v1.0_20260915.md).
Only Qwen3.6-35B-A3B-FP8 is used as solver; the second solver is deferred by the user.
Official repositories, task data, flight database and all native environments are ready.
DEV/VALID/SUPPORT/TEST and all diagnostic subsets were frozen before development generation.
Four native methods have completed DB/OS pairs and a complete seven-person travel group.
The v0.3 candidate scored DB 1/2, OS 2/2 and travel PS 0 / SPS 7.14 / SR 0 on DEV;
no natural Actor revision has yet been observed. Earlier deviating variants remain separately labeled.
Real-bank new-process retrieval and the public SDK round trip of six generated cards pass.
v0.3 VALID completed 12 DB tasks and eight travel groups across four methods.
Its candidate had 13/58 terminal travel sessions; all methods had PS 0. Failures are retained.
Selected v0.4 exposes authorized plans before adoption and Actor work:55/58terminal sessions,
50nonemptyplans,PS1.72/SPS22.00/SR0;997generations/18,989,059settledtokens,no unknowns.
DB/OS support banks are complete. Two OS workers and two travel support workers are now paused.
SUPPORT has 42 successful jobs, 14 failed, 2 paused and 8 unstarted; the early DB/OS batch has
27 successful jobs, 1 failed, 2 paused and 30 unstarted. All 221 remaining formal travel jobs are unstarted.
Full regression passed: 4,643 passed / 1 optional SDK skip in 4,177.63 seconds.
After the narrow v0.4 change, 16 affected tests, boundary, ruff, mypy and build passed.
The full suite was completed on v0.3 and was not repeated for this narrow change.
DB main F/O and verified replay are terminal: 820 native records, 3,053 generations / 12,036,387 settled TEST tokens, no unknown usage.
MiLAi correct F/O 81%/82% versus RB 76%/77% and Native 90%/88%; the paired intervals do not establish the required gain.
No source read or natural revision occurred in the 200 candidate DB main tasks.
OS formal evaluation is incomplete and paused; travel TEST, contribution/resource comparisons and
the fixed-input diagnostic are unstarted. An empty native-history recording fix passed three checks
with the upstream object; its separate runtime amendment is recorded. The original failed OS F job
retains 15 native records, task 90 lacks a terminal record, and 86 later tasks remain unstarted.
[DB formal results](../studies/active/MILA_REASONINGBANK_DB_RESULTS_20260916.md),
[Development results](../studies/active/MILA_REASONINGBANK_DEVELOPMENT_RESULTS_20260915.md),
[source/protocol](../studies/active/MILA_REASONINGBANK_SOURCE_AND_PROTOCOL_20260915.md),
[implementation and use](REASONINGBANK_NATIVE_RESEARCH.md),
[execution manifest](../data/manifests/reasoningbank-transfer-20260915.json).

## Latest closed first release

Stage: **ADAPTIVE_MEMORY_ENGINEERING_COMPLETE / RESEARCH_CLOSED**.
[Results](../studies/active/MILA_ADAPTIVE_MEMORY_DEVELOPMENT_RESULTS_20260915.md),
[experiment report](../studies/active/MILA_ADAPTIVE_MEMORY_EXPERIMENT_REPORT_v1.0_20260915.md),
[manifest](../data/manifests/adaptive-memory-development-20260915.json),
[usage](HOST_REVERSIBLE_WORKSPACE.md),
[complete Goal](../studies/active/MILA_ADAPTIVE_MEMORY_DEVELOPMENT_AND_CONTRIBUTION_GOAL_v1.0_20260915.md).
New method v0.1 / adapter v0.7: one current view, four maintenance modes, sparse revision,
Actor/Controller recall, optional review and public recovery implemented. 147 adjacent tests,
static/build checks and final public SDK lifecycle pass. Full regression: 4628 passed / 1 optional
SDK skip, exit 0, 4004.95 seconds; all 4629 distinct test identities have terminal coverage.
E1 all three native rewards are 1; OM/SIMPLE/CANDIDATE use 3/4/4 generations.
Both adaptive real reviews were rejected and the current drafts delivered UNREVIEWED.
One fixed-input diagnostic pair returns the same legal DELIVER in both branches; no prompt promoted.
Total 13 generations / 103,103 tokens settled, 85 allocated unused positions closed; no further sends.
Decision: KEEP_OM_AT_THIS_WORKPOINT / SPECIAL_POLICY_BENEFIT_NOT_ESTABLISHED.
N1–N4 working paths have engineering checks, but no natural revision/reuse benefit in this task.
E3 and M4 unstarted; product default and public schema unchanged.

## Previous closed RWC v0.4 result

On the exposed multi-source-data-merger task, SIMPLE scores reward 1 in 32 generations
(109,956 tokens), RWC scores 0 and ends INCOMPLETE in 32 (152,266 tokens), and OM scores
1 in 8 (59,878 tokens). Same-task quality/cost supports OM here, not a broad dominance claim.

W1 three-arm use, two W2 fixed-input diagnostics and W4 convergence are closed. D1 changes
the next action without establishing memory reuse; D2's recall format rejection confounds
its action change. Neither produced a policy to promote. RWC v0.4 / adapter v0.6 / OM v0.1
and the formal policies remain unchanged. Improved-version pairing, transfer and continuation
were not started; this is not completion of every optional route in the
[plan](MILA_RWC_v0.4_后续开发与创新验证规划_v1.0_20260915.md).

Total 80 generations / 358,729 tokens, all settled. Of 128 allocated positions, 48 unused
positions are closed; the unstarted 64-call full-pair reservation is also closed. Conditional
transfer/continuation packages remain unallocated. No further run follows from this summary.
72 nearby tests and boundary/ruff/mypy/build pass for this execution round; full regression
and public recovery were not rerun. Do not add these 72 to prior counts.

Both workspace arms deferred control only once despite batch=3; subgoal boundaries caused
earlier maintenance and summaries. No simultaneous batch=1 comparison establishes batching's
net effect. The ending path worked for SIMPLE and gave RWC an honest incomplete response;
neither observation proves special-policy benefit. OM also produced an inaccurate observation,
so task success does not establish long-history memory accuracy. N1–N4 net benefit remains unproved.

Previous live round: [usability results](../studies/active/MILA_HOST_MEMORY_CONTROL_USABILITY_RESULTS_20260914.md).
RWC v0.3 / OM v0.1 / adapter v0.5 implement sparse updates, independent OM and public recovery.
All three same-task native outputs pass (reward 1, 3/3); OM submits final in 7 calls,
RWC/SIMPLE use all 14 without final. Total 56/64 generations, 216,546 settled tokens;
unused allocation closed. Full regression for that version: 4578 passed / 1 skipped.
Architecture completion does not establish special-policy benefit or current-version live performance.

Previous development: [reversible workspace repair results](../studies/active/MILA_HOST_MEMORY_CONTROL_REPAIR_RESULTS_20260914.md),
[repair Goal](../studies/active/MILA_HOST_MEMORY_CONTROL_REPAIR_GOAL_v1.0_20260914.md),
[implementation/usage](HOST_REVERSIBLE_WORKSPACE.md).
MILAI_RWC v0.2: deduplicated materials, independent cards, ACT/RECALL/DELIVER, ordinary
WORKSPACE_SIMPLE policy, local and public Working State recovery implemented.
Real public SDK fresh-process recovery, CAS and revoked-dependency checks pass; zero model HTTP
for that lifecycle. Four native attempts: 41 generations / 135,952 tokens, all settled.
The one valid same-version pair ties at reward 1 (3/3 each); candidate saves 1 call / 1,573 tokens.
Both cancellation attempts lack scores. Frequent rejected Controller output and no natural recall
limit the behavior claim; BENEFIT_NOT_ESTABLISHED. Model allocation closed (215 unused).
Final adapter v0.4.2 also detaches checkpoint objects and reopens a finished checkpoint for a new
goal; 128 nearby tests and the final public lifecycle pass. Boundary/ruff/mypy/build pass;
all 4574 final test identities are terminal: 4573 passed / 1 optional SDK skip, no omissions
or duplicate counting. DEVELOPMENT_COMPLETE / BENEFIT_NOT_ESTABLISHED. Initial failures from a
pyproject packaging edit are preserved. The unnecessary edit was reverted, historical dependencies
match again. The slow test's 62 dependencies were unchanged by the final recovery patch;
all other test identities were rerun on final source. Final code/configuration digests match.

Previous development: [integrated Host workspace control](../studies/active/MILA_HOST_WORKSPACE_CONTROL_DEVELOPMENT_RESULTS_20260914.md),
[implementation/usage](HOST_WORKSPACE_CONTROL.md).
INTEGRATED_LOOP_IMPLEMENTED / SINGLE_NATIVE_TASK_PASS / REGRESSION_COMPLETE / BENEFIT_NOT_ESTABLISHED.
One independently authorized native CONTROL_0 trajectory: 26 generations / 71,708 tokens,
all settled; reward 1, native 6/6 passed. Real selection, feedback maintenance, two receipt
reads, one fresh-Host handoff and one delivery review observed; no natural branch return.
75 targeted tests, boundary/ruff/mypy/build passed. Its full regression is now terminal:
4520 passed / 1 optional skip in 4014.29 seconds. Unused 38 model calls closed.

Previous closed work: [HiAgent evidence-maintenance results](../studies/active/MILA_HIAGENT_EVIDENCE_MAINTENANCE_DISCOVERY_RESULTS_20260914.md),
[execution Goal](../studies/active/MILA_HIAGENT_EVIDENCE_MAINTENANCE_DISCOVERY_GOAL_20260914.md).
KEEP_SIMPLE_SPECIAL_POLICY_NOT_SUPPORTED: 8 attempts / 60 generations / 434,611 tokens,
all settled; one scored root, all valid rewards zero, transfer unscored. 4497 tests passed,
1 optional skip; engineering complete and prior allocation closed. This result is not
retroactively replaced by the new integrated method's single-task pass.

Historical execution: [HiAgent single-task results](../studies/active/MILA_HIAGENT_BASELINE_EXECUTION_20260914.md),
following the [method transplant](../studies/active/MILA_HIAGENT_BASELINE_IMPLEMENTATION_20260914.md).
LIVE_MECHANISM_OBSERVED / NATIVE_TASK_FAILED / ENGINEERING_COMPLETE.
One preserved invalid-action attempt and one interface repair: 57 generations / 50,153 tokens,
all settled within a separate 64-call allocation; unused 7 calls closed. The repaired trial
used 11 actor / 45 summary calls; 10 subgoals, 9 actor inputs containing summaries, no retrieval.
Native verifier: 5 passed / 1 failed, reward 0. No efficacy or product-default change claim.
86 targeted tests and boundary/ruff/mypy/build passed. Full regression exited 0 with
4473 passed / 1 optional SDK skip in 4040.54 seconds. Combined with the 5 new budget tests,
all 4479 current test identities have terminal results (4478 passed / 1 skipped; no duplicates).
The earlier interrupted regression remains historical evidence. Trial containers and regression exited.

Previous closed comparison remains [complex-task KEEP_SIMPLE](../studies/active/MILA_HOST_COMPLEX_TASK_POLICY_DISCOVERY_SUMMARY_20260914.md):
16 trajectories / 337 generations / 5,754,068 settled raw tokens, no transferable net policy benefit.
Its closed Goal and unused allocation remain closed; the HiAgent prototype does not reopen them.

Previous completed continuation Goal v1.1: [natural-context execution and results](../studies/active/MILA_HOST_CONTINUATION_RESULTS_20260914.md).
Completed: natural-context N/R/S and one interpretation diagnostic, 10 generations / 56,547 known raw tokens.
Full regression: 4433 passed / 1 optional SDK skip; all 4434 items covered. Other required checks/build pass.
Keep simple references and only a local interpretation hypothesis; prior restricted 6 calls / 24,196 tokens remain separate.

Previous managed follow-up: [implementation, comparisons and engineering status](../studies/active/MILA_HOST_WORKSPACE_MANAGED_RESULTS_20260914.md).
Managed v4 three-arm and NOTE retention ablation complete; 51 generations / 234,134 known raw tokens,
including preserved scheduling/capacity failures. All work records stayed empty. Keep simple NOTE and
opt-in managed capability; no stable policy or short-record benefit claim. The frozen-source test now
passes; full regression is terminal: 4423 passed / 1 optional SDK skip, with all 4424 items covered.
The original exit-139 run is preserved; fixed-inventory shards both exited 0, and other required
engineering checks pass. This development follow-up is complete; cross-source validation remains incomplete.

Latest Host workspace development: [A three-arm results](../studies/active/MILA_HOST_WORKSPACE_DEVELOPMENT_RESULTS_20260913.md).
One real source, NOTE/REVIEW/REGULATED complete; 10 generations, 44,209 known raw tokens, no new unknown usage.
All work records stayed empty; keep the simple NOTE reference and pause extra candidate trials.
B has a bounded unavailable disposition, not a completed second-source comparison. See the report for actual engineering limits.

As of: `2026-09-13`

Prior V0224 evidence snapshot: `GATE_A_FUNCTIONAL_PASS_UNDER_R03_R04_USER_PRIORITY / NATIVE_WMA_PARTIAL / JUDGE_TIMEOUT_USAGE_UNKNOWN / MEMORY_EFFECT_INCONCLUSIVE`.
See the [V0224 development and experiment report](../studies/active/MILA_V0224_NATIVE_WMA_DEVELOPMENT_REPORT_20260913.md)
for the 2026-09-13 17:45:47 Asia/Shanghai evidence snapshot. Native WMA has run; the original NOT_STARTED planning label is stale.
Three of eight primary answer units completed:165 answers and164 valid scored questions. Two baseline roots scored21/55 and22/55 Correct;
the first ordinary-Note root scored20/54 with one unresolved question. Five answer units and all review runs remain unrun.
The only paired root has identical question/retrieval/image records for55/55 questions; four identical answers receive different Judge labels.
No independent Memory benefit or harm follows from the one-question net difference.

[Latest native v4 terminal](/cra/memory/mx_memory/evidence/v0224/20260913-native-wma-v1/batch-terminal-v4.json):
NATIVE_BATCH_FAILED at judge-personal_18-M_note after a roughly600-second ReadTimeout.
511 generations have usage records totaling13,520,967 known raw tokens; one additional generation has unknown usage.
The actual total remains unknown. Revisions and failed scores are preserved; do not automatically retry or report the missing usage as zero.
Owned API/MCP processes were still present at read-only inspection; batch exit is not a service-shutdown certificate.

The [functional certificate](/cra/memory/mx_memory/evidence/v0224/20260913-cpu-completion-segment-v1/functional-gate-a.json)
closes CPU Gate A: complete 16+80 references, P3 16/16 and P4 24/24; 40 successful workers across 41 attempts.
Original P4 timeout evidence remains intact. Successful-path mock generations 96 plus failed-attempt mock generations 4 total 100.
Six engineering checks passed (4285 tests, one existing optional dependency skip); composed correctness, isolation, CAS,
receipts, world effects and accounting passed. This is not a single fresh batch PASS or an unchanged-R02 authority claim.
Efficiency is nonblocking; no further performance candidate or CPU calibration is planned.
Real model/experiment HTTP requests for this CPU acceptance are zero; engineering localhost protocol traffic is accounted separately.
Historical unknown usage and stopped runs are not erased by these zeros.

The [Goal v0.4](../studies/active/MILA_V0224_功能GateA收口与原生Benchmark最小实验_GOAL_v0.4_20260913.md)
remains the frozen planning document. The separately frozen [native contract](../configs/v0224-native-wma.json)
superseded its provisional zero allocation for the executed WMA batch, not for new work in this report.
Current implementation plans an extra review call after an M draft, not the Goal's same-call review; it has not run.
Next is resolving the unknown request and the evaluation/comparison limits, not redoing Gate A or developing State.
This report update grants zero new experiment/model/Provider HTTP/confirmation allocation. A0 default, public deployment and Schema NO-GO are unchanged.
[Execution history](../studies/active/MILA_V0224_EXECUTION_STATE_20260913.md), older Goals, R03/R04 and frozen evidence remain intact;
their earlier pending labels do not override the signed functional terminal. No real-model Memory effect has been established.

Frozen predecessor V0222 remains **blocked, unfinished**: see its
[experiment report](../studies/active/MILA_V0222_EXPERIMENT_REPORT_20260913.md) and
[execution state](../studies/active/MILA_V0222_EXECUTION_STATE_20260912.md).
Its 3329 PASS / 1 optional skip is historical engineering evidence. Actual CPU preparation stopped before
first P4 generation, with two admissions totaling 97.161 seconds against a 60-second Session.
All 40 old formal CPU positions remain PENDING. Historical V0222 usage is 54 real generations /
1,051,344 settled raw tokens; cross-history actual usage remains unknown because the old 28,284 reservation is unresolved.

## Historical V0222 boundary signal and implementation milestones

[Diagnostic](../studies/active/MILA_V0222_BOUNDARY_DIAGNOSTIC_20260912.md) completed the frozen
16-request matrix: B0 exact4/8, B1 exact8/8; two same-root improvements repeat in both orders.
568796raw settled,0new unknown/business effects.48tokenize/36identityGET, HTTP-only;1959tests pass/1skip.
Final independent result review PASS. [Full-gate design](V0222_PRESENTATION_FULL_GATE_DESIGN_NOT_ADMITTED.md)
has offline-only scope review; finish and multi-turn execution are untested extensions.
New full/finish16 and conditional24 execution chains require new implementation, freeze and review.
Old stopped P3 and all downstream NOT_TRIGGERED states remain unchanged; the old V0222 Goal remains blocked; V0224 is progressing separately.

[Offline implementation](../studies/active/MILA_V0222_PRESENTATION_IMPLEMENTATION_20260912.md):
complete new-scope16+80 references,24chains and40SQLite Worlds verified and independently hash-reviewed;
current-auditor revalidation PASS. Full Batch Mock16→24 plus2388tests/1optional skip PASS.
The sole formal instance has completed offline preparation (16+80 references,24chains,40Worlds);
final scope review and16/16 P3 HTTP capacity passed. [Terminal](../studies/active/MILA_V0222_PRESENTATION_FULL_GATE_20260912.md):
12P3 PASS,13th EPISODE_DEADLINE at the1800s phase bound;13requests/449759raw settled,3P3/24P4 unrun.
Independent terminal review PASS with5784stable files; offline read-scope engineering follow-up only, stopped instance cannot retry.
[Offline component](V0222_ADMISSION_READ_SCOPE_OFFLINE_20260912.md):46local tests and independent review PASS,
component baseline2434tests/1optional skip PASS (session6214 terminal); boundary/Ruff/Mypy/build PASS.
5784-file scale and5267 JSON parses independently checked; [evidence adapter R2](V0222_SCOPED_EVIDENCE_IMPLEMENTATION_20260912.md)
has64local tests/review and exact5865-file old/new/close coverage PASS; full pytest89818 completed2498PASS/1skip.
The [subsequent history adapter](V0222_SCOPED_HISTORY_IMPLEMENTATION_20260912.md) recomputes57pinned ledgers;
its own later full baseline is2574PASS/1skip. [Partial Batch core](V0222_SCOPED_BATCH_IMPLEMENTATION_20260912.md)
has a 2707-pass/1-skip core R1 baseline; [new execution wiring](V0222_SCOPED_EXECUTION_WIRING_20260912.md)
now has3097PASS/1skip and independently reconstructed complete Mock16→24 plus two negative raw cases.
[CPU entrypoints](V0222_SCOPED_CPU_REPLAY_IMPLEMENTATION_20260912.md) retain the earlier192-component/124-dependency checkpoint.
67617 subsequently reported one failure and was closed with authorized cleanup; replacement baselines passed.
Current230-component/126-dependency measured revision passed full regression but its CPU instance stopped in preparation.
Actual40 cold processes and full-stage timing remain unproven; the new live root was not created.

## V0222 bounded result: string signal, full target fidelity NOT_MET

[Improved Goal](../studies/active/MILA_V0222_解码语义与意图保真改进_GOAL_20260911.md) records
read-only request evidence and a bounded decoder-rule diagnostic before any prompt changes.
The correct action was already present at the end; recipient/summary share pattern and minLength rules.
No live backend cause is established. [Roadmap](V0222_后续执行与Memory再准入规划.md) separates
full action fidelity, known-intent execution, recovery, natural no-carry competence and later Memory use.
[P1 result](../studies/active/MILA_V0222_P1_STRING_DIAGNOSTIC_20260911.md):24requests/4451raw,
D11 uniquely selected6/6; all current usage settled. User-directed implementation is active:
[P2 design](V0222_STRING_RULES_RUNTIME_V1_DESIGN.md),96full-reference HTTP preflight PASS,
1812tests pass/1skip. First P3 selects legal S01 instead of authorized manager_report;
HTTP/full-schema PASS,28338raw settled,0business dispatches. Permanent stop,15P3/24P4 unrun.
[Complete batch results](../studies/active/MILA_V0222_RESULTS_20260911.json):25requests/32789raw,
0new unknown. P4/E1/E2/M0/M1 NOT_TRIGGERED; [residual boundary plan](V0222_RESIDUAL_INTENT_BOUNDARY_DIAGNOSTIC_PLAN.md)
requires a separate frozen reviewed instance. HTTP-only, no service/device calls.
V0221 remains stopped; historical unknown, A0 and Schema NO-GO remain unchanged.

## Completed bounded check: V0221 HTTP-only, intent fidelity NOT_MET

[Report](../studies/active/MILA_V0221_HTTP_ONLY_EXECUTION_20260911.md): no direct device/driver/container
calls. Full96-reference/192-tokenize preflight PASS. First W2 full returns HTTP200 and valid complete
schema JSON but recipient/summary differ from the explicit authorized values.1request/27864raw settled,
0new unknown,0live business effects; permanent stop,15W2 positions and24W3 chains unrun.
Local pre-generation branch-order correction retained separately with0model/0tokenize attempts.
31new HTTP/admission tests;1602pass/1optional skip; coordinator/Provider/audit implemented.
Old usage unknown remains; no Memory admission or service/Product/State/pool change.
See [HTTP-only supplement](V0221_HTTP_ONLY_EXECUTION_V1.md) and Goal section13.

## Historical bounded check: V0221 SERVICE_NOT_READY; W2/W3 not triggered

[Report](../studies/active/MILA_V0221_LIVE_COMPAT_AND_EXECUTION_20260911.md): user granted
path B for W2/conditional W3 with old unknown retained. Early W1 check: baseline identity/selected
parameters match and HTTP200, but container NVML fails and diagnostic cuInit returns NO_DEVICE.
Persistent stop recorded;0model/0tokenize calls,16W2 positions and24W3 chains unrun.
26new authorization-scope tests;1571pass/1optional skip. Full coordinator/Provider/capacity integration
is not implemented or admitted. No service changes; no further GPU queries/calls without specific
user agreement. Historical usage remains unknown, A0/Schema NO-GO and protected pool unchanged.

## Latest repair: wire compatibility CPU PASS; live/V2 still not admitted

[Repair](../studies/active/MILA_V0220_WIRE_COMPAT_FIX_20260911.md) implements an explicit
dual-contract opt-in Provider: uniqueItems is deferred in generator grammar only; unchanged
full public schema remains presented and enforced before dispatch. No value repair or target filtering.
Eight wire CPU variants pass; 25 full mechanical records and duplicate/identity/CAS guards pass.
40 new tests,1545pass/1optional skip. Historical usage guard verified with zero HTTP:
2221known raw +28284unknown reservation, actual total unknown. No real generations, V2/Memory
admission, Product/shared-service changes or pool access. See [design](V0220_PROVIDER_WIRE_FIX_DESIGN.md).

## Latest follow-up: Provider hardening; DO_NOT_RESUME_V2

[Report](../studies/active/MILA_V0220_PROVIDER_HARDENING_20260911.md): all four original full
schemas checked with installed validation code; 3 reject uniqueItems, 1 CPU pass; finish controls4/4.
Actual error wrapper reproduces the identical empty-message HTTP500 from schema rejection.
32 new offline tests verify explicit unknown usage, exact request/response evidence and no retry.
Historical usage remains unknown: 2221 known raw plus 28284 unresolved reservation, not a total.
No new generation, State, task, service change or silent integration into frozen V2.
The earlier closed report below retains its original knowledge state; this follow-up adds evidence.

## Latest completed: V02-20 — bounded validity failure, no Memory readmission

[Final report](../studies/active/MILA_V0220_FINAL_REPORT_20260911.md) closes the
[Goal](../studies/active/MILA_V0220_动作执行有效性校准与记忆复验准入_GOAL_20260911.md)
under its bounded failure/unknown-usage stop rule: CONTRACT_CALIBRATED_ONLY / VALIDITY_BLOCKED /
INCONCLUSIVE. V0/V1 mechanical checks pass (75 adapter/Host tests,25 full records,88 cold faults,
16 scripted Host processes,4 independent Note/DONE negatives);14 additional V2 auditor tests pass.
Two real small synthetic compatibility requests pass, but the first full V2 request returns HTTP500.
24 chains frozen,1 attempted,0 completed,23 unrun; no model action or business effect.
Full schema uniqueItems incompatibility reproduced on CPU; exact HTTP500 cause and usage remain unknown.
Three total Provider requests:2 settled/2221raw,1 pending/28284raw reservation; actual total raw unknown.
V3–V5 not triggered, all four roots unadmitted. No extra compatibility, second candidate, Product changes,
service restart or protected-pool opening. Shared vLLM unchanged; C=0. Fourth old root remains hr_task3.
This does not establish model encoding/task competence or a Memory effect. See the
[execution ledger](../studies/active/MILA_V0220_EXECUTION_20260911.md) for immutable evidence hashes.

## Latest completed study: V02-19 bounded failure discovery; no qualified regime

[Final decision](../studies/active/MILA_V0219_INNOVATION_DECISION_20260911.md),
[baseline](../studies/active/MILA_V0219_BASELINE_RESULTS_20260911.md) and
[failure map](../studies/active/MILA_V0219_FAILURE_MAP_20260911.md):
WHOLE_GOAL_COMPLETE_WITH_DECLARED_VALIDITY_GAPS / FAILURE_REGIMES_RECORDED /
KEEP_SIMPLE_NO_QUALIFIED_REGIME. G_REGIME not met; pause this consumption profile,
zero candidates/pilots, F4–F6 NOT_TRIGGERED. No new allocation or C consumption.

[Execution ledger](../studies/active/MILA_V0219_EXECUTION_20260911.md):
F0 full-file neutral inventory and exposure reconstruction completed with explicit gaps;
A-lane Seal A freezes 62 D candidates / 9 families and protects 26 reserve candidates / 4 families.
All 18,760 pinned files / 10,800,744,184 bytes reverified; 100 ClawMark tasks, 461 WMA JSON
candidate files (not independent histories), and Supersede generator/code inventoried separately.
Compacted history and missing comprehensive access logs prevent proving non-exposure:
C static accepted=0; reserved candidates are not an admitted confirmation set.
First fifty-six candidates decided in frozen order: four ACCEPT_STATIC (real-estate, investment
analysis and two HR roots), fifty-two HOLD (forty-eight text-profile modality/source gaps, three prospective capacity gaps,
and one final-text-only/source-grounded-variation gap). First accepted prefix is [1, 3, 31, 56];
candidate 57 remains unopened and further opening pauses for the first baseline wave. Accepted roots span
three families. Full profiles have 272, 175, 271 and 331 offline calibration checks, preserving source conflicts
and content-bound semantic review, not keyword scores. PDF layout/complete HTML text sources
are supported without OCR or cropping; an unusable Disney HTML challenge is not treated as data.
The baseline-only wrapper preserves exact R1 and full pending-question prefetch equally;
prospective complete inputs fit live 65536 context. Full Host assembly tested offline;
accepted profiles/hash/code frozen. Current model config includes vision architecture, but Seal A
is explicitly text-supported; HOLD is not a claim of intrinsic model visual incapability.
Candidate 14 completed 328 offline artifact checks and 60 real file exports across four SQLite
worlds, but its complete reference cold start exceeds context even in N0 without Note (71221 tokens).
Candidate 21 retains all five HTML bodies; even a lower-overhead common-Note R1 diagnostic plus
output reservation exceeds context. Both HOLDs are prospective profile limits, not model failures.
Candidate 31 is now statically accepted: actual supplied audio transcripts and full PDF/workbook text,
seven complete records, 271 source-reviewed calibration checks, five SQLite worlds and 35 actual file exports.
Its answer-bearing instruction file stays evaluator-only; source-supported alternate recommendations
require explicit tradeoff and cross-record semantic review, not native-gold selection. Five full-input
tokenize diagnostics fit 65536 with4096 output; synthetic Note/reference A are not natural model outcomes.
Candidates 36–42 remain source/modality HOLDs, not model failures. Candidate 40's referenced student
submission directories are absent from both pinned catalog and local task, not evidence of missing downloaded bytes.
Candidates 43–52 are also HOLD. Candidate 48 has legitimate final technical-assessment text, but its
earlier complete verification needs unsupported media and no later native change remains after that final text.
This is a declared profile limit, not a claim that all narrative evidence is missing. Supplied audio transcripts
in candidates 51/52 and substantive documentary sources throughout were retained rather than mislabeled missing.
Candidates 53–55 are source-verification HOLDs; available PDF/email/transcript facts are preserved.
Candidate 56 is accepted with three full interview transcripts, all score/log/schedule/weekly sources,
the formal complaint email and both policy pages. Seven complete documents retain actual score correction,
three ATS cases, all coordination messages and weekly reporting. Five SQLite worlds/35 exports and
331 checks pass. Friday's native deadline triggers reporting and overdue Legal follow-up, not new evidence
or invented clearance. Administrative closure and concrete continued-follow-up alternatives require
consistent current-status metrics; native answer-bearing AGENTS is withheld as an explicitly replaced contract.
Five full-payload tokenize checks fit context; one premature capacity precheck failed before Provider access
and is retained. Those capacity checks made no experimental generation requests.
The new batch runner and full-request/public-Note/SQLite auditor are implemented; 28 additional
offline tests cover natural-Note, NO_WRITE, read-only handoff after a settled resource stop and
tampered evidence. These are synthetic tests, not real chain claims.
First wave `f2-wave1-v1` is executed: four roots, 28 episodes,448 actual generations,
unchanged16/4096/900-second episode bounds and exact N0/N1/R1. C remains untouched.
Manifest SHA256: `e70a4a2030e8ffff7c0b51d4a62a3761ce6a4a1f28f6eca6082d1b5597ab0159`.
Run-specific public Product delivery and installed wheel bytes verified; only owned scopes/services.
The original run ended normally with28/28 episodes,448 requests/9,820,337 raw,
pending0/violations0 and no uncompleted items. Do not restart or overwrite its frozen artifacts.
All28 actual chains have been replay-audited:4A/24B,12B old/current dual presentations,
120 full public prefetch reads and matched same-world inputs. The second A made no
Note write: its15 successful reads never queried policy, where the complete documents
were available. Its B arms received full policy through the common prefetch but have no
inherited-Note dual-presentation denominator; NO_WRITE is retained, not repaired.
First-root A plus six B source-bound nonblind reviews are complete: all six B final
business states fail, all have protocol rejections, and only Changed-N0 commits B records.
Changed-N0 repairs the exhaust field but falsely claims completed negotiation; Changed-N1
attempts the correct exhaust value but cannot execute it. N0 also exhibits the same
rent-calculation and identity-field errors, so these are not established Memory causes.
Eight existing B semantic fields were adjudicated; missing records remain structural failures.
Second-root sixB semantic review is complete:42 actual fields,31CORRECT/9INCORRECT/2DISPUTED.
All six B write correct core numeric facts but leave required objects absent; three falsely
claim specific record/delivery completion. No inherited-Note effect denominator exists here.
Third-root seven episodes are reviewed; five B keep the flawed A records unchanged and
Changed-N1 writes plan/fourATS but falsely claims two absent outbox deliveries. Changed-N0
also makes false plan/report and no-escalation claims without inherited Note.
Source review discovered a private-checker overextension: public policy explicitly fixes
organizational medium risk, not a unique personal low-to-medium mapping. Seven affected
field verdicts are therefore disputed via an append-only addendum; original frozen scores
remain. Effective third-root semantic counts:7CORRECT/5INCORRECT/7DISPUTED.
Missing deliverables and honest-reporting/actual escalation obligations remain independently
checkable. Individual exact-risk labels must not become definitive failure/regime evidence.
Fourth-root review is complete: all seven episodes have empty business records; mixed A Note,
repeated identity rejections, and Changed-R1 final false completion despite previously recognizing Friday due.
All28 episodes now have source-bound reviews and a full F3 map. Effective semantic fields total
38CORRECT/23INCORRECT/9DISPUTED, no unreviewed required fields; missing objects fail independently.
All24 B fail complete delivery,8 have actual business writes,7 have definite final false completion.
G_REGIME is not met: common protocol failure is an upstream supporting problem, and the remaining
source-valid R1 patterns lack sufficient unconfounded independent roots. Four-family coverage is the
overall D target, not a separate first-wave gate; the registered branch allows closing after this wave.
C2 remains closed, no mechanism preselected; calibration is not model behavior evidence.
First-wave allocation448 is settled; no new batch allocated. Judge=0, raw cap=null.
Owned API/processes stopped, owned PostgreSQL Exited(0), volume retained; shared vLLM stays running.
Product/A0/schema unchanged. Pre-wave35 tokenize diagnostics remain separate from actual request prechecks.
Latest full gates PASS, 1384 tests / 1 optional SDK skip (39.80seconds), including28 offline batch tests;
all frozen implementation/dependency hashes revalidated unchanged after the checks.
The latest increment references the prior full-download audit and rechecks unchanged catalogs,
newly opened task assets, ordered receipts and 274 accepted code/artifact hashes; hf.env was not read.
Old 12D and protected pools remain excluded; all V0218 results and accounting stay separate.

## Latest completed research: V02-18 bounded discovery and innovation decision

[E5 decision](../studies/active/MILA_V0218_INNOVATION_DECISION_20260911.md):
WHOLE_GOAL_COMPLETE / KEEP_SIMPLE_NO_CANDIDATE + ENGINEERING_GAIN_ONLY.
T0–T5 and E0/E1/E2/E5 complete; zero qualified mechanism candidates, E3/E4 NOT_TRIGGERED.
The testbed remains a contribution candidate requiring external review, not proven novelty.

[T5](../studies/active/MILA_V0218_T5_REVIEW_20260911.md): 12 adapted source lineages / 9 coarse
families, 49 actual replay branches; all exposed D, unopened C=0.
[E0](../studies/active/MILA_V0218_E0_V4_20260911.md): six-root standard 42 episodes plus
20 separately counted probes; S*=N1. Failures preclude a baseline-sufficient conclusion.
[E1](../studies/active/MILA_V0218_E1_DISCOVERY_20260911.md): two candidates/two roots/two cold
runs, 28 episodes. C2 B 8/8 vs N1/C1 6/8, quality signal confined to one scheduling update.
[E2](../studies/active/MILA_V0218_E2_RESULTS_20260911.md): all 32 episodes completed and audited,
30 exact cold dual presentations and 120 complete public prefetch reads shared across five arms.
C2 and ordinary review R1 have identical paired outcomes (3/6); N1/C1/P1 each 2/6.
All Stable pass; unresolved tasks and news updates remain failures. No distinct C2 structure claim.

All 14 closed model batches, including failed protocols: 1340 requests / 3,353,114 raw,
pending/unknown/violations=0. Raw cap null; Judge=0. Owned API/compose stopped, volumes retained;
no active allocation. Final gates: 1258 tests / 1 optional SDK skip, boundary/Ruff/mypy/build/diff PASS.
[Downloads](../studies/active/MILA_V0218_BENCHMARK_ACQUISITION_20260910.md): pinned repositories
and 16,059 WMA data files upstream-hash verified; matching MemTrap executable artifact remains HOLD.
Product uses separately verified immutable public releases; existing global pin drift preserved.
No Product behavior/API/schema/permission changes, A0 switch, protected-pool access or deployment.

## Latest admission: V02-17 validity gaps recorded; full P Lane remains unadmitted

[Goal v0.3](../studies/active/MILA_V0217_Benchmark_Discovery与行为真值准入_GOAL_20260910.md) and
[B0–B4 admission report](../studies/active/MILA_V0217_BENCHMARK_ADMISSION_20260910.md):
`VALIDITY_GAPS_RECORDED`. Four candidates audited; 40 local native-function checks expose 11
semantic counterexamples, and 66 data-boundary/simulated-event checks pass. WMA data revision
and CC BY-NC license verified; one public sample inspected. MemTrap artifact locator remains HOLD.
Native Agent tasks/model/Judge requests=0; P Lane admitted=0. Partial PROBE_ONLY is not full
runtime admission. Lab gates pass, 777 tests / 1 optional SDK skip. Original preflight is preserved.
The old v0.1 N0/N1 design is historical, not the current execution contract.
Local vLLM/model/key mapping is allowed; no cloud key is required, and no gold fallback is allowed.
No new model generation or Judge requests, Product implementation, permission/schema changes,
public deployment or protected-pool access. V02-16 stays complete; A0 remains the default.

## Latest model experiment: V02-16 failure map recorded; keep simple, no memory-causality claim

[Execution](../studies/active/MILA_V0216_EXECUTION_20260910.md) and
[failure map](../studies/active/MILA_V0216_FAILURE_MAP_20260910.md): two synthetic roots,
0 → 32 → 8 other-object records, fixed NOTES/REMINDER policies and normal tools/resources.
36 deliveries, 28 supported correct; 7 retrieval/representation failures and 1 necessary
acquisition not attempted. All 118 requests / 581,953 raw settled; no token cap, no Judge.
Models chose zero notes, so persistent-memory use and old-premise persistence were not exercised.
767 SDK-environment tests and Lab gates pass; three owned service stacks stopped, volumes retained.
No new mechanism, protected-pool opening, A0/public deployment or Schema change. T0–T3 complete.

## Previous: V02-15 bounded open exploration complete; no candidate selected

[Execution](../studies/active/MILA_V0215_EXECUTION_20260910.md) and
[mechanism/selection memo](../studies/active/MILA_V0215_MECHANISMS_AND_SELECTION_20260910.md):
two disclosed synthetic roots, ordinary notes vs simple reminder vs checkpoint, then adaptive
delivery/readiness diagnostics. All attempts: 88 local requests / 458,071 raw, unknown zero;
9 infrastructure failures retained. Final readiness comparison: notes/reminder 2/2, checkpoint
1/2 at higher cost. R1/R2 select zero candidates; R3–R5 conditions not triggered, no independent
confirmation or product-benefit claim. 761 tests with SDK pass, Lab static/boundary/build pass;
four owned environments stopped. A0, protected pools, public deployment and Schema NO-GO unchanged.

## V02-14 successor: actual opt-in SDK Host integration verified locally

[SDK Host follow-up](../studies/active/MILA_V0214_SDK_HOST_FOLLOWUP_20260910.md): the local
Host now explicitly selects wheel-pinned Client 0.1.4 and keeps one event loop per cold session.
All 16 exposed-development phases pass (15 deliveries, 1 clarification), including actual
Note save/cold recovery and concurrent scope isolation. New allocation: 29 requests / 194,079
raw, all settled, cumulative token cap null; old D0–D7 accounting remains separate and unchanged.
752 tests pass with the actual SDK wheel (default Lab: 751/1 optional skip); static/boundary/build
pass. Owned services stopped. MCP retains its frozen Client 0.1.3/Runtime 0.1.4 hash-backend stack;
no external Host, BGE, independent-confirmation, default-flip or release/deployment claim.

## V02-14 complete: independent synthetic confirmation and optional Client helper

[V02-14 report](../studies/active/MILA_V0214_HOST_RESULTS_20260909.md): generic bounded
source acquisition, readiness-first typed delivery and durable final reserve complete D0–D7.
Final development H passes 16/16 phases; independent synthetic confirmation H 4/4 versus
A0 1/4, fixed lexical diagnostic 2/2 long cases. All failed development attempts retained:
133 requests / 877,655 raw, unknown usage zero; no cumulative raw-token cap.
Client 0.1.4 now has an explicit-import mechanical helper, locally built and not deployed/default.
Lab 748, Client 209, MCP 385 passed/7 optional skips; all six adapter checks/builds pass.
Public Runtime is separately verified 0.1.5; experiment retains frozen 0.1.4/hash-backend pin.
No BGE effect claim, State mechanism, protected-set opening, public change or Schema freeze.

## V02-13 Host cold recheck verified; A0 retained

[Host recheck](../studies/active/MILA_V0213_HOST_RECHECK_20260909.md): H1 v1 fails its second
cold coordinate run; H1 v2 reads public source pages through EOF and uses typed intent delivery.
Both original adjudicable tasks pass both independent cold Host/Product rounds (4/4 delivered
correct intents). A0 stays unchanged: coordinate abstentions, weather correct; no parameter 0/2
claim. 30 new requests/276,265 raw across v1/v2, all settled, no cumulative token cap.
685 tests and all gates pass; services stopped. No State, new samples, public deployment,
BM25/Product retrieval claim, or isolated causal claim for completion-classification alone.

## V02-13 P3 complete; fixed prefix exhausted, task-contract gaps identified

[P3 results](../studies/active/MILA_V0213_P3_RESULTS_20260909.md): remaining two accepted tasks
run A0/R1; both Oracles declared insufficient before generation (ambiguous subject / missing
business ID). 8 requests/71,781 raw, all settled; combined 16/145,220 with cumulative tokens
uncapped. A0 abstains twice; R1 has one empty-plan format failure and one unscored intent.
All P3 parameter denominators zero; no task substitution or new effect claim. Keep A0 and the
first-wave classification fix; next candidate is the task/clarification contract, not State.
676 tests, boundary/Ruff/mypy/build pass. Owned services stopped; confirmation unchanged.

## V02-13 first-wave historical result; action-delivery classification fixed

[Results](../studies/active/MILA_V0213_RESULTS_20260909.md): zero-generation replay reconciles
all 10 old requests/69,325 raw and reconstructs both unsent third payloads. Fixed Mem2ActBench
admission reserves 98 confirmation clusters; first two of four accepted clusters run A0/R1/O.
8 new local requests/73,439 raw, all settled under the user's uncapped cumulative-token policy.
A0 has one source-acquisition abstention and one empty-plan format failure; R1/O each deliver
two correct parameter intents. Empty business plans now fail completion classification; no
repair generation or behavior-benefit claim. 669 tests, boundary/Ruff/mypy/build pass.
Keep Product 0.1.15/A0, no State or public MCP deployment; owned services stopped, evidence retained.
At that first-wave close P3 was not allocated; the continuation above supersedes that status.
Earlier Horizon confirmation/unrun tasks and V02-11 status remain unchanged.

## V02-12 bounded Horizon diagnosis complete; keep A0

[Results](../studies/active/MILA_V0212_RESULTS_20260909.md): cluster-first Seal A/B accepted
12 clusters/24 queries. First wave plus one conditional fixed-prefix wave ran4 clusters/8 queries:
10 local generations/69,325 raw,6 final answers (2 correct/4 incorrect),2 budget stops.
No new independent same-kind failure in wave2; no State mechanism proposal.55 confirmation
clusters/712 questions stay sealed;16 accepted queries NOT_RUN.609 tests/checks pass;
owned services stopped, volumes retained. V02-11 remains blocked/incomplete.

## V02-11 stopped at external-sample qualification; A0 diagnosis incomplete

[Admission report](../studies/active/MILA_V0211_ADMISSION_20260909.md): X0 metadata/source
engineering and subagent qualification review complete their recorded scope. All 69 positions
remain: 59 lack an eligible new partition, the fixed first candidate is an exposed near-duplicate,
and nine later candidates are NOT_RUN under the sequential rule. No substitution or protected
partition opening. Zero benchmark generations/raw; no QA or State-use inference.
200 trajectories/5,095 states/images preserve full Small sources; online backend FIT_UNVERIFIED.
Independent X0 checks pass: 18 actual public MCP calls verify two synthetic Notes/State
scopes and denied cross-scope reads; source pagination/search/original-image transport pass.
601 tests and checks pass; the new owned services are stopped. A new qualified allocation
is still needed; actual model image presentation and QA remain NOT_RUN.

## V02-10 v0.5 bounded pilot complete; baseline retained

[v0.5 results](../studies/active/MILA_V0210_V05_RESULTS_20260909.md): independent dynamic
A/B, zero-model Git/real MCP mechanical recovery and four cold N/S processes completed.
12 local generations / 10,346 raw, paid 0, all settled. Dynamic prompt net gain unproved;
cold full sufficiency 0/4. Current candidates close; general H2/H3 remain research questions.
598 tests and boundary/Ruff/mypy/build pass; owned services stopped, data retained.
The following v0.4 entry retains its original scope and results.

## MILA-V02-10 v0.4 completed through negative diagnosis; baseline retained

[Terminal record](../studies/active/MILA_V0210_CONTROL_RESULTS_20260908.md): complete-material
C0/C1/C2 E1 plus two controlled B2 scenarios used 10 local generations / 43,656 raw tokens.
E1 full sufficiency is 0/3; C2 adds no qualified benefit. B2 corrects the targeted old error but
does not establish complete semantic safety. No P2/E2 or P3/E3 expansion; Product 0.1.15/A0 remains.
The allowed terminal is COMPLETED_DIAGNOSED_KEEP_BASELINE; 590 tests/static/build checks pass.

## MILA-V02-04 non-model increment complete

[Cost audit and readable environment](../studies/active/MILA_V02_COST_FIRST_RESULTS_20260906.md):
C0–C2 complete; 24 failed reads replay successfully, 12 full histories recover byte-for-byte,
and all 180 tests plus static/boundary/build checks pass. Field-order and optional edge-field
removal checks cover reader robustness, not Agent generality. Zero new model sessions/tokens;
C3 remains unentered because cumulative task-cost control is unverified. Historical ledger,
Product pin and N5 status are preserved; all 12 smoke containers removed.

## MILA-V02-03 correction complete at the cumulative token gate

[Payload fidelity repair and continuation](../studies/active/MILA_V02_PAYLOAD_FIDELITY_CORRECTION_20260906.md):
the original terminal-newline stop was corrected with a general Product input repair. Four ordinary
notes roundtrip unchanged; 12 followups across three complete histories were correct in offline
source review and met their per-history cost gates. N5's other history completed G/save but its four
followups were blocked by the original 2.4M-token launch gate. All17 allocations/16 actual model
sessions are terminal, known usage2402257. Confirmation remains incomplete; full A0 stays selected.
Product real-PG971 passed/1 dependency skip; Lab158 tests and static/boundary/build gates passed.
Own services stopped, data retained, auth copies0; no public deployment or automatic maintenance.

## MILA-V02-02 complete; import speedup retained, A0 unchanged

[Execution and terminal results](../studies/active/MILA_V02_LME_INCREMENTAL.md): 14 allocations are
terminal, including the source-session annotation leak and its repaired diagnostics. No justified
QA candidate entered L2/L3. Three full484-Event controlled imports reduced serial preparation from
about165s to4–5s with matching public capture/projection/retrieval results. Two actual conditional
updates and four independent U/V pairs yielded eight correct followups; net token/wall gains were
negative for both histories after generation cost. Keep A0; no automatic maintenance. Lab boundary,
Ruff, mypy,133 tests and build passed. Own services stopped, all data retained; Product code/public
deployment, Formal500 and Product-11 remained unchanged.

## v0.2 usability-first memory flow complete; baseline retained

[MILA-V02-01](../studies/active/MILA_V02_MEMORY_FLOW.md) completed G0–G4 as
`COMPLETED_KEEP_BASELINE`. Real Host use/save/resume, eight A0/A1 pairs, three A0/H1 pairs,
one actual-update U/V pair, all 12 G2 followups, and four new planning/writing tasks plus two
followups are recorded. A1/H1 produced no net task wins; the baseline remains selected. All46
allocations include early failures and Host deviations; known usage totals2774937 raw input/output
tokens, with two startup failures' usage unknown. Automatic stale-State maintenance and saved-memory
net value remain unproved. Lab gates: boundary/Ruff/mypy/build PASS,123 tests passed; Product
adapter gates and real PostgreSQL refusal probes passed. No Formal500, public deployment,
Product-11 restart or Schema freeze.

## LME D2 selector validation complete and negative

The D2 mechanism probe was followed by a presealed, label-blind selection simulation on the 21 S2
opened-development cases not used to design the policy. Public Context covered `23/32` exact answer
turns and had nine misses across seven cases. The D2 candidate pool contained two of those misses,
but the frozen first-novel-per-source/global-cap-20 selector recovered `0/9`; gain/loss cases were
`0/0`. One recoverable miss was already coarse and belongs to admission/frontier behavior, while the
other was the third novel turn in its source. D2 remains SHADOW and no Product/X2 effect claim is
made. A 484-Event timing probe measured capture `21.916s`, projection tail wait `0.951s`, and resolve
`0.686s`; capture, not projection readiness, dominates the measured critical path. See the
[LME behavior report](../studies/active/MILA_LME_CODEX_BEHAVIOR_SIMULATION_20260905.md).

A subsequent zero-Skill, single-MCP guided D1 diagnostic targeted all seven known public-gap cases.
Codex made seven correct predecessor-bound second calls and received 152 novel turn refs, but those
pages recovered `0/6` missing required turns within the same runs; exact-turn-complete cases stayed
`2/7` from Call 1 to cumulative Context. For 3,419 Events, capture took `161.368s` and projection
readiness tail waits took `2.878s`. This independently confirms that more persisted-page consumption
is not a substitute for better acquisition/admission and that capture dominates test latency.

## MCP tool-selection isolation complete

The zero-Skill S0-S3 matrix isolates the HC4 activation failure. An explicit request selected and
completed `milai_working_state_get(scope=TASK)` with all 13 tools visible (`1/1`), proving MCP
callability. The identical generic resume intent then produced zero MiLA calls with only State
GET/UPDATE, with resolve plus State GET/UPDATE, and with all 13 tools (`0/3`). Thus tool-catalog
dilution is not the primary cause and catalog narrowing is not a sufficient repair. The frozen
trigger-first metadata treatment is exhausted; S4 was not entered. `MCP_AUTO` is best effort, while
deterministic resume requires a separately claimed `HOST_MANAGED` prefetch path. See the
[selection study](../studies/active/MILA_MCP_TOOL_SELECTION_STUDY.md).

## HC-4 terminal: guided self-maintained adoption negative

HC4-A1 completed the previously missing third chain with four fresh-Codex public-IP HTTPS/OAuth
engineering sessions. The only treatment was bounded, non-mandatory guidance in the existing MCP
instruction and two tool descriptions. Runtime, State schema, 13-tool catalog, scope/CAS/TTL/RLS,
Canonical and retrieval remained frozen. Natural Working State use was again zero (`0/4`). JSONL,
MCP journal and PostgreSQL agree on no GET/UPDATE and no ACTIVE State. The preregistered terminal is
`HC4_A1_GUIDED_ADOPTION_NEGATIVE`: prompt escalation stops, the self-maintained route is parked as
manual/explicit, and HC4-C2 usefulness remains not evaluable. See the
[A1 study](../studies/active/MILA_HOST_COGNITIVE_AFFORDANCE_HC4_A1.md).

The combined HC4 observation is now 12 real sessions across 3 chains with 0 natural State calls.
This is not a usefulness comparison because definition-valid continuation sessions remain zero.
Any automatic start-read/end-write policy requires a separate Host-managed claim.

### A0 sealed baseline

The first Host Cognitive usability study stopped at the frozen minimum-sample gate as
`HC4_INCOMPLETE`: 8 real fresh-Codex session-tasks across 2 continuous workstreams were completed,
versus the required 10 tasks / 3 chains / 6 continuation sessions. At that A0 execution time,
Product-11 kept Chain A blocked on real-human labels and continuation opportunities; no authorized genuine schema/migration task
was available for Chain B. No task, failure, State or label was manufactured to fill the matrix.

The early observational signal is strong but not a PASS/PARKED effect verdict: all 8 eligible tasks
received the frozen minimal `codex-full` instruction over a reachable HTTP MCP, yet selected no MCP
tool and made zero Working State GET/UPDATE calls. The database ended with 0 state heads, versions,
Evidence refs and state-update idempotency rows. Consequently `CognitiveStateUseRate=0/8`, while
CrossSessionStateReadRate and USEFUL/NEUTRAL/HARMFUL are undefined because no prior ACTIVE TASK
state existed. CAS correction, semantic stale correction and natural restart recovery were not
demonstrated. Seven observed safety counters remained zero; HC-3 remains the independent substrate
proof.

The real coding work itself completed two Product outcomes without changing HC code, migration or
MCP behavior: five retrieval assertion drifts were closed, and a query-only `RecollectionFacade`
plus lazy-compatible application exports reduced its import closure from 63 modules to 2. The final
verified-empty PostgreSQL Runtime gate passed 912 tests with one declared optional `milai_client`
skip; Ruff, strict mypy, sdist, wheel and built-wheel identity checks passed. See the
[HC-4 study](../studies/active/MILA_HOST_COGNITIVE_AFFORDANCE_HC4.md).

## Product-11 X0 terminal: subagent-sealed opportunity insufficient

Product-11 execution is authorized under the frozen v0.2 mechanism contract. Product ADR-032 and
the acceptance contract are complete. Final source-only A0 run `p11-x0-a0-20260904f` captured and
projected 238 non-Formal events, completed 24/24 Product/MCP traces from a fresh `0/0/0` database,
kept Canonical mutation and Product label access at 0, and passed cleanup.

The original HUMAN workflow remains packaged and unchanged, with human completion still `0/24`.
The user subsequently authorized a separate model-adjudicated path. Two role-specific subagents read
separate source-only packets and completed all 24 cases. Their normalized result agreed exactly on 60
required instance groups and 70 acceptable exact turn refs; conflict count was zero. The new seal
explicitly records `SUBAGENT_SEALED`, `human_adjudication_status=NOT_PERFORMED`, and the claim ceiling
`OPENED_DEVELOPMENT_MODEL_ADJUDICATED`.

The authoritative `20260905c` execution uses dedicated source-only packets, a pre-execution
orchestration manifest, two fresh subagent invocations, and seal-time deterministic recomputation of
both proposals. Architecture re-review returned `PASS`. Its v0.2 receipt preserves and explicitly
supersedes the earlier provenance-incomplete v0.1 receipt.

Only after agreement did the merger load the immutable A0 trace. It derived `0 continuation / 8
intra-source / 16 control` opportunities, so the required `8/8/8` gate failed. The terminal is
`PARKED_PRODUCT11_INSUFFICIENT_SUBAGENT_SEALED_OPPORTUNITY`; X1--X4 were not entered, no source
reshaping is permitted, and Formal files/cases remain `false/0`. See the
[subagent report](../studies/active/MILA_PRODUCT11_X0_SUBAGENT_SEAL_20260905.md),
[runbook](PRODUCT11_X0_SUBAGENT_REVIEW_RUNBOOK.md), and
[tracker](../refine-logs/EXPERIMENT_TRACKER.md).

## Product-10 terminal: instance coverage unresolved

Product-10 completed its sealed X0--X2 sequence and ended
`PARKED_PRODUCT10_INSTANCE_COVERAGE_UNRESOLVED`. The final exact-pool matched run recorded A0/B1
micro coverage `29/36` vs `29/36`; B1 raised mean coverage by `+0.04167` and recovered three admission
losses, but displaced three previously visible groups through budget/adjacency changes. Two
previously full-coverage cases became partial, so H1 failed both its mean-gain threshold and its
case-level zero-loss guard after the second general repair.

All run-validity and safety gates passed: fresh PostgreSQL, 11,893/11,893 capture/projection,
same candidate pool, isolated tenants, scope/snapshot stability, zero Reader/vLLM/retry/Canonical
mutation, label-after-trace and database-volume cleanup. Only 1 A0 / 2 B1 continuation opportunities
were audited against the required 6, so X3/X4 were not entered and formal 500 scoring remains
unconsumed. The sealed summary's two-loss list is superseded only for that derived field by correction
receipt v2 `167ee995…18a9d`; v3 `065812c5…b5659` aligns the H1 threshold to the pre-registered
full-case guard. The immutable run and all other metrics remain unchanged. See
[Product completion audit](../../MiLAi-Product/docs/goals/MILA_PRODUCT-10_COMPLETION_AUDIT.md) and
[`p10-x2-matched-20260904b`](../artifacts/product10/p10-x2-matched-20260904b/summary.json).
The final packaging tree `0b170d3f…a7b5` is independently pinned by
`data/locks/product10-final-product.lock.json` (logical digest `4bf9ee43…6d68b`, verification PASS),
without replacing the effect-run lock.

## Product-09 persistent Codex HTTP lifecycle complete

Product-09 records two successful local synthetic integration runs across HostAgentEvent → PostgreSQL
→ projection → HTTP MCP → Codex. The restart covered API/worker/MCP, not PostgreSQL, and only one
target was queried after restart. Several zero invariants are emitted configuration assertions rather
than durable observed counters.

A four-family opened-development LongMemEval run persisted 1,772 turns with 8 capture workers and
ran 4 Codex tasks concurrently. One run recorded normalized EM/F1 `0.75/0.75`: ordinary user lookup,
assistant-answer lookup and state update passed; multi-session COUNT answered 2 instead of 3. All
required sessions were visible. Qwen model-assisted turn labels gave 3/4 case completion and 6/7 micro
turn visibility. A longer-instruction run recorded 2/4, but treatment identity and replication are
insufficient for a causal claim. See the
[Product-09 study](../studies/active/MILA_PRODUCT-09_CODEX_HTTP_PERSISTENT_MEMORY.md).

The Product-09 lock is `data/locks/product09-product.lock.json`: tree `557ad090…9171f` over 329
files, logical digest `d3c22762…4ae78`, verification PASS. Historical results do not carry that pin.
The 500-case files were read before subsetting, but no formal 500-case scoring run was performed.

## Product-08 Codex HTTP MCP baseline complete

The Product-08 identity is the Codex Streamable HTTP MCP evidence-context baseline. Real Codex CLI
`0.151.0` passed three black-box HTTP behaviors against an independently running `milai-mcp` process:
required memory used one resolve, an unrelated control used zero, and explicit continuation used two
with the second bound to `previous_context_id`; all final answers were exact. The model-controlled
argument surface stayed `query / previous_context_id`. See the
[active E2E record](../studies/active/MILA_PRODUCT-08_HOST_REASONING_MCP_E2E.md).

P08 uses Codex as its only Host acceptance surface; Claude Code is not a gate and no compatibility
claim is made. Host capture/restart recall, real PostgreSQL retrieval and multi-turn coding usability
are successor work. Formal LongMemEval 500 is still unconsumed.

The Host-MCP Product lock is `data/locks/product08-host-mcp.lock.json`: tree
`d866c5ff…cc1a` over 329 files, logical digest `5b15eb6c…c386`, verification PASS. It does not
overwrite the older retrieval-candidate lock.

## Prebase Product-08 additive-retrieval candidate

The Product-07 first-loss diagnosis remains implemented as a default-OFF prebase candidate. The
published read-only `context-testkit-v0.1` captures one governed acquisition snapshot per case and
replays C/X/Y without fresh repository, embedding, vector, Provider or Canonical mutation calls.
The Lab runner fixes C/X to the same candidate and DecisionSnapshot, tests informational soft
admission independently, and adds full-query FTS + requirement-local FTS + real Dense only in Y.
RecallWorkspace is excluded.

Its historical `data/locks/product08-product.lock.json` verifies tree
`4b09042b...3259`, 323 files and 8 public interfaces; logical lock digest is
`8b3c0dd5...9fa5`. Product Runtime has 738 passing unit tests; Lab has 61 passing tests, and both
repositories pass Ruff, strict mypy and build. The opened 24-case R3 Context comparison has not run:
a frozen real 128d-projection embedding model path was not supplied. Therefore no retrieval effect
claim is made, defaults remain unchanged, and formal 500 remains unauthorized and unconsumed. See
the [prebase contract](../studies/active/MILA_PRODUCT-08_CONTEXT_REPAIR.md).

## Repository

- Independent root: `/cra/memory/mx_memory/MiLAi-Lab`
- Selected default baseline: sibling `MiLAi-Product`, direct path retained after Product-07
- Product-07 formal run pin: `data/locks/product07-product-s2-b1.lock.json`, tree `01ad1775...94612`, run-time PASS
- Product-07 final delivery pin: `data/locks/product07-product-final.lock.json`, tree `17df2c8f...face3`, PASS
- Legacy source: read-only migration source `/cra/memory/mx_memory/MiLAi`
- Latest completed Context gate: Product-07 R3, 24 fresh-PostgreSQL tenants / Context-only comparisons
- Latest experiment terminal: `PARKED_PRODUCT07_NO_GENERAL_EVIDENCE_GAIN`; direct retained
- Current disposition: Product-07 v1.4 complete; no further Product-07 execution authorization
- Completed experiment record: `refine-logs/EXPERIMENT_PLAN.md`
- Formal 500-case Product/Answer/Judge holdout: not consumed

The selected Product-07 baseline history is sealed by:

```text
Product version         0.1.0-candidate
Product manifest schema milai-product-manifest-v1
Product tree files      320
Product tree SHA-256    17df2c8fd601ce497fe8c6913b2bf3b63b1b911082bf95390ddf4281a4fface3
Lab lock logical digest 98a9b091f3053b38615e94e13cefcc890e0e4268bb6ee7f561fd1d2c5151959b
Lab lock file SHA-256   369220b32f6ac23e8843a61d13810432e5b8d41476451112e81eb952180bc927
Public interfaces       7
Pin verification        PASS
```

Product-06 v1.1 was explicitly authorized and completed PARTIAL. Its timestamped
[experiment plan](../refine-logs/EXPERIMENT_PLAN_20260903_080031.md) and
[tracker](../refine-logs/EXPERIMENT_TRACKER_20260903_080031.md) record the bounded model-native vLLM Reader, internal
calculator and fixed 12-case result. The corrected comparison was direct 7/12 versus Reader 7/12,
with zero loss, unsupported answer, protocol rejection, retry, leak or Canonical mutation. Four of
five baseline misses lacked required Evidence groups in the frozen Context, so H1 could not be met by
a legal Reader-only repair. Direct remains the executable default; R3 and formal 500 were not consumed.
The R2 execution lock digest `ac578345…fd413` and final R4 lock digest `86e79b6c…23b1c` cover the
same Product behavior tree; R4 only refreshes the Product-owned manifest identity after regeneration.

The completed [Product-07 plan](../refine-logs/EXPERIMENT_PLAN.md) and
[tracker](../refine-logs/EXPERIMENT_TRACKER.md) authorize no further execution. B1 passed V0 at
11/12 complete EvidenceSets, 0.9167 coverage and zero old loss, then was frozen under formal Product
tree `01ad1775...94612`.

The authoritative run `var/product07/r3-context-b1-r4` executed all 24 R3 cases. A versus B1 was
10/24 versus 8/24 complete and 0.5667 versus 0.4722 mean group coverage. B1 recovered two shapes but
lost four old-complete cases; any-gold-session recall fell from 22/24 to 17/24. Candidate set/order,
hydration and effective 16,384-token budget matched 24/24, but window closure matched 22/24. All 24
tenant namespaces projected consistently with zero cross-namespace source and zero Canonical
mutation. R3 used zero Provider, Answer, Judge or hidden model calls.

P07-H1 failed, so H2, B2, residual official reads, D0/D1 and OpenWorker Answer effect were not
entered. RecallWorkspace is query-local, non-persistent, default OFF and not selected. Formal 500
remains unauthorized and unconsumed.

## Active package

The maintained package provides:

- experiment arm authority contracts;
- workload/result contracts;
- bounded runtime leases;
- compact artifact writing;
- external dataset manifests;
- provider endpoint configuration;
- deterministic answer smoke scoring;
- product tree and public-interface pin verification;
- a static boundary check that rejects private product and legacy imports.

It intentionally does not contain retrieval, memory formation, Reader, or canonical
state implementation. Those belong either to the pinned product or to an explicitly
declared research-prototype study.

## Historical material

The legacy archive is non-authoritative. Historical PASS/FAIL/PARKED outcomes remain
facts about their original runs; copying them does not reactivate their goals or feature
flags. See `RESULTS_INDEX.md` and the archive manifest.

The filtered snapshot contains 1,728 source/document files totaling 32,723,074 bytes.
All recorded destination and source digests verify. The two pre-existing user-modified
DG13U files are additionally preserved with exact SHA-256 equality.

## Split verification

```text
Active tests                       89 passed
Ruff                               PASS
strict mypy                        PASS (29 source files)
Active private-import boundary     PASS
Product pin                        PASS
Legacy snapshot replay             PASS (1,728 files)
Wheel and source distribution      PASS
Lightweight active-package CI      PRESENT
Legacy workspace mutation          0 by this migration
Product-01 S1 preflight            PASS (24/24; Reader/Judge 0)
Product-01 S2 paired gate          PASS (B1 precision 1.0; DG28 6/7)
Product-01 S3 local usability      PASS (golden; 23/24; warm 100/100)
Product-01 S4 LongMemEval          FAIL_S4_REPAIR_OR_KEEP_BASELINE
Product-02 U3 local usability      PASS (golden; 24/24; warm 100/100)
Product-02 sealed 128 decision     PASS_KEEP_SIMPLER_BASELINE; B2 PARKED
Product-03 real OpenWorker LME     SINGLE-CASE PASS; 466 turns; 1 MCP; 1 Qwen
Product-03 V02 usability replay    2/3 PASS; all full-chain; semantic COUNT miss explicit
Product-04-tree real replay        1/2 PASS; COUNT evidence visible, Reader consumption miss
Product-05 lifecycle               PASS; 2 tenants; restart 2/2; leaks/mutations/retries 0
Product-05 Reader effect           UNRESOLVED after 3 rounds; direct retained; S2 not entered
Product-06 Reader execution        PASS; 12/12 pairs; 12 tenants; 24 native operations
Product-06 Reader effect           NO GAIN; corrected 7/12 vs 7/12; direct retained; R3 not entered
Product-07 V0 B1 development       PASS; 11/12 complete; 0.9167 coverage; old loss 0
Product-07 R3 Context H1           FAIL; B1 complete -2; coverage -0.0944; old loss 4
Product-07 R3 safety               PASS; 24 tenants; leaks/mutations/model calls 0
Product-07 terminal                PARKED; direct retained; B1 default OFF
Product-08 Codex HTTP MCP E2E      PASS; 3/3 Host behaviors; resolve calls 1/0/2
Product-08 Claude MCP E2E          NOT IN SCOPE / NO CLAIM
Product-08 Host AgentEvent         SUCCESSOR; live PostgreSQL E2E not part of P08
Product-09 persistent lifecycle    PASS; capture/projection/restart/scope; Canonical 0
Product-09 LME diagnostic          3/4 exact; all required sessions visible; COUNT unresolved
LME D1/D2 behavior simulation      2/4 exact; natural continuation 0/4; D2 recovered 1/1 fine miss
Formal 500-case run                NOT ENTERED / NOT CONSUMED
```

The CI intentionally does not invent a Product repository URL. It verifies the active Lab package,
boundary, tests, build, and archived-source replay. After the first Product and Lab commits and
remote identities exist, CI must check out the pinned Product commit and run the same
`milai-lab-verify-product` gate used locally.

The Product-02 authoritative artifacts are `product02-u3-local-final-006` and
`product02-u3-longmemeval-128-007`. The latter passed all infrastructure and governance hard gates,
but B2 regressed exact answer-turn coverage from 0.418129 to 0.052632 and Qwen Judge accuracy from
0.265625 to 0.078125. The selected disposition is `B0_B1_EQUIVALENT_BASELINE`; B2 remains default
OFF. The v4 answer-turn labels are model-assisted evaluation labels, not independent human ground
truth or leaderboard-equivalent evidence.

Post-terminal analysis localized the B0/B1 errors into 59 discovery misses, 10 session-hit/turn
admission misses, 15 partial-role EvidenceSets, 9 visible-but-wrong outcomes and 1 abstention/Judge
error. It also showed that B2 changed only LOOKUP presentation: 114/128 EvidenceSets were empty and
Raw Evidence was removed before Context. See
[Product-02 128-case failure families](PRODUCT02_128_FAILURE_FAMILIES.md). The report makes the
current 128 slice opened development evidence; it is not an unseen validation set for Product-03.

Product-03 subsequently replayed one opened-development LongMemEval case through the actual local
OpenWorker → Host → UDS broker → MCP → Runtime → Qwen composition. After repairing explicit-read
budget ownership and preserving Runtime-owned MemoryContext across MCP diagnostic compaction, the
466-turn case passed with one logical MCP call, one Provider call, no automatic retry and no
Canonical mutation. Runtime remained honestly `PARTIAL`; the run-local corrective summary reports
20 selected governed Evidence units and confirms that the answer-bearing Evidence was Reader-visible.
This is a large-haystack usability proof for one
case, not a LongMemEval accuracy or generalization claim. The formal 500-case holdout remains
unconsumed. See [the Product-03 simulation report](../studies/active/MILA_PRODUCT-03_OPENWORKER_LME_SIMULATION.md).

The default-OFF V02 follow-up then raised only the explicit local budget to 120 candidates, 16,384
Context tokens and 5,000 ms. Three isolated OpenWorker replays all reached Qwen exactly once: the
439-turn assistant-source lookup and 466-turn user-source lookup passed, while the 484-turn
multi-session count remained `PARTIAL / UNBOUNDED` and answered incorrectly. The result is therefore
`PASS_V02_LOOKUP_USABILITY_COUNT_SEMANTICS_PARTIAL`: the product is usable for these lookup paths,
but set-member identity/dedup and completeness remain unresolved. No case-specific rule was added,
and the formal 500-case holdout remains unconsumed.

After Product-04 removed Raw TypeBinding authority and made governed partial Context available to
the Reader, two opened cases were replayed through the real chain. The assistant-source phone lookup
passed. The multi-session clothing count failed with answer `1` rather than `3`, although both
answer-bearing evidence groups were present in the exact Reader Context. This moves the next repair
from query rejection to model evidence consumption; it does not justify a count-specific regex,
TypeBinding, or another unconditional Top-k increase.

Product-05 is complete with a PARTIAL terminal. Its Host-owned facade passed a final fresh database
gate with two isolated tenants, exact user/assistant capture, 10/10 projections, 2/2 restart recall,
and zero cross-tenant leak, duplicate, self-amplification, model-visible write tool, semantic retry,
or Canonical mutation. Fixed-Context inventory, one-pass grounded and three bounded two-pass ledger
repairs did not establish P05-H2. The final B2 run exposed four Host calculation-validation
rejections, and the nine completed pairs yielded only one additional correct case in one family.
Direct Reader remains selected; the gated 24-case S2 and formal 500-case holdout were not entered.
See the [completed plan](../refine-logs/EXPERIMENT_PLAN_20260902_224941.md),
[tracker](../refine-logs/PRODUCT05_TRACKER.md), and `var/product05/terminal.json`.

Product-06 is complete with
`PARTIAL_PRODUCT06_LEDGER_REMOVED_READER_GAIN_UNRESOLVED`. R0 localized the final Product-05 strict
Ledger misses to four Host calculation-protocol rejections and two semantic errors, establishing that
the dominant failure was the consumption contract rather than Memory storage or retrieval. R1
replaced that candidate path with one ephemeral model-native Reader session and an adapter-internal
safe calculator; it did not add an MCP tool, database object or Canonical authority.

R2 then completed 12/12 fixed-Context pairs through fresh PostgreSQL, Runtime, MCP, native OpenWorker
and Qwen. Two valid insufficiency answers were initially rejected only by the Lab's deterministic
abstention regex; after a general scorer correction, both arms were 7/12 with no paired gains or
losses. Required-Evidence-group recall was 0.5833, and four of the five baseline-wrong cases had
incomplete Reader-visible evidence. The Goal forbade widening retrieval, so R3 was correctly skipped
instead of cycling prompts or selecting a favorable sample. See `var/product06/r2-summary.json`.

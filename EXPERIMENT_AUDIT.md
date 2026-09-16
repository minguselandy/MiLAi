# Experiment Audit Report

**Date**: 2026-08-27  
**Auditor**: GPT-5.6-Sol ultra (fresh same-family agent, read-only, provisional)  
**Project**: MiLAi DG-17  
**Review independence**: same-family  
**Acceptance status**: provisional

# DG-17 experiment-integrity audit

Overall verdict: **FAIL**

Integrity status: **evaluation design compromised in key causal lanes; release evidence incomplete**.

This is a provisional, same-family independent semantic review. It is not acceptance or cross-family validation. No files were modified.

The decisive findings are:

1. Q0 arms C/D are labeled “predicted IR,” but the code supplies a constant placeholder with `"operator": null`; they cannot isolate compiler/operator failure.
2. Q3C supplies the deterministic route/operator to the model in its prompt, so apparent classification accuracy is teacher-assisted, not independent.
3. The generic nDCG implementation uses prediction length in its ideal denominator.
4. Q1’s focused `0/9` wrong-COMPLETE result does not hold in the live matched path.
5. Q6 has never run, and its implemented evaluator contains source-agnostic coverage, incomplete wrong-COMPLETE detection, hardcoded safety zeros, and a semantic “arm” that merely copies deterministic quality.
6. Q6 preflight 003 dropped the local deterministic-gate binding present in preflight 002.
7. Q3C, Q6, governance, cost, operability, and final review remain unexecuted.

## A. Ground-truth provenance — FAIL

The LongMemEval answers and answer-session labels are genuine dataset GT:

- Dataset and hashes: `/cra/memory/mx_memory/MiLAi/evals/dg16/lme10.py:19-30`
- Label loading: `/cra/memory/mx_memory/MiLAi/evals/dg16/lme10.py:129-143`
- Answer/session extraction: `/cra/memory/mx_memory/MiLAi/evals/paper/datasets/longmemeval.py:137-192`

However:

- DG17 atom, slot, join, and `gold_ir` labels are author-curated at `/cra/memory/mx_memory/MiLAi/evals/dg17/fixtures/lme10-answer-bearing-labels.v0.1.json:2-123`. The envelope records hashes but no annotation protocol, annotator identity, adjudication, or independent validation.
- Loader validation proves only that spans occur at the declared source offsets: `/cra/memory/mx_memory/MiLAi/evals/dg17/measurement.py:104-198`. It does not independently validate the semantic operator, slots, or joins.
- Q0 “predicted IR” is not a prediction. It is a hardcoded null object: `/cra/memory/mx_memory/MiLAi/evals/dg17/measurement.py:545-575`. The goal promises real predicted-IR arms at `/cra/memory/mx_memory/MiLAi/MiLAi_DG-17_语义记忆读取与证据集执行_GOALS.md:1268-1282`.
- The test explicitly accepts that placeholder: `/cra/memory/mx_memory/MiLAi/tests/test_dg17_measurement.py:70-84`.
- Q3C computes the deterministic answer at `/cra/memory/mx_memory/MiLAi/evals/dg17/semantic_shadow.py:203-223`, then serializes it into the model prompt at `/cra/memory/mx_memory/MiLAi/runtime/src/milai/application/semantic_hint.py:146-180`. The unit-test provider simply copies it at `/cra/memory/mx_memory/MiLAi/tests/test_dg17_semantic_shadow.py:30-55`.

No evidence shows that the official answer GT itself was generated from model outputs. The failure is manual-label provenance plus reference leakage and false oracle-arm identity.

The benchmark uses a custom deterministic scorer, not an official LongMemEval evaluation implementation: `/cra/memory/mx_memory/MiLAi/evals/paper/scorers/longmemeval.py:12-50`.

## B. Score normalization — FAIL

Most metrics are transparent:

- EM/F1 uses standard normalized token overlap: `/cra/memory/mx_memory/MiLAi/evals/paper/scorers/longmemeval.py:15-50`.
- Raw F1 and latency accompany Q6 quality-per-second: `/cra/memory/mx_memory/MiLAi/evals/dg17/q6_matched.py:320-377`.
- Q3C reports raw token means with its ratio: `/cra/memory/mx_memory/MiLAi/evals/dg17/semantic_shadow.py:337-345`.

But the paper nDCG denominator depends on the number of results predicted:

- `/cra/memory/mx_memory/MiLAi/evals/paper/scorers/longmemeval.py:63-83`

`ideal` uses `min(len(relevant), len(unique_ranked))`. A prediction returning one relevant item out of several can therefore obtain nDCG 1.0 because its shorter prediction also shrinks the ideal denominator. Raw coverage is reported alongside it, but the nDCG itself violates a fixed-denominator comparison.

This flaw does not alter the DG16 aggregate F1/coverage table, because DG16 summaries omit nDCG and aggregate hit/coverage instead: `/cra/memory/mx_memory/MiLAi/evals/dg16/lme10.py:223-296`.

Scores near 1.0 occur in small real-GT diagnostics and deterministic simulations; they are not evidence of prediction-statistic normalization beyond the nDCG defect.

## C. Result existence and claim traceability — FAIL

All explicitly named primary files exist. The failures are version selection, causal labeling, lineage, and status traceability.

| Claim | Artifact evidence | Assessment |
|---|---|---|
| DG16 512 MiLA EM `1/10`, F1 `.1194`, Hit@K `.70`, coverage `.50`; 2048 `2/10`, `.20`, `.70`, `.60`; BM25 `.0857/.60/.45` | Goal cites rescored receipt at `/cra/memory/mx_memory/MiLAi/MiLAi_DG-17_语义记忆读取与证据集执行_GOALS.md:121-138`; metrics are in `/cra/memory/mx_memory/MiLAi/var/dg16/lme10/dg16-lme10-compare-20260827-002/receipt-rescored.json:3496-3623` | Exact only for `receipt-rescored.json`. Requested `receipt.json` reports retrieval hit/coverage zero because it used the wrong session-identity source. Rescore provenance is explicit at `/cra/memory/mx_memory/MiLAi/scripts/rescore_dg16_lme10.py:38-103`. |
| Q0 measurement: N10, turn recall `.475`, AnswerSessionCoverage `.60`, evidence coverage `.347826087`, boundary loss `.333333333`, operator accuracy `0/10` | `/cra/memory/mx_memory/MiLAi/var/dg17/q0/dg17-q0-measurement-20260827-001/receipt.json:1` | Numeric match, but operator accuracy is not an executed metric: `operator_correct=False` is unconditional at `/cra/memory/mx_memory/MiLAi/evals/dg17/measurement.py:317-322`, while the trace says `NOT_EXECUTED` at `:397-400`. |
| Q0 oracle complete | Both oracle receipts at `.../dg17-q0-oracle-20260827-001/receipt.json:1` and `...-002/receipt.json:1` | Both say `Q0_COMPLETE`, but disagree radically. Run 001 A/C: EM `1/10` and `2/10`; run 002: `6/10` and `5/10`. No supersession/revocation field or multi-seed aggregate exists. |
| Q0 diagnosis | Oracle 002 diagnoses seven acquisition/composition failures | Invalid causal attribution. C/D are placeholder IR arms. The diagnostic also counts EM-wrong answers with F1 `>=.15` as successes at `/cra/memory/mx_memory/MiLAi/evals/dg17/measurement.py:663-689`. |
| Ad-hoc semantic probe: N12, stated latency and 11/12 classifications | `/cra/memory/mx_memory/MiLAi/MiLAi_DG-17_语义记忆读取与证据集执行_GOALS.md:286-307` | No versioned result artifact was found. The document explicitly labels it “NOT A DG17 RECEIPT,” so it is an unverified feasibility note only. |
| Q1 focused wrong COMPLETE `0/9` | `/cra/memory/mx_memory/MiLAi/var/dg17/q1/dg17-q1-p0-focused-20260827-001.json:2-18` | Exact for a synthetic candidate made from the query itself: `/cra/memory/mx_memory/MiLAi/scripts/run_dg17_q1_p0_focused.py:44-79`. It is not a live-product result. |
| Q1 matched | `/cra/memory/mx_memory/MiLAi/var/dg17/q1/dg17-q1-p0-matched-20260827-002/receipt.json:2882-2947` | At 2048, premature terminals improve `7→3`, but EM `2→1`, F1 `.20→.10`, and coverage remains `.347826087`. At 512, terminals `9→5`, F1 `.119417476→.122807018`, coverage unchanged. C1 is not achieved. |
| Live wrong-COMPLETE zero | Same Q1 receipt | False. Case `88432d0a` is premature at `/cra/memory/mx_memory/MiLAi/var/dg17/q1/dg17-q1-p0-matched-20260827-002/receipt.json:2817-2822`, yet its sufficiency status is COMPLETE at `:2863-2877`. |
| Q3A crosswalk complete | `/cra/memory/mx_memory/MiLAi/var/dg17/q3a/dg17-q3a-crosswalk-20260827-001/crosswalk.json:1` | Exact infrastructure claim: N10, 23 atoms/interpretations/bindings, 22 unique spans. No live semantic prediction score. |
| Q3C | `/cra/memory/mx_memory/MiLAi/var/dg17/q3c/dg17-q3c-infrastructure-20260827-001/report.json:1` | Only `Q3C_INFRASTRUCTURE_READY_NO_MODEL_CALLS`: N29, 25 supported, 25 deterministic matches, zero model calls. No live shadow result. |
| Q4 complete | `/cra/memory/mx_memory/MiLAi/var/dg17/q4/dg17-q4q5-product-20260827-001/report.json:1` | Exact only as N7 oracle-evidence operator isolation: 7/7, wrong COMPLETE 0, p95 5.627581 ms, external calls 0 and experiments paused. |
| Q5 complete | `/cra/memory/mx_memory/MiLAi/var/dg17/q5/dg17-q4q5-product-20260827-001/report.json:1` | Exact only as four deterministic traces, including synthetic evidence; external calls 0 and experiments paused. |
| Q6 readiness | Three preflights, most recently `/cra/memory/mx_memory/MiLAi/var/dg17/q6/dg17-q6-preflight-20260827-003/preflight.json:1` | Honest preflight: runtime, retrieval, reader, hint, and repair calls all zero; live Q3C/Q6 absent; release false. |
| Q6 local gate bound | Compare preflights 002 and 003, each at line 1 | Regression: 002 binds `local_deterministic_gate` and reports it passed; 003 drops both. Current bindings at `/cra/memory/mx_memory/MiLAi/evals/dg17/q6_preflight.py:31-87` contain no local gate. |
| Compatibility disposition available | Q6 preflight readiness | Hardcoded true at `/cra/memory/mx_memory/MiLAi/evals/dg17/q6_preflight.py:199-204`, but the compatibility disposition is not included in `BOUND_ARTIFACTS`. |
| Local tests | Five local-gate receipts, each line 1 | Runs 001/002 fail; 003–005 pass. Latest reports 292 runtime-unit, 14 contract, and 20 DG17 tests = 326. Goal’s “39 passed” at `/cra/memory/mx_memory/MiLAi/MiLAi_DG-17_语义记忆读取与证据集执行_GOALS.md:2125-2126` has no identified receipt and is not traceable to the latest gate. |
| Reader stability | `/cra/memory/mx_memory/MiLAi/var/dg16/reader-stability/dg16-reader-stability-20260827-001/receipt.json:441-505` | Exact single-case characterization: 11 calls, same-payload variation observed, explicitly not a generalization or Q6 denominator. |
| Historical DG16 LME effect | `/cra/memory/mx_memory/MiLAi/var/dg16/lme/dg16-lme-effect-20260827-003/receipt.json:96-102,2263-2285` | N5×2 live result, but its gate is FAIL. At 2048 EM4/5 and one baseline regression; 512 EM5/5. Must not be mixed with current10. |

The tracker is conservative about release, but stale about code/artifact existence: it says Q3C has no adapter/fixture/receipt at `/cra/memory/mx_memory/MiLAi/MiLAi_DG-17_语义记忆读取与证据集执行_GOALS.md:2111-2117`, despite the current infrastructure artifact.

## D. Dead or unexecuted code — WARN

| Path | Status |
|---|---|
| `score_semantic_predictions` at `/cra/memory/mx_memory/MiLAi/evals/dg17/semantic_crosswalk.py:130-275` | No live prediction artifact. Only the test calls it, using predictions copied from the crosswalk GT at `/cra/memory/mx_memory/MiLAi/tests/test_dg17_semantic_crosswalk.py:37-83`. |
| `run_semantic_shadow` at `/cra/memory/mx_memory/MiLAi/evals/dg17/semantic_shadow.py:196-360` | No live artifact. Existing runner used deterministic-only mode: `/cra/memory/mx_memory/MiLAi/scripts/run_dg17_q3c_shadow.py:26-49`. |
| Q6 scorer/gate at `/cra/memory/mx_memory/MiLAi/evals/dg17/q6_matched.py:31-378` | Wired into the runner, but no Q6 matched receipt exists. |
| Q6 live runner at `/cra/memory/mx_memory/MiLAi/scripts/run_dg17_q6_matched.py:64-310` | Unexecuted. |
| External LME10 summarizer at `/cra/memory/mx_memory/MiLAi/evals/dg16/external_lme10.py:181-230` | Wired to an external runner, but no completed comparison artifact; only an incomplete Graphiti checkpoint was found. |
| Generic paper scoring at `/cra/memory/mx_memory/MiLAi/evals/paper/runners/longmemeval.py:480-567` | Implemented, but no current scoped paper metrics artifact. |
| `judge_provider.py` | No DG17 result uses it. |
| Q4/Q5 helpers | Executed into deterministic reports. |
| Q0 and Q1 metric helpers | Executed, subject to the integrity defects above. |
| DG16 LME10 scoring/rescoring | Executed into the original and rescored artifacts. |

The DG17 local gate also omits `tests/test_dg16_reader_stability.py`; its root test glob is limited at `/cra/memory/mx_memory/MiLAi/scripts/run_dg17_local_gate.py:35-45,78-93`.

## E. Scope assessment — WARN

Evidence is small and generally single-run:

- Current primary development denominator: 10 cases.
- Q4: seven current temporal cases with oracle evidence.
- Q5: four focused traces, two synthetic and two oracle-derived.
- Q3C deterministic manifest: 29 authored fixtures; its “unseen” items are hardcoded in the evaluation source at `/cra/memory/mx_memory/MiLAi/evals/dg17/semantic_shadow.py:117-149`, not a held-out sampled set.
- Q0 oracle: one seed per case per run, with two highly inconsistent runs.
- Q1: one candidate run per case/budget.
- Reader stability: one case, one seed, repeated 11 times across five arms.
- Q6 actual N=0.
- Q7’s required 20–50 cases have not run: `/cra/memory/mx_memory/MiLAi/MiLAi_DG-17_语义记忆读取与证据集执行_GOALS.md:1687-1706`.

The goal appropriately restricts claims to `PRODUCT MECHANISM CANDIDATE / OPENED-DEV CHARACTERIZATION` and forbids formal benchmark, production, novelty, or superiority claims at `/cra/memory/mx_memory/MiLAi/MiLAi_DG-17_语义记忆读取与证据集执行_GOALS.md:1575-1589`.

Overstatement remains possible in artifact status strings such as `Q4_PRODUCT_VERTICAL_COMPLETE` and `Q5_PRODUCT_VERTICAL_COMPLETE`. They mean deterministic oracle/simulation traces only.

The reader-stability diagnostic is correctly excluded from Q6 by `/cra/memory/mx_memory/MiLAi/docs/runbooks/dg17-semantic-read.md:198-209`.

## F. Evaluation-type classification — WARN

| Family | Classification | N/configurations | Seeds/runs | Live model calls | Claim ceiling |
|---|---|---:|---:|---:|---|
| DG16 LME10 | `real_gt` | 10 cases × 2 methods × 2 budgets = 40 cells | 20 case-budget seeds shared across methods; one run | 40 | Opened-dev paired characterization; custom scorer |
| Q0 measurement | `real_gt` answers plus human-curated diagnostic labels | N10; 23 atoms, 16 slots, 9 joins | None | 0 | Retrospective failure localization |
| Q0 oracle 001/002 | `real_gt` answer diagnostic with manual oracle evidence | Each N10×4 arms | Ten seeds/run, shared across arms; two inconsistent runs | 40/run | Reader/evidence diagnostic only; IR attribution invalid |
| Q1 focused | `simulation_only` | 10 synthetic query-derived candidates | None | 0 | Unit stop-policy regression |
| Q1 matched | `real_gt` plus manual evidence labels | 10 cases × 2 budgets × 2 represented policies | One case-budget seed; baseline reused | 20 new calls, 20 historical baseline calls represented | Same-family characterization; gate failed |
| Q3A | Deterministic infrastructure, not performance | N10, 23 bindings, 22 spans | None | 0 | Schema/measurement bridge |
| Q3C infrastructure | `simulation_only` | 29 authored fixtures, 25 supported | None | 0 | Deterministic parser fixture smoke |
| Planned Q3C live | `self_supervised_proxy` | Same 29 fixtures | Planned one minimal and one full-plan seed/case | Planned 58; actual 0 | Schema/latency/agreement only because teacher target is in prompt |
| Q4 | `simulation_only` | Seven oracle-evidence temporal traces | None | 0 | Operator isolation only |
| Q5 | `simulation_only` | Four focused traces | None | 0 | Composition safety/mechanism only |
| Q6 preflight | Infrastructure/preflight, not performance | Prospective 20 cells/arm; actual N0 | None | 0 | Readiness and blocking state |
| Q6 matched | Planned `real_gt`/manual-proxy mix | Planned 10×2 | Planned one run | Actual 0 | No empirical claim |
| Local gate | Deterministic infrastructure | Latest 326 tests | None | 0 | Unit/static consistency |
| DG16 reader stability | `real_gt` single-case diagnostic | One case, five arms, 11 attempts | One repeated seed | 11 | Single-case variability signal |
| DG16 LME effect | `real_gt` plus manual atom labels | Five cases × two budgets | Ten cells, one run | 10 | Historical focal characterization; gate FAIL |
| Ad-hoc semantic probe | `synthetic_proxy` | 12 synthetic questions | Undocumented | Claimed, no receipt | Unverified feasibility note |
| External LME10 | Planned `real_gt`; incomplete | Checkpoint below 10-case denominator | Incomplete | Incomplete | No result claim |

## G. Goal-gate completeness — FAIL

| Gate | Audit state | Evidence |
|---|---|---|
| Q0 | **COMPROMISED CHARACTERIZATION** | Measurement exists, but operator denominator is unexecuted and oracle C/D are not predicted IR. Oracle lineages conflict. |
| Q1 | **CHARACTERIZED / GATE FAIL** | Premature terminals remain; coverage unchanged; main-budget EM/F1 regress. Focused simulation cannot substitute. |
| Q2 | **IMPLEMENTED SIGNAL ONLY** | Production path does use deterministic v0.2 compilation: `/cra/memory/mx_memory/MiLAi/runtime/src/milai/application/memory_query.py:342-367`, `/cra/memory/mx_memory/MiLAi/runtime/src/milai/application/query_planner.py:20-89`. No current matched Q2 receipt. |
| Q3A | **DETERMINISTIC INFRASTRUCTURE COMPLETE** | Crosswalk and compatibility disposition exist; no live semantic score. |
| Q3B | **PARTIAL** | Deterministic route/family fixtures and focused operators exist; no full functional/matched proof. |
| Q3C | **NOT RUN** | Infrastructure only; zero model calls. Existing design is teacher-assisted. |
| Q3D | **NOT AUTHORIZED / NOT RUN** | Requires useful live Q3C gain; product integration absent. |
| Q4 | **ORACLE OPERATOR ISOLATION COMPLETE; PRODUCT INCOMPLETE** | Seven deterministic traces, no acquisition/model/database. |
| Q5 | **FOCUSED SIMULATION COMPLETE; PRODUCT INCOMPLETE** | Four traces, no live matched composition evaluation. |
| Q6 | **NOT RUN** | Latest preflight explicitly reports zero calls and missing live receipts. Its evaluator needs repair before execution. |
| Q7/Q8 | **NOT STARTED** | No expanded 20–50-case or strong retrieval ablation artifacts. |
| Correctness/quality | **FAIL/INCOMPLETE** | Current10 thresholds at `/cra/memory/mx_memory/MiLAi/MiLAi_DG-17_语义记忆读取与证据集执行_GOALS.md:1665-1685` are unmet/unrun. |
| Governance/safety | **INCOMPLETE** | No final nonzero-denominator gate; future Q6 hardcodes two accepted counters. |
| Online cost | **INCOMPLETE** | Deterministic microtimings exist; no live semantic-assist/Q6 matched accounting. |
| Operability | **INCOMPLETE** | Q1 lifecycle cleanup exists, but no successor Q6 E2E operability gate. |
| Release-boundary review | **NOT STARTED** | Goal requires all prior gates at `/cra/memory/mx_memory/MiLAi/MiLAi_DG-17_语义记忆读取与证据集执行_GOALS.md:2146-2152`. |
| Release | **NO-GO** | `CANDIDATE / EXPERIMENTAL / NO-GO FOR FREEZE` remains correct at goal lines 4–11 and runbook lines 3–8. |

## Additional Q6 evaluator defects

These must be corrected before spending external-call budget:

- Required-evidence coverage checks only whether atom text occurs anywhere in the context and ignores source identity: `/cra/memory/mx_memory/MiLAi/evals/dg17/q6_matched.py:188-205`. Q0 uses the same source-agnostic pattern at `/cra/memory/mx_memory/MiLAi/evals/dg17/measurement.py:274-286`.
- The fixture has 23 atoms but 22 unique spans because Ava and Lily share one span: `/cra/memory/mx_memory/MiLAi/evals/dg17/fixtures/lme10-answer-bearing-labels.v0.1.json:63-68`. Atom and unique-span coverage must remain distinct.
- Wrong-COMPLETE is based only on `derived_result.status`: `/cra/memory/mx_memory/MiLAi/evals/dg17/q6_matched.py:249-304`. It can miss a terminal COMPLETE sufficiency decision with no correct derived result, the exact pattern already seen in Q1.
- Cross-case contamination and label-leakage accepted counts are hardcoded to zero: `/cra/memory/mx_memory/MiLAi/scripts/run_dg17_q6_matched.py:334-345`.
- The semantic arm copies deterministic summaries, sets quality/coverage changes to zero, and adds only shadow cost: `/cra/memory/mx_memory/MiLAi/scripts/run_dg17_q6_matched.py:360-405`. It is a cost overlay, not a matched product arm.
- The receipt would nevertheless publish that overlay as `DG17_MINIMAL_SEMANTIC_QUERY_HINT_SHADOW`: `/cra/memory/mx_memory/MiLAi/scripts/run_dg17_q6_matched.py:284-289`.
- Its error counts mix current10 cost denominators with the global 29-fixture error aggregate: `/cra/memory/mx_memory/MiLAi/scripts/run_dg17_q6_matched.py:363-394`.
- Q6 operator correctness is a handwritten case-ID evaluator: `/cra/memory/mx_memory/MiLAi/evals/dg17/q6_matched.py:249-304`. Its ceiling is these ten cases, not generic operator accuracy.

## Action items

### Fixes requiring no external model/database calls

1. Invalidate or relabel Q0 C/D as placeholder arms; construct them from sealed, actual compiler IR before any further oracle claim.
2. Replace the `.15` oracle diagnostic-success shortcut with predeclared task-correct criteria, while retaining raw EM/F1 and answers.
3. Version-fix nDCG so the ideal denominator uses a predeclared K, not returned prediction length; rescore affected paper metrics.
4. Add an annotation manifest for atoms, IR, slots, and joins: author, procedure, source basis, independent review, disagreements, and date.
5. Make atom/span coverage source-aware and report unique-span, event-identity, and atom denominators separately.
6. Remove `deterministic_outcome.route/operator_family` from any Q3C prediction-quality prompt. Use a genuinely held-out fixture split and label the lane `self_supervised_proxy` if teacher context remains.
7. Rename Q3C/Q6 shadow overlay as a cost overlay; do not present it as a matched semantic arm or quality comparison.
8. Make wrong-COMPLETE inspect both terminal sufficiency and derived-result correctness.
9. Measure cross-case contamination and label leakage from actual source/scope traces; never initialize their accepted counts as asserted zero.
10. Restore and hash-bind the current local gate and compatibility disposition in Q6 preflight.
11. Add end-to-end scorer tests for source-identity collisions, duplicate spans, terminal COMPLETE without derived output, hardcoded safety counters, and variable-K nDCG.
12. Add explicit `supersedes`, `superseded_by`, code hash, prompt hash, and seed schedule to Q0/Q6 receipt lineage.
13. Update the status board and replace the untraceable “39 passed” statement with a concrete receipt path and suite breakdown.
14. Include the reader-stability test in the local gate, or explicitly justify its exclusion.

### Work requiring resumed external execution

1. Rerun Q0 A–D with actual sealed predicted IR, a predeclared multi-seed schedule, and an aggregate instability report.
2. Run the corrected, non-teacher-leaked Q3C shadow; preserve all 29 per-cell provider receipts and report seed-level variation.
3. Run Q6 deterministic-only over 10 cases × two budgets after evaluator repair, sealing 20 label-free contexts and 20 generations.
4. Run a genuinely executed semantic-hint arm only if Q3C establishes an independent mediator benefit; do not substitute the overlay.
5. Run nonzero-denominator governance, cost, cleanup, and operability gates.
6. If current10 passes, run Q7 on the predeclared 20–50 stratified opened-dev set.
7. Conduct the single independent release-boundary review only after all prerequisite artifacts exist.

```json
{"overall_verdict":"FAIL","integrity_status":"COMPROMISED_EVALUATION_DESIGN_AND_INCOMPLETE_EXECUTION","reason_code":"Q0_FAKE_PREDICTED_IR_Q3C_TEACHER_LEAKAGE_PREDICTION_DEPENDENT_NDCG_Q6_UNRUN","summary":"Real LongMemEval answer GT and several honest opened-dev artifacts exist, but Q0 causal arms are invalid, Q3C is teacher-assisted, nDCG has a prediction-dependent denominator, Q1 still has live premature COMPLETE decisions, and Q6 plus final gates are unrun. Release remains NO-GO.","checks":{"A":{"status":"FAIL","reason":"Manual semantic labels lack independent provenance; Q0 falsely labels a null placeholder as predicted IR; Q3C places deterministic targets in the model prompt."},"B":{"status":"FAIL","reason":"Paper nDCG ideal denominator depends on returned prediction length; raw coverage is also reported and DG16 aggregate F1/coverage are unaffected."},"C":{"status":"FAIL","reason":"Rescored/original DG16 versions differ, Q0 complete lineages conflict, focused Q1 conflicts with live matched behavior, preflight 003 drops its local-gate binding, and the 39-test claim is untraceable."},"D":{"status":"WARN","reason":"Live semantic scoring, Q3C, Q6, external LME10 final scoring, and current paper scoring are implemented but lack live result artifacts."},"E":{"status":"WARN","reason":"Most families use 10 or fewer cases and one seed; Q0 instability is large, Q4/Q5 are oracle/synthetic, and Q6/Q7 are absent. The goal itself correctly limits claims to opened-dev characterization."},"F":{"status":"WARN","reason":"Real-GT, manual-proxy, self-supervised, simulation, and infrastructure lanes need clearer labels; PRODUCT_VERTICAL_COMPLETE and shadow-arm names can exceed their evidence ceiling."},"G":{"status":"FAIL","reason":"Q1 fails, Q3C and Q6 are unrun, Q4/Q5 are not matched product evidence, and correctness, governance, cost, operability, and release review remain incomplete."}},"evaluation_families":[{"id":"dg16_lme10","classification":"real_gt","n":"10x2 methodsx2 budgets","runs":1,"live_model_calls":40,"claim_ceiling":"opened-dev paired characterization"},{"id":"q0_measurement","classification":"real_gt_plus_manual_diagnostic_labels","n":10,"runs":1,"live_model_calls":0,"claim_ceiling":"retrospective failure localization"},{"id":"q0_oracle","classification":"real_gt_oracle_diagnostic_compromised","n":"10x4 per run","runs":2,"live_model_calls":80,"claim_ceiling":"reader/evidence diagnostic; no compiler attribution"},{"id":"q1_focused","classification":"simulation_only","n":10,"runs":1,"live_model_calls":0,"claim_ceiling":"unit stop-policy regression"},{"id":"q1_matched","classification":"real_gt_plus_manual_proxy","n":"10x2 budgetsx2 represented policies","runs":1,"live_model_calls":"20 new plus 20 reused baseline records","claim_ceiling":"opened-dev characterization; gate failed"},{"id":"q3a","classification":"infrastructure","n":"10 cases/23 bindings/22 spans","runs":1,"live_model_calls":0,"claim_ceiling":"measurement crosswalk"},{"id":"q3c_infrastructure","classification":"simulation_only","n":"29 fixtures/25 supported","runs":1,"live_model_calls":0,"claim_ceiling":"deterministic parser smoke"},{"id":"q3c_planned_live","classification":"self_supervised_proxy","n":29,"runs":0,"live_model_calls":0,"claim_ceiling":"none until teacher leakage is removed"},{"id":"q4","classification":"simulation_only","n":7,"runs":1,"live_model_calls":0,"claim_ceiling":"oracle-evidence operator isolation"},{"id":"q5","classification":"simulation_only","n":4,"runs":1,"live_model_calls":0,"claim_ceiling":"focused composition safety"},{"id":"q6_preflight","classification":"infrastructure","n":"0 executed/20 prospective per arm","runs":3,"live_model_calls":0,"claim_ceiling":"readiness and blockers only"},{"id":"reader_stability","classification":"real_gt_single_case_diagnostic","n":"1 case/11 attempts","runs":1,"live_model_calls":11,"claim_ceiling":"single-case variability signal"}],"claims":[{"id":"baseline_metrics","status":"MATCH_RESCORed_ARTIFACT_ONLY"},{"id":"C1_sufficiency_gain","status":"FAIL"},{"id":"C2_generalization","status":"PARTIAL_SIMULATION_ONLY"},{"id":"C3_semantic_assist_gain","status":"NOT_RUN_AND_DESIGN_LEAKED"},{"id":"q0_complete","status":"COMPROMISED_LINEAGE"},{"id":"q1_wrong_complete_zero","status":"FALSE_ON_MATCHED_PATH"},{"id":"q4_q5_complete","status":"DETERMINISTIC_VERTICAL_ONLY"},{"id":"q6_matched","status":"NOT_RUN"},{"id":"release","status":"NOT_AUTHORIZED"}],"q_gates":{"Q0":"COMPROMISED_CHARACTERIZATION","Q1":"CHARACTERIZED_GATE_FAIL","Q2":"IMPLEMENTED_NOT_MATCHED","Q3A":"INFRASTRUCTURE_COMPLETE","Q3B":"PARTIAL","Q3C":"NOT_RUN","Q3D":"NOT_AUTHORIZED","Q4":"ORACLE_ISOLATION_ONLY","Q5":"FOCUSED_SIMULATION_ONLY","Q6":"NOT_RUN","final_correctness":"INCOMPLETE","final_quality":"FAIL_OR_UNRUN","final_governance":"INCOMPLETE","final_cost":"INCOMPLETE","final_operability":"INCOMPLETE","release_review":"NOT_STARTED","release":"NO_GO"},"action_items":{"without_external":["replace fake Q0 IR arms","fix nDCG denominator","document and independently review annotations","remove Q3C teacher target","fix source-aware coverage and wrong-COMPLETE","measure safety counters","restore Q6 bindings","version receipt lineage","update tracker and tests"],"requires_external":["multi-seed corrected Q0 oracle","unbiased live Q3C","repaired Q6 deterministic matched run","executed semantic arm only after proven mediator gain","nonzero governance/cost/operability gates","Q7 if current10 passes","final independent release review"]}}
```


# Phase 3C research preflight — no model allocation

Goal: `MILAI-POST-CLEANUP-DEVELOPMENT-01`. Status: `DRAFT_NOT_ADMITTED`.
This is a preparation record, not an experiment manifest or permission to send a
request. Model requests, generations and tokens allocated by this document: **0**.
The current [Goal](../../MiLAi-Product/docs/cleanup/MILA_POST_CLEANUP_DEVELOPMENT_GOAL_v1.0_20260922.md)
controls admission; the [Opportunity Ledger](MEMORY_OPPORTUNITY_LEDGER.md) controls
accounting. 3B-2 closed through PR #39 at `53e13c47c72a3f49f4cd66007320083babdc07be`,
with exact-head fast `35717333297`, identical candidate/merge trees and main fast
`35718296416` all PASS. This engineering gate does not allocate research calls.

## First bounded question: Utility Selection

Does pre-existing, permitted utility evidence change the selected exact memory
bundle and improve paired quality or complete cost without safety regression?

The first arms are `STATIC` and `UTILITY`; only selection may differ. Do not combine
new revision, attention, controller prompts, retrieval expansion or larger context
with the utility treatment. No Product default, schema or route changes are admitted.

Before any outcome, freeze task inputs, candidate pool, meaningful bundle choices,
utility evidence/version, policy and the static comparator. Eligible opportunities
require at least two candidates, two meaningful alternatives and utility that can
distinguish them. Semantic alternatives must be justified by task-visible evidence;
distinct hashes alone are insufficient. No-opportunity tasks remain in overall
cost/quality accounting but not in the mechanism denominator.

The same task, model/profile, tools, generation/context ceilings and visible feedback
must apply to both arms. Pair order must be declared before execution. A difference
in policy action establishes activation, not benefit. Observable-use evidence and
native task outcome remain separate. Primary comparisons are paired task-quality
delta and complete token/latency delta, with selection change and supported use as
mechanism measurements. Every failure, unknown usage and safety regression stays in
the record; no silent pair deletion or outcome-conditioned resampling.

Stop on exhausted budget/time, safety regression, invalid pin/input identity or
unsettled usage that cannot be preserved. No selection change ends the slice as
`STOP_INSUFFICIENT_MECHANISM_OPPORTUNITY`; changed selection without repeatable
benefit leads to `KEEP_SIMPLE` or a separately reviewed redesign, not automatic
sample expansion. A small DEV signal does not authorize holdout or Product promotion.

## Existing implementation is not the new experiment

- `methods/experience_utility.py::VersionUtility` stores exact versions, confirmed
  request exposures and ordered-sequence outcome associations. `confirm` does not
  establish observable use, and `selection_view` is explicitly not causal credit.
  A bridge must map these records to exposure, not fabricate supported use.
- `methods/evidence_utility_session.py::EvidenceUtilitySession` requires selected
  projection and post-task revision. Reusing that whole arm would change more than
  selection. Its v0.7 policies, bank format and historical results must remain intact.
- The 3B-2 actual fixture run has zero multi-choice selection opportunities. It
  proves accounting, not that Utility has no opportunities in a new task population.
  Its synthetic fixture token units are not model costs or reusable utility rewards.
- Historical banks, task allocations and `product.lock.json` are not new-run inputs
  or authority. No old experiment, protected pool or leftover budget is reopened.

The next implementation must therefore provide an explicit Lab-only matched
selection seam and actual request/version accounting; it cannot claim the old A1
path already implements this comparison. Offline implementation can precede model
authorization, but it cannot supply the missing benefit evidence.

## Required execution decisions still missing

| Field | Current state / requirement |
| --- | --- |
| Allowed input scope | User-approved new DEV source/task range; no formal holdout |
| Task and split identities | Freeze exact bytes, membership and hashes before execution |
| Candidate/utility provenance | Task-visible evidence and permitted prior outcomes; no current hidden labels |
| Method and policy | Freeze actual implemented selection rule and source identity |
| Arm kind | Declare Product black-box/testkit or research prototype honestly; no forged Product owner facts |
| Product baseline | Run-specific verified lock against selected exact main, not the historical repository pin |
| Solver/model/endpoint/profile | Explicit finite authorization; no automatic reuse of the old Qwen profile |
| Request/generation ceiling | 0 allocated; new finite maximum required |
| Input/output/maintenance token ceilings | 0 allocated; model and embedding/maintenance costs all included |
| Wall-time ceiling | New finite duration required |
| Native outcome/visible feedback | Freeze scorer and H/R visibility; scoring output cannot leak into selection |
| Stop/success thresholds | Freeze finite slice, opportunity threshold and paired quality/cost/safety criteria |
| Failure settlement | Persist attempted requests, known subtotals, unknown usage and unused allocation closure |

Missing or unresolved fields mean **DO NOT START MODEL CALLS**. A response that only
says “continue” does not specify these ceilings. The present Goal authorizes local
preparation and CI closure, not unlimited calls or shared-service reconfiguration.

## Later work remains in scope

Revision (`APPEND_ONLY` versus `REVISION`) needs original evidence, visible feedback,
exact predecessor/new version and independent later exposure; unused revisions cost
maintenance but do not demonstrate effect. Correction and scope narrowing are not
interchangeable with example refresh. New versions do not inherit old utility.

Attention begins with bounded deterministic `FOCUS / CONFLICT / EXPLORE`, explicit
state owner/freshness/absence, and cost/evidence-coverage/non-regression measurements.
No extra controller model is admitted. RL-like adaptation remains unadmitted until a
prior mechanism changes real actions. Transfer, dependent multi-session, second
solver and Product promotion retain their original independent-confirmation gates.

This document does not conclude `KEEP_SIMPLE`, `NO_PROMOTION` or overall completion:
those require the Goal's actual evidence, not the absence of current authorization.

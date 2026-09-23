# Joint Revision / Attention native runtime candidate

2026-09-23. **INTEGRATED_RUNTIME_CANDIDATE / NOT_EXECUTION_ADMISSION**.
Base/rollback: `0299b584730ea035f87c702d95382aaa4493fa38` (PR #48).
The [confirmed joint allocation](REVISION_ATTENTION_FIRST_BATCH.md) remains the
only authority: unchanged 32 pairs / 64 maximum arms and one finite budget.
No new external model/embedding/probe requests; real batch clock not started.

## What is implemented

[joint_native_runtime.py](../tools/joint_native_runtime.py) now connects the existing
native DB/OS Actor adapter, global-budget-gated `NativeProvider`, deterministic
Attention policy/durable expansion, and revision eligibility/accounting. It is a
callable runtime, **not a CLI that can admit or start an experiment**. Only `COMMON`
and `LAB` constants are imported from the closed Utility adapter; its `run`, `seal`,
root, ledger and historical execution are never invoked or reopened.

The native tasks still own tools, interaction and terminal scoring. DB remains
three rounds, OS five rounds / 20-second command timeout; Actor M1 remains unchanged.
The runtime sends the full native history, native system prompt, existing memory
consume wording when sources are projected, and existing action-budget context,
with only the explicitly declared memory-arm treatment added.
Each arm claims a fresh exclusive directory before reset. Exceptions retain native
and Provider costs; memory-accounting and release errors are recorded and cleanup
is attempted independently. Elapsed arm time includes cleanup. Scorer outcomes do
not enter a memory producer, state label, reward update or revision decision.

`actor_step` requires the exact shared `FiniteBudgetTransport`, calls the existing
Provider, checks actual messages SHA / SETTLED session-role-request receipt, and
records exact source bodies present in the request. Assembly is not exposure;
transport failures produce no confirmed exposure. A settled response with invalid
output still retains its confirmed input exposure and cost. All use remains UNKNOWN.

## Revision formation and later exposure

[joint_revision_formation.py](../tools/joint_revision_formation.py) sends only the
exact old card, original evidence, earlier visible question and later visible tool
feedback to the same Qwen `revise` role (temperature 0 / output cap 2048). Its
whitelist excludes later-target questions, target IDs, native outcomes and ranking
or analyst labels even if present in the caller's input object.

The response is either `NO_CHANGE` or a specific `CORRECTION` / `SCOPE_NARROWING`
proposal with cited visible feedback and changed claims/applicability. Malformed,
uncited or unchanged responses are charged and retained, not repaired/regenerated.
Shape/provenance validation does **not** establish semantic support.

After a genuine pre-native source review, the identical supported proposal is
applied with `EvidenceUtilitySession._apply_proposal` and the existing patch engine:
APPEND_ONLY retains predecessor plus new handle; REVISION preserves history and
replaces the current version. No fake `start`/adopt/generation is called to apply an
offline patch. The source bank is copied, never edited. Existing `VersionUtility`
records predecessors and cold-start versions; it does not copy old rewards.

The actual runner chronology binds proposal, application, source review, later
retrieval and SETTLED Actor exposure. Runtime rejects changed seals, unsupported or
non-core revisions, unknown lineage and target-cluster overlap before dispatch.
After the native terminal it uses the existing eligibility bridge against exact
retrieval/version/receipt facts. Structural eligibility still is not benefit/use.

The admission caller must authenticate the formation transcript and resolve/pin
the source review, not simply supply a dictionary marked SUPPORTED. Formation
costs are shared once in the actual global ledger; the final paired-cost analysis
must separately declare its counterfactual/amortization rule. Per-arm Provider
cost alone is explicitly **not** the complete lifecycle cost.

## Attention producer and review-preview rule

Only ATTENTION asks the existing Actor to emit a bounded leading
`<milai_attention>` JSON frame inside its normal response. STATIC is not charged
this treatment-only prompt/output. The frame contains relevant source IDs, all
conflicting source IDs and coverage SUFFICIENT/GAP/UNKNOWN. No extra controller,
judge, solver, round or generation budget is added. A complete leading frame is
removed before native parsing; business action bytes remain intact. Malformed,
foreign, duplicate, oversized or absent assertions yield UNKNOWN without retries.
Raw Provider output and parsing status remain in private artifacts.

State binds the actual settled input, question, task, exact whole pool and turn.
It guides only the **next** decision, with one-turn lifetime. It is explicitly
lagged: intervening new tool feedback has not yet been reviewed. A response can
refresh a whole-pool assertion only if all exact pool bodies were in that actual
request. Listing IDs or echoing an earlier judgment does not substitute for the
bodies. Focusing away sources can therefore cause the next state to be UNKNOWN
and restore the baseline. This conservative behavior is measured, not hidden.

A GAP may use the existing durable singleton expansion against the caller's
frozen, same-query, source-cluster-filtered ranking. This is local cached-vector
retrieval, with elapsed cost and an explicit zero external-request receipt, not a
new embedding or rerank. Formation of the query cache remains separately charged.
Returned sources fit the same eight-source / 8192-content-byte cap. Empty retrieval
still spends the attempt and re-decides to `EXPANSION_EXHAUSTED`, not an old intent.

When new sources arrive, old state/coverage is invalidated. A **single bounded
review preview** exposes the updated pool to the next existing Actor call with
coverage explicitly UNKNOWN. This is additional real exposure/cost, not selection
benefit or sufficient convergence. Only that Actor's subsequently produced frame
can guide a later focused decision. This preview is an explicit whole-method arm
difference, as is the frame prompt/format; unchanged-selection quality differences
must not be attributed to deterministic policy action.

Runtime assertions are not independent evaluation labels. Relevance, conflict and
coverage evaluation must be frozen separately before native outcomes; unknown
labels stay unknown. Modes not activated cannot be claimed as empirically tested.

## Verification and remaining admission work

Local **117 targeted tests PASS**, including 22 new integration cases plus existing
eligibility, Attention policy and durable-expansion tests. Changed-file Ruff and
both Lab dependency gates pass. The new tests use the real NativeProvider/finite
transport/global SQLite accounting with **local HTTP fixtures**, plus native task
interface doubles for DB/OS grammar, rounds, cleanup and no replay. There is no
real model call, benchmark scoring result, Docker execution or effect evidence.

The integration cases cover proposal whitelist, common proposal under both patch
rules, real serialized receipt/version joins, stale/unseen pool fallback, one-shot
preview, empty expansion, failed request upper-bound retention, deadline blocking,
malformed frame/proposal, changed source/predecessor, source-review rejection and
native release failure. CI owns package-wide checks/build; Product full and
historical experiments are not repeated.

Still required before the first external request:

1. Implement the single exclusive batch driver and durable formation → source
   review → native transition, all sharing one ledger/deadline; interrupted or
   unknown attempts may not become a new allocation.
2. Pin exact native checkout/images/prompts, corrected v2 review inputs, candidate
   ranking/cluster exclusions, source-window selection, full executable/prompt
   closure and stop/quality/complete-cost rules. The allocation itself is unchanged.
3. Reserve a verified embedding upper bound for the three missing instructed query
   vectors; any actual dispatch starts the same four-hour timer. Never use raw bank
   vectors or silently treat missing vectors as no opportunity.
4. Authenticate actual proposals and pre-native source reviews; freeze independent
   Attention evaluation labels, retain unknowns and all rejected/no-reuse costs.
   A review seal or these synthetic tests cannot replace this work.

No Product default behavior, API, Schema, permission or Canonical change. Schema
remains EXPERIMENTAL / NO-GO; overall Goal and mechanism-effect terminals are open.

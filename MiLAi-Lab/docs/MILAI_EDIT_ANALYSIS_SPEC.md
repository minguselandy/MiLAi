# MiLAi-Edit analysis specification v1

Fixed before E1 output inspection on 2026-10-04. This supplements the original
plan; the user's amendment permits one Qwen3.6 family throughout.

## Common information and first attempts

B0, B1, B2 and M receive the same original dialogue characters, roles, dates,
chronological formation boundaries, source token budget (4096), retrieval limit
(10), model, output allowance and Reader instructions. All source partitions are
processed in order; prepared coverage is persisted as original character ranges. Source
IDs, immutable revisions and issued range references identify evidence, without
proving semantic support. Previously formed records are available through the
same retrieval procedure. Old source reference metadata does not deliver old
raw bodies. No reference memories, persona, update flags, answers or future
questions are delivered to Writer.

Use every session of the four already selected development users. A model
format/length failure or rejected proposal consumes its first source opportunity
and remains visible. There is no extra reviewer or automatic semantic repair in
the main four-arm comparison. Unknown execution outcomes are preserved and are
never treated as permission to repeat the original operation.

Metadata admission found one start-time inversion in the first development
user: original session 61 is 2035-05-01 14:12:12 and session 62 is the same day
12:09:34. Normalize all four arms by stable start-time ordering, retaining original
session ordinals in outputs. The other three users already have ordered start
times. Record this departure from upstream array order; no session is removed.

## Official outcomes and denominators

Execute the upstream HaluMem integrity, accuracy, update and QA functions and
aggregation without changing their prompts or scoring rules. Their current
reference-guided update retrieval remains read-only and separate from natural QA.
Keep all native update opportunities, empty retrieval, missing-original cases,
attempted judgments, valid judgments and failures visible beside the official
table. Report the upstream aggregate exception if a denominator is absent.
Provide per-user counts and metrics; never count model calls as independent users.

Primary comparisons are B0→B1 (local text edits), B0→B2 (representation), and
B2→M (local operators at the same representation). Also report paired B1 versus
M. Use a paired user-cluster bootstrap, seed 20261004, 10000 resamples, and
percentile 95% intervals. With four development users the interval is descriptive
and cannot establish broad population effects or noninferiority.

## Native update diagnostic selection

Select up to 32 official native updates, at most eight per development UUID.
Only evaluator code may inspect their original/reference memory and dialogue.
Within each user, select the earliest available case from each of these categories,
then fill remaining slots in original chronological order without duplicates:
ordinary value correction; continuing condition or exception; scope-limited
override; explicit cancellation; historical correction; explicit uncertainty.
Classification uses the actual before/after reference text and observed dialogue,
not method output. Persist IDs, classification and rationale before judging arms.
The lexical shortlist was persisted while E1 was running, after three first-session
format receipts had been inspected for evidence-ID errors. No native mechanism
outcome or comparative arm score was used to select the shortlist. Its source review
is separate from that earlier engineering diagnosis.
The category labels are selective diagnostics, not additional official gold.
If a category has no actual source-supported case, report that gap. Do not create
an official case or use ideal reference memories to initialize an arm.

Evaluate new requirement completion, still-valid conditions, cancellation,
outside-scope behavior and unsupported additions from each method's own actual
before/after formed state. NeverWrite uses its unchanged actual before state;
retain-all combines actual before and newly formed text while retaining old
conditions. Neither control receives gold initialization. Diagnostic queries and
labels stay outside Writer and the official metric table.

## Confirmation, external comparison and sensitivity

After fixing a candidate from development, use all histories of the sixteen
reserved HaluMem users for B1/M confirmation and the attribution control needed
for the final claim. Do not tune methods or prompts using these outputs. Keep
variant histories linked to their original UUID for all uncertainty estimates.

LongMemEval-S has one connected shared-history component and prior local
development exposure. It provides descriptive external task evidence only.
Preselect a balanced category subset by identifier/order metadata, consume each
selected case's complete original history, export ordinary official hypotheses,
and report category and total numerators with the selected denominator. Do not
call a subset result a score on all 500 cases. A preselected answer-audit subset
adds whole-answer fidelity judgments without replacing official accuracy.

The external table compares raw RAG, rolling summary, one author-implemented
A-MEM adaptation and M on identical selected histories/Reader budgets. Record
author version, transport/embedding changes and any unavailable dependency.
External systems and operator attribution appear in separate tables.

The metadata-only external selection is fixed in
`data/manifests/milai-edit-external-subset-v1.json`: four lexicographically earliest
answerable IDs in each of the six categories, plus the earliest abstention ID in
each of the four categories where abstention exists. This is 28 questions and
1354 complete case histories (shared histories can recur). The complete-answer
audit uses the first answerable ID in each category plus all four chosen abstention
IDs, ten questions. This subset is selected before its model outputs, without
question text, answers, answer-session markers or method scores.

Before external admission, metadata preflight verifies all 1354 selected session
occurrences and chronological date ordering. Cases `001be529` and `078150f1` each
repeat an original session ID at two distinct dates, with the same observed role/body
content. Preserve every occurrence; external capture uses an ordinary occurrence key
and stores the original session ID/date in `source-occurrence.json`. This applies
equally to all external arms, without changing dates, bodies, original question IDs,
selection or counts. The original-ID overlap graph remains one connected source
component; these capture keys do not establish independent histories. This correction
was made before any selected external method output or model judgment.

A-MEM executes the author's original JSON-schema `memory_layer.py` class bodies
at Git commit `0c8039f28fdcc08189a23c07a3437d9d2482f9c2`. This is the original
implementation adaptation, not the separately recommended robust implementation
or an unchanged cloud-model reproduction. Provider callbacks use Qwen3.6 and
bge-m3; NumPy supplies the same row-normalized cosine operator. Author formation,
evolution, ranking, neighbor expansion and consolidation remain unchanged. Native
neighbor expansion may exceed k; the common Reader receives the first ten complete
note occurrences, while native context and every omitted occurrence are recorded.

Sequential drift follows native chronology. Order swaps use only updates
manually established to concern independent subjects; wording and Chinese/English
variants preserve actual propositions and form new memory banks from their own
dialogue. They share a source cluster and do not establish cross-family or
independent-judge generalization. Separate existing optional review ablations
from the four-arm main methods, preserving first versus final proposals.

## Functional and reporting conclusion

One final candidate must run prior L1, L2, L3, old L4 and new functional stories
through the current normal entry, with actual model calls and persisted results.
Keep ordinary failures, partial effects, UNKNOWN recovery and unchanged historical
r52 evidence. Deliver separate engineering, public-task, mechanism and functional
conclusions and a reproduction/contribution draft. Product acceptance is not
implied by completing this research plan.

## Evaluation implementation fixed 2026-10-05

This extension was prepared while B0 was still running and before any paired E1,
native mechanism, reserved-user, external audit or sensitivity result. The initial
four-arm protocol above remains unchanged. These evaluator additions do not change
the running Writer, proposal schema, source delivery, Reader or first-attempt policy.

The 32-item native review contains twelve actual sessions from four users. Its
source-supported requirement and diagnostic question are fixed in the source-review
manifest. Review disagreements with official references remain separate annotations;
the official scorer and references are unchanged. No scoped override or historical
erratum is verified in this shortlist, which is not a statement about all 595 native
opportunities. All four development arms must finish before scoring the slice.
Snapshots are the arms' own actual first-before and last-after states for the source
session. Historical Reader probes restore those exact current values into the same
MemoryService/SqliteStore, without gold initialization or extra Writer calls.

The transition Judge receives actual role-attributed new dialogue and only old source
ranges cited by that actual before state, including unit and relationship support.
Each cited old range carries the original message timestamp from its actual delivery,
not the later ingestion timestamp. Current dialogue likewise retains its original
dates. It never enumerates future bank records. Ordinary source and record identifiers are
renamed for assessment; rendered representation can still reveal the method, so this
is incomplete blinding. Report valid versus invalid judgments, initial target presence,
grounded prior-claim opportunities, unknown grounding, damage, unsupported additions,
current conflicts and cancellation opportunities separately. Cancellation without a
valid explicit judgment is unscored and remains in the all-opportunity denominator.
An unavailable Reader answer is also retained in the full-answer denominator.
The native answer Judge sees the reviewed current dialogue, the same actually cited
old source ranges and the question date; a legitimate retained old fact is not
automatically unsupported merely because the current session did not repeat it.
Report complete-answer support and requirement-correct-plus-supported rates
separately. A supported answer that misses the requested result is not task success.
Non-target damage rates use valid judgments with at least one source-supported
still-valid prior claim. Missing grounding or invalid judgments are not zero damage.
Unsupported-addition rates use valid transition judgments. Additional paired
user effects cover these two rates, cancellation success over all cancellation
opportunities and correct-plus-supported answers over all selected opportunities.
Report the actual paired and unscored users for each metric; a metric with no paired
users has no interval. All-opportunity requirement rates stay separate from valid-only
rates, and repeated cases do not become independent source clusters.
Pure assessment schemas and aggregation live in `analysis/edit_mechanism.py`;
network orchestration and own-state restoration remain in `runners/edit_mechanism.py`.

The external ten-question complete-answer audit uses the original unchanged hypothesis
and every chronological source session, not just answer-bearing sessions. Its evaluator
can see the official reference answer; Writer and Reader cannot. No additional Reader
generation replaces an answer. If the complete evidence cannot fit the existing context
limit, the audit preserves that first unavailable assessment rather than truncating
history or selecting favorable evidence. Official accuracy remains a separate table.

Native continuous drift assesses all 277 chronological sessions for every development
arm, together with original per-session official outputs. It counts cumulative damage
and unsupported-addition events, not unique damaged facts, and displays invalid gaps.
Only actually cited old ranges and the current session's original dialogue enter each
local transition assessment. This does not estimate global recovery of every omitted
past fact; official recall/QA retains initial formation failures and a complementary
trajectory. No extra editor generation modifies the native banks.

The controlled supplement is `milai-edit-controlled-dialogues-v1.json`: three authored
story clusters, ten variant histories, five observations per history. These are newly
written test dialogues, not official samples or observed natural users. Every variant
forms its own memory from those actual messages. English, equivalent English wording
and Chinese/English wording share one source cluster. One declared adjacent pair changes
salary and withdraws a food preference; its independence rationale is fixed before
outcomes. Only that pair is swapped. The stories cover temporary scope, shared conditions,
global changes affecting an override, cancellation, historical correction, uncertainty
and conflicting assistant assertions. Their questions/reviews stay evaluator-only.
Use the same four arms without an extra editor reviewer and retain ordinary failures.
Inside/outside scope success requires both the transition requirement and the complete
multi-part downstream answer to be requirement-correct and supported. This supplement
is admitted only after the final candidate
and common Writer version are fixed. It cannot establish natural-user or cross-family
generalization. Prepared configurations are not completed experiment evidence.

## Operational availability clarification 2026-10-05

This read-only reporting addition was made after B0 completed and while B1 was
still running. It is not a pre-output hypothesis or a change to the frozen methods.
The original four-arm comparison, source selection and semantic denominators remain.
`analysis/edit_results.py` now exports recorded operational counts per original user,
including an explicitly incomplete report with no paired effects before all arms seal.

Source ranges prepared in `source-coverage.json` establish partition coverage only.
Report their character counts separately from characters in a recorded Writer request
and in a confirmed Writer response. A context-capacity refusal before HTTP consumes
the prepared source opportunity without confirmed model exposure. A request lacking
its original response remains unconfirmed. Length/format failures and structural
rejections retain their first-attempt denominators, with paths to original failures.
Partially prepared sessions and batches remain pending rather than successful or
interference cases. All-session official results remain separate from these counts.

Count receipt status `committed` separately from accepted `no_change`, structural
rejection and any other/unconfirmed status. A replay carrying original status
`committed` confirms that original operation, without a second write; report it
separately rather than classifying it as pure no-change. Proposals and operation names describe
what was attempted; neither a commit nor a valid proposal establishes semantic
correctness. Preserve the running v1 maintainer's extracted-output list as its actual
official scorer input. The maintainer can include an accepted `no_change` record in
that list when its receipt contains an ID, so its extracted-output count must not
be presented as the number of changed records. Explain this limitation alongside
the original scores; do not silently recompute historical scorer inputs.

Source-only review also identifies a possible context-growth path: delivery includes
the complete retrieved current state and content, with historical evidence metadata
also listed separately. Local additions can grow that state; replacement or retraction
can shrink it, so growth is not necessarily monotonic. Old raw source bodies are not
redelivered. The shared proposal schema expresses operations for all arms, with arm
restrictions enforced at application time. This permits a structurally parseable
cross-arm operation to be rejected. Repeated valid evidence IDs are deduplicated and
are not themselves evidence-unavailable errors. These are code facts, not a causal
attribution of the observed failures; inspect original proposals and complete paired
results before drawing that conclusion or preparing a generic subsequent version.

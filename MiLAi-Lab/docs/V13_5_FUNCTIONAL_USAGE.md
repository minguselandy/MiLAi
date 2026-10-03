# v13.5 functional profile

**R46 is a mechanically checked development candidate; model acceptance has not run.**
It adds selected-original revision review and bounded unavailable-tool feedback under the
original allowances. Neither same-model approval nor valid provenance certifies semantic
support. R45 failed its communication regression; no stable configuration is recommended.
Its explicit confirm_existing_memory tool passed the actual existing-record story: real
no_change/effect none, original ID/revision/history and truthful unchanged confirmation.
However an ounces-to-grams correction selected only the old ounces source, a core support
failure. Another withdrawal answer added an unsupported smooth-outcome claim; label-only
continuation completed correctly but then proposed an unavailable update tool and failed
protocol delivery. The original11/27 was sealed as4 scoped PASS/3 FAIL/4 NOT_RUN, with15
COMPLETED/1 FAILED/11 unrun messages. Correct effects remain valid; no replay was performed.
R45's 469 mechanical checks, 18 production tokenizer probes and 4 SDK checks do not replace these
model results. Same-version L1–L4 have not been admitted. See [progress](V13_5_PROGRESS.md).
R46 has 546 passing regression checks, 23 production tokenizer probes and 4 installed SDK checks;
its exact source commit `81c8bc5` passed Fast CI 37141214168, while Full 37141214049 was skipped.
The [r46 checkpoint](V13_5_CHECKPOINT_r46_20261004.md) consolidates current results, CI,
costs and remaining work; the [r45 checkpoint](V13_5_CHECKPOINT_r45_20261004.md) is historical.
Product remains NO_GO.

This is an opt-in Lab entry over the existing public SQLite MemoryService,
LangGraph Agent loop and accounted vLLM provider. Its acceptance status is recorded
separately in `V13_5_REQUIREMENTS_AND_ACCEPTANCE.md`; the existence of this guide
does not establish semantic correctness or a Product release decision.

## Current candidate configuration

`configs/v13-5-functional-r46.json` is the current development candidate. Required
native declarations use temperature 0 with thinking disabled; execution uses temperature 1
and current-turn tool reasoning. Ordinary usable Agent answers are delivered directly after
receipt, visibility and delivery checks. Business and visibility effects still use program
receipt responses. There is no separate semantic rewrite of an ordinary answer.

Private checkpoints and diagnostic traces retain audit data; this is not physical erasure.
R30/R31/R32 communication included truncation. R34 completed with 5 scoped PASS/1
absence-inference FAIL; R35 had 4 scoped PASS/2 FAIL, including an unavailable tool proposal.
R36 adds the actual current-phase tool catalog beside the persisted intent interpretation,
including its restrictions during completion and tool-free answer repair. Permissions do
not expand. Full original L1 admission requires usable communication without unplanned
protocol failures or critical effects/privacy/integrity faults. Ordinary semantic failures
can remain explicitly open while collecting full regression under plan11.6; they are not
promoted to semantic or integrated acceptance. No stable configuration is recommended.

Every functional read now explicitly states that missing visible evidence cannot prove
never supplied, topic-specific forgetting or physical erasure. The reason remains unknown
unless actual evidence establishes it; this is a tool contract, not a semantic validation.

The candidate preserves these contracts; actual model choices still require evaluation:

- With `revision_support_review=selected_originals_v1`, every nontrivial revision receives
  one separately framed same-model assessment of each changed field and its selected
  original fragments before commit. Unsupported/uncertain decisions leave the revision
  uncommitted. The old record supplies unchanged context; the trigger is not automatically
  selected evidence. Legitimate same-source reinterpretation remains possible. This does
  not review new saves or certify semantic truth: stored support remains `unchecked`.
  Calls share the original durable per-message and queue budgets. Exact-input decisions
  persist across reopen; no valid persisted decision after an attempted review means
  pending, without a hidden retry. No_change and committed replay skip review. A returned
  review's exposure participates in forgetting without making the earlier user input derived.
- With `tool_catalog_errors=bounded_feedback_v1`, unavailable native tool names receive
  explicit nonexecuted catalog feedback before dispatch, within the original shared format
  allowance. No tool permission is added. Malformed batches and answer-only tool proposals
  remain protocol failures; completed business effects are never replayed to repair them.

- A current-request declaration controls memory maintenance, forgetting and the exact
  business mutation catalog separately. Historical requests do not renew authorization.
  An unresolved action grants no business mutation. Read-only requests still permit live
  business queries. The declaration is a model interpretation, not proof of user intent.
- `save_memory(content, fragment_handles)` takes one supported assertion with its limits
  retained in the text. `update_memory` requires a real read handle and separate selected
  fragments for each changed field. The program extracts quotes; literal identity does not
  prove semantic support. For a full withdrawal, `retract=true` with optional `changes=[]` uses
  `evidence_for_withdrawal` containing actual cancellation evidence, separate from the old
  target and its affirmation. Current input is not automatically evidence.
  The R42 `anchored_assertion_v3` interface selects each changed field's source using
  `{fragment_handle, supporting_words}` entries. `supporting_words` is a short exact
  phrase (1–160 characters) from that fragment expressing the new assertion or cancellation.
  The program rejects mismatched handle/cue pairs before commit and extracts the full quote.
  It neither substitutes a source nor certifies semantic support. Same-source legitimate
  reinterpretation and archived evidence remain allowed. Full withdrawal uses the same
  cue entries in `evidence_for_withdrawal`. The failed R39 preview profile is historical;
  R42 does not require a review token.
  R41 additionally refuses a full withdrawal supported only by intervals already
  covered by that record's affirmative support, including subset/union aliases.
  It requires at least one distinct evidence span; an archived event or another span
  in the same source remains eligible. It never auto-selects the current request.
  If a legitimate cancellation shares only already-used intervals, this profile
  requires a separately selected withdrawal witness; it will not silently retract.
  R42 allows omitted/null changes only for full withdrawal. Ordinary updates must supply
  changes, including [] for an explicit no_change check.
  Distinctness is a provenance constraint, not semantic validation, and does not
  apply to ordinary same-source revisions or exact no_change.
  Unchanged fields keep their values and support. Repeating the
  exact same-message save returns `existing_record`/`no_change`, not a second write.
- With `existing_confirmation=explicit_no_change_v1`, `confirm_existing_memory(read_handle)`
  returns the original exact no_change receipt. It checks the issued current version and
  owner under the actual bound message; stale/revoked/other-owner targets cannot confirm.
  Describe it as already present, never as newly saved. It has no content or patch arguments
  and does not validate semantic equivalence to the request. It is available only where
  memory maintenance was already permitted; readonly queries do not gain a maintenance tool.
- One actual write receipt is necessary for a requested save confirmation; it cannot prove
  that every requested item was saved. Missing maintenance can use one bounded completion
  within the original shared repair allowance. Previously permitted forgetting remains
  available there only under the declared operation-completion policy; business mutations
  cannot be replayed by that completion.
- `operation_status` separately reports raw capture, listed semantic writes, visibility
  changes and business effects from actual receipts. It does not certify the model's prose
  or complete user intent. The `receipt_or_agent_response_v1` profile renders business and
  forgetting results from receipts; ordinary usable Agent content is delivered without an
  extra composition call. Legacy `readonly_response_v1` runs keep their separate stage.
- `bank_recent_v2` supplies at most four recent visible records and four public events in
  the same owner/bank within the existing material limit, across sessions. Current input
  stays first. Explicit fixed candidate pools receive no supplementation or reordered
  evidence. Old user requests, assistant speech and actual observations retain their roles.
- `fresh_query_with_history_v3` requires a current same-object query before mutating a
  previously operated business object. Live queries include up to sixteen original
  operation receipt summaries with an omission count. Historical unknown results remain
  unknown even when a current query establishes the present state. A semantic observation
  timestamp is not automatically the business event's time.

Interpretation repair, answer-only repair and missing-maintenance completion share one
persistent allowance within the same 24-call limit. A checkpointed `read_limit_exhausted`
ends execution as FAILED with preserved effects; resuming the message does not reset its
three-read limit. `receipt_status_v4` can deliver a program failure report, including shared format
reproposal exhaustion, without another model call. A readable failure report does not turn the execution into COMPLETED. Successful
business actions are not repeated to repair an unusable final response.

`completion_tool_choice=required_until_attempt_v1` keeps the existing completion's tool
selection required after prerequisite reads until an actual save/update/forget receipt.
Any attempted outcome, including rejection or unknown, releases the requirement; it does
not require a successful write or authorize retries. The original read-exhaustion stop and
shared generation/repair bounds still apply, including after checkpoint reopen.

The historical `completion_tool_choice=required_once` applies only to the first proposal of a persisted
missing-maintenance completion. It binds the actual restricted catalog; business mutations
stay unavailable, forgetting is available only if already authorized, and an exact empty
update can confirm an existing record without a new version. The phase survives reopen;
following tool replies use auto again. There is no additional repair allowance. Requiring
a proposal does not prove that its selected object, value or support satisfies the request.

The renderer currently uses Chinese labels and reports listed operations only. Destination
and packing are configurations; document publication is a local sandbox effect. Ordinary
memory answers remain model text and can be wrong. Owner isolation, source visibility and
replay checks apply before delivery; the explicit diagnostic `world` sidecar retains audit
history and is not material supplied to the Agent. Raw experiment artifacts are not a
physically erased or remotely authenticated user store.

## Accepted configuration

None. Full same-version L1 and integration acceptance with no critical blocker is required.
The exposed r29 targeted cohort was 2 scoped PASS/1 FAIL; L1-r25 and L4-r28 are also historical
results, not results for r43. Do not combine their successful cases into a new cohort score.

## Candidate example (r43, development only)

Run from `MiLAi-Lab` with the repository's pinned Python environment and `PYTHONPATH=src`.
The checked-in configuration uses the existing local model, tokenizer hashes and continuous
cost ledger. It does not deploy a service. Use an unused run root for each changed version.

```bash
export PYTHONPATH=src
python tools/run_functional.py prepare \
  --root artifacts/v13-5/personal-r43 \
  --config configs/v13-5-functional-r46.json
python tools/run_functional.py message \
  --root artifacts/v13-5/personal-r43 --bank personal --owner alice \
  --session monday --message-id first \
  --text '请记住：工作日午餐我吃素，周末不作这个限制。'
python tools/run_functional.py message \
  --root artifacts/v13-5/personal-r43 --bank personal --owner alice \
  --session tuesday --message-id recall \
  --text '我工作日午餐有什么偏好？周末呢？'
```

## Historical reproduction

Use the original cohort's source commit and its recorded configuration, such as
`configs/v13-5-functional-r0.json`. R0 parameters on current source constitute a new run,
not a replay of r0. Existing frozen roots reject changed source/configuration. Historical
pause files and sealed cohort outputs remain unchanged; see the run manifest for identity.

Keep `root`, `bank` and `owner` unchanged to reuse long-term state. A different
session starts with the same owner-visible Store; earlier conversation text is
retrieved through that Store. Each public message runs in its own resumable
checkpoint and may be executed by a fresh process. Owner identifiers are trusted
caller context, not an authentication service; exposing this CLI as a remote API
requires a separate authenticated owner boundary.

Natural requests use the same tool path:

| Intent | Example |
| --- | --- |
| Save | “请记住我倾向于简短回答。” |
| Revise | “把之前的回答长度偏好改为详细解释，其他偏好不变。” |
| Read history | “我最初怎么说的，后来改了什么？” |
| Retract a condition | “取消之前仅限工作日的条件。” |
| Forget | “忘记我的回答长度偏好，包括它的原始来源。” |
| Check business state | “先查询上次预订的实际状态，已经完成的不要再做。” |

The assistant chooses real issued fragments and record read handles. A semantic
card must be committed before a save confirmation; observed Host violations of
that requirement are retained in the run register. Exact quotation extraction and
version checks are program responsibilities; whether the proposed prose follows
the evidence remains a semantic quality question. A rejected proposal is not a
saved record. Current values, recorded history and raw source are distinct reads.

## Business workflows

Use `--workflow reservation` for booking and label tools, or `--workflow document`
for draft editing, version approval and sandbox publication. Each workflow has
its own application state and shares the bank's MemoryService. Application tools
own business permission and current versions. Memory IDs, archived receipts and
source hashes do not authorize application changes.

Report reservation success and label failure separately. Draft edits invalidate
old approvals; approval and publication refer to the current version and digest.
The document backend publishes a durable local sandbox artifact, not a message
to an external audience.

## Interrupted work and outcomes

Reusing the same message ID with the same input returns its recorded result only
while its material remains visible. A later forget can invalidate live replay
of that archived response; the original audit artifact remains retained.
Changing text under that identity is rejected. `--resume` explicitly resumes an
interrupted message using its durable checkpoint and remaining generation budget.
Original attempt artifacts remain available. It does not grant permission to
repeat a mutation whose outcome is unknown.

| Outcome | Meaning and next step |
| --- | --- |
| `COMPLETED` | The public loop returned text passing the minimal delivery check; meaning and task quality are evaluated separately. |
| `FAILED` | A known input, format, capacity or runtime failure; inspect its category. |
| `BUDGET_EXHAUSTED` | The message or frozen queue cannot admit more generation. |
| `PROVIDER_ERROR` | The provider request failed; usage and the failed attempt remain recorded. |
| `UNKNOWN` | A storage or business effect cannot be confirmed from its receipt. |
| `NOT_RUN` | A preceding failure or queue stop prevented this step from running. |
| `VISIBILITY_REVOKED` | A stored response depends on material later forgotten; live replay returns no archived body. Use a new message for a new request. |

Current candidate responses include `operation_status`, computed from durable
current-message receipts, separately from `final_answer`. It reports raw event
capture, semantic writes, visibility changes, business mutations and observations.
Each operation retains its receipt reference and affected record ID/version where
available. A read is not a new write; one successful write cannot certify other
requested changes. `request_completion` remains `unchecked`. Clients must use
these fields for execution status rather than infer success from free prose.

`final_delivery` checks for usable text presence only; it does not judge truth or
relevance. Null provider content, blank text and punctuation-only output fail
delivery without undoing confirmed effects or promoting reasoning to an answer.
An explicit `--resume` can request one answer-only recovery, sharing the existing
format-reproposal and generation budgets. That path has no tool catalog or
dispatcher. Original attempts and checkpoint history remain evidence, and a
successful recovery never changes the first attempt's failure score.

On an unknown business result, discover current state through its public query
before considering any remaining action. The original unknown receipt is retained
beside the discovery. Receipt capture, memory projection, semantic commit and
checkpoint delivery are separate stages; a pending stage does not mean all prior
stages failed. A stale memory read requires a fresh explicit read and new proposal.

## Bounds, visibility and rollback

The current candidate permits 8,192 tokens of ordinary material, three explicit
additional reads, 8,192 output tokens, 24 generation calls per public message,
and at most one format reproposal. The full outgoing prompt, tool protocol,
material, output reservation and safety margin must fit the pinned 65,536-token
provider capacity. Message reservations survive restart. A frozen queue also has
finite request and reserved-token limits; the existing continuous ledger remains
the usage authority. Omitted body text is reported with a snapshot-bound cursor.

Forget revokes the selected record and its supporting Sources, explicitly
selected additional Source fragments, the current forget request, and assistant
outputs that received the selected material. Revocation covers each selected
Source event, including raw fallback, and invalidates previously issued reads
and material caches. An independent user input remains visible even when
another Source was prefetched during its save. To remove independent copies,
select their actual issued fragments with `additional_fragment_handles` beside
the record read handle, or use Source-only forget. There is no automatic semantic
copy or paraphrase detector; the receipt states the selected scope and counts.
It does not promise physical erasure of SQLite pages, experiment traces, backups or sealed earlier
cohorts. Use isolated test banks for deletion experiments. Experiment files may
contain the original source and should be handled accordingly.

Disable the functional entry without deleting evidence:

```bash
python tools/run_functional.py disable --root artifacts/v13-5/personal-r43
```

This blocks new functional messages before capture or model dispatch. `enable`
reopens the same profile. Existing legacy entries and defaults remain separate;
use their original configuration and state paths when rolling back to them. Do
not point a legacy writer at a functional namespace. Changed code or configuration
requires a new frozen run directory instead of rewriting an earlier cohort.

The persistence guarantee covers cooperating serial processes and these tested
SQLite backends. It is not a distributed exactly-once guarantee, automatic physical
erasure, an independent Judge result, or a claim that arbitrary prose is correct.


The current `fresh_query_with_history_v3` candidate retains the single-attempt phase contract: for each exact
business object, each phase has at most one actual attempt in a public request,
including known failure/no-effect results. `reserve_and_label` includes the label
phase. A new user request can continue unfinished work after a live query; reopening
the same public request does not reset the allowance. Draft, approval and publication
are distinct document phases. This bounds automatic retries; it does not infer user
authorization or certify that the model chose the correct object. Legacy profiles
keep their previous behavior. Completion feedback is folded into the leading system
message for the actual provider template; the original checkpoint marker remains.


Historical R12 used `current_request_native_v1`; its boolean declaration and original
results remain frozen in that cohort. The current candidate uses the v6 independent
capability declaration described above. Neither is a semantic authorization oracle.

# v13.5 functional profile

**Development resumed by explicit user instruction on 2026-10-03.** R16 completed
all original 24 stories / 48 messages: 24 PASS on the frozen original rubric and
scoped current-state/source/maintenance review. Exact-commit Fast CI passed.
Full L2-r17 completed all12/26: 10 scoped PASS, 2 FAIL. L2-r18 then stopped after
4 completed messages on an unauthorized document edit during publication continuation.
L2-r19 preserved the original document and actual publication, but stopped on a bounded
read failure and rejection of a literal negative quote in a read-only declaration.
L2-r20 completed all12/26 with 6 scoped PASS and 6 FAIL: source selection, live-query omissions,
operation declaration omissions and redundant read exhaustion remain. Its exact Fast CI passed.
These failures remain preserved. L3/L4 remain unrun. Full functional acceptance is still
pending and no stable configuration is recommended. Earlier failures and scoped
communication cohorts remain separate evidence; their scores are not pooled.
See [current functional progress](V13_5_PROGRESS.md); the
[pause report](V13_5_PAUSE_STATUS_20261003.md) remains historical evidence.

This is an opt-in Lab entry over the existing public SQLite MemoryService,
LangGraph Agent loop and accounted vLLM provider. Its acceptance status is recorded
separately in `V13_5_REQUIREMENTS_AND_ACCEPTANCE.md`; the existence of this guide
does not establish semantic correctness or a Product release decision.

## Current candidate configuration

Use `configs/v13-5-functional-r21.json` with a new root for current candidate
validation. R21 uses native v4 with thinking enabled, with unchanged capacity/call/read limits.
It requires a current same-object query before a new mutation of an earlier operated object,
and shows exact original content beside each business source fragment handle.
R21 retains exact current-message save idempotency and first interprets the current
request without retrieved history. A three-state memory-write declaration distinguishes queries, new assertions and
explicit storage requests; reading a memory result is not a write request.
A separate business action declaration distinguishes none, perform and conditional continuation,
and requires an exact current-request clause for an action. It also lists the specific
public business operations permitted; the catalog and dispatcher enforce that list.
Document editing is distinct from semantic memory maintenance. A read-only v4
declaration may keep an exact current negative/query clause or an empty quote;
its operation list remains empty and mutation tools remain unavailable. The literal check is not semantic
authorization. The persisted interpretation separately controls
memory maintenance, forgetting and business mutation tools. A read-only interpretation
still permits live business queries. This is a model interpretation, not a proof of
intent, authorization or semantic support; full functional acceptance is pending.
It uses the same accounted provider and durable 24-call message quota. Interpretation
format repair, answer-only repair and missing-maintenance completion share the existing
single reproposal allowance. For an admitted memory write (explicit request or actual new assertion/correction)
with no actual save/update receipt, the candidate final answer is withheld and one memory-only completion step
may run. It cannot replay business mutations or forgetting. All candidate answers
remain in the audit; only the admitted final answer is delivered. A receipt for one
item does not establish full request completion, semantic support or prose truth.
Historical roots freeze their original source/configuration and cannot be resumed
under changed code. No configuration is listed as accepted until full L1 passes
without unresolved critical functional defects.

The candidate exposes `save_memory(content, fragment_handles)`: include the complete
fact and its explicit applicability limits together in `content`. New saves have no
separate free-form scope argument; existing scoped records remain editable.
The candidate `receipt_business_response_v1` policy renders the two business workflows
from matched actual ToolMessages and current-message journal identities. It reports raw
capture, semantic writes and business effects separately. Historical facts use only already
delivered original tool fragments or public document-query history. Execution drafts cannot
announce effects to the user. Destination/packing are configurations; publication is a local
sandbox effect. Chinese receipt labels are currently supported. The renderer reports listed
operations, not proof of complete user intent or correctness of saved semantic content.

Ordinary memory answers retain the `readonly_response_v1` no-tool composition stage,
with a fresh original-request/evidence frame excluding execution draft prose. Its reservation
and response survive restart, and its generation shares the original 24-call limit. A failed
response can use only the remaining shared repair allowance on explicit resume.
`operation_status` remains the independent program receipt summary.
The `single_phase_with_history_v2` business policy includes the latest16 original
owner/object operation receipt summaries in a live query, ordered with an explicit
omission count. Original unknown outcomes remain unknown; current observed state is
separate. Old request/document bodies are excluded from these summaries. Publication receipts
also carry the actual `attempted_audience`, separately from successful publication
`audience`, including known failed attempts. Original native responses remain preserved.

A checkpointed `read_limit_exhausted` now ends execution in this candidate. The result is
FAILED with an available outcome report and preserved effects, not a completed task. Resume
on the same message encounters the same terminal receipt without resetting its allowance.


The current `update_memory` catalog requires `fragment_handles` inside each
`changes` item. Select support for the new value or removal, independently for
each changed field. Unchanged fields retain support; top-level handles are for
whole-record retraction only. `input_relation` distinguishes current input from
archived Sources but never makes either one semantically sufficient evidence.
Repeating an identical save in the same public message returns `existing_record`,
`no_change`, and `effect=none`; it does not count as a new write. Requests with
different content, scope, selected evidence or public-message identity remain
distinct. The program does not decide that paraphrases describe the same matter.

## Historical reproduction example (r0, not an accepted configuration)

Use the recorded original source commit for faithful historical reproduction.
Running r0 parameters under current source is a new run, not a replay of r0 results.

Run from `MiLAi-Lab`, with the repository's pinned Python environment and
`PYTHONPATH=src`. The checked-in configuration names the existing local model,
tokenizer hashes and continuous cost ledger. It does not deploy a service.

```bash
export PYTHONPATH=src
python tools/run_functional.py prepare \
  --root artifacts/v13-5/personal \
  --config configs/v13-5-functional-r0.json
python tools/run_functional.py message \
  --root artifacts/v13-5/personal --bank personal --owner alice \
  --session monday --message-id first \
  --text '请记住：工作日午餐我吃素，周末不作这个限制。'
python tools/run_functional.py message \
  --root artifacts/v13-5/personal --bank personal --owner alice \
  --session tuesday --message-id recall \
  --text '我工作日午餐有什么偏好？周末呢？'
```

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
python tools/run_functional.py disable --root artifacts/v13-5/personal
```

This blocks new functional messages before capture or model dispatch. `enable`
reopens the same profile. Existing legacy entries and defaults remain separate;
use their original configuration and state paths when rolling back to them. Do
not point a legacy writer at a functional namespace. Changed code or configuration
requires a new frozen run directory instead of rewriting an earlier cohort.

The persistence guarantee covers cooperating serial processes and these tested
SQLite backends. It is not a distributed exactly-once guarantee, automatic physical
erasure, an independent Judge result, or a claim that arbitrary prose is correct.


The current candidate opts into `single_phase_per_public_turn_v1`: for each exact
business object, each phase has at most one actual attempt in a public request,
including known failure/no-effect results. `reserve_and_label` includes the label
phase. A new user request can continue unfinished work after a live query; reopening
the same public request does not reset the allowance. Draft, approval and publication
are distinct document phases. This bounds automatic retries; it does not infer user
authorization or certify that the model chose the correct object. Legacy profiles
keep their previous behavior. Completion feedback is folded into the leading system
message for the actual provider template; the original checkpoint marker remains.


R12 uses `current_request_native_v1`: the same host emits exactly one
`classify_current_request` declaration with four boolean flags and no free explanation.
This declaration executes nothing and is not an authorization or semantic oracle.
A pure question differs from a request to query and then finish remaining work.
Invalid declarations receive the original bounded schema reproposal; all attempts
remain accounted. Save/update parameter descriptions require source-faithful
restrictions in the actual content and explicit applicability limits in scope;
they do not mechanically prove semantic support or eliminate model errors.

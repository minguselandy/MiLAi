# v13.5 functional profile

**Development resumed by explicit user instruction on 2026-10-03.** No configuration
has passed full L1 acceptance. R0–r4 are historical failed/incomplete cohorts;
r5 was not run; r6 failed communication admission. R7 passed scoped communication
but failed L1 after a duplicate save. R8 is the current candidate;
there is no stable recommended configuration yet.
See [current functional progress](V13_5_PROGRESS.md); the
[pause report](V13_5_PAUSE_STATUS_20261003.md) remains historical evidence.

This is an opt-in Lab entry over the existing public SQLite MemoryService,
LangGraph Agent loop and accounted vLLM provider. Its acceptance status is recorded
separately in `V13_5_REQUIREMENTS_AND_ACCEPTANCE.md`; the existence of this guide
does not establish semantic correctness or a Product release decision.

## Current candidate configuration

Use `configs/v13-5-functional-r8.json` with a new root for current candidate
validation. It retains r7's fixed native nonthinking provider and capacity limits.
R8 adds exact current-message save idempotency; full functional acceptance is
still pending.
Historical roots freeze their original source/configuration and cannot be resumed
under changed code. No configuration is listed as accepted until full L1 passes
without unresolved critical functional defects.

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

The initial profile permits 8,192 tokens of ordinary material, three explicit
additional reads, 4,096 output tokens, 24 generation calls per public message,
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

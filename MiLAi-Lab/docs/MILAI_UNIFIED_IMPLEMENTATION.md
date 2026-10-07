# Unified memory implementation contract

The user activates [the task cards](MILAI_MULTI_AGENT_DEVELOPMENT_TASKS.md) and
[the companion architecture plan](MILAI_UNIFIED_MEMORY_ARCHITECTURE_AND_BUILD_PLAN.md).
Both source documents have been read and copied into this worktree unchanged.
This extends the existing build-first candidate and retains its full validation scope.

## Ordinary stored-history reading and independent recipe branches (4b3501b)

Current record fragments expose actual committed_at and one bounded stored_history
index per record: the existing six-revision window, actual total/omitted counts,
index cursor and existing history/revision tool entries. The index contains revision
identities, not historical bodies. Body reads retain owner/visibility checks, the
explicit read allowance and original snapshot pagination; historical_exact_revision
does not make old content current. Storage time is not reported or effective time,
and the service index cursor is distinct from the functional body cursor. Explicit
forget still revokes old history entries and original source visibility.

The normal SQLite example now saves r1, adds an exception in r2, withdraws it in r3,
reopens, reads actual r2 through ordinary tools and then forgets. Reads do not mutate
the record. Initial metadata prose exceeded an existing 2600-character packet;
compact wording restores its original full 100-character first fragment without
changing the budget or omitted material. Real Agent tool selection remains untested.

The recipe comparison clones each actual prepared bank. Before issuing its views,
it removes copied read grants for absent records or revisions beyond the actual
before, keeping past grants. Actual stored values and prepared originals are unchanged.
It saves the first maintenance result before observing after or calling the Reader.
This fixes the frozen962 comparison's post-commit future-grant collision; its first
failure remains preserved. No Runtime handle collision check is weakened, no new
retry or content fingerprint is introduced. Full affected checks total247; core
three-source/example mypy passes, while the tool's separate strict type check still
has the same five pre-existing errors as main2cf. New real comparisons remain0.

## Actual request progress and current execution (402d7d5)

The same request journal now keeps business.status as the observed aggregate of
its required steps (incomplete/partial/completed/unknown/current-state-changed).
Current dispatch status, can_execute, allowed_operations and readonly live in
business.execution. Initial or unevaluated snapshots explicitly say not_evaluated;
that view never grants an adapter capability. A readonly check of a partly completed
request preserves its completed effects and shows partial alongside observed_only.
Ordinary receipt presentation renders both fields, leaving original attempts,
unknowns, semantic-save receipts and Host feedback checkpoints separate. This is
execution state, not a semantic fact or authorization from memory text.

The follow-up editor prompt (4a2d7ba, from 743c2ded) locates applicability inside
the owning assertion and gives a hypothetical conditioned date example. It does
not move malformed output, change the public schema or infer effective dates
from Source report metadata. Its real-model effect remains untested.

## Shared calls and ownership

| Capability | Existing authority and implementation seam | Owner |
|---|---|---|
| Ingest | `MemoryService.capture_user/capture_assistant/capture_tool`; immutable original sources | Root |
| Maintain | `maintain_event(method, delivery, ..., model_call, commit)`; one logical MemoryService | D |
| Recall | `MemoryService.search/read`, ordinary Host and shared read applicability | Root, B/D |
| Consolidate | bounded selection of visible episode sources and records, invoking supplied maintenance callback | A |
| Forget | existing `MemoryService.forget`; derived views recheck original visibility | Root, A/E |
| Resume | existing journal/discover and confirmed operation IDs; explicit new semantic attempt preserves failure | C/D, Root |

Root alone edits `contracts/memory.py`, `memory/service.py`, central runners, public
configs and status. A owns new `memory/episodes.py`, `methods/consolidation.py` and
its example. B owns `memory/edit_units.py`, `methods/edit_memory.py`,
`methods/edit_features.py` and its example. C owns `application/functional.py`,
`application/recovery.py`, `application/refs.py`, new thin application adapter and
its example. D owns `methods/edit_maintenance.py`, `methods/functional_edit_memory.py`,
`memory/retrieval.py` and its example. E owns new `memory/activation.py`,
`harness/memory_simulation.py` and its example. Each worker uses an isolated worktree
and synthetic SQLite only; no real model HTTP or private benchmark data.

## Small module seams

- Optional `SourceEvent.calendar_context` is a caller-declared nominal coordinate,
  not a physical timezone. Capture retains it immutably; old sources without it
  cannot be backfilled. `occurred_at` is statement time and `observed_at` remains
  the actual UTC capture clock. ISO and English-month values retain precision;
  a date denotes a whole day. Floating values compare only within the same
  explicitly declared calendar; offset-aware values compare by their offsets.
  Missing, different or mixed contexts stay unresolved.
- Ordinary Host `message` and CLI separately accept `calendar_context`,
  `query_time` and `query_calendar_context`. Both functional read projections
  use the same Reader target time; omission retains the service-clock default.
  Statement time does not become the query target or the assertion's onset.
  Benchmark `calendar_context` explicitly declares the nominal source/query
  frame; [predict v2](../configs/milai-unified-prefix8-v2.json) demonstrates it
  with unchanged model, dense K10 and budget. This is a new-run declaration,
  never metadata inferred from a dataset name or added to old results.
- Reader transport shares exact repeated descriptions, clock strings and issued
  references with the existing JSON `$ref` format. Expansion preserves the full
  actual view; it does not alter persistent values or give references new authority.
  The [SQLite revision example](../tools/example_unified_revision.py) covers
  current/history, expiry, retrospective reports and unresolved coordinates.

- Episodes reference actual `source_refs` in the same owner Store. Episode identity
  is explicit, source content stays at the source authority, and every read checks
  visibility. Reported, observed, inferred and uncertain descriptions remain distinguishable.
  Consolidation takes a caller callback using current visible sources and records;
  replay never captures a fresh event or becomes independent support.
- Revision rendering takes actual state and an optional explicit query time. It
  reports source time, explicit effective limits, current/historical statements,
  active relations and unresolved scope without allocating aggregate counts to members.
  Changed assertions use new support; retained qualifiers retain existing support.
- Application adapters expose lookup, execute, observe and discover through the
  existing reservation and document sandboxes. Verified identity is neither current
  permission nor a current-state claim. Recovery uses actual receipts and the
  current request's permissions, and presents business and memory effects separately.
- Common maintenance accepts actual current source, separate prior context, both
  recipes and Append-only. Explicit retry is a new attempt ID after a declared
  reconciliation; an unknown request is never sent again under the old identity.
  Repeated reads track delivered object/version/cursor progress and use existing evidence.
- Activation exposes transparent time decay and deduplicated use, and utility
  updates require actual feedback provenance. They are retrieval aids, not truth,
  permission or deletion policies. The dense comparison remains available unchanged.
  Simulation uses a separate owner/SQLite, virtual clock and the same public callbacks;
  evaluator truth and scripted transport stay outside runtime evidence.

`SourceEvent`, `VerifiedObjectRef` and `ObservationProfile` remain the basic public
objects. Workers request only necessary optional fields from Root; no parallel DTOs,
new source hashes or replacement fingerprint checks. A single optional unified
profile enables the added capabilities in ordinary Host and predict configuration.

## Integration and evidence

All five handoffs are integrated at5c36b28. Root adds the ordinary Host/predict
configs and explicit same-bank consolidate/full-request resume CLI. Read quota
exhaustion uses delivered material; actual Reader deliveries record deduplicated
usage, while cache/scorer reads do not. Lossless source subbatches have distinct
HTTP paths, preserving first inputs/responses. Source commit is a normal run
annotation, never a SHA/fingerprint gate. Calls, migration/export, limitations
and the fixed interrupted-score observation are in
[the unified usage document](MILAI_UNIFIED_MEMORY_USAGE.md).

Three worker slots require staggered execution of the five task cards. Root reviews
and integrates each handoff, runs affected existing checks and one normal example,
then the unified five-flow real smoke and concentrated predict/score. Module examples
using scripted transport prove engineering behavior only. Same-version controls,
65/277 histories, reserved users, native/drift/ablations, external and complete Host
validation remain outstanding; no final method or Product approval is inferred.

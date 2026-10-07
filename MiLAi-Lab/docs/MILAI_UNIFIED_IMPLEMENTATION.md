# Unified memory implementation contract

The user activates [the task cards](MILAI_MULTI_AGENT_DEVELOPMENT_TASKS.md) and
[the companion architecture plan](MILAI_UNIFIED_MEMORY_ARCHITECTURE_AND_BUILD_PLAN.md).
Both source documents have been read and copied into this worktree unchanged.
This extends the existing build-first candidate and retains its full validation scope.

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

Three worker slots require staggered execution of the five task cards. Root reviews
and integrates each handoff, runs affected existing checks and one normal example,
then the unified five-flow real smoke and concentrated predict/score. Module examples
using scripted transport prove engineering behavior only. Same-version controls,
65/277 histories, reserved users, native/drift/ablations, external and complete Host
validation remain outstanding; no final method or Product approval is inferred.

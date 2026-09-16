# ADR-052: Bounded cross-type memory discovery

Status: ACCEPTED FOR LOCAL IMPLEMENTATION, 2026-09-08, under the user's instruction
to reorganize retrieval tools and change the retrieval logic. Public deployment,
model generation and automatic memory maintenance remain out of scope.

## Problem

The ordinary catalog can save Notes, but `milai_memory_resolve` searches the existing
governed retrieval path, not Notes. External OAuth assembly overwrites the ordinary
catalog instructions. Note matching uses a literal substring, yet presentation always
returns the first 256 characters, possibly hiding the actual matched passage.
These are discovery/presentation defects, not evidence that all cross-session storage
is broken. A particular live conversation's final source still needs its raw trace.

## Decision

Add `milai_memory_search(query, note_query?, note_limit=3)` to the opt-in
`ordinary-memory-v1` catalog. Keep the legacy 13-tool catalog and the existing
resolve/get/Note/Working State semantics. The complete ordinary catalog now has 23
registered tools, filtered by current authorization at discovery and dispatch.

This read-only facade concurrently invokes exactly two existing tool dispatches:
`milai_note_search` and `milai_memory_resolve`. The former receives a literal
`note_query` when supplied, otherwise `query`; the latter receives the original query.
No automatic query rewriting, synonym table, case-specific routing, model call,
full Evidence inventory scan, pagination loop or retry is introduced.
Note results default to 3 and are capped at 5; governed reads retain the existing
Runtime budget/profile and output bounds. Each branch has a bounded 35-second await;
transport-level completion remains subject to the existing client's timeout/cancellation.
Cancellation is propagated, not silently retried or converted to no history.

The facade is admitted with **either** `milai.note.read` or `milai.memory.read`.
This is an OR entry-capability rule, not a grant of the other source. Each nested
dispatch rechecks the existing per-request admission and its own source scope.
Listing and calling use the same rule. The primary mapping remains `milai.memory.read`
with the alternate read capability declared in `TOOL_SCOPE_ALTERNATIVES`; callers
must use `AdmissionPolicy.allows_tool`, not infer authorization from that primary
mapping alone. No new JWT scope, identity derivation, tenant permission or Runtime
role is introduced. Note-only users cannot reach governed storage and vice versa.

Results remain grouped by source. Existing object authority, exact references,
versions and continuations are preserved; the facade does not rerank, promote Notes,
count overlapping records as independent corroboration, or advance a cursor past
results it did not present. A successful branch may survive another branch's failure.
Each source reports OK, DEGRADED, NOT_AUTHORIZED, UNAVAILABLE, TIMEOUT or ERROR.
Only two successful empty queries produce MISS; partial failure produces INCOMPLETE
when no results were obtained. `absence_confirmed=false` always: completing bounded
queries is neither search-space exhaustion nor proof that no historical record exists.
Working State is not part of this search and retains its explicit resume/read tool.

## Presentation and instructions

Keep the existing case-insensitive literal Note query contract. Render a 256-character
window near the literal match, with offsets into the original text, match visibility,
partial-match status and exact-version get references. Unicode case conversion must
not shift offsets. A collation/presentation mismatch is explicitly non-confirmed and
requires an exact read; it is not an excuse to change repository eligibility.
List without a query keeps the prefix. Recorded/observed timestamps are returned as
metadata, not interpreted as event time or silently applied as event-date filters.

Compose ordinary-catalog routing with external authentication guidance, rather than
overwriting it. Tool descriptions name their source coverage and describe focused
queries, bounded follow-up and qualified negative answers. Relative event dates are
the Host's semantic responsibility, using the question time, user timezone and source
content; Runtime does not infer meetings or enforce a new business schema.

## Validation and rollback

Require direct tests for long-tail/Unicode/literal snippets, OAuth instructions,
each read-scope combination, partial failure, concurrency and cancellation. Use
real PostgreSQL and HTTP MCP for two-subject isolation, new-client discovery and
post-restart discovery. These are engineering tests with synthetic data, not real
OAuth consent, native Agent selection, cross-language retrieval quality or net benefit.

No migration is required. Rollback removes the additive facade and returns to the
existing source tools; stored Notes, Evidence and Canonical history are unchanged.
Permission alternatives must be removed together with the facade if rolled back.
Retaining the instruction and snippet fixes is safe independently. Public packages
must be separately deployed before claiming the live endpoint has changed.

Schema remains 0.1.x EXPERIMENTAL / Implementation CANDIDATE / NO-GO FOR SCHEMA FREEZE.

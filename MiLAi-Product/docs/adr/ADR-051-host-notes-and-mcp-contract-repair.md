# ADR-051: Independent Host notes and accurate MCP contracts

Status: ACCEPTED FOR LOCAL IMPLEMENTATION, 2026-09-08, under the instruction to
execute MILA-V02-07. No public deployment or model execution is authorized.

Preserve the existing 13-tool catalog, Canonical procedures and Working State
semantics. First repair the actual public validation and exact-read defects.
Use adjacent regression tests; do not build a separate validation platform.

## Storage decision

Existing `HostCognitiveBinding` permits SESSION/TASK/PROJECT only. Migration 0050
enforces one active binding and scope-specific expiry; its repository exposes
current checkpoint reads and append writes, not independent Note browsing,
public historical reads or single-lineage deletion. Those contracts cannot
implement ordinary memory by placing all notes in one checkpoint payload.

Add the minimum independent Note head, immutable version and declared Evidence
reference tables in the same MiLA PostgreSQL database. Reuse Database session
context/RLS, operation ledger, operational audit and current eligibility checks.
Append migration 0056; never reinterpret existing checkpoint rows. Each Note has
a UUID lineage, an integer version and server-bound principal/private project.
Only the addressed head is locked for update/delete; unrelated notes do not
share a mutation lock. Content and its operation receipt commit atomically.

Initial content is exact UTF-8 text or Markdown, at most 65536 bytes. Notes do
not inherit checkpoint TTL: no automatic expiry is implemented, and responses
declare `expires_at=null`. No embeddings, extraction or summary models run.
Search reads authorized current rows lexically, with `search_index_status=DIRECT`.

Delete appends a tombstone and blocks all versions. It never revokes shared
Evidence, changes Canonical or removes audit history. Initial physical purge
is NOT_IMPLEMENTED and backup deletion is NOT_SCHEDULED; neither is reported
complete. Source eligibility applies to the version being read and every
replay; denied opaque content, snippets and content-derived metadata are withheld.
Include the three Note tables in the existing single-tenant quiescent backup
inventory. This preserves versions/tombstones in an archive; it does not implement
Note physical purge, a backup expiry schedule, or multi-tenant backup support.
New writes cannot reference already unreadable Evidence. File references require
a locator plus revision or content digest; they are Host declarations, not a
Runtime semantic endorsement or a claim to have checked external file access.

Downgrade must reject while Note rows/receipts exist; an empty extension can be
removed. Old binaries may ignore the new tables but cannot edit Note records.
Database migration and role grants require direct local PostgreSQL verification.

## Public interface decision

Retain `milai_memory_get` for Canonical. Add `milai_note_add/get/list/search/update/delete`,
`milai_note_operation_get`, and `milai_evidence_get/list`. Bare MCP writes require
operation_id; a Host SDK may generate and retain it before sending. A submitted
operation is identified by authenticated scope and operation_id, not current head.
Unknown transport outcomes are reconciled by that operation or identical replay.

Use explicit catalog version `ordinary-memory-v1`; the complete new catalog is
opt-in and preserves the old tools. Do not change the public deployment default.
New scope mapping:

| Tools | Scope |
| --- | --- |
| note_get/list/search/operation_get | milai.note.read |
| note_add/update | milai.note.write |
| note_delete | milai.note.delete |
| evidence_get/list | milai.evidence.read |

Prefix every table tool name with `milai_`. Existing scopes do not implicitly
grant these new scopes. Directory and dispatch share the same effective-scope
intersection. Delete requires current explicit intent, represented by a DELETE
accident guard as well as Host authorization; this literal is not authorization.

Freeze detailed executable input/output models alongside implementation rather
than maintaining a second manually edited schema. Bounds: tags <=32, each 1..128
characters; source refs <=1024; list/search limit 1..100 (default 20); get pages
1..8192 Unicode characters (default 8192) with explicit offset/next_offset and
whole-content digest. Search snippets are marked incomplete. Cursor must bind
principal/project, filters and snapshot position; every page rechecks eligibility.
Update replaces content; omitted metadata preserves it, explicit empty arrays
clear it. Every write response identifies object type HOST_NOTE, authority
HOST_WORKING, original committed version and a typed read reference.

Source-reference display is independently paged: default 8, maximum 32 per Note
get, with source_offset/next_source_offset, total_source_refs and a completeness
flag. All stored references remain subject to the eligibility guard on every read.
Browse/search return source counts and exact read references instead of copying
all provenance into every result. Evidence browsing reads only eligible metadata,
filters before LIMIT and binds its cursor to caller/project/filters. Its timestamp
boundary does not promise a retained MVCC snapshot across concurrent late commits.

## Validation and release

User's 48-call report remains REPORT_ONLY until original artifacts are indexed.
Reuse existing tests and add only direct checks for changed behavior. Real PG,
HTTP, restart and two-principal evidence remain necessary for those properties.
U5 remains unauthorized; engineering progress cannot complete the whole Goal.

Schema 0.1.x EXPERIMENTAL / Implementation CANDIDATE / NO-GO FOR SCHEMA FREEZE.

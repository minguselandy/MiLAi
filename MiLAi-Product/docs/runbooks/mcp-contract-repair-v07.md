# MCP contract repair — local implementation

These changes are local, not a public deployment. Existing Canonical and
Working State tools retain their meaning. The local ordinary Note implementation
is now selectable with `--catalog ordinary-memory-v1` on codex-full with the async
Runtime transport. This candidate catalog has 22 tools: the original 13, seven
Note tools, and Evidence get/list. Final delivery gates remain pending. The default stays legacy.

The codex-full capture schema now publishes source_type as an uppercase
identifier (`^[A-Z][A-Z0-9_]*$`, 1..64 characters), source_ref as 1..2048
characters, subject_id as a business identifier of 1..512 characters, and
observed_at as a date-time with timezone. The source type is not a fixed enum;
subject_id is neither an OAuth subject nor necessarily a UUID. Content is
preserved, including whitespace, Unicode, CRLF and code.

Optional source_context contains session_id, turn_id, turn_ordinal, round_id,
round_ordinal and optional previous_turn_id/next_turn_id. Ordinals are
nonnegative; neighbours must be distinct and cannot refer to the current turn.

Executable synthetic capture and CREATE templates are maintained in
`integrations/mcp/src/milai_mcp/input_contracts.py`. Use fresh operation IDs for
new intentions and replace the example supporting Evidence UUID with the actual
capture receipt. CREATE requires subject_id, predicate, claim_type, payload and
confidence; authority remains server-supplied. Non-CREATE needs a target and
expected Claim version. Business payload remains open JSON.

Invalid capture/proposal input returns MCP isError with INVALID_ARGUMENT,
field paths and safe expected constraints. Input content and backend exception
messages are not copied into those field errors. Review policy_version and
reason_code are audit labels, not a registry or automatically executed policy.

Exact Canonical reads use the Canonical Gate's address resolution. A completed
EXACT_STATE binding describes that addressed read; it is not a claim that the
Host's larger task has sufficient evidence or was understood correctly.

The new SDK `get_evidence_content(evidence_id, project_id=...)` intentionally
returns source content. It requires a paired Runtime supporting project-limited
GET; the project must come from the authenticated Host binding. Runtime rejects
foreign-project requests before reading source bytes. Revoked/unreadable
Evidence has content=null. Existing `get_evidence_metadata` still removes content.
`milai_evidence_list(source_type?, subject_id?, limit?, cursor?)` browses currently
readable Evidence metadata without a search query. Exact filters and authenticated
tenant/actor/project bind the signed cursor; each page reapplies current eligibility
before LIMIT. It does not load source bodies. Its timestamp boundary is not a retained
database transaction snapshot: concurrent late commits are not guaranteed to appear;
start a fresh browse when a complete new inventory is needed.
Capture, list and search return typed read references in the new catalog. Evidence
IDs address `milai_evidence_get`; a known Claim ID addresses `milai_memory_get`.
Canonical references label their read semantics CURRENT_CANONICAL and separately
record the returned Claim version; a version ID is never passed as a Claim ID.
Aggregate contexts without an exact object address do not invent one.
`milai_evidence_get(evidence_id, offset?, length?)` exposes bounded content pages in
the candidate catalog. New reads require `milai.evidence.read`; Note reads require
`milai.note.read`, add/update require `milai.note.write`, and delete requires
`milai.note.delete`. Old grants do not acquire these capabilities. Enabling these
scopes and deploying the candidate to the public service have not been performed.

Ordinary flow: note_add(content, operation_id) -> note_get(memory_id) or note_list /
note_search(query) -> note_update(memory_id, expected_version, content, operation_id).
Use note_operation_get(operation_id) to reconcile an uncertain write. Bare MCP
clients retain their operation IDs; the SDK does not silently retry Note mutations.
note_delete requires memory_id, expected_version, operation_id and DELETE confirmation.
Deletion blocks every version; physical purge is NOT_IMPLEMENTED and backup expiry
is NOT_SCHEDULED. Notes never create Claims or replace Working State.

Note get returns at most 8192 content characters plus a separate source-reference
page (default 8, maximum 32). Follow `next_offset` for content and
`next_source_offset` using `source_offset` for references; pin the returned `version`
when continuing. `content_complete` and `source_refs_complete` are independent.
List/search return snippets, source counts and exact Note read arguments rather than
repeating every source reference. All referenced Evidence still participates in the
eligibility check, including references outside the presented page. File revisions
are Host declarations, not a claim that Runtime has verified external files.

The existing local MCP → HTTP Runtime → PostgreSQL check now also verifies Evidence
browsing, filter/caller cursor binding, source-reference reconstruction, and revoked
source withholding on Note get/history/list/search/replay/operation lookup. These
engineering checks do not establish semantic quality or native Agent recovery.

New ordinary tools reuse their MCP argument models for safe validation errors,
returning INVALID_ARGUMENT and field constraints without echoing source text.
FILE source schemas explicitly require a non-null revision or content_digest.

Schema 0.1.x EXPERIMENTAL / Implementation CANDIDATE / NO-GO FOR SCHEMA FREEZE.

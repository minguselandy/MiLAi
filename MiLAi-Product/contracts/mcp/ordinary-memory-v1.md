# ordinary-memory-v1 executable contract index

Current increment: MCP 0.1.13 / client 0.1.3 / Runtime 0.1.4. The ordinary catalog
now has [22 tools](ordinary-memory-v1.repair-0.1.13.tools.json): namespace cleanup
submission is no longer registered or callable, while its scoped status query remains.
Legacy retains its 13-tool contract. Ordinary response advice is `suggested_next_step`
(no `mcp_guidance` alias): optional=true, authorization_granted=false, and every
suggested mutation requires_user_authorization=true. Working State's returned usage
contract is explicitly advisory, not authorization. Common rules belong in initialize
instructions; Proposal also has a short CREATE envelope fallback in its own description.
See [ADR-053](../../docs/adr/ADR-053-ordinary-mcp-advisory-and-admin-boundary.md).
Earlier versions and snapshots below are preserved as history, not the current count.

Current local candidate: MCP 0.1.11, client 0.1.3, Runtime 0.1.4; migration stays
0056_host_notes. Current in-process protocol snapshots are
[ordinary, 23 tools](ordinary-memory-v1.repair-0.1.11.tools.json) and
[legacy, 13 tools](legacy.repair-0.1.11.tools.json). The preceding actual signed
private HTTP snapshot is retained as
[ordinary-memory-v1.repair-0.1.10.tools.json](ordinary-memory-v1.repair-0.1.10.tools.json).
Both current Codex catalogs expand generated Proposal references, because the
current Codex endpoint uses legacy. Their names, dispatch permissions and parser
semantics are unchanged. These snapshots are not target Host conversion evidence.
The [nine synthetic Proposal envelopes](proposal-examples-0.1.10.json) exercise the
same generated input model and do not grant authorization to submit or review.
The prior search-0.1.9 snapshot is preserved as historical evidence.
The older `ordinary-memory-v1.tools.json` is retained as the MCP 0.1.7 baseline snapshot.
Neither is proof of public deployment. Tool names and per-source scope boundaries
are checked with signed test subjects. `scope_alternatives` records the unified
search entry's OR capability; each nested source still checks its own scope.

Input owners: MCP `input_contracts.py` and `ordinary_memory.py`; Runtime
`domain/host_note.py` and `domain/evidence.py`. No business State schema is imposed.
Output owners: Runtime `application/host_note.py`, `application/evidence.py`, MCP
`ordinary_memory.py`, `memory_search.py` and `evidence_context.py`.
The following result rules are normative:

| Result | Required meaning / fields |
| --- | --- |
| Note reference | object_type=HOST_NOTE, authority=HOST_WORKING, memory_id, version, status, direct_read_available, expires_at=null, read_tool, read_arguments |
| Note receipt | reference plus operation, operation_id, replayed, commit_status=COMMITTED, durable=true; content_digest only when eligible; search_index_status=DIRECT or NOT_VISIBLE |
| Note read ACTIVE | exact content page, SHA-256 digest of whole content, offset/next_offset/total_characters/content_complete, format, tags, observed_at (possibly null), recorded_at, source_refs/source_offset/next_source_offset/total_source_refs/source_refs_complete |
| Note read withheld | status=DELETED or SOURCE_UNAVAILABLE; content=null; no content-derived digest, tags, source metadata or body |
| Note list/search | items with Note references, snippet/snippet_only, original-text snippet_offset/snippet_end, match_in_snippet/match_complete, recorded_at/observed_at, source counts; next_cursor/snapshot/DIRECT/truncated; Note-only search_scope and absence_confirmed=false |
| Unified discovery | memory-search-v1; independent notes/governed source tool, query, status and unchanged result; retrieval_status=HIT/MISS/INCOMPLETE; coverage=PARTIAL or BOUNDED_QUERIES_COMPLETED; absence_confirmed=false; no Working State search, full inventory scan or semantic-completeness claim |
| Delete | logical=APPLIED, physical_deletion_supported=false, primary_storage=NOT_IMPLEMENTED, derived_cleanup=NOT_APPLICABLE, backup_expiry=NOT_SCHEDULED, scope=SINGLE_NOTE_ALL_VERSIONS, history_retained=YES |
| Evidence browse | metadata-only items with object_type=EVIDENCE, evidence_id, source_type, subject_id, observed_at/captured_at, read_tool/read_arguments; next_cursor/snapshot/truncated |
| Evidence read | object_type=EVIDENCE, evidence_id, status=READABLE or UNREADABLE; readable pages have content, content_digest, source_ref, observed_at, offset/next_offset, content_complete/total_characters; unreadable has no source content |
| Search read reference | Evidence IDs use milai_evidence_get; Claim IDs use milai_memory_get with CURRENT_CANONICAL semantics, returned version recorded separately; no invented address for aggregate-only material |
| Unknown Note write | MCP isError with NOTE_OUTCOME_UNKNOWN, original operation_id and milai_note_operation_get recovery; no implicit write retry or change of operation ID |
| Rejected input | MCP isError, stable code, field paths/type/expected where available; no raw input/backend parameters copied |
| Ordinary State/Note backend error | error_contract=ordinary-memory-errors-v1, code, retryable=false, recovery_action; State conflicts preserve scope and exact-object Runtime version only when supplied; Note conflicts require a fresh GET |
| Unknown State write | WORKING_STATE_OUTCOME_UNKNOWN; no invented operation lookup tool, no automatic SDK write retry, controlled replay retains exact ID/payload |
| Optional guidance | Existing next_tool/when remain; action suggestions are optional; governance/deletion suggestions require current user authorization and never prove it |

Notes: exact text/Markdown, 1..65536 UTF-8 bytes; 0..32 unique tags (1..128 chars),
0..1024 source refs; source FILE needs locator plus revision or digest. get content
pages 1..8192 characters; source pages 1..32 (default 8). list/search 1..100 items,
default 20. Cursors are signed, expire after one hour, bind caller/project/filters
and recheck current disclosure eligibility on every page. A timestamp boundary is
not a retained cross-request MVCC snapshot. All source dependencies are checked,
including refs outside the displayed page. Source relations are HOST_DECLARED.

Executable checks, from their owning package:

| Requirement | Existing selector / authoritative implementation |
| --- | --- |
| F01–F04, F07 / M01–M03 | MCP tests/test_input_contracts.py; Runtime domain and API evidence models; private HTTP slice includes actual Runtime note rejection and safe source error |
| F06 / M04 | Runtime tests/integration/test_retrieval_api.py::test_memory_state_view_is_dynamic_bitemporal_and_exact_cost_bounded |
| F05 / M05 | MCP tests/test_ordinary_memory_postgres.py and tests/test_agent_memory_profile.py |
| M06–M09, M11–M13 | Runtime tests/integration/test_host_notes.py + MCP tests/test_ordinary_memory_postgres.py |
| M10, M14–M16 | MCP tests/test_ordinary_memory_postgres.py: real HTTP cuts, persisted reconciliation, fresh native protocol client processes, Runtime/listener restart, concurrent requests and two signed subjects |
| Legacy catalog / input compatibility | MCP tests/test_aigcit_full.py, tests/test_aigcit_http.py, tests/test_codex_full_profile.py |
| Unified routing / OAuth / permissions / failures | MCP tests/test_memory_search.py; real PG/HTTP and new-process default discovery in tests/test_ordinary_memory_postgres.py |
| Match-centered presentation / original offsets / dates | Runtime tests/unit/test_note_search_presentation.py and tests/integration/test_host_notes.py |
| M17–M18 actual Agent use | U5 audit and authorized native Agent evidence required; protocol client checks do not establish model selection/reasoning |

Local PG checks require the owned database-role environment and
`MILAI_MCP_BASELINE_E2E=1`; they create/drop a unique synthetic database. No public
record IDs, OAuth tokens or model requests are needed. Skipped selectors are not
proof. Keep failed attempts and limitations in the Lab evidence index, not as
production exceptions or extra runtime modules.

Retrieval methods, limits and negative-answer handling are explained in
[the retrieval runbook](../../docs/runbooks/memory-retrieval.md); see
[ADR-052](../../docs/adr/ADR-052-bounded-cross-type-memory-discovery.md) for compatibility and rollback.

The current [calling contract and error compatibility](../../docs/runbooks/mcp-contract-repair-v08.md)
also explains scope-sensitive recovery and Proposal reference expansion in both Codex catalogs.
Legacy State text errors remain supported. Host rendering and actual Agent selection are
separate gates: a parsed schema is not proof of either.

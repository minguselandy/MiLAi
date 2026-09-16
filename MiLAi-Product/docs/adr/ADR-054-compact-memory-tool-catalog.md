# ADR-054: Compact content-first MCP catalog

Status: ACCEPTED FOR LOCAL IMPLEMENTATION, 2026-09-08.

The user requested fewer tools and one interface for Note/Evidence operations. Introduce
the opt-in `compact-memory-v1` catalog with eight public tools: search, read, list, save,
delete, status, Working State get and update. Keep `legacy` (13) and
`ordinary-memory-v1` (22) selectable with their existing names and meanings. Do not add
the compact aliases alongside the 22-tool directory. CLI defaults and public deployment
are unchanged by this implementation.

Reuse MiLAi's current handlers, SDK transport, authenticated request context and Runtime.
Register only eight tools with the public MCP manager. A private SDK handler manager
contains only the required Note/Evidence/exact-Claim/search operations; no Proposal,
review or namespace cleanup handler is reachable from the compact facade. A cached
legacy tool name must fail at public dispatch, even with all grants.

Directory admission may accept either type's existing scope, but the selected private
operation independently rechecks live admission and its exact original scope. Note write
does not authorize Evidence capture; Note delete does not authorize Evidence revocation;
Evidence read does not authorize canonical reads. No new OAuth scopes, identity derivation,
credentials or permission broadening. Keep existing Runtime operation-ID namespacing so
an identical authorized request can be reconciled across catalogs, rather than duplicated.

`memory_save(content, operation_id)` creates a Note by default. Typed options distinguish
ADD_NOTE, UPDATE_NOTE (requires CAS version), and CAPTURE_EVIDENCE (requires original
source envelope and CAPTURE confirmation). Typed read/list/delete/status targets publish
complete generated schemas. Keep reads, writes and destructive operations in different
tools so annotations remain honest. Do not introduce an opaque `action + arbitrary object`
dispatcher. Common safety/routing text lives in server instructions, not every tool.

Unification is an interface decision, not a merger of storage or authority. Evidence
remains immutable, Note update remains versioned, Note deletion remains logical with
history retained and physical purge unsupported. Evidence revocation retains synchronous
eligibility blocking and asynchronous purge/backup stages. Note-to-Evidence promotion,
automatic Proposal/review and an independent Evidence capture-status API are not added.

Search keeps the existing bounded concurrent Note/governed branches and per-source failure
semantics. It does not become an exhaustive raw-Evidence scan or change lexical ranking.
Typed references point to the compact read tool; Note pagination and governed continuation
remain usable. Rewrite only known server envelopes, never user content, Claim payloads or
declared source references. Fix the search-only leftover `mcp_guidance` field to follow
ADR-053's optional `suggested_next_step` contract.

Acceptance: signed local HTTP schemas and dispatch checks, full per-action scope matrix,
old-name denial, defaults/CAS/unknown commit errors, reference read-through and source status;
real isolated PostgreSQL save → new client search/read → edit → delete/revoke → blocked read,
cross-user denial and cross-catalog idempotency; existing catalog regressions and package
lint/type/test/build gates. No paid/local model experiment is required for this adapter
change; protocol tests do not certify a model's selection quality or public rollout.

No database migration or Runtime behavior change. Rollback selects the prior catalog or
pinned package without changing data. Public activation needs a separately authorized
deployment and client directory refresh; rollback to a larger catalog restores its broader
tool visibility, not additional OAuth grants.

Schema 0.1.x EXPERIMENTAL / Implementation CANDIDATE / NO-GO FOR SCHEMA FREEZE.

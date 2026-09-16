# DG-13 MCP vNext compatibility contract v0.1

Status: `M0 FROZEN / M1 QUERY-FIRST + M2 EXACT-STATE + M3 ONLINE REUSE + M4 BOUNDED SEARCH + M5 GOVERNED REVIEW + M6 OPTIONAL TASK NARROWING REGISTERED`  
Runtime / Schema: `0.1.x CANDIDATE / 0.1.x EXPERIMENTAL / NO-GO FOR FREEZE`

This contract freezes semantic ownership while the public MCP surface migrates. It does not register
TARGET tools by itself. A compatibility alias must call the same application service, authorization
policy, Canonical Gate and internal domain result as its TARGET owner.

| CURRENT surface | TARGET semantic owner | Compatibility decision |
| --- | --- | --- |
| `milai_recall` | `milai_memory_resolve` | Keep the CURRENT wire schema; adapt from one resolver result. |
| `milai_claim_get` | `milai_memory_get` | Keep Claim-ID exact read; TARGET additionally accepts StateKey. |
| `milai_status` | `milai_memory_capabilities` | One capability document; no second capability truth. |
| `milai_trace_get` + `milai_evidence_metadata_get` | `milai_memory_explain` | Compose readable trace/provenance; authorize each referenced object independently. |
| `milai_evidence_capture` | same name | Preserve Evidence-only semantics; capture never creates a Claim. |
| `milai_proposal_create` | `milai_memory_propose` | Preserve pending Proposal semantics; no direct canonical commit. |
| Runtime `POST /v1/proposals/{id}/review` | `milai_memory_review` | Registered only on the dedicated M5 reviewer profile. |
| `milai_evidence_revoke` | `milai_memory_delete` | Keep the old command schema. TARGET requires an explicit mode and confirmation. |
| `milai_deletion_status_get` | `memory://deletion-requests/{id}` | Remains read-only and separately authorized from delete commands. |
| no CURRENT tool | `milai_memory_export` | Deferred; no placeholder is advertised. |
| hidden `milai_prepare_context` | OpenWorker extension over `milai_memory_resolve` | Never a public Core prerequisite and never a second query/Gate implementation. |

## Read outcome mapping

The CURRENT `milai_recall` output remains `OK | DEGRADED | ABSTAINED` for the compatibility window.
The TARGET adapter owns one explicit mapping:

| Runtime fact | CURRENT status | TARGET status |
| --- | --- | --- |
| one or more canonical-gated items, no live conflict | `OK` | `HIT` |
| readable items plus typed degradation | `DEGRADED` | `PARTIAL` |
| live OpenIssue changes certainty | `OK` or `DEGRADED`, with `open_issue_ids` retained | `CONTESTED` |
| no applicable item in readable scope | `ABSTAINED` + `NO_CANDIDATE` | `ABSENT` |
| evidence/authority/consistency insufficient | `ABSTAINED` + typed reason | `ABSTAINED` |
| principal/capability/scope rejected | existing MCP/API error | `DENIED` |
| Runtime or canonical store unavailable | existing MCP/API error or 503 | `UNAVAILABLE` |

`ABSENT`, `ABSTAINED`, `DENIED`, `CONTESTED` and `UNAVAILABLE` must never collapse into an empty
successful result or Host `Need.NONE`.

## Trace compatibility

`RetrievalTrace` remains the only durable retrieval trace. Migration 0029 appends payload-free
execution facts and stage metrics; migration 0030 adds the authoritative Gate's explicit historical
mode without creating a StateView table. Migration 0031 adds a controlled task-free capsule creation
function on the existing ContextCapsule/ContextPointer objects; it creates no receipt or StateView
table. `AccessTrace` is a read-only view that links:

```text
Host attempt ID
→ MCP handler / UDS or broker span
→ Runtime request ID
→ RetrievalTrace ID / canonical position
```

No query plaintext, Evidence body, prompt, token or credential is stored in these trace fields.
Legacy RetrievalTrace rows are backfilled with `route_trace_complete=false` and the explicit gap
`LEGACY_STAGE_DETAIL_UNAVAILABLE`; the migration does not invent historical stage observations.

## Removal rule

No CURRENT tool is removed until its real clients migrate and a separate compatibility decision is
accepted. Additive TARGET tools must not change CURRENT input schemas, status values or error
behavior during that window.

M1 registers `milai_memory_resolve`; M2 additionally registers `milai_memory_get` on detail-capable
reader profiles. `milai_memory_get` accepts exactly one ClaimID or canonical
`{subject,predicate,claim_type}` StateKey, and optional `valid_at`/`known_at`; scope, authority,
principal and policy ceiling remain deployment-owned. Known-address hints on the configurable
`milai_memory_resolve` contract route through the same `StateAddressService` and dynamic
`MemoryStateViewService`.

`milai_claim_get` remains registered during the compatibility window and does not own a second
implementation. `reader-lite` remains query-only and intentionally does not advertise
`milai_memory_get`; `reader-detail`, the legacy `reader` alias, submitter and operator profiles may
read the exact target. The real generic client and OpenWorker conformance paths continue to call
the same resolve contract. M3 adds only the optional opaque `previous_context_id` locator to
`milai_memory_resolve`; it does not add Host-owned Memory content. Runtime reauthorizes the locator,
validates exact request coverage, dependencies and currentness online, and either returns a governed
reuse view or runs the primary EXACT/SEARCH plan in the same call. OpenWorker still performs one
resolve per same-session turn and may retain only that opaque locator. The hidden
`milai_prepare_context` extension remains only a compatibility path and is not a prerequisite for
query-first, exact retrieval or online reuse.

M4 adds optional `entities` and `memory_types` narrowing hints only to the configurable
detail-profile `milai_memory_resolve` schema. They cannot broaden deployment-owned scope,
principal, authority, consistency or limits; `reader-lite` remains query + optional opaque locator.
The additive response `access_plan` and `search_trace` fields expose Runtime-owned candidate,
deadline, context and conditional-reranker bounds. Compatibility `milai_recall` still adapts the
same resolver execution and keeps its existing status/schema semantics.

M5 registers a new opt-in `reviewer` profile without changing any existing profile. Its
`milai_proposals_list` and `milai_proposal_get` tools expose the canonical pending-review inbox;
`milai_memory_review` maps to the existing Runtime review procedure and requires a matching
decision/confirmation pair plus a stable operation ID. Reviewer and submitter credentials map to
different Runtime actors and mutually exclusive write/review capabilities. No MCP tool directly
writes a ClaimVersion or resolves an OpenIssue.

M6 adds `task_context` only to configurable detail-profile `milai_memory_resolve`. It contains no
Task/session identity and no scope, authority, consistency, credential, write or review controls.
Runtime intersects project/entity/type hints with deployment-bound constraints before the existing
planner and Canonical Gate; a disjoint hint is invalid instead of becoming an empty/unbounded
partition. `action_risk` is trace-only and non-authoritative. `reader-lite` remains unchanged, and
omitting TaskContext on any detail profile preserves the M1–M4 query-first route.

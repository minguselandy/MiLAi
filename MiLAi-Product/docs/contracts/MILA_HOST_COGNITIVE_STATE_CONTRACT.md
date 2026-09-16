# MiLAi Host Cognitive State contract

> Contract: `host-cognitive-state-v1`  
> Status: `IMPLEMENTED LOCAL CANDIDATE`  
> Authority: `HOST_WORKING`  
> Schema: `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`

## 1. Boundary

MiLA persists and versions Host-provided JSON. Codex owns every semantic interpretation in that
JSON. The object is not Evidence, Canonical State, Context, an authority source, a completeness
claim, or `RetrievalContinuationState`.

No operation in this contract may create/update a ClaimVersion, move a ClaimHead, submit/review a
Proposal, change an OpenIssue, or assert `FRONTIER_EXHAUSTED`.

## 2. Identity and persistence

| Field | Meaning |
| --- | --- |
| `state_id` | stable lineage handle |
| `state_version_id` | unique immutable semantic version |
| `version` | contiguous integer, starting at 1 |
| predecessor | previous `state_version_id`, null only for version 1 |
| `state_digest` | SHA-256 over authority, schema, binding and canonical payload JSON |
| `authority` | literal `HOST_WORKING` |
| `schema_name` | literal `codex-cognitive-state-v1` |

The head row is the only mutable locator. History rows and Evidence-reference rows reject UPDATE
and DELETE, including owner attempts.

## 3. Server-owned binding

Runtime receives an internal binding containing `principal_binding_digest`, `project_id`,
`scope_type`, and `scope_ref`. The MCP schema exposes only `scope_type` as `scope`; all other fields
are injected from the authenticated 7337 process.

```text
PROJECT ref = the exactly-one bound project
TASK ref    = MILAI_CODEX_TASK_REF or deterministic endpoint default
SESSION ref = MILAI_CODEX_SESSION_REF or deterministic endpoint default
```

State rows are RLS-isolated by tenant and Runtime actor and filtered by the complete binding.

## 4. Payload

The payload is a JSON object, full-replaced on each version, with a maximum canonical wire size of
65,536 bytes. Recommended fields are:

```yaml
task:
  active_goal:
  current_question:
  relation_to_previous:
  phase:
  completion_conditions: []
requirements: []
known: []
missing: []
hypotheses: []
decisions: []
failed_approaches: []
open_issues: []
blockers: []
memory_needs: []
memory_intentions: []
next_actions: []
context_preferences: {}
```

Runtime does not require or interpret this shape. Unknown JSON fields are retained.

## 5. Exact Evidence pointers

At any nesting depth, `evidence_id` is reserved for one UUID string and `evidence_refs` for an array
of UUID strings. At most 256 distinct references are accepted. Every reference must exist in the
same tenant, be currently readable and unrevoked, and include the bound project in its permission
snapshot. SESSION state additionally requires the exact structured source session.

Persisted relation is `HOST_ASSERTED`. Runtime does not claim entailment. If a reference later
becomes revoked or unreadable, `get` returns:

```json
{
  "code": "EVIDENCE_REFERENCE_STALE_OR_UNREADABLE",
  "evidence_id": "..."
}
```

Under [ADR-041](../adr/ADR-041-working-state-disclosure-on-stale-references.md), any such warning
withholds the entire opaque payload (`payload={}`, `payload_withheld=true`) on GET and update
receipts, including idempotent replay. Eligible active versions return their original payload.
Version identity and operation success remain independent of current content disclosure.
History is not silently rewritten. Undeclared dependencies and independent file copies are not
automatically tracked by this contract.

## 6. MCP operations

### `milai_working_state_get`

Input:

```json
{"scope": "TASK"}
```

`scope` defaults to `TASK`. Result status is `ABSENT`, `ACTIVE`, `EXPIRED`, `ARCHIVED`, or
`DELETED`. ABSENT has version 0 and an empty payload. Expired/non-active results never expose their
payload.

This read automatically emits a safe audit event. That audit is an allowed observability side
effect, not a working-state or canonical mutation.

### `milai_working_state_update`

Create:

```json
{
  "operation_id": "hc-task-20260904-create",
  "scope": "TASK",
  "state_id": null,
  "expected_version": 0,
  "payload": {"task": {"active_goal": "..."}}
}
```

Update:

```json
{
  "operation_id": "hc-task-20260904-v2",
  "scope": "TASK",
  "state_id": "<stable UUID>",
  "expected_version": 1,
  "payload": {"task": {"active_goal": "..."}, "next_actions": []}
}
```

Create requires `(state_id=null, expected_version=0)`. Update requires a state UUID and a positive
expected version. No confirmation literal is required because this is fallible Host working state,
not Canonical/Proposal/Revocation mutation. `operation_id` remains mandatory for retry safety.

The `codex-full` MCP entrypoint uses one lifespan-owned `AsyncMilaiClient` for Working State
GET/UPDATE. Independent requests may overlap; the serving event loop owns creation and closure
of its pooled HTTP transport. Each request still derives its principal/scope binding before I/O.
The Runtime decides CAS and idempotency, with no client-side blind rebase or overwrite. Cancellation
of an in-flight update is audited as UNKNOWN; cancelling locally does not prove it did not commit.
The tool catalog, payload, authority and response semantics are unchanged. The generic
`milai-mcp --working-state-transport sync` option retains the serialized compatibility path;
the fixed Codex entrypoint uses async with zero automatic retries. Embedded callers can supply
`working_state_client_factory` to `build_server`; without it, their supplied synchronous client
continues to be used. This does not make the other MCP tools asynchronous or guarantee a latency SLO.

## 7. Typed failures

| Code | HTTP | Meaning |
| --- | ---: | --- |
| `STALE_WORKING_STATE` | 409 | expected version is not current; details include current version |
| `OPERATION_CONFLICT` | 409 | operation ID reused with different request semantics |
| `EVIDENCE_REFERENCE_INVALID` | 409 | missing, revoked, unreadable or out-of-scope pointer |
| `HOST_WORKING_STATE_SCOPE_DENIED` | 403 | lineage does not match complete binding |
| `HOST_WORKING_STATE_NOT_FOUND` | 404 | visible lineage is absent |
| `HOST_WORKING_STATE_EXPIRED` | 409 | update attempted on an expired/non-active lineage |

## 8. TTL and audit

TTL is Runtime-owned and refreshed on successful update:

```text
SESSION  24 hours
TASK     30 days
PROJECT  365 days
```

Automatic audit is enabled by default. Access and append events contain state/version identity,
scope type, scope-ref digest, state digest, and reference count. They contain no payload text.

## 9. Acceptance gates

```text
same binding roundtrip                         PASS
append-only version 1 -> 2                    PASS
same operation replay                         PASS
different-payload operation conflict          PASS
stale version                                 typed 409
cross project                                 denied
cross tenant / actor                          RLS hidden
revoked Evidence pointer on new write         rejected
later-revoked pointer on get/replay            warning + whole payload withheld (ADR-041)
audit payload disclosure                      0
direct Canonical write                        0
recall-side working-state mutation             0
working-state/continuation-state conflation    0
```

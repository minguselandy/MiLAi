# MiLAi Host Hooks

`milai-hook` is a trusted Host-side adapter. It is not a model-visible MCP tool.

## Raw AgentEvent capture

Set Runtime identity and scope in the Host process, then explicitly enable event capture:

```bash
export MILAI_BASE_URL=http://127.0.0.1:18080
export MILAI_AGENT_TOKEN="$MILAI_AGENT_SUBMITTER_TOKEN"
export MILAI_AGENT_SCOPE_JSON='{"project_ids":["my-project"]}'
export MILAI_HOST_EVENT_CAPTURE=ON

printf '%s' '{
  "schema_version":"host-agent-event-v1",
  "event_id":"codex-session-7-turn-3",
  "event_type":"USER_MESSAGE",
  "session_id":"codex-session-7",
  "source_id":"codex:session-7:turn-3",
  "subject_id":"user-123",
  "observed_at":"2026-09-03T10:00:00+08:00",
  "content":"Keep the migration reversible.",
  "turn_id":"turn-3",
  "turn_ordinal":3
}' | milai-hook AgentEvent
```

The adapter derives speaker and Evidence source type from `event_type`, derives a stable idempotency
identity from `source_id + event_id`, and preserves session/turn identity in `source_context`. The result is Raw
Evidence only. It never creates a Proposal, Claim, OpenIssue, or other Canonical mutation.

The wire contract is
[`host-agent-event-v1.schema.json`](../../contracts/agent/v1/host-agent-event-v1.schema.json).

## Optional sparse reconciliation journal

The trusted Host may additionally index low-volume dialogue and session observations in the
SHADOW Host execution Event journal:

```bash
export MILAI_HOST_EVENT_JOURNAL=SHADOW
export MILAI_HOST_PRINCIPAL_BINDING_DIGEST=<64-lowercase-hex-host-binding>
export MILAI_HOST_PROJECT_ID=my-project
export MILAI_HOST_TASK_REF=my-stable-task
```

`MILAI_HOST_PROJECT_ID` must also be present in `MILAI_AGENT_SCOPE_JSON`. These bindings come from
the Host environment, never from the AgentEvent JSON or an MCP/model argument.

For `USER_MESSAGE` and `ASSISTANT_MESSAGE`, the journal stores only:

```text
DIALOGUE / MESSAGE
exact Evidence ID
role
observed_at
```

The message body remains in Evidence and is not copied into the Event payload. `SESSION_MARKER`
becomes `LIFECYCLE / SESSION_BOUNDARY`; it is only a boundary observation and does not mutate
Working State. High-volume `TOOL_RESULT` and `ARTIFACT_CHANGE` inputs remain Evidence-only and
return `NOT_JOURNALED_REQUIRES_AGGREGATION` until a bounded Host-side aggregation adapter exists.

This mode does not create Claims, update Working State, trigger reconciliation, or add an MCP tool.
Static SHADOW configuration is validated before Evidence capture. If Evidence succeeds but the
journal request fails dynamically, the command returns
`PARTIAL_EVIDENCE_CAPTURED_JOURNAL_PENDING_RETRY` with the committed Evidence receipt and a stable
retry identity; repeating the same AgentEvent safely replays both operations.

## StateDelta validation and merge

`milai_hooks.state_reconciliation.validate_and_merge_state_delta` is a pure Host-side primitive.
It accepts the prior full Working State payload, the exact base State identity/version, and the set
of Event IDs in the frozen input window. It does not call a model or write MiLA.

```json
{
  "base_state_id": "state-id",
  "base_version": 3,
  "no_material_change": false,
  "changes": [
    {
      "field": "next_actions",
      "op": "REPLACE",
      "value": ["Run the focused regression"],
      "reason_event_ids": ["event-id"]
    }
  ]
}
```

A missing semantic field means KEEP. `REPLACE` carries the direct JSON replacement value, not a
JSON-encoded string. `CLEAR` omits/removes that field and may carry no value (or `null`). Every
change must cite an exact Event ID from the supplied window; this proves reference validity only,
not semantic grounding. Authority, binding, State identity, version, basis, and arbitrary JSON
Patch operations are not writable through this primitive.

## Explicit Working State reconciliation

`milai-hook ReconcileState` is a trusted Host command, not a model-visible MCP tool. The Host first
reads the current TASK State and bounded Event window, gives those inputs to Codex to produce a
StateDelta, and then invokes this command with the exact base and Event watermark Codex saw:

```bash
export MILAI_BASE_URL=http://127.0.0.1:18080
export MILAI_AGENT_TOKEN="$MILAI_AGENT_SUBMITTER_TOKEN"
export MILAI_AGENT_SCOPE_JSON='{"project_ids":["my-project"]}'
export MILAI_HOST_PRINCIPAL_BINDING_DIGEST=<64-lowercase-hex-host-binding>
export MILAI_HOST_PROJECT_ID=my-project
export MILAI_HOST_TASK_REF=my-stable-task

printf '%s' '{
  "operation_id":"checkpoint-task-7-v3",
  "after_position":0,
  "expected_event_high_watermark":42,
  "event_limit":100,
  "delta":{
    "base_state_id":"current-state-id",
    "base_version":3,
    "no_material_change":false,
    "changes":[{
      "field":"next_actions",
      "op":"REPLACE",
      "value":["Run the focused regression"],
      "reason_event_ids":["event-id-from-window"]
    }]
  }
}' | milai-hook ReconcileState
```

Bindings always come from the Host environment and the project must be in
`MILAI_AGENT_SCOPE_JSON`. The command reads the current TASK State again, reads the Event window,
requires the window to be complete, checks that its high watermark still equals
`expected_event_high_watermark`, validates and merges the Delta, and performs one exact CAS update.
`no_material_change=true` creates no State version. Events with stale/revoked Evidence warnings are
not eligible Delta references. A stale State head, changed Event watermark, incomplete window, or
invalid Delta returns a structured `code/problem/fix` error and does not report success.

The result contains a non-persisted `basis_candidate`. C4 deliberately does not add Basis storage,
automatic dirty detection, session-end checkpointing, or a hidden model call. The stable
`operation_id` protects the Runtime mutation request and its transport retries; after a completed
command, a later reconciliation must be prepared against the new State head. Before sending it to
Runtime, the Host namespaces the public operation identity by principal, project, task, and contract
version, so independent tasks may safely use the same caller-local ID.

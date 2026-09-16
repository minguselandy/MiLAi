# DG-13U U1 shared interface freeze

Status: `FROZEN FOR U1 IMPLEMENTATION`  
Scope: local, reader-lite, `STRICT_CURRENT`, MCP-only memory transport  
Execution override: `docs/contracts/DG13U-U1-user-direct-execution-override-20260825.md`

This document is the cross-lane implementation boundary for U1. It narrows ADR-024 to the accepted
Host-controlled MCP slice and does not modify the frozen architecture.

## Access outcome

The Python client owns the single Host-facing outcome definition:

```text
AccessOutcome
  status:
    NO_MEMORY_NEEDED
    CONTEXT_READY_CURRENT
    MEMORY_REQUIRED_BUT_UNAVAILABLE
    MEMORY_INSUFFICIENT
    GOVERNANCE_BLOCKED
  execution_action: CONTINUE | RETRY | ASK_USER | ABSTAIN
  provider_execution: ALLOWED | PROHIBITED
  terminal_stage: NONE | CACHE | EXACT | GATE | SUFFICIENCY | TRANSPORT
  context_digest: sha256 | null
  canonical_position: non-negative integer | null
  reason_code: non-empty string | null
  trace_id: non-empty string
```

The exact allowed matrix is:

| status | execution_action | provider_execution |
| --- | --- | --- |
| `NO_MEMORY_NEEDED` | `CONTINUE` | `ALLOWED` |
| `CONTEXT_READY_CURRENT` | `CONTINUE` | `ALLOWED` |
| `MEMORY_REQUIRED_BUT_UNAVAILABLE` | `RETRY` | `PROHIBITED` |
| `MEMORY_INSUFFICIENT` | `ASK_USER` | `PROHIBITED` |
| `GOVERNANCE_BLOCKED` | `ABSTAIN` | `PROHIBITED` |

`TaskPreparedContext.outcome` is authoritative. Compatibility status/reason properties, if retained,
must be derived and must not create a second truth source. `context_digest` is SHA-256 of the exact
rendered Context injected into the provider request, not a Runtime capsule content hash. The Host has
one provider barrier: execute only when `provider_execution == ALLOWED`.

## Runtime CACHE to EXACT behavior

The Runtime retains its existing current-state envelope and execution trace contracts. A requested
`CACHE` route performs at most one cache validation. A miss, coverage miss, stale dependency, or
head/issue revision change falls through inside the same Runtime prepare request to exactly one L0
`EXACT` primary attempt. The logical trace records:

```text
requested_route = CACHE
planned_route = CACHE
attempted_routes = [CACHE, L0]
terminal_route = L0
fallback_reason = <typed cache miss reason>
next_route_recommended = null
```

The Host issues one logical hidden MCP call, the broker issues one MCP tool call, and MCP issues one
Runtime prepare call. The deadline is shared and never reset. Cache miss cannot become a terminal
lease miss while exact is available, cannot require another user Turn, and cannot perform duplicate
retrieval.

Current-state mapping is fixed:

| Runtime result | Access outcome |
| --- | --- |
| current `HIT` | `CONTEXT_READY_CURRENT` |
| `MISS` or `AMBIGUOUS` | `MEMORY_INSUFFICIENT` |
| governed `BLOCKED` | `GOVERNANCE_BLOCKED` |
| canonical unavailable | `MEMORY_REQUIRED_BUT_UNAVAILABLE` |

## Exact aliases

The exact three-family list and order are those in
`contracts/agent/v1/dg13u-u1-candidate-fixture.json` at SHA-256
`47175b17cdc8444955d28cf3ec2f6d96964faf2099decf34bd317cf7729bb555`.
Alias normalization is Unicode NFKC, casefold, and whitespace normalization. Exact aliases are
resolved before any broader Need rule. A normalized alias owned by more than one live StateKey is
`STATE_KEY_ALIAS_AMBIGUOUS`; lexical tie-breaking, Need `NONE`, search, embeddings, reranking, and
auxiliary models are prohibited.

## Task metadata and ingress

The OpenWorker plugin emits exactly the three headers frozen in
`openworker-task-metadata-headers.md`. The Host validates in this order:

```text
constant-time ingress Bearer authentication
→ exact single-value metadata tuple
→ bounded JSON body parse
→ typed provider request parse
→ hidden MCP when required
→ provider barrier
→ at most one local vLLM call
```

The Host derives same-process task relation/generation from
`(host_instance, task_session, task_operation)`. Body content and model-visible text cannot select
task identity, scope, profile, authority, Need, route, or outcome. Adapter restart discards registry,
slot, and pending operation state.

`OPENWORKER_URL` points directly to the run-owned Host `/v1` origin on a dedicated Docker bridge.
The historical gateway is excluded. The Worker receives only its ingress token and reader-lite UDS
mount; it receives no MiLA token, Runtime URL, DSN, secret directory, Docker socket, direct vLLM
capability, or write/review/revoke capability.

## Provider request contract

The only accepted top-level fields are:

```text
model, messages, stream, stream_options, tools, tool_choice,
temperature, top_p, max_tokens, seed, response_format
```

The exact accepted model is `Qwen3.6-35B-A3B-FP8`; `AUTO` and unknown models are rejected. Fields are
preserved byte-semantically after only the Context message insertion. System/user/assistant/tool
roles, synchronous tool call/result IDs, tools, and tool choice are retained. Other top-level fields
are rejected before provider I/O as `PROVIDER_REQUEST_UNSUPPORTED`.

For `stream=true`, `stream_options` must be exactly `{ "include_usage": true }` and upstream SSE is
streamed without buffered reconstruction. For `stream=false`, `stream_options` must be absent and the
Host returns one JSON completion. Provider calls are never automatically retried.

## Accounting and terminal invariants

```text
NONE:                   hidden MCP = 0, provider = 1
EXACT success:          hidden MCP <= 1, provider = 1
CACHE miss then EXACT:  one composite MCP call, provider = 1
memory unavailable:     hidden MCP <= 1, provider = 0
provider failure:       provider <= 1, no automatic retry
visible memory tool:    0 for every prefetch case
auxiliary model/vector/embedding/reranker/reconstruct calls: 0
```

AccessTrace, MCP receipt, Runtime trace, provider ledger, native request ID/usage/finish reason, and
cleanup receipt join on one run/case/turn access identity. Durable artifacts contain hashes rather
than raw session IDs, prompts, content, or credentials.

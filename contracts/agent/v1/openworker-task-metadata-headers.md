# OpenWorker task metadata headers v1

Status: `U1 CANDIDATE / OWNER ACCEPTANCE REQUIRED`  
Transport: OpenWorker provider request to Host adapter only  
Visibility: HTTP headers; never model-visible content

This is the narrow wire design for DG-13U decision 9. It uses OpenCode's existing `chat.headers`
plugin hook, whose input contains the real `sessionID` and current user-message identity. It adds no
new memory transport and does not expose a MiLA token or Runtime address to OpenWorker.

## Provider-network topology

For the local U1 slice, `OPENWORKER_URL` points directly at the run-owned Host adapter `/v1`
endpoint over the explicit OpenWorker-to-Host provider network required by the DG-13U goal. The
Host remains the only component that owns the vLLM capability and the hidden MCP capability.
The Host binds only to the run-owned Docker bridge gateway and a random port. `OPENWORKER_KEY`
contains one run-random ingress Bearer token; the Host validates it in constant time before reading
task metadata or the request body. This token authenticates only the local provider ingress and is
not a MiLA memory token or upstream provider capability.

The historical `openworker-gateway-api` is not in this path. Exact inspection of image
`sha256:535bb8b7e3b735cc24b04950449f2a70c9905273eafa7d1b322526ecdc5d3860` showed that its
`/v1/chat/completions` route parses only the body and constructs fresh upstream headers, so all
three `X-MiLAi-*` headers are deterministically dropped. The exact image and four source/compiled
file hashes are recorded in `contracts/agent/v1/dg13u-gateway-header-inspection.md`. Broad header
forwarding, silently moving the metadata into the body, or claiming unchanged-gateway compatibility
are prohibited. Gateway support is a separate future topology and would require an exact
three-header allowlist plus its own acceptance and evidence.

## Native producer fields

The OpenWorker plugin emits exactly:

| Header | Source | Meaning |
| --- | --- | --- |
| `X-MiLAi-Host-Instance` | one opaque UUID created at plugin process setup | distinguishes OpenWorker process lifetimes |
| `X-MiLAi-Task-Session` | `chat.headers.input.sessionID` | real OpenCode session identity |
| `X-MiLAi-Task-Operation` | current `UserMessage.id` | synchronous provider-operation identity |

The plugin does not emit tenant, scope, profile, authority, relation, generation, route, Need, or
memory status. Those values are not owned by model-visible content:

- reader-lite scope/profile/authority come only from the Host adapter's mounted capability and
  broker policy;
- the Host maps `(host_instance, task_session)` to one same-process task identity;
- a never-seen pair is `TASK_START`; a repeated pair is `CONTINUE`;
- a changed host instance invalidates retained task state and cannot reuse the old slot;
- repeated operations with the same `(host_instance, task_session, task_operation)` are the same
  synchronous operation, not a new generation;
- asynchronous or delayed result rebinding remains unsupported in U1.

## Host validation

After ingress authentication, the HTTP boundary parses these headers once before the request body is
converted into product typed values. Each header must occur exactly once. Values must be non-empty
ASCII, at most 256 bytes, and contain only UUID/identifier-safe characters. All three headers are
required together in `memory_mode=prefetch`; duplicate, conflicting, partial, malformed, or missing
metadata yields `TASK_METADATA_INVALID` before MCP or provider I/O.

The Host never accepts body fields, prompt text, tool arguments, model output, `user`, or a static
adapter CLI value as a competing task identity. Compatibility modes outside DG-13U U1 may retain
their existing behavior but cannot satisfy the U1 gate. The Worker can observe its own ingress token,
so the trust claim is bounded to this run-owned integration and network, not hostile in-container
code. Even an authenticated Worker cannot select scope, profile, authority, Need, relation,
generation, or memory status.

## Trace binding

Artifacts store only hashes of the three native values. The joined access identity remains:

```text
access_id = <run_id>:<case_id>:<turn_id>
```

`join-reconciliation.json` binds the hashed native tuple and the Host-derived task identity to that
`access_id`. Raw session/operation identifiers are not written to durable artifacts.

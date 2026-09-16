# OpenWorker MiLAi MCP UDS capability contract v1

Status: `0.1 CANDIDATE / LOCAL SYNTHETIC ONLY`  
Transport: local stdio bytes over one Linux Unix stream socket  
Data boundary: synthetic or de-identified only  
Remote MCP: prohibited

This contract specializes ADR-020/021 for an OpenWorker whose Agent can run as root and use bash.
The Worker is not a MiLAi secret host. It receives exactly one filesystem capability: a read-only
bind mount of one profile-specific Unix socket.

## Trust and process boundary

```text
OpenCode local MCP child
  -> /usr/local/bin/milai-mcp-relay /run/milai-mcp/reader-lite.sock
  -> read-only single-file bind mount
  -> trusted host broker for reader-lite

OpenWorker Host query-first adapter
  -> the same profile-scoped host broker socket

trusted host broker for reader-lite
  -> exact milai-mcp --profile reader-lite [--max-retries 0]
  -> milai_memory_resolve(query)
  -> loopback-only MiLAi Runtime
```

The relay MUST NOT parse, frame, retain, hash, log, inspect, or transform MCP bytes. It validates the
socket pathname and inode, then applies bounded-kernel-buffer backpressure while copying stdin to the
socket and socket bytes to stdout. Diagnostics contain only fixed reason codes.

The broker MUST:

- run as a dedicated process for one profile and pin its effective UID as socket owner;
- accept a strict, secret-free JSON policy and a separate mode-`0400`/`0600` token file;
- bind a mode-`0600`, profile-named socket in a non-writable, non-symlink directory it owns;
- pin the socket device/inode/owner/mode and revalidate it before and after every accept;
- restrict peers by Linux `SO_PEERCRED` UID;
- verify the exact absolute `milai-mcp` executable SHA-256 before every child start;
- spawn exactly `milai-mcp --profile <fixed-profile>` when the optional retry policy is absent, or
  append exactly `--max-retries 0` when broker policy declares `mcp_max_retries: 0`;
- discard child stderr and log no MCP body, token, Runtime response, Prompt, memory, or model output;
- close or terminate the child on EOF, crash, broker stop, policy drift, or socket replacement.

The child environment is exactly:

```text
LANG
LC_ALL
PATH
PYTHONDONTWRITEBYTECODE
PYTHONNOUSERSITE
MILAI_BASE_URL
MILAI_AGENT_TOKEN
MILAI_AGENT_SCOPE_JSON
MILAI_AGENT_REQUIRED_AUTHORITY
MILAI_AGENT_CONSISTENCY_FLOOR
MILAI_AGENT_MAX_LIMIT
```

No proxy, Provider credential, database variable, `PYTHONPATH`, `LD_PRELOAD`, `BASH_ENV`, or inherited
environment entry is forwarded.

## Capability mounting rule

Mount the socket file itself, not its containing host directory:

```text
/run/milai-broker/reader-lite/reader-lite.sock
  -> /run/milai-mcp/reader-lite.sock:ro
```

The image contains `/run/milai-mcp` as a root-owned mode-`0555` directory. The container MUST NOT
have `CAP_SYS_ADMIN`, host networking, privileged mode, the Docker socket, a PostgreSQL socket, the
Runtime environment, or a host secret directory. Mounting one socket file pins the capability inode;
replacing the host pathname does not authorize a new socket. Broker path drift stops new sessions and
causes bounded failure.

`mcp_max_retries`, when present, is a broker-owned fixed policy value and only the JSON integer `0`
is valid. It is never read from MCP input or the Worker environment. Unknown policy fields and any
other retry value fail closed; omitting the field preserves the existing MCP client default.

Ordinary OpenWorker instances mount only `reader-lite.sock`. Submitter and operator profiles require
separate broker processes, OS identities, token files, socket paths, Worker instances, and Agent
policies. A model argument can never select a profile, Scope, authority, consistency floor, limit,
Runtime retry count, base URL, token, or executable.

## Lifetime and failure contract

1. The broker validates policy, token source, executable, directory, and absence of a pre-existing
   socket before binding.
2. The Worker is created only after the broker socket exists and is mounted as a single read-only
   file.
3. Each connection receives one new MCP child. EOF is propagated in both directions.
4. Child stderr is discarded. Operational logs contain fixed reason codes and connection sequence
   numbers only.
5. Relay/broker failure, overload, invalid peer, socket drift, executable drift, or Runtime failure
   cannot select another profile or transport. The MCP session ends explicitly.
6. Disable order is: disable `mcp.milai`, recreate the Worker without the socket mount, stop broker,
   revoke token, then confirm the tool catalog no longer contains MiLAi.

The relay/broker transport does not turn MCP or model output into canonical truth. Evidence,
Proposal, Decision, Canonical Procedure, OpenIssue, revocation, and Canonical Gate invariants remain
unchanged.

In Host `query-first` mode every native user operation invokes `milai_memory_resolve` exactly once.
Continuation in the same OpenCode session may pass only the previous opaque `context_capsule_id` as
`previous_context_id`; the new operation still reaches MCP and receives a freshly authorized typed
outcome. The Host MUST NOT retain Memory items, Claim heads, OpenIssues, request coverage or
dependency state. Runtime validates owner, tenant, scope, coverage, dependencies, currentness and
expiry online; any miss runs the primary route in the same call. A locator never authorizes offline
reuse when Runtime is unavailable. Task/session headers remain Host correlation metadata and are not
inputs to the Core resolve contract. Both MiLAi memory tools are removed from the provider payload
after Host compilation.

M2 does not widen the ordinary OpenWorker socket capability. `milai_memory_get` is advertised by
`reader-detail` and other detail-capable profiles, not `reader-lite`; therefore the first-party Host
continues to expose only query-first resolve/recall over its existing socket. Exact StateKey/ClaimID
conformance is exercised by an ordinary `reader-detail` stdio MCP client against the same Runtime
application services and Canonical Gate.

M4 also leaves the ordinary `reader-lite` socket unchanged. Optional entity/type narrowing is
available only on a configurable detail-profile resolve call and never broadens the Host-fixed
policy. Both generic clients and OpenWorker use the same Runtime-owned bounded search semantics:
hard partition before ranking, temporal/FTS first, vector only after a recorded sparse miss,
Canonical Gate before sufficiency, and whole-item Context budgeting.

M6 likewise does not add TaskContext to the ordinary OpenWorker `reader-lite` socket. The optional
detail-profile TaskContext is a generic client hint that Runtime intersects with Host-bound policy;
it is neither derived from OpenWorker task headers nor required for a turn. OpenWorker's task-free
query-first behavior remains the non-regression arm and continues to use the same planner and Gate.

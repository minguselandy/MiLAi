# MiLAi OpenWorker MCP adapter

Status: local candidate only. This directory does not authorize a Provider request, spend, real
data, Beta, remote MCP, or image redistribution.

- `milai_openworker_mcp.relay` is the only new executable copied into the Worker and is also
  installed as `milai-mcp-relay` by the product wheel.
- `broker/milai_mcp_broker.py` runs outside the Worker and starts one exact MCP child per connection.
- `policy/reader-lite.example.json` is secret-free and must be rendered outside the repository with
  an exact installed `milai-mcp` executable digest.
- `openworker/opencode.json` is the persistent image template. It contains no MiLAi token, Runtime
  URL, DSN, or secret path.
- `openworker/Dockerfile` is pinned to the observed local base image ID. The upstream Worker source
  and redistribution license are not established, so the resulting image is local-only.

For DG-13 M1, the Host adapter's `query-first` mode calls the same public
`milai_memory_resolve(query)` contract on every user turn. It does not consult the Host Memory Need
resolver or send either the TARGET tool or the compatibility tool to the answer provider. A
same-session continuation always performs a new MCP call with a new native operation identity. The
older `prefetch` mode remains a compatibility path for the hidden
`milai_prepare_context` composite contract.

DG-13 M2 adds `milai_memory_get` only to detail-capable MCP profiles. The ordinary OpenWorker
`reader-lite` socket and query-first behavior are unchanged: a known canonical address may be sent
through the configurable detail-profile resolve contract by other clients, while OpenWorker still
uses one fresh query-only resolve per turn and receives no second Host truth store.

DG-13 M3 allows the Host adapter to retain one opaque `context_capsule_id` per native session and
send it as `previous_context_id` on the next resolve. It never retains Memory items, Claim heads,
OpenIssues, coverage facts or dependency state. Runtime performs online reauthorization and
revalidation; a miss, expiry or changed dependency falls back to the primary route inside that same
MCP call. Runtime/transport failure remains `MEMORY_REQUIRED_BUT_UNAVAILABLE` and blocks provider
invocation; a locally retained locator is never treated as offline CURRENT memory.

DG-13 M4 keeps the OpenWorker `reader-lite` wire contract unchanged while the shared Runtime kernel
adds bounded progressive Search. Candidate/deadline/context limits, hard partitions, escalation and
stop reasons remain Runtime-owned; the Host neither reranks candidates nor caches a result set.
Optional entity/type narrowing is reserved for configurable detail-profile clients.

DG-13 M6 keeps this socket task-free. Configurable detail-profile clients may send optional
TaskContext narrowing hints, but OpenWorker does not derive them from task/session headers and does
not need them for Memory reachability or correctness.

The normative process, mount, failure, logging, and rollback rules are in
`contracts/agent/v1/openworker-mcp-uds.md`.

Build the local image from this directory. The script verifies the observed source tag, creates a
content-identity-named local lock tag, builds with pull disabled and build networking disabled, then
verifies the locked base layer prefix and labels:

```bash
./build_local_candidate.sh
```

The Worker must receive a read-only bind mount of the socket file itself:

```bash
--mount type=bind,src=/run/milai-broker/reader-lite/reader-lite.sock,\
dst=/run/milai-mcp/reader-lite.sock,readonly
```

Do not mount the socket directory, Docker socket, Runtime `.env`, PostgreSQL socket, or a host secret
directory. Do not use `--network host` or `--privileged`.

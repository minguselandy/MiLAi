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

For the local usability evaluation only, the Host may select the fixed canonical
`MCP_INTERACTIVE_STANDARD_V01` resolve budget by starting the broker with that profile and rendering the reader-lite policy with
`max_limit=50`. The MCP process then sends exactly 50 results / 120 candidates / 8192 Context tokens
/ 2000 ms to Runtime. The reader-lite tool schema remains query-only, so the Worker cannot select or
override this budget. Deprecated `OPENWORKER_USABILITY_WIDE_V01` is an exact compatibility alias.
Omitting the startup option preserves the ordinary Product defaults.

For large-haystack local usability work, the Host may instead opt into
`MCP_INTERACTIVE_WIDE_V01`. It sends 50 results / 120 candidates / 16,384 Context tokens /
5,000 ms and raises only that profile's MCP wire ceiling to 262,144 bytes; the Host accepts at most
262,144 explicit context characters. It remains default-OFF, and omitting
`--resolve-budget-profile` still preserves ordinary Product defaults. The Worker and model cannot
choose or raise either profile. Deprecated `OPENWORKER_USABILITY_WIDE_V02` is an exact alias.

An informational `PARTIAL` result may expose governance-admitted evidence to the Provider for a
best-effort answer, but its Runtime status and lineage must remain visible. That presentation path
does not establish accepted Binding, completeness, typed `COMPLETE` or Canonical authority.

## Product-05 Host-owned exchange settlement

To persist completed OpenWorker exchanges, run a separate submitter broker on the trusted host and
configure both lanes on the Host adapter:

```text
--memory-mode query-first
--prefetch-socket /run/milai-broker/reader-lite/reader-lite.sock
--submitter-socket /run/milai-broker/submitter/submitter.sock
--memory-subject-id <host-selected-semantic-subject>
--memory-data-classification SYNTHETIC|DEIDENTIFIED|PERSONAL
```

The reader and submitter paths must be different sockets with their corresponding exact broker
profiles. Do not mount the submitter socket into OpenWorker and do not expose its tools to the model.
`memory-subject-id` describes whose memory the content concerns; it is not a tenant selector. The
Runtime credential behind each broker supplies the security `tenant_id`.

`openworker/milai-task-metadata.js` binds the native session and exact user/assistant message IDs and
timestamps to the request. After a complete provider answer, the Host submits the original user turn
and delivered assistant turn once. The replay identity excludes capture time, injected Memory
Context and system content. Assistant Evidence carries its recalled `memory_support_refs`, allowing
later reads to avoid treating a model restatement as independent user-fact support. If submitter
configuration is omitted, settlement is disabled and the existing read-only behavior is unchanged.

`--evidence-use-mode` defaults to `direct`, which is the Product-05 selected behavior. `inventory`,
`grounded` (`GroundedEvidenceUseV01`) and `ledger` (`EvidenceLedgerV01` followed by a grounded final
answer) are default-OFF experimental diagnostics. The Host may validate JSON shape, visible aliases,
explicit members and arithmetic consistency. It does not certify factual truth, set completeness,
Raw typed operands, Requirement `COMPLETE`, or Canonical state. The structured treatments did not
pass the Product-05 effect gate and must not be enabled as a claimed reliability improvement.

`model-native` is a separate default-OFF Product-06 diagnostic. It gives Qwen one ephemeral bounded
Reader session over the complete governed Context. Qwen may answer immediately or request up to four
expressions from an adapter-internal decimal calculator, then receives standard `tool` messages and
must finish on the second Provider round. The Host filters citations to Reader-visible aliases and
converts Reader/provider failures into one terminal insufficient answer, so OpenWorker does not
repeat the native operation. The calculator has no MCP or OpenWorker tool surface and cannot access
code or I/O. Product-06's fixed-Context validation established execution and safety but no accuracy
gain over `direct`; therefore `model-native` is not a reliability claim and `direct` remains the
default.

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

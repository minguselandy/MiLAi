# UA-04 MCP compatibility evidence

> Status: `PASS / MCP STDIO READY`  
> Runtime boundary: loopback, synthetic, Schema experimental, Implementation candidate.

## Frozen dependency and protocol surface

`milai-mcp 0.1.0` is locked to the official `mcp 2.0.0` package. The same server was exercised with
the official client in modern `2026-07-28` mode and legacy handshake mode negotiating
`2025-11-25`. Both in-process and real stdio child-process calls returned structured content plus
text content. Reconnect twice against a single server instance passed. The implementation follows
the official v2 documentation: modern discovery is stateless while the SDK continues to serve the
preceding handshake revision.

- Official SDK v2 notes: <https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/whats-new.md>
- Official stdio/HTTP transport guide:
  <https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/client/transports.md>
- Protocol transport rule:
  <https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/basic/transports/streamable-http.mdx>

## Security/catalog results

- Reader exposes exactly six sorted read tools.
- Submitter adds only Evidence capture and Proposal creation; both require literal host
  confirmation and return a redacted confirmation summary.
- Operator is separate and adds only Evidence revoke/deletion status. Revoke requires literal
  `REVOKE` and states immediate fail-closed vs asynchronous purge consequences.
- Reviewer, direct Claim/OpenIssue mutation, bulk delete, database query and tenant clear tools are
  absent in every profile.
- A server extension rejects unexpected arguments before execution, and advertised input schemas
  set `additionalProperties=false`; a caller cannot smuggle `profile=submitter` into a reader tool.
- Outputs are capped at 65,536 bytes and Evidence metadata never returns content. Credentials and
  database DSNs are absent from tool output and generated host configuration.

Automated package gate: Ruff, formatting, strict mypy and six MCP tests pass. The final isolated
three-session E2E adds two real stdio hosts: the official high-level Python Client in
`2026-07-28` mode and an independent minimal JSON-RPC wire host negotiating `2025-11-25`.
Both return the same canonical state/OpenIssue and independently persisted trace semantics;
post-revoke stale V2 is rejected. Reconnect and both protocol modes remain covered by package
tests. Scope and authority are fixed in the host environment and cannot be tool arguments.

# ADR-035: Explicit non-loopback `codex-full` MCP deployment

> Status: accepted for an explicitly authorized candidate deployment  
> Schema: `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`  
> Transport: MCP Streamable HTTP (HTTP request/response plus SSE), not WebSocket

## Context

ADR-033 approved only loopback operation because `codex-full` combines read, capture, Proposal,
review, revocation, cleanup and Host Working State authority. A requested remote deployment needs a
non-loopback listener, but a changed default would make accidental public exposure too easy.

Ports `7961` through `7967` on the target host are already assigned. `7968` is the selected MCP
port. `7969` remains unassigned; it is not presented as a WebSocket MCP endpoint because Codex uses
the standard Streamable HTTP transport and the MCP package has no governed WebSocket contract.

## Decision

1. Loopback remains the default and requires no new option.
2. A non-loopback Streamable HTTP listener fails closed unless the operator passes
   `--allow-non-loopback`.
3. A non-loopback listener also requires `MILAI_MCP_HTTP_PUBLIC_BASE_URL`; wildcard bind addresses
   cannot become the issuer/resource identity advertised to clients.
4. The endpoint retains one strong static Bearer credential, one server-owned principal, exactly
   one server-owned project scope, four internal role-routed Runtime credentials and zero automatic
   mutation retry.
5. Runtime remains on loopback. Runtime role credentials never cross the MCP process boundary.
6. The deployment service reads the inbound token from a root-only file, restarts on failure and
   never places the token in Product configuration, logs or command output.

The selected candidate endpoint is:

```text
http://36.140.33.19:7968/mcp
```

The URL denotes MCP Streamable HTTP. Streaming responses use HTTP/SSE. `ws://...` is neither an
alias nor a supported Codex transport.

## Security boundary

This approval does not claim Internet production readiness. Plain HTTP does not protect a Bearer
token from an on-path observer. The listener should be restricted to trusted source addresses by
the host/cloud firewall or placed behind an HTTPS reverse proxy before use across an untrusted
network. TLS/OAuth, token issuance, per-client principals and rate limiting remain unresolved.

Memory is untrusted data, never authorization. Namespace cleanup still requires an explicit request
in the current conversation. All normal confirmation literals, operation IDs, RLS, CAS,
revocation-first behavior and automatic audit remain unchanged.

## Compatibility and rollback

There is no database or public tool-schema change. Existing loopback commands behave identically.
Rollback is operational: stop and disable the public MCP service and remove the root-only inbound
token. Migration `0050_host_cognitive_state` is additive and is not downgraded as part of endpoint
rollback.

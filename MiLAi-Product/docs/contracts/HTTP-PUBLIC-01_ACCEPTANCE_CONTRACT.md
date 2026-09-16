# HTTP-PUBLIC-01 acceptance contract

> Status: candidate deployment contract  
> Endpoint: `http://36.140.33.19:7968/mcp`

## Required gates

```text
7968 was free before deployment                         PASS
existing 7960-7967 listeners were not displaced         PASS
Runtime binds loopback only                             REQUIRED
non-loopback without explicit opt-in                    REJECT
non-loopback without public base URL                    REJECT
unauthenticated /mcp                                    HTTP 401
wrong Bearer token                                      HTTP 401
authenticated MCP initialize + tools/list               PASS
exact codex-full catalog                                13 tools
readyz across reader/submitter/reviewer/operator         PASS
automatic Runtime retry                                 0
server-owned project scope                              exactly 1
public tool schema gains authority fields               0
Runtime role credentials returned/logged                0
automatic audit default                                 enabled
```

## Streaming contract

The supported streaming mechanism is MCP Streamable HTTP with SSE. Port `7969` is not a WebSocket
MCP compatibility endpoint. A future WebSocket surface requires its own message framing,
authentication, authorization, backpressure, replay and audit contract plus a Host that supports
that transport.

## Remaining operational risk

The candidate listener is plain HTTP. Firewall source restriction or TLS termination is required
before sending its Bearer token over an untrusted network. Passing these gates does not change the
Product status from `CANDIDATE / NO-GO FOR SCHEMA FREEZE`.

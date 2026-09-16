# HTTP-STANDARD-MCP-01 Acceptance Contract

> Status: implemented candidate  
> Schema: `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`

## Wire and authentication

```text
Streamable HTTP JSON-RPC at POST /mcp                      REQUIRED
Accept application/json and text/event-stream              REQUIRED
Mcp-Session-Id lifecycle                                   REQUIRED
Authorization: Bearer <server-issued-token>                 REQUIRED
custom identity header                                     FORBIDDEN AS A REQUIREMENT
principal/scope/authority in tool arguments                 FORBIDDEN
WebSocket                                                   NOT IMPLEMENTED
```

## Credential gates

```text
unique Token maps to exactly one server-owned principal     PASS
first successful Bearer authentication activates PENDING    PASS
second authentication is idempotently ACTIVE                PASS
unknown/revoked Token                                       401
clear Token absent from registry and audit                  PASS
issue/register/revoke audit appended automatically          PASS
registry/lock/audit owner-only                              PASS
existing static principal compatibility                     PASS
tool catalog remains exactly 13                             PASS
Memory/Canonical/Runtime schema changed                     0
```

## Client configuration truthfulness

`mcpServers` is documented as client configuration, not as an MCP protocol object. `type: "http"`
is emitted for clients that explicitly support that convention. Codex uses URL plus
`bearer_token_env_var`; no URL-only OAuth claim is allowed until an HTTPS Authorization Server,
discovery, client registration, login, Authorization Code + PKCE and token lifecycle pass direct
tests.

## Authority limits

Registration is server-issued onboarding, not public signup. A credential identifies a Host
principal within the endpoint's fixed tenant/project; it does not provide tenant isolation or raise
Memory authority. Canonical mutations continue through Evidence → Proposal → Review and deletion
continues through revoke-first semantics.

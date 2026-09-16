# HTTP-OAUTH-DCR-01 Acceptance Contract

> Implementation: PASS candidate  
> Public HTTPS deployment: BLOCKED  
> Schema: `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`

## Protocol gates

```text
RFC 9728 Protected Resource Metadata                         PASS
RFC 8414 Authorization Server Metadata                       PASS
RFC 7591 Dynamic Client Registration                         PASS
public-client `none` token/revocation auth advertised        PASS
Authorization Code grant                                     PASS
S256 PKCE required and verified                              PASS
missing PKCE challenge                                      REJECTED
RFC 8707 exact authorization/token-request MCP binding      PASS
browser user authorization                                   PASS
access token accepted by MCP initialize                      PASS
refresh-token rotation                                       PASS
old refresh-token replay                                     invalid_grant
token-family revocation                                      PASS
administrator user revocation invalidates live token pair    PASS
administrator revocation invalidates unexchanged auth code   PASS
non-HTTPS/non-loopback redirect URI                          REJECTED
exact codex-full 13-tool catalog after OAuth                 PASS
```

## Identity and persistence gates

```text
DCR client identity treated as end-user identity             0
anonymous full-control authorization                         0
one-time enrollment code plaintext at rest                   0
authorization/access/refresh token plaintext at rest         0
OAuth event audit written by default                          PASS
OAuth principal propagated into Working State binding         PASS
client-selected tenant/project/role/authority                 0
Runtime/Canonical schema changes                              0
public MCP process requires root privileges                   0
Runtime PostgreSQL role URLs loaded into MCP process          0
```

## Public deployment gate

```text
trusted HTTPS MCP/Authorization Server origin                BLOCKED
public 80/443 or managed reverse-proxy control               MISSING
URL-only Codex public install claim                          NOT AUTHORIZED
```

The implementation may run over loopback HTTP for tests. Public operation must not use HTTP,
self-signed certificates, disabled verification or anonymous consent.

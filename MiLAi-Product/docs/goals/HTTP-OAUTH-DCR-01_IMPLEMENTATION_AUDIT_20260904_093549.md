# HTTP-OAUTH-DCR-01 Implementation Audit

- Audit time: `2026-09-04T09:35:49Z`
- Product state: `IMPLEMENTED CANDIDATE`
- Public deployment state: `BLOCKED — TRUSTED_HTTPS_ORIGIN_UNAVAILABLE`
- Schema: `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`

## Outcome

MiLAi MCP now implements the OAuth discovery, DCR, Authorization Code + S256 PKCE, browser
authorization, token refresh/rotation and revocation chain required for a URL-only Codex
Streamable HTTP registration. The user does not configure or copy an OAuth access/refresh token.

This does not make DCR an end-user registration mechanism. DCR registers the Codex OAuth client.
The current MiLAi candidate binds the browser authorization to a server-approved user with a
one-time enrollment code. A future account or enterprise OIDC login may replace that browser
identity step without changing the MCP client contract.

## Reference-system observation

The supplied AIGCIT endpoint was observed live:

```text
GET https://mcp.aigcit.com/web-search/mcp
→ 401
→ WWW-Authenticate: Bearer resource_metadata=
  "https://mcp.aigcit.com/.well-known/oauth-protected-resource/web-search"

Protected Resource Metadata
→ resource=https://mcp.aigcit.com/web-search
→ authorization_servers=[https://auth.aigcit.com]
→ scopes_supported=[search.web]

Authorization Server Metadata
→ authorization_endpoint=/oauth/authorize
→ registration_endpoint=/oauth/register
→ token_endpoint=/oauth/token
→ revocation_endpoint=/oauth/revoke
→ authorization_code + refresh_token
→ code_challenge_methods_supported=[S256]
```

The installed Codex CLI `0.153.0` exposes `--url`, optional
`--oauth-client-registration AUTO|CIMD|DCR`, and
`codex mcp login`. OpenAI documentation confirms Streamable HTTP OAuth with CIMD/DCR and states
that `auth=oauth` is the default when no configured Bearer/Authorization credential resolves.

## Implemented behavior

```text
unauthenticated /mcp
→ RFC 9728 Protected Resource Metadata
→ RFC 8414 Authorization Server Metadata
→ RFC 7591 DCR
→ exact registered redirect URI
→ required S256 PKCE + RFC 8707 resource
→ browser APPROVE/DENY with one-time enrollment
→ digest-only authorization/access/refresh/enrollment secrets at rest
→ OAuth principal-bound access token
→ authenticated 13-tool codex-full catalog
→ rotating refresh pair; replay rejected
→ token-family or user-wide revocation
→ default metadata-only security audit
```

OAuth identity cannot select tenant, project, Runtime role or Canonical authority. The existing
server deployment continues to bind project/scope and route the four Runtime credentials. Evidence
immutability, Proposal/Review, ClaimVersion, revocation-first deletion and Working State authority
are unchanged.

## Verification

From `integrations/mcp`:

```text
uv run ruff check src tests
→ All checks passed

uv run mypy
→ Success: no issues found in 10 source files

uv run pytest -q
→ 92 passed in 12.45s

uv build
→ milai_mcp-0.1.3.tar.gz
→ milai_mcp-0.1.3-py3-none-any.whl

uv build  # integrations/python-client
→ milai_client-0.1.0.tar.gz
→ milai_client-0.1.0-py3-none-any.whl

uvx --with ../python-client/dist/milai_client-0.1.0-py3-none-any.whl \
  --from ./dist/milai_mcp-0.1.3-py3-none-any.whl \
  milai-oauth-user --help
→ PASS; packaged issue/revoke/list CLI loaded
```

The test closure includes discovery metadata, unauthenticated challenge, DCR, exact resource,
missing-PKCE rejection, browser consent, authorization-code exchange, MCP initialization,
codex-full exact catalog, Working State principal propagation, refresh rotation and replay,
token-family revocation, administrator user revocation, secret-at-rest assertions and redirect URI
rejection.

The MCP wheel is a server-side artifact and currently depends on the repository-owned
`milai-client`, which is not published on the public package index. A standalone index-only MCP
wheel resolution therefore fails; the clean paired-wheel check above passes. Remote Codex users do
not install either wheel in the URL-only flow.

## Public deployment boundary

The currently reachable service remains:

```text
http://36.140.33.19:7968/mcp
```

Both public MCP and Runtime services were active and `/readyz` returned `200` at audit time. This
endpoint remains the static server-issued Bearer fallback. It is not published as OAuth because it
is plaintext HTTP and this host does not control the NAT address's public 80/443 routes. An ACME
HTTP-01 attempt for a temporary DNS name timed out from the public Internet; no trusted certificate
was issued.

Public URL-only onboarding remains unauthorized until a controlled domain with trusted HTTPS is
reverse-proxied to the backend and a real Codex public login smoke passes. Self-signed TLS,
disabled certificate verification, anonymous full-control authorization and an HTTP issuer are not
accepted workarounds.

## Final user command after the deployment gate

```bash
codex mcp add milai --url https://<controlled-domain>:7968/mcp
```

If a client version stores the server without immediately opening the authorization flow:

```bash
codex mcp login milai --oauth-client-registration DCR
```

The browser OAuth consent happens on the user's machine. No shell approval on the MCP server is
required, but a real MiLAi user identity/enrollment is required before full-control authorization.

## Impact and rollback

- Runtime/PostgreSQL migration: none.
- Public MCP tool schema: unchanged; exact 13-tool catalog retained.
- Canonical/permission semantics: unchanged.
- OAuth persistence: owner-only edge SQLite; no Canonical data.
- Rollback: omit `MILAI_OAUTH_DB` and retain the static Bearer verifier.
- Remaining blocker: external DNS/TLS/gateway authority.

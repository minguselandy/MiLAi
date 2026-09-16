# HTTP-REMOTE-REGISTRATION-01 Completion Audit

- Executed: 2026-09-04 15:49:14 +08:00
- Endpoint: `http://36.140.33.19:7968/mcp`
- Result: `IMPLEMENTED_CANDIDATE`
- Schema: `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`

## Delivered

- server-side `milai-codex-user issue/list/revoke` credential lifecycle;
- exact generic `mcpServers` JSON as the only new-user client artifact;
- per-user random Token stored only as SHA-256 digest;
- Token pre-binding to validated `x-agent-id`;
- atomic first-use `PENDING → ACTIVE` activation;
- request principal propagation through stateful MCP async dispatch;
- dynamic Host principal in Working State binding, Proposal identity and mutation audit;
- automatic private JSONL audit for issue/register/revoke;
- deployed registry at `/var/lib/milai-mcp/codex-users.json`;
- dedicated user guide and ADR-036.

No Runtime endpoint, Memory tool schema, Evidence/Claim behavior or database migration changed.

## Verification

```text
MCP Ruff                                      PASS
MCP strict mypy                               PASS
MCP pytest                                    87 passed
MCP sdist + wheel build                       PASS
public systemd service active/enabled         PASS
/healthz                                      200
/readyz                                       200
unauthenticated /mcp                          401
legacy authenticated catalog                  13 tools
fresh issued JSON first-use authentication    PASS
fresh user status after first use             ACTIVE
registration audit                            USER_REGISTERED
revoked credential                            401
registry directory                            0700
registry / lock / audit                       0600
```

The first service probe immediately after restart raced process startup and returned connection
refused once. Service logs showed normal startup one second later; bounded re-probe passed health
and readiness. This was an operational startup timing issue, not an auth or Runtime failure.

## Security conclusion

The requested JSON-only flow is implemented without trusting arbitrary `x-agent-id`. A different
server-issued Token is required for every user, and changing the header cannot impersonate another
principal. There is deliberately no open self-signup using arbitrary Token strings.

Registered users on this endpoint are still collaborators in the fixed `milai` project. Host
principal separation protects per-principal Working State and audit identity, but does not create
tenant/project data isolation. The public endpoint remains plain HTTP and therefore candidate-only.


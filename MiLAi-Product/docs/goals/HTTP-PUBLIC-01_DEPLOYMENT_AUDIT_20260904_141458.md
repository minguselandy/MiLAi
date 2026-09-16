# HTTP-PUBLIC-01 deployment audit

> Executed: `2026-09-04 14:14:58 +08:00`  
> Terminal: `PUBLIC_STREAMABLE_HTTP_MCP_RUNNING_CANDIDATE`  
> Product: `0.1.0-candidate`; Schema: `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`

## Delivered state

The host port survey found `7960`, `7968` and `7969` free. Existing listeners on `7961` through
`7967` were preserved. The authorized endpoint uses `7968`:

```text
Codex
  -> MCP Streamable HTTP / SSE
  -> http://36.140.33.19:7968/mcp
  -> codex-full / 13 tools / one bound project
  -> http://127.0.0.1:28180
  -> MiLA Runtime / PostgreSQL
```

The user cancelled the WebSocket requirement. No process binds `7969`; no private WebSocket MCP
protocol was introduced.

Two persistent systemd units are enabled and active:

```text
milai-product-api-mcp.service       127.0.0.1:28180
milai-codex-full-public.service     0.0.0.0:7968
```

The inbound token is generated once at `/etc/milai/codex-full-public.token`, mode `0600`. Runtime
role tokens stay in the existing root-only Runtime environment and are never returned by MCP.
The root Codex configuration registers the public URL and only the variable name
`MILAI_CODEX_TOKEN`; `/etc/milai/codex-full-client-env.sh` loads the credential without copying it
into configuration or shell history.

## Compatibility operation

The existing database was at `0049_cleanup_terminal_counts`. The additive migration
`0050_host_cognitive_state` was applied successfully before the current Runtime was restarted.
Existing Evidence/Claim data was not rewritten. Runtime remains loopback-only.

## Verified gates

```text
database migration head                              0050_host_cognitive_state
Runtime /health/ready                                HTTP 200
MCP /healthz                                         HTTP 200
MCP /readyz across four Runtime roles                HTTP 200
public http://36.140.33.19:7968/healthz              HTTP 200
unauthenticated /mcp                                 HTTP 401
wrong Bearer /mcp                                    HTTP 401
authenticated initialize + tools/list                PASS
tool count                                            13
working-state read                                   PASS / ABSENT
systemd active                                       2 / 2
systemd enabled                                      2 / 2
WebSocket listener                                   0
root Codex MCP registration                           enabled
```

The package adds an explicit `--allow-non-loopback` opt-in. Non-loopback startup without the flag,
or without `MILAI_MCP_HTTP_PUBLIC_BASE_URL`, fails closed. Loopback defaults remain unchanged.

## Failure reflection and repair

- Port `7966` and then `7967` were found occupied by AgentMemory stream/viewer services; no process
  was terminated. The deployment moved to free port `7968`.
- The first OpenSSL invocation used an incompatible option order and created no file. The compatible
  invocation generated one 64-hex-character token with mode `0600`.
- A transient Runtime unit prevented enablement. It was stopped without deleting data and replaced
  by an equivalent persistent unit.
- The legacy EnvironmentFile overrode `MILAI_BASE_URL`, sending MCP readiness to port `28080`; the
  Runtime URL is now set last in `ExecStart`.
- The same precedence issue made the new Runtime attempt port `28080`, already used by the untouched
  legacy Runtime. The persistent unit now sets its bind address last and uses isolated port `28180`.
- The first manifest help command assumed a Product-root virtualenv. The final manifest command uses
  the locked Runtime Python.

At no point was 503 readiness treated as success. Each failure was attributed and repaired before
the authenticated MCP check.

## Security and remaining risk

Scope is server-owned and fixed to project `milai`. The public schema exposes no tenant, principal,
role or authority override. Confirmation literals, operation IDs, RLS, CAS, revocation-first
behavior and automatic audit remain enabled.

This is still plain HTTP. A Bearer token can be observed by an on-path attacker. Restrict `7968` to
trusted source addresses or add HTTPS termination before using it over an untrusted network. This
deployment does not claim production readiness.

## Operations

```bash
systemctl status milai-product-api-mcp.service
systemctl status milai-codex-full-public.service
systemctl restart milai-codex-full-public.service
systemctl stop milai-codex-full-public.service
```

Stopping the MCP service does not delete memory. Endpoint rollback requires no database downgrade.

The separate remote-machine registration deliverable is recorded in the
[remote package audit](HTTP-PUBLIC-01_REMOTE_REGISTRATION_PACKAGE_AUDIT_20260904_143217.md).

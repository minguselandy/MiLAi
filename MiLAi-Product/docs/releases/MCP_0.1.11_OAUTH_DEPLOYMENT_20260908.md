# MCP 0.1.11 OAuth deployment — 2026-09-08

Superseded on the OAuth endpoint by
[MCP 0.1.12](MCP_0.1.12_OAUTH_DEPLOYMENT_20260908.md), which publishes the payload-hint
fix. The local-only statements below describe the earlier 0.1.11 follow-up.

Subsequent user-reported check confirms loading 23 tools (including memory search),
direct Proposal object schemas, nine rejected invalid requests, three-scope State
reads and updated error/deletion hints. UI `unknown`, State write/recovery and unknown
commit scenarios remain unconfirmed by that client. The reported CREATE payload-hint
mix-up was fixed locally after this deployment; that source change is not in the live
0.1.11 package. See the [execution audit](../goals/MILA_V02_08_EXECUTION_20260908.md).

Status: DEPLOYED; public edge checks pass, complete OAuth acceptance remains pending.
The user explicitly requested deploying the current MCP to
`https://milai.aigcit.com:7960/mcp` after the separate 7968 deployment.

## Change

`milai-aigcit.service` now runs MCP 0.1.11 / client 0.1.3 instead of MCP 0.1.8.
The independent environment is
`/opt/milai-aigcit/releases/product-v0208-0.1.11/oauth-mcp-venv`.
Its interpreter is the existing `/opt/milai-aigcit/python/bin/python3.11`, not a
root-home interpreter inaccessible under this service's `ProtectHome=true`.

The new `zzz-product-v0208.conf` drop-in changes only the executable and unit
description. It retains the loopback listener at 7969, `ordinary-memory-v1`, the
`milai-mcp` user/group and existing hardening. TLS/proxy configuration, OAuth issuer,
resource URL, scopes, credentials, admission policy and per-user identity bindings
were not modified. All MILAI process environment values and the two environment
files plus bindings file have identical before/after hashes. Protected-resource
metadata and its 12 advertised scopes are also identical.

The shared Runtime remains the already-deployed 0.1.4. No API/worker/7968 service
was restarted in this increment. No migration, grant mutation, client registration,
token issuance/revocation, memory test write, cleanup or model inference was performed.

## Commands and verification

The same previously verified 0.1.11 delivery archive was installed with:

```sh
MILAI_INSTALL_PYTHON=/opt/milai-aigcit/python/bin/python3.11 sh /opt/milai-aigcit/releases/product-v0208-0.1.11/milai-mcp-delivery-0.1.11/install.sh /opt/milai-aigcit/releases/product-v0208-0.1.11/oauth-mcp-venv mcp
systemd-analyze verify /etc/systemd/system/milai-aigcit.service
systemctl daemon-reload
systemctl restart milai-aigcit.service
```

All 40 packaged checksums, locked installation, `uv pip check` and CLI help passed.
The release-local `verify_oauth.py preflight` constructs the installed CLI with the
live environment after dropping to the actual service account, without starting a
listener. It verified 23 registered tools and their generated input schemas against
the packaged ordinary snapshot. Calling its protected directory without a request
identity was correctly denied; registered-tool inspection is explicitly not an
authenticated public tools/list result. The probe was adjusted to retain this denial
check and inspect registration separately, rather than inventing an OAuth identity.

`verify_oauth.py before` and `verify_oauth.py after`, using the new environment's
Python, saved redacted `oauth-before.json` and `oauth-after.json` in the release root:

- Public HTTPS `/healthz` and `/readyz`: HTTP 200 with normal TLS verification.
- Loopback 7969 and the existing 7968 health/readiness: HTTP 200.
- Protected metadata: exact resource URL and `https://auth.aigcit.com` issuer retained.
- Auth discovery and JWKS: reachable; exact resource registration active with matching scopes.
- Public MCP initialize with no token and with an invalid token: HTTP 401 and the
  exact HTTPS protected-resource metadata challenge.
- Configuration, binding and metadata hashes: unchanged.
- New OAuth MCP PID: 3365642, active with zero automatic restarts at handoff.

These HTTPS probes originate on the deployment host; independent-client network
reachability and actual user login/read/refresh were not retested. No valid user OAuth
token was supplied or retrieved for testing. Existing grants were not expanded.

The unchanged strict command below reports BLOCKED both before and after switching:

```sh
/opt/milai-aigcit/releases/product-v0208-0.1.11/oauth-mcp-venv/bin/milai-oauth-readiness --base-url https://milai.aigcit.com:7960 --external-issuer https://auth.aigcit.com
```

The external Auth metadata still omits `revocation_endpoint_auth_methods_supported`;
the checker requires public-client method `none`. This is a pre-existing external
contract gap, not a new MCP deployment failure. The checker was not weakened, and
the independent successful edge checks above are not represented as full OAuth readiness.
Actual user tools/list, refresh/revocation and Host rendering remain unverified.

## Rollback

The previous unit and all existing drop-ins are preserved under the release's
mode-0700 `oauth-rollback/` directory; the old installed 0.1.8 environment is intact.
Run:

```sh
sh /opt/milai-aigcit/releases/product-v0208-0.1.11/rollback_oauth.sh
```

The script renames only the new override to `.disabled`, reloads systemd and restarts
only `milai-aigcit.service`, restoring its previous pinned MCP entrypoint. It passed
`sh -n`; an actual rollback was not exercised after the successful switch. No data,
credentials or configuration are deleted or restored from a database snapshot.

This deployment does not change the current client's separate 7968 connection URL.
Clients already using the OAuth HTTPS URL keep that address and their existing grants.
Earlier local test results remain applicable to the byte-identical candidate; no new
product source changes or full test-suite rerun were needed for this executable switch.

Schema 0.1.x EXPERIMENTAL / Implementation CANDIDATE / NO-GO FOR SCHEMA FREEZE.

# Public HTTPS OAuth MCP final deployment handoff

> Historical audit from 2026-09-04. Its public HTTPS blocker and 13-tool static/full-control
> deployment are not the current private-user service status. See the
> [2026-09-08 MCP delivery](../releases/MCP_0.1.5_HANDOFF_20260908.md) for the current handoff.

> Independent audit: `2026-09-04T19:27:18+08:00`
> Repository disposition: `PACKAGE_READY_FOR_OWNER_CUTOVER`
> Public deployment disposition: `BLOCKED_TRUSTED_HTTPS_ORIGIN_UNAVAILABLE`
> Product: `Implementation CANDIDATE`
> Schema: `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`

This handoff is the deployment boundary, not a public OAuth completion claim. The audit made no
change to systemd, Nginx, firewall, DNS, credentials, databases, listeners, or the public endpoint.
No public OAuth DCR/login smoke was performed because the configured public IP does not currently
serve trusted HTTPS.

## Independent conclusion

The repository-side OAuth/DCR implementation, locked MCP package, paired local `milai-client`
wheel, credential-free readiness probe, and uninstalled systemd cutover example are internally
consistent and installable. No remaining repository code defect was supported by the audit, so no
code or protocol contract was changed. This document is the only authored handoff change.

Public cutover is not ready. The remaining external blocker is ownership of one trusted HTTPS
origin: either a controlled DNS name with a publicly trusted certificate and gateway route, or a
publicly trusted certificate containing the literal IP as an IP SAN plus control of its 443 route.
The current NAT/gateway behavior is not that origin.

## Live read-only facts

Observed without credentials or state-changing OAuth requests:

```text
milai-product-api-mcp.service             active / enabled
milai-codex-full-public.service           active / enabled
Runtime listener                           127.0.0.1:28180
Runtime /health/ready                      HTTP 200
current MCP listener                       0.0.0.0:7968
current MCP /healthz                       HTTP 200
public HTTP protected-resource metadata    HTTP 200; resource/authorization server use HTTP 7968
public HTTP authorization-server metadata  HTTP 404
public HTTP unauthenticated MCP initialize HTTP 401
host global address                        192.168.0.19/24 (private)
host 443 listener                          absent
public IP port 80 /healthz                  HTTP 502
public IP TLS /healthz                      handshake EOF; no HTTPS response
milai-oauth-readiness over public IP        BLOCKED at the first trusted-HTTPS health request
```

The protected-resource `200` is not evidence that OAuth is deployed: it advertises the existing
plaintext resource, while Authorization Server discovery is absent. The live unit remains the
legacy static/registered-Bearer candidate. It runs from the development checkout as root, loads the
legacy Runtime `.env`, binds publicly, and does not set `MILAI_OAUTH_DB`. The cutover prerequisites
from the repository example are not installed: the `milai-mcp` system account, dedicated four-token
environment file, and `/opt/milai/mcp-venv` entry point are absent. Existing credential contents
were not read.

## Repository and package evidence

From `integrations/mcp`:

```text
uv lock --check                         PASS
uv run --frozen ruff check src tests    PASS
uv run --frozen mypy                    PASS; 11 source files
uv run --frozen pytest -q                PASS; 105 tests
uv build                                PASS; sdist + wheel
systemd-analyze verify cutover example  PASS
```

From `integrations/python-client`:

```text
uv lock --check                         PASS
uv run --frozen ruff check src tests    PASS
uv run --frozen mypy                    PASS; 14 source files
uv run --frozen pytest -q                PASS; 171 tests
uv build                                PASS; sdist + wheel
```

Artifact identities from this audit:

```text
1fb92a2c2992f00d459368cb3cd26acd6d5f78637800795d6cc5f22f2a04ab53  milai_mcp-0.1.3.tar.gz
9e0cd4224005c6b07d3fe89375ce113e00faf8b30a1dc5af98351135a68bfd5f  milai_mcp-0.1.3-py3-none-any.whl
df2e4e2dba6ba46d0ae4cb5ca647a32c4e40dbc2d3354ca0bb0524a095c20a3f  milai_client-0.1.0-py3-none-any.whl
```

A disposable Python 3.11 environment installed all third-party dependencies from the exact hashed
`uv.lock` export, then installed both wheels with `--no-deps`. Both `milai-oauth-readiness --help`
and `milai-oauth-user --help` loaded. Installed versions were `milai-mcp 0.1.3`, `milai-client
0.1.0`, `mcp 2.0.0`, and `starlette 0.52.1`. A stale same-version `uvx` tool cache initially hid the
new readiness entry point; `--refresh-package milai-mcp` loaded the wheel correctly, so this was not
a package defect.

The generated Product manifest exactly matches the current included tree: 343 files,
`aa50bf1b70d1d5835ccfeb4ab3ff3591b2788af39cf72f35eabefa32d4055442`. Build outputs and disposable
installation files remain outside that Product identity.

The full Runtime suite and real-PostgreSQL gates were not rerun: this handoff changes no Runtime,
Canonical, migration, RLS, revocation, or transaction behavior. The live Runtime readiness check
passed. This is not evidence for production readiness.

## Deployment-owner checklist

Do not start this checklist until the gateway owner supplies the exact HTTPS origin and confirms
control of its certificate and public 443 route.

1. Freeze one external origin, normally `https://<controlled-domain>` on 443. Use a port suffix only
   when TLS genuinely terminates on that external port. The value must contain no path, query,
   fragment, or userinfo. If using `https://36.140.33.19`, the publicly trusted certificate must
   contain `36.140.33.19` as an IP SAN.
2. Save the current unit and its `hc4-a1.conf` drop-in for rollback. Decide the intended
   `MILAI_CODEX_TASK_REF`; the existing drop-in otherwise overrides the example's value.
3. Build both packages from their locked checkouts and verify the three SHA-256 values above, or
   record new hashes if the source changes. A source change invalidates this handoff and requires
   the package gates again.
4. Create the non-login `milai-mcp` system account. Create
   `/etc/milai/codex-full-mcp.env` as root-owned mode `0600`, containing only the four Runtime API
   Bearers: reader, submitter, reviewer, and operator. Do not load `runtime/.env` into the MCP unit.
5. Keep `/etc/milai/codex-full-public.token` root-owned mode `0600` and pass it with systemd
   `LoadCredential`. Before cutover, rotate every static or per-user Bearer ever sent over plaintext
   port 7968. Treat prior plaintext exposure as a rotation requirement, not as proof of compromise.
6. Install the verified wheels and locked third-party dependencies into a root-owned, non-writable
   deployment environment. One reproducible installation shape is:

   ```bash
   cd /cra/memory/mx_memory/MiLAi-Product/integrations/mcp
   uv export --frozen --no-dev --no-editable --no-emit-project \
     --no-emit-package milai-client --format requirements-txt \
     --output-file /tmp/milai-mcp-runtime.lock
   install -d -m 0755 -o root -g root /opt/milai
   uv venv --python 3.11 /opt/milai/mcp-venv
   uv pip install --python /opt/milai/mcp-venv/bin/python --require-hashes \
     --requirements /tmp/milai-mcp-runtime.lock
   uv pip install --python /opt/milai/mcp-venv/bin/python --no-deps \
     ../python-client/dist/milai_client-0.1.0-py3-none-any.whl \
     dist/milai_mcp-0.1.3-py3-none-any.whl
   ```

   Confirm `/opt/milai/mcp-venv` is owned by root and not writable by `milai-mcp`. Remove the
   temporary exported lock after installation; it contains no credential.
7. Adapt
   [`milai-codex-full-public.service.example`](../../examples/codex-mcp/milai-codex-full-public.service.example)
   only for the frozen origin and intended task reference. Keep backend bind `127.0.0.1:7968` when
   the gateway is on this host, `User=milai-mcp`, the dedicated environment file, `LoadCredential`,
   `StateDirectoryMode=0700`, and the `/opt` entry point. Do not install the old public-bind unit as
   the OAuth backend.
8. Configure the gateway to forward the complete same-origin surface: `/mcp`, both `/.well-known/`
   metadata paths, `/register`, `/authorize`, `/token`, `/revoke`, `/oauth/consent`, `/healthz`, and
   `/readyz`. Preserve OAuth locations and authentication/MCP headers; disable response buffering
   and allow long-lived SSE on `/mcp`. Rate-limit registration, authorization, token, and consent
   surfaces. Do not expose Runtime port 28180. An off-host gateway also needs a source-restricted
   private backend route.
9. During the authorized maintenance window, install the unit, enable `MILAI_OAUTH_DB`, and restart
   only after the gateway, dedicated credentials, account, and deployment venv are ready. A 503 from
   `/readyz` is a failed cutover.
10. From a genuinely external client network, using the system trust store and no TLS bypass, run:

    ```bash
    milai-oauth-readiness --base-url https://<controlled-domain>
    ```

    Require `status=READY`, the exact origin/resource/endpoints, S256, public-client `none`, the
    unauthenticated OAuth challenge, and `mutating_requests=0`.
11. Only after the preflight is ready, issue a disposable test enrollment and perform a real public
    Codex DCR/browser login. Verify the authenticated `codex-full` catalog contains exactly 13 tools,
    a controlled read works, refresh rotation works, revocation makes the token unusable, and no
    token appears in logs or configuration. Revoke the test user afterward.
12. Publish `codex mcp add milai --url https://<controlled-domain>/mcp` only after step 11 passes.
    Until then, do not claim public OAuth, URL-only onboarding, or production readiness.

## Rollback boundary

The preferred OAuth-only rollback keeps the trusted TLS gateway in place, removes `MILAI_OAUTH_DB`
from the MCP process configuration, and restarts the same loopback backend with the matching HTTPS
public base and rotated static break-glass Bearer. Preserve the OAuth SQLite file read-only as edge
audit history; do not delete or rewrite it during rollback.

If the owner instead restores the exact pre-cutover unit and drop-in, the system returns to the
currently observed plaintext public-Bearer candidate. That is a mechanical rollback, not an
acceptable OAuth or untrusted-network deployment state. Keep it blocked from publication.

Rollback requires no Runtime migration or PostgreSQL downgrade and must not change migration 0050,
Evidence, ClaimVersion, ClaimHead, OpenIssue, Working State, RLS, permissions, revocation, or
Canonical transaction semantics. The OAuth database is an edge store, not canonical memory.

## Final status

```text
Repository implementation   CANDIDATE; package/install gates pass
Public HTTPS origin         BLOCKED; gateway/DNS/certificate authority missing
Public OAuth smoke          NOT RUN; impossible truthfully on the current endpoint
Canonical/API/schema impact NONE from this handoff
Production readiness        NOT CLAIMED
Schema                      0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE
```

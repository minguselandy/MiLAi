# MCP 0.1.12 public OAuth deployment — 2026-09-08

Superseded on the OAuth endpoint by [0.1.13](MCP_0.1.13_OAUTH_DEPLOYMENT_20260908.md):
22 tools, administrator-only cleanup submission and optional non-authorizing advice.
The deployment facts below describe the preceding 0.1.12 release.

Status: DEPLOYED. The user authorized publishing the CREATE payload-hint fix.
`https://milai.aigcit.com:7960/mcp` now runs MCP 0.1.12 / client 0.1.3.
Shared Runtime remains 0.1.4; the separate 7968 MCP remains on installed 0.1.11.

Only `milai-aigcit.service` was restarted. Release root:
`/opt/milai-aigcit/releases/product-v0208-0.1.12`; installed environment:
`oauth-mcp-venv`, using `/opt/milai-aigcit/python/bin/python3.11` for compatibility
with the existing `milai-mcp` account and ProtectHome isolation. New override:
`/etc/systemd/system/milai-aigcit.service.d/zzzz-payload-hints-0.1.12.conf`.

## Change and release proof

Source comparison against deployed 0.1.11 found only the version module and
`input_contracts.py`, `recovery.py`, `server.py` changed. Trusted operation context
now selects payload guidance: CREATE expects `business JSON object`; State retains
its existing 65536-byte / 1024-reference limits. No schema, validation, permission,
identity, authority or transaction rules changed. No migration is needed.

From `integrations/mcp`, `uv lock --offline`, `uv run --locked pytest -q`,
`uv run --locked ruff check src tests`, `uv run --locked mypy` passed: 341 tests,
6 PG-conditional skips, 23.07s; mypy checked 19 files. Diagnostic-only changes did
not need a new PG transaction/model test. From Product,
`sh tools/build_mcp_delivery.sh` produced a new archive without overwriting 0.1.11.

- Delivery: `integrations/mcp/dist/delivery/milai-mcp-delivery-0.1.12.tar.gz`.
- Archive SHA-256: `8dc34cdb3ac781bbeca24ed533a330fc4fcb6ccafb6de89cd329f1c866661bd3`.
- MCP wheel SHA-256: `ae2e38776c04c5fccdc3c6f363ecaec2a6f66252fb5e47f4a6694e2d336cd4b7`.
- Sidecar and all 40 internal checksums passed; installed package files exactly
  match the wheel. Client/Runtime wheels are byte-identical to the previous delivery.
- Locked installation, `uv pip check` and CLI help passed.

Installation and switch commands:

```sh
MILAI_INSTALL_PYTHON=/opt/milai-aigcit/python/bin/python3.11 sh /opt/milai-aigcit/releases/product-v0208-0.1.12/milai-mcp-delivery-0.1.12/install.sh /opt/milai-aigcit/releases/product-v0208-0.1.12/oauth-mcp-venv mcp
systemd-analyze verify /etc/systemd/system/milai-aigcit.service
systemctl daemon-reload
systemctl restart milai-aigcit.service
```

The release-local `verify_oauth.py preflight` constructed the installed CLI under
the actual account/environment without starting a listener. It verified 23 registered
schemas against the unchanged 0.1.11 snapshot, required identity for protected
directory access, and tested missing/list/string CREATE payload hints separately
from State hints. This is installation/registration inspection, not an authenticated
public user test. The local full suite covers actual protocol rejection behavior.

`verify_oauth.py before` / `after` saved redacted receipts under the release root:

- Public trusted HTTPS health/readiness and loopback 7969/7968: HTTP 200.
- Missing/invalid tokens: HTTP 401 with the exact protected-resource challenge.
- JWKS reachable; exact resource registration active with the same 12 scopes.
- Complete MILAI environment, both environment files, bindings file and protected
  metadata hashes match before/after. Credentials and raw memory were not logged.
- OAuth MCP active, PID 3423651, zero automatic restarts at handoff. API/worker/7968
  retained PIDs 3328692 / 3328694 / 3328695; no other service was restarted.

TLS/proxy, grants, credentials, identity bindings and data configuration were not
modified. No public memory write, deletion, review, model experiment or database
mutation was performed. Public probes originated on the deployment host; real-user
authenticated error retesting and client rendering remain acceptance work.

The unchanged strict `milai-oauth-readiness --base-url https://milai.aigcit.com:7960
--external-issuer https://auth.aigcit.com` still reports the existing missing
`revocation_endpoint_auth_methods_supported` declaration. Full OAuth acceptance
is not claimed and the checker was not weakened.

## Rollback

Original unit/drop-ins are preserved in the release's mode-0700 `rollback/`.
Run `sh /opt/milai-aigcit/releases/product-v0208-0.1.12/rollback_oauth.sh` to rename
only the new override to `.disabled`, reload systemd and restart the OAuth service
onto the intact pinned 0.1.11 environment. Script syntax passed `sh -n`; a live
rollback was not exercised after success. No data/files are deleted and no database
restore is required. Earlier published artifacts remain unchanged.

Schema 0.1.x EXPERIMENTAL / Implementation CANDIDATE / NO-GO FOR SCHEMA FREEZE.

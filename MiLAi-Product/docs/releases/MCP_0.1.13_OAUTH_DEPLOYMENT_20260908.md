# MCP 0.1.13 public calling-experience repair — 2026-09-08

Status: DEPLOYED_SERVER_REPAIR_CLIENT_RENDERING_PENDING. The requested server-side
repair is deployed to `https://milai.aigcit.com:7960/mcp`; remote UI and real Agent
acceptance are not inferred from deployment or protocol fixtures.

## User-visible changes

| Concern | Current implementation / acceptance boundary |
| --- | --- |
| Proposal unknown | Generated inline object with nine operation constraints retained; concise CREATE envelope fallback added to its tool description. Signed protocol schema tests pass; remote UI not available for inspection. |
| Repeated principles | Ordinary initialize no longer appends duplicated OAuth common prose. Tool descriptions do not contain the common prefix. A client may still repeat initialize instructions itself; no unverified UI fix is claimed. |
| Advice as commands | Ordinary emits only suggested_next_step, optional=true, authorization_granted=false. Every suggested mutation requires_user_authorization=true. Working State usage metadata is explicitly advisory. Legacy key remains compatible. |
| Conflict/recovery | Structured errors, safe same-object current version, READ_AND_REBASE and retryable=false retained and regression-tested. Unknown commits are reconciled, not blindly retried. |
| State scopes | Get/save advice preserves SESSION/TASK/PROJECT; both catalogs tested. |
| Note deletion | Logical-only semantics and physical_deletion_supported=false retained. No tool rename or physical purge implementation is claimed. |
| Namespace cleanup | Ordinary removes cleanup submission from registration and dispatch; scoped status remains. Full-admin signed requests cannot invoke it. Existing separate operator/API administration is unchanged; no new public admin UI or Host-policy bypass was added. |

The public ordinary catalog intentionally changes from 23 to **22** tools. Clients
must refresh their tool definitions and stop calling the removed cleanup submit tool.
Advice consumers must read `suggested_next_step`, not `mcp_guidance`. This boundary is
recorded in [ADR-053](../adr/ADR-053-ordinary-mcp-advisory-and-admin-boundary.md).
Identity, OAuth grants, Runtime permissions, validation, Canonical transactions and
database schema remain unchanged; the ordinary tool surface is narrowed only.

## Tests and artifacts

From `integrations/mcp`: `uv lock --offline`, `uv run --locked pytest -q`,
`uv run --locked ruff check src tests`, `uv run --locked mypy`.
Final results: **345 passed / 6 PG-conditional skips in 23.03s**, Ruff passed, mypy
19 files passed. Adjacent signed HTTP/schema/scope slice passed 80 tests.

`MILAI_MCP_BASELINE_E2E=1 uv run --locked pytest -q tests/test_ordinary_memory_postgres.py`
with credentials scoped to the existing owned test container passed **1 test in
14.87s**. It created/dropped only its disposable database and exercised signed private
HTTP, three-scope CAS, unknown-commit cuts/replay, deletion/source eligibility,
query-only cold discovery, new client/token and restart. No production database or
model was used. The final two advisory flags were subsequently covered by the full
MCP suite; no transaction code changed after that PG slice.

The test container `milai-v0208-contract-20260908a` was restarted for the test and
stopped afterward; its existing volume was retained. Initial test orchestration used
the wrong owner-password environment key and stopped before pytest; the corrected
run used the container's POSTGRES_PASSWORD without printing credentials. Initial
lint line-length/import issues were corrected before final gates.

The signed 22-tool snapshot is
`contracts/mcp/ordinary-memory-v1.repair-0.1.13.tools.json`. The PG log is under
`MiLAi-Lab/artifacts/v02-08-mcp-contract-repair/pg-http-0.1.13-final.log`.

`sh tools/build_mcp_delivery.sh` from Product built the independent delivery:

- Archive: `integrations/mcp/dist/delivery/milai-mcp-delivery-0.1.13.tar.gz`.
- Archive SHA-256: `37524a33456d606d836055f1319ce61d44bfaf1e27b8b322c718fd38ed4d07ba`.
- MCP wheel SHA-256: `1dc472e5809404b1dfa7817f324f8a7209bd8e4f495692902a90c69940167a4d`.
- Sidecar and all 42 manifest entries passed; installed package bytes match the wheel.
- Client 0.1.3 and Runtime 0.1.4 wheels match the preceding release byte-for-byte.

## Installation and switch

Release root: `/opt/milai-aigcit/releases/product-v0208-0.1.13`.
Only `milai-aigcit.service` was changed, via
`/etc/systemd/system/milai-aigcit.service.d/zzzz-usability-0.1.13.conf`.

```sh
MILAI_INSTALL_PYTHON=/opt/milai-aigcit/python/bin/python3.11 sh /opt/milai-aigcit/releases/product-v0208-0.1.13/milai-mcp-delivery-0.1.13/install.sh /opt/milai-aigcit/releases/product-v0208-0.1.13/oauth-mcp-venv mcp
systemd-analyze verify /etc/systemd/system/milai-aigcit.service
systemctl daemon-reload
systemctl restart milai-aigcit.service
```

Locked installation, pip check and CLI help passed. Release-local `verify_oauth.py
preflight` ran installed CLI construction under the actual milai-mcp user/environment
without starting a listener: 22 registered tools, exact snapshot schemas, cleanup
submission absent, protected listing denied without identity, new advice flags and
payload hints verified. This is installed registration inspection, not a forged or
real-user OAuth tools/list test.

`verify_oauth.py before` / `after` produced redacted receipts in the release root:
public trusted HTTPS health/readiness 200; loopback 7969 and 7968 healthy; missing and
invalid tokens 401 with the exact metadata challenge; JWKS reachable and exact
resource registration active. Complete MILAI environment, both environment files,
bindings and protected metadata hashes match before/after. All 12 scopes stay the same.

New OAuth MCP PID 3483698 is active with zero automatic restarts. Shared API/worker
and 7968 legacy were not restarted; they remain Runtime 0.1.4 / MCP 0.1.11 respectively.
TLS/proxy, secrets, grants, user data and schema were not changed. No public business
write/delete/review, OAuth token extraction or model experiment was performed.

The existing strict OAuth checker still reports missing external Auth
`revocation_endpoint_auth_methods_supported`. The checker was not weakened; full
OAuth/refresh/revocation acceptance remains distinct from these edge checks. Public
probes originate on the deployment host, not an independent user network.
The first post-switch strict invocation encountered a TLS unexpected-EOF while
reading Auth discovery. One subsequent read-only recheck reached discovery and
reported the existing missing-method declaration; both outcomes remain non-passing.

## Rollback and remaining acceptance

Original unit/drop-ins are preserved in the release's mode-0700 `rollback/`.
`sh /opt/milai-aigcit/releases/product-v0208-0.1.13/rollback_oauth.sh` renames only
the new override to `.disabled`, reloads systemd and restarts on intact pinned 0.1.12.
It passed `sh -n`; live rollback was not exercised. It also restores the older
cleanup-submit exposure and advice key, so rollback requires an explicit operator
decision. No data deletion, database restore or credential change is needed.

The user was asked for current remote unknown/repeated-description evidence; none
was available during this rollout. Reconnect the OAuth client and inspect its actual
22-tool definition output. If it still rewrites object schemas to unknown or prepends
common prose, diagnose that client transformation rather than claiming it fixed by
server tests. Real Agent cross-session use remains a separate authorized acceptance
gate, not a reason to run new models or destructive public probes automatically.

Schema 0.1.x EXPERIMENTAL / Implementation CANDIDATE / NO-GO FOR SCHEMA FREEZE.

# MCP 0.1.14 Host descriptions — public deployment, 2026-09-08

Status: DEPLOYED_SERVER_METADATA_HOST_RENDERING_PENDING.
User authorized deploying the completed description changes to the public service.
At 19:27:10 Asia/Shanghai, only `milai-aigcit.service` was restarted onto MCP 0.1.14
at `https://milai.aigcit.com:7960/mcp`. Active PID: 3610216; NRestarts: 0.

## Scope

Initialize now exposes MiLAi title and the full Host-submitted governed-memory
description. Every tool has a readable title and purpose-first description with
relevant authorization, recovery and deletion limits. Ordinary remains 22 tools.
See [the complete description inventory](../runbooks/mcp-host-descriptions.md).

No tool-ID, input-schema, risk-flag, OAuth grant, identity, database, permission or
Canonical transaction changes. No migration, data restore, public memory mutation
or model experiment occurred. Shared Runtime 0.1.4 and client 0.1.3 are unchanged.
API PID 3328692, worker PID 3328694 and legacy 7968 MCP PID 3328695 are unchanged.

## Verification and artifacts

From `integrations/mcp`:

```sh
uv lock --offline
uv run --locked ruff check src tests
uv run --locked mypy
uv run --locked pytest -q
```

Ruff passed; mypy passed for 19 files; pytest: **354 passed, 6 PG-conditional skips
in 23.27s**. Signed synthetic HTTP checks inspect initialize and all 22 descriptions,
checking schemas and risk flags against the 0.1.13 snapshot. Eight profiles are
covered. PG was not rerun because only presentation metadata and version changed.
`git diff --check` passed. From Product, `sh tools/build_mcp_delivery.sh` succeeded.

- Archive: `integrations/mcp/dist/delivery/milai-mcp-delivery-0.1.14.tar.gz`.
- Archive SHA-256: `78726384d8c158baf1ecf2b2ff8a1b7e4dfd82089d9f046d553ef570d6eb3f1f`.
- MCP wheel SHA-256: `d0b7d843d31b056246ac18abfab7ed106bbaca018c24b856aa34ff50ae57a782`.
- Archive sidecar and all 43 internal manifest entries passed.
- All 20 installed MCP package files match the wheel.
- Client and Runtime wheels match the prior release byte-for-byte.
- MCP package source differences from 0.1.13 are limited to `__init__.py`,
  `server.py`, `ordinary_memory.py` and `memory_search.py`.

The archive is the pre-switch candidate snapshot; its embedded local-only audit
and description inventory status record that build time. This separate receipt
supersedes those historical deployment-status statements. No archive was overwritten.

## Install and switch

Release root: `/opt/milai-aigcit/releases/product-v0208-0.1.14`.
New override: `/etc/systemd/system/milai-aigcit.service.d/zzzzz-descriptions-0.1.14.conf`.

```sh
MILAI_INSTALL_PYTHON=/opt/milai-aigcit/python/bin/python3.11 sh /opt/milai-aigcit/releases/product-v0208-0.1.14/milai-mcp-delivery-0.1.14/install.sh /opt/milai-aigcit/releases/product-v0208-0.1.14/oauth-mcp-venv mcp
systemd-analyze verify /etc/systemd/system/milai-aigcit.service
systemctl daemon-reload
systemctl restart milai-aigcit.service
```

Hash-locked independent installation, dependency check and CLI help passed. The
release-local `verify_oauth.py preflight` constructs the installed CLI under the
actual milai-mcp account/environment without starting a listener. It verifies server
description, all 22 titles/descriptions, unchanged schemas, deletion disclosure,
search description, and missing-identity denial. This is registration inspection,
not a real-user authenticated tools/list. User/Group milai-mcp and ProtectHome remain.

`verify_oauth.py before` / `after` receipts in the release root verify trusted public
HTTPS health/readiness 200, both loopback MCP services healthy, missing/invalid tokens
401 with the expected resource challenge, reachable JWKS and active exact resource
registration. All MILAI environment values, both environment files, binding file,
protected-resource metadata and 12 scopes have unchanged hashes/values.

## Rollback and limits

Original unit and drop-ins are preserved in the release's mode-0700 `rollback/`.
Run `sh /opt/milai-aigcit/releases/product-v0208-0.1.14/rollback_oauth.sh` to rename only
the new override to `.disabled`, reload systemd and restart on intact pinned 0.1.13.
Syntax checked with `sh -n`; live rollback was not exercised. No data or credential
restoration is needed. This rollback preserves 0.1.13's narrowed ordinary catalog.

Public probes originate on the deployment host. Real OAuth user login, remote Host
rendering and real Agent cross-session use were not retested. Reconnect the actual
7960 OAuth client to reload metadata. The existing external Auth discovery still
lacks `revocation_endpoint_auth_methods_supported`; no full refresh/revocation
acceptance is inferred and no checker or security policy was weakened.

Schema 0.1.x EXPERIMENTAL / Implementation CANDIDATE / NO-GO FOR SCHEMA FREEZE.

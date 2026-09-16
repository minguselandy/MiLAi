# Product HTTP MCP deployment — 2026-09-08

Subsequent update: the separate public OAuth MCP was also upgraded to 0.1.11 on
explicit user request; see [the OAuth deployment receipt](MCP_0.1.11_OAUTH_DEPLOYMENT_20260908.md).
Statements below that it was not restarted refer only to this earlier 7968 switch.

Status: HTTP_DEPLOYED_HOST_RENDERING_PENDING. The requested service switch is complete;
this is not full V02-08 acceptance or production-readiness certification.

The user explicitly authorized verification followed by HTTP migration, then requested
switching the current Product to the HTTP MCP service. That authorization supersedes
the earlier deployment gate recorded in the candidate handoff.

## Deployed boundary

- Existing endpoint: `http://36.140.33.19:7968/mcp`, legacy 13-tool catalog.
- `milai-codex-full-public.service`: independent MCP 0.1.11 / client 0.1.3 environment.
- `milai-product-api-mcp.service` and `milai-product-worker-mcp.service`: independent
  Runtime 0.1.4 environment, upgraded from installed Runtime 0.1.2.
- Release root: `/opt/milai-aigcit/releases/product-v0208-0.1.11`.
- Only executable overrides were added as `zzz-product-v0208.conf` in these units'
  drop-in directories. Ports, catalog, all existing environment references and security
  settings were preserved. SHA-256 of each process's complete MILAI environment matches
  its own pre-switch value; secret values are not included in receipts.
- The separate OAuth MCP service `milai-aigcit.service` was neither replaced nor restarted.
  Its shared Runtime was upgraded; its loopback health/readiness checks still pass.

## Verification and exact commands

The existing archive `milai-mcp-delivery-0.1.11.tar.gz` passed its SHA-256 sidecar check:
`4ecdabbabe9cf3d4a6d5b00799f4185a4f26cfb8762b4a16f714dec38976f4fb`.
Both installers verified all 40 internal manifest entries. From the release root:

```sh
sh milai-mcp-delivery-0.1.11/install.sh /opt/milai-aigcit/releases/product-v0208-0.1.11/mcp-venv mcp
MILAI_INSTALL_EMBEDDING=1 sh milai-mcp-delivery-0.1.11/install.sh /opt/milai-aigcit/releases/product-v0208-0.1.11/runtime-venv runtime
```

Locked dependency installation, `uv pip check`, MCP CLI help and isolated Runtime import
passed. Runtime configuration validation with the actual service environment passed.
ONNX Runtime 1.28.0 and tokenizers 0.23.1 match the previous environment; imports succeeded,
without loading models or running inference. A read-only database query verified revision
`0056_host_notes`; no migration ran. The API role correctly cannot read the migration table;
the existing migration credential was used for that read-only revision query only.

Unit verification and switch commands:

```sh
systemd-analyze verify /etc/systemd/system/milai-codex-full-public.service /etc/systemd/system/milai-product-api-mcp.service /etc/systemd/system/milai-product-worker-mcp.service
systemctl stop milai-codex-full-public.service milai-product-worker-mcp.service
systemctl daemon-reload
systemctl restart milai-product-api-mcp.service
systemctl start milai-product-worker-mcp.service milai-codex-full-public.service
```

The release-local `verify_http.py before` / `verify_http.py after`, run using
`mcp-venv/bin/python`, recorded redacted `before.json` / `after.json`:

- 7968 and 7969 `/healthz` and `/readyz`: all HTTP 200.
- API 28180 `/health/ready`: HTTP 200.
- Public address 7968 `/healthz` and `/readyz`: HTTP 200 using direct curl.
- Unauthenticated 7968 MCP request: HTTP 401, before and after.
- Existing bearer credential: initialize, tools/list and TASK working-state read pass.
- All 13 deployed input schemas exactly match the packaged legacy snapshot.
- Proposal changed from `$ref` to a direct `type: object`; no tool names were changed.
- Current Host's existing `milai_working_state_get(scope="TASK")` also succeeded after
  switching, without a new model-generation test or business mutation.
- API/worker/MCP are active with zero automatic restarts at handoff; new PIDs are
  3328692 / 3328694 / 3328695. OAuth MCP remains PID 2415945.

The complete working-state response digest differs between versions and is not treated
as evidence of data equality or data loss. No raw memory payload is stored in the report.
The deployment made no direct memory, canonical, grant, credential or database-content
changes. Normal pre-existing worker processing was resumed, not experimentally exercised.

Two preflight harness issues were corrected before switching: the probe initially used
an old three-value MCP transport API, and configuration validation initially inherited an
unrelated ambient MCP variable. The corrected probe uses the installed MCP client API;
Runtime validation isolates the live service environment. Neither caused a service change.

## Rollback and limits

Original units/drop-ins are retained in the release's mode-0700 `rollback/` directory.
Run `sh /opt/milai-aigcit/releases/product-v0208-0.1.11/rollback.sh` to disable only the three
new overrides (rename to `.disabled`), reload systemd, and restore the previous service
entrypoints. No files/data are deleted and no database restore is needed. The script passed
`sh -n`; an actual rollback was not exercised after the successful switch.

The old Runtime is an independent pinned release. The previous MCP entrypoint is a mutable
workspace venv, so restoring that path cannot guarantee restoring the exact code previously
loaded in memory. This pre-existing rollback limitation is not hidden by the config backup.
The new release is independently installed and does not depend on workspace edits.

Actual Host-transformed tool-schema rendering remains unverified: the existing session's
cached definition is not refreshed by proof of a server switch or successful read. A Host
reconnect/reload and definition export is still needed for that broader goal. No actual Host
cleanup-denial trace was tested. Public writes, destructive tests and model experiments
were not run. The existing plaintext HTTP transport is preserved, not a TLS/security upgrade.

Schema 0.1.x EXPERIMENTAL / Implementation CANDIDATE / NO-GO FOR SCHEMA FREEZE.

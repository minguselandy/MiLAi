# MCP 0.1.11: current Host endpoint correction

OAuth deployment update: the public HTTPS service now also runs MCP 0.1.11 / client
0.1.3 with its existing ordinary catalog and OAuth bindings; see the
[OAuth deployment receipt](MCP_0.1.11_OAUTH_DEPLOYMENT_20260908.md) for checks and limits.

Deployment update: the user subsequently authorized the switch. MCP 0.1.11 / client
0.1.3 and shared Runtime 0.1.4 are now installed on the existing HTTP service.
See [the deployment receipt](MCP_0.1.11_HTTP_DEPLOYMENT_20260908.md). The no-deployment
statements below describe the original candidate handoff, not the current live state.

Candidate: MCP 0.1.11 / client 0.1.3 / Runtime 0.1.4. No public restart,
deployment, grant change, memory mutation or model call has been performed.

Read-only inspection found that the current Codex `milai` configuration points
to `http://36.140.33.19:7968/mcp`, served by `milai-codex-full-public.service`.
That service runs the Product workspace venv with the legacy 13-tool catalog.
The separate `milai-aigcit.service` runs installed MCP 0.1.8, ordinary-memory-v1,
on loopback 7969 behind the OAuth `https://milai.aigcit.com:7960/mcp` endpoint.
Both local health endpoints returned HTTP success. No credentials were read;
only the configured server URL, process launch paths and systemd metadata were inspected.

Therefore deploying only the OAuth service would not address the current Host.
0.1.10 expanded Proposal references only for ordinary. 0.1.11 applies the same
generated-schema serialization to both Codex catalogs. It does not change legacy
tool names, argument semantics, confirmation checks, text error format or catalog
selection. The nine operation examples exercise Schema and tools/call for both
catalogs. No second validation schema was created. Non-Codex profiles are unchanged.

All earlier repairs and their PG/SDK/Runtime evidence remain in
[the 0.1.10 handoff](MCP_0.1.10_HANDOFF_20260908.md). Only MCP schema export and
corresponding tests/docs changed in 0.1.11; there is no new migration or transaction
behavior. MCP locked adjacent tests, full suite, Ruff/mypy/build and installed
package checks are recorded in [the execution audit](../goals/MILA_V02_08_EXECUTION_20260908.md).
The 0.1.10 archive/hash remain available as historical candidate evidence.

## Concrete deployment boundary

The actual current-Host target is `milai-codex-full-public.service`, port 7968,
not `milai-aigcit.service`. Deploying its candidate requires separate authorization.
The currently running service imports a workspace venv; prepare a new independent,
pinned release venv before any authorized switch. A restart alone against the dirty
workspace is not a reproducible release. Preserve the existing server-owned
principal, task/project binding, environment references, credentials, port and legacy
catalog. Do not switch to ordinary or change the Codex URL implicitly.

The shared API/worker currently use `/opt/milai-aigcit/releases/ordinary-v1/runtime-venv`.
If deploying the complete repair combination, stage Runtime 0.1.4 independently,
retain its existing database/blob/model configuration and optional dependencies,
then switch the existing API/worker entrypoints with an exact rollback override.
This shared Runtime change also affects other connected MCP services and must be
included in the deployment authorization. No database snapshot restore or new
migration is part of this increment. Old executable paths/configuration remain the
rollback targets; credentials and database contents are never copied into the package.

After an authorized switch, verify unauthenticated health/readiness and the existing
authenticated principal's tools/list, preserving 13 legacy tools. Then the target
Host must reload/export the transformed tool definition without a new model run.
A server restart does not prove that the Host has refreshed its cached definitions.
Proposal object visibility and conditional CREATE constraints must be checked in
that actual Host output. No public writes/review/cleanup are needed for this check.
No actual Host cleanup-denial trace has been supplied; F7 remains evidence-limited.

Full Goal status remains LOCAL_REPAIR_COMPLETE_HOST_VALIDATION_PENDING when the
local checks pass. Public deployment and model behavior are not inferred from it.
Schema 0.1.x EXPERIMENTAL / Implementation CANDIDATE / NO-GO FOR SCHEMA FREEZE.

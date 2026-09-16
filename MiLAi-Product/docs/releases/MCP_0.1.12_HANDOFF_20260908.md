# MCP 0.1.12 — context-specific payload guidance

Candidate: MCP 0.1.12 / client 0.1.3 / Runtime 0.1.4. The user authorized deploying
the payload-hint correction to the public OAuth endpoint
`https://milai.aigcit.com:7960/mcp`. Deploy only `milai-aigcit.service`; retain its
ordinary-memory-v1 catalog, credentials, admission policy, issuer/resource, scopes,
service account and hardening. Do not restart the other MCP or shared Runtime.

The previous hint selected guidance solely by field name `payload`. CREATE errors
therefore incorrectly mentioned Working State size/reference limits. This release
uses trusted operation context: CREATE expects a business JSON object; only State
ingress/backend diagnostics mention State's existing 65536-byte / 1024-reference
limits. Backend input/message/context cannot select or contaminate these hints.
Both catalogs are covered. No tool schema, validation rule, authority, permission,
identity, database schema or transaction semantics change. SDK/Runtime are unchanged.
The 0.1.11 tool-schema snapshots remain the exact expected schemas.

Local correction evidence before versioning: full MCP suite 341 passed / 6 conditional
PG skips; Ruff, mypy (19 files) and build passed. Release verification and deployment
results are recorded separately in `MCP_0.1.12_OAUTH_DEPLOYMENT_20260908.md` after the
switch. The shipped 0.1.10 history and execution audit are historical evidence, not
claims that this candidate was already deployed when packaged.

Install into a new pinned venv using `/opt/milai-aigcit/python/bin/python3.11` so the
existing unprivileged service can execute it with ProtectHome enabled. Keep the
0.1.11 venv and systemd override intact as rollback targets. No migration or database
restore is required. Preserve credentials/data; do not exercise public memory writes,
grant changes, revocation or models for deployment verification.

The existing external Auth discovery gap for
`revocation_endpoint_auth_methods_supported` is separate and remains unresolved.
Full OAuth acceptance and user-client UI/State write/fault tests are not implied by
health, package checks or earlier user-reported 23-tool acceptance.

Schema 0.1.x EXPERIMENTAL / Implementation CANDIDATE / NO-GO FOR SCHEMA FREEZE.

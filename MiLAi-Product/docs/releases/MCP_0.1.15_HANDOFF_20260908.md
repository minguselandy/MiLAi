# MCP 0.1.15 — compact-memory-v1 local candidate

Status: COMPLETED_COMPACT_MCP_USABLE. MCP 0.1.15 / SDK 0.1.3 / Runtime 0.1.4.
The [final acceptance audit](MCP_0.1.15_FINAL_ACCEPTANCE_20260908.md) supersedes pending
statements below: raw client 12/12 checks, matching tool metadata and deployed-service
correlation complete the protocol gate. No model acceptance or Schema freeze is claimed.
The user subsequently authorized operations and independent subagent audit. The final
compact package is deployed on OAuth 7960; see the [receipt](MCP_0.1.15_OAUTH_DEPLOYMENT_20260908.md).
The packaged handoff's earlier local-only state records pre-switch build time.

Target-client update: supplied eight-tool metadata matches the release; the user reports
8/8 public cross-session save/search/read checks passed. The supplied synthetic body hash
was independently reproduced, but raw client receipts have not been supplied here.
The user subsequently reports 12/12 checks across four fresh sessions: save, cold read,
update to version 2, receipt check, historical read and another cold read of version 2.
Both test Notes remain ACTIVE and unchanged by this agent. Maintenance now has a user
report; raw connection/session/call evidence review remains pending. Public deletion is
not required to complete this update-maintenance chain. No real-model, semantic-search
or cross-account acceptance is claimed. See the receipt for
session identifiers, provenance and exact scope. This update requires no redeployment.

The opt-in `--catalog compact-memory-v1` exposes eight tools, filtered by existing
scopes. `memory_save` defaults to Note; typed options support Note edits and explicit
Evidence capture. Typed read/list/delete/status share only the interface, not
authority, storage or permissions. Each branch checks its original scope. Search
adapts generated references without rewriting Host bodies or source declarations.
No new OAuth scopes, schema migrations, background models or maintenance jobs.

See [ADR-054](../adr/ADR-054-compact-memory-tool-catalog.md) and
[the compact contract](../../contracts/mcp/compact-memory-v1.md).
Ordinary 22 and legacy 13 remain selectable; cached old names cannot dispatch through
the compact catalog. The remaining search advisory field now follows ADR-053's
optional/non-authorizing suggested_next_step format, including the ordinary catalog.

Public OAuth now uses pinned 0.1.15 compact; 7968 remains separate legacy.
Future deployments still need authorization, a new pinned venv and explicit catalog
selection. Preserve the resource URL, issuer, binding, grants and service account.
Rollback selects ordinary or restores pinned 0.1.14; no data deletion or restore.

Exact package hashes, engineering tests, isolated resource cleanup and remaining
gates are recorded in the V02-09 local release receipt once gates complete.
Local synthetic protocol clients are not target Host UI or real-model acceptance.

Schema 0.1.x EXPERIMENTAL / Implementation CANDIDATE / NO-GO FOR SCHEMA FREEZE.

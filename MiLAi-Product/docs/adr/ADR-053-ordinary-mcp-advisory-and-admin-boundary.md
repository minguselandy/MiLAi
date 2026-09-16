# ADR-053: Ordinary MCP advice and namespace administration boundary

Status: ACCEPTED FOR IMPLEMENTATION, 2026-09-08, following the user's request to
fix the remaining calling-experience problems and deploy to the public OAuth MCP.

Ordinary-memory-v1 is the interactive memory catalog, not the namespace administration
surface. Remove `milai_namespace_cleanup_submit` from its registration, not merely its
display. Keep the scoped status query. Full-scope or cached clients must not dispatch
the removed tool. Legacy/operator catalogs and the underlying governed Runtime cleanup
procedure remain unchanged; no new administrator identity, public admin UI or bypass
is introduced. Existing operator/API workflows are reserved for separately authorized
administration, not an automatic fallback for a refused model request.

This narrows ordinary catalog exposure from 23 to 22 tools. OAuth scopes/consent and
identity derivation do not change: operations.admin still controls cleanup status.
The mapping union must retain legacy tools while the ordinary catalog has its own
exact expected set. This is an intentional versioned catalog compatibility change;
clients should refresh definitions and stop calling the removed submit tool.

Ordinary responses rename server advice from `mcp_guidance` to `suggested_next_step`.
No duplicate alias is emitted. Advice is optional, explicitly grants no authorization,
and governance/destructive suggestions require current user authorization. Existing
legacy response fields remain compatible. Backend-provided fields cannot replace the
server's advisory metadata. These flags describe suggestions, not proof of authorization.

Common principles remain in initialize instructions; redundant ordinary/OAuth prose
is removed. Proposal keeps generated inline object constraints and gets a short,
tool-specific CREATE envelope explanation as a fallback for limited client renderers.
Server-side changes cannot certify an unseen client's UI or strip client-injected prose.

No Note delete rename, physical-purge implementation, permission expansion, Runtime
transaction change or database migration is part of this release. Version conflicts
retain retryable=false and READ_AND_REBASE; unknown commits are not silently retried.
Existing three-scope and deletion diagnostics remain mandatory regressions.

Acceptance requires signed local HTTP directory/dispatch denial with all scopes,
advisory and description/schema checks, both-catalog scope guidance, full MCP regression,
locked build/install and public read-only edge checks. Actual user-client UI, model
choice and destructive Host refusal behavior require their own evidence; do not forge
tokens, disable policy or run public cleanup to make those checks pass.

Rollback restores the prior pinned executable only and preserves data/credentials.
It also restores that older ordinary catalog's cleanup exposure, so rollback is an
explicit operator decision, not an automatic downgrade after a cosmetic client issue.

Schema 0.1.x EXPERIMENTAL / Implementation CANDIDATE / NO-GO FOR SCHEMA FREEZE.

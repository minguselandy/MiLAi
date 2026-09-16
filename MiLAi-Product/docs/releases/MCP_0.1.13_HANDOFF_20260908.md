# MCP 0.1.13 — ordinary calling experience and admin separation

Candidate: MCP 0.1.13 / client 0.1.3 / Runtime 0.1.4. User authorized repair and
public OAuth MCP rollout. Apply only to `milai-aigcit.service` at
`https://milai.aigcit.com:7960/mcp`; leave 7968 legacy and shared Runtime unchanged.

See [ADR-053](../adr/ADR-053-ordinary-mcp-advisory-and-admin-boundary.md): ordinary
removes namespace cleanup submission entirely (22 tools; status retained), renames
`mcp_guidance` to `suggested_next_step` with no duplicate alias, makes all advice
optional/non-authorizing, and requires user authorization for suggested mutations.
State usage metadata is advisory. Legacy/operator dispatch and response keys remain
compatible. No ACL, identity, validation, transaction or database schema changes.

Proposal keeps inline generated object Schema and nine operation constraints, with a
short CREATE envelope description for limited renderers. Ordinary OAuth instructions
no longer append duplicated public principles. Server changes do not prove how an
unavailable remote client renders unknown types or duplicates instructions. Three-scope
guidance, conflict/read-and-rebase diagnostics and Note physical-deletion disclosure
remain regressions. No blind retries or physical-erasure claims are introduced.

Local signed synthetic HTTP tests verify full-admin-token directory exclusion and
direct-dispatch rejection without Runtime effects; advice and descriptions/schema
are checked through tools/list and tools/call. The full suite and isolated signed
HTTP/PG slice (CAS, three scopes, unknown-commit cuts/replay, deletion eligibility,
new client/token, query-only cold discovery and restart) are recorded in the audit.
No public destructive tests, user-token extraction or model experiments are authorized
by these engineering checks. Real Agent/remote UI acceptance remains separate.

Install in a new pinned venv with `/opt/milai-aigcit/python/bin/python3.11`, retaining
the service's unprivileged account, ProtectHome, issuer/resource, grants and binding.
No re-registration, new consent, data migration or Runtime restart is necessary.
The existing operator/API administration surface is not a fallback for a refused
model request; no separate public admin UI is added by this release.

Rollback restores the old pinned executable and preserves data. It also restores
0.1.12's ordinary cleanup-submit exposure, so it must be an explicit operator action.
The pre-existing external Auth revocation metadata gap remains an independent issue.
Deployment facts and exact hashes are in the separate 0.1.13 deployment receipt.

Schema 0.1.x EXPERIMENTAL / Implementation CANDIDATE / NO-GO FOR SCHEMA FREEZE.

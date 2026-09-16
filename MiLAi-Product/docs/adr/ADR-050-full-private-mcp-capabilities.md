# ADR-050: Complete private MCP capabilities

Status: ACCEPTED FOR IMPLEMENTATION, 2026-09-08, under the user's explicit request
“补全全部的功能，milai mcp提供全部的功能”. Supersedes ADR-049's five-tool pilot cap;
identity derivation, tenant isolation and Canonical governance remain unchanged.

The AIGCIT resource server can expose all 13 existing codex-full tools. Directory and
dispatch use the same exact tool-to-scope mapping. Effective scopes are still the
intersection of verified token grants, deployment enablement and local admission.
Unknown tools/scopes fail closed. Existing credentials do not acquire new grants.
Default library admission stays read-only; the full deployment/client examples explicitly
request the complete supported set. The historical PILOT_SCOPES remains a valid subset.

All operations bind to the authenticated user's derived private project. Proposal
creation checks supporting/contradicting Evidence and target Claim scope. Review checks
the Proposal scope before committing through the existing Runtime role/procedure.
Revocation/deletion queries check Evidence ownership; cleanup derives the project and
checks job ownership. Models cannot select another principal or project.

The operations.admin scope means the existing bound-project cleanup capability here,
not server, tenant, database or other-user administration. Confirmation literals are
accident guards, not independent evidence of present user intent. Host instructions still
require an explicit current request for governance/destructive actions; no automatic
reviewer or destructive workflow is introduced. OAuth scope consent authorizes capability,
not automatic deletion. SINGLE_HOST_FULL_CONTROL is not independent semantic review.

Opening proposal listing revealed a real multi-user defect: taking the global newest
100 records before filtering can hide all of a user's proposals. Add an optional
project_id filter to the role-authorized Runtime GET /v1/proposals and client, applied
before LIMIT. MCP binds this argument server-side and retains response scope checks.
Omitting the filter preserves existing Runtime callers. It narrows reads, grants no
additional Runtime authority and needs no migration. New MCP requires the matching
Runtime read-filter implementation and client >=0.1.1.

Release gates include exact catalogs and denied dispatch, two signed private subjects,
own lifecycle through real PostgreSQL, cross-user proposal/review/revoke/job denial,
private cleanup preserving the peer, scoped listing before limit, and existing regression.
Tests use disposable data; user experiment pause remains in force. No model generations
or production destruction are part of validation. OAuth AS registration/consent and live
deployment are reported separately from local engineering results.

Schema remains 0.1.x EXPERIMENTAL / Implementation CANDIDATE / NO-GO FOR SCHEMA FREEZE.

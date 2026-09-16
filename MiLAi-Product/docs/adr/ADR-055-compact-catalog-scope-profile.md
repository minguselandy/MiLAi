# ADR-055: Align deployment scope requests with the compact tool catalog

Accepted 2026-09-09 following the user's request to align scopes with deployed tools.

OAuth 7960 selects compact-memory-v1 (eight tools). Advertise, enable and request the
union of permissions for every supported branch: nine existing scopes, as specified in
the compact contract. Remove the three unused Proposal/review/admin scopes from this
resource profile. Preserve all nine actual branch checks, subject/private-project
derivation, token verification, Runtime roles and canonical/deletion semantics.

This is configuration alignment, not new scope names, grant fabrication, permission
merging, a schema migration or a default privilege increase. Existing tokens remain
bounded by granted ∩ enabled scopes; they cannot gain missing Note permissions.
Ordinary and legacy examples remain distinct. User grants require real client consent.

Deployment: add an isolated final environment override, restart only OAuth MCP, verify
nine-scope metadata and fail-closed unauthorized access, then refresh the single existing
Auth resource registration and verify its status. Do not revoke or mint user credentials.
Rollback removes only that override, restarts the same pinned wheel, and refreshes the
same resource metadata to its prior set. No memory data, bindings or issuer changes.

Tests derive the required union from actual public entry alternatives and private backend
scopes, compare client/env/reauthorization profiles, and exercise nine-scope versus old
eight-scope grants through signed MCP requests. No public business writes or model calls.

Schema 0.1.x EXPERIMENTAL / Implementation CANDIDATE / NO-GO FOR SCHEMA FREEZE.

# `agent.v1` compatibility policy

`GET /v1/capabilities` is the compatibility handshake. A client may use `agent.v1` only when
`api_version=1`, `contract_version=agent.v1`, L0/L1 and `CANONICAL_REQUIRED` are advertised.

Within v1, the Runtime may add optional response fields, capability flags and tools to a new
opt-in profile. It may not:

- delete or rename a required request/response field;
- change `OK/DEGRADED/ABSTAINED` safety meaning;
- omit OpenIssue, trace, fallback, canonical position or revocation semantics already promised;
- relax unknown-field validation on security-sensitive tools;
- add review/direct canonical mutation/bulk delete to an existing Agent profile;
- reinterpret operation IDs, idempotency keys, 409 conflicts or retryability.

Such a change requires a new contract major. Schema/Alembic revisions are never client contract
identifiers and must not be imported by integrations.

DG-13 M4 uses that additive rule for `access_plan` / `search_trace` response fields, bounded-search
feature flags, and optional entity/type narrowing on `reader-detail`. `reader-lite` input remains
query plus optional opaque locator; no client-supplied hint can broaden authenticated policy.

DG-13 M5 uses the new-profile rule for a dedicated `reviewer` catalog. Existing reader, submitter
and operator catalogs are not granted review. The reviewer can inspect the canonical Proposal inbox
and call the Runtime-owned review procedure, but cannot capture Evidence, create a Proposal or
directly mutate canonical Claim state; Runtime actor separation remains authoritative.

DG-13 M6 additively permits optional TaskContext narrowing only on configurable detail profiles.
It cannot change Host-bound scope/authority/consistency, and task omission preserves the existing
query-first route. `reader-lite` remains query plus opaque locator, so Task cannot become a Core
reachability gate through a v1 schema change.

MCP compatibility is tested independently for `2026-07-28` and `2025-11-25`; protocol negotiation
does not grant capability. HTTP/remote transport is outside v1 local-beta approval.

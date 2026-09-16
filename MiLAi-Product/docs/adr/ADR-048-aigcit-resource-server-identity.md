# ADR-048: AIGCIT resource server identity and admission

- Date: 2026-09-07
- Status: ACCEPTED FOR INCREMENTAL IMPLEMENTATION; public deployment NOT VERIFIED
- Schema: 0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE

The HTTP-AIGCIT-AUTH-01 execution request authorizes implementation of the previously
design-only plan. AIGCIT authenticates users; MiLAi alone grants access to its fixed
project. This decision adds no Runtime authority, schema migration, account service,
model, or Canonical mutation. ADR-037/038 remain applicable to separate legacy modes.

## Decisions

1. Explicit `aigcit` mode accepts only ES256 `at+jwt` access tokens from the configured
   HTTPS issuer and exact single resource audience. No static or local OAuth fallback.
   PyJWT performs signature verification; request-provided key URLs are never fetched.
2. An immutable deployment resource binding carries project/scope identity independently
   of credentials. `(issuer, sub)` maps to a stable, project-bound principal, independent
   of client, token, key rotation and policy version. The initial admission format uses
   a derived `aigcit:` principal; rebinding an existing principal is rejected. A future
   explicit migration must record verified owner consent; no old data is rewritten.
3. The root-owned admission file allows at most one enabled owner. It is reread on each
   protected request; errors fail closed. Its version is an audit label, not permission
   to retain an old snapshot. Atomic replacement is the deployment update procedure.
4. Effective scopes intersect verified token scopes, current admission and enabled
   deployment scopes. Every registered tool needs an explicit mapping. Per-request
   filtering cannot mutate global tool state, and direct calls enforce the same gate.
5. HTTP identity is mandatory for protected handlers; local embedded compatibility
   cannot supply a fallback owner to HTTP requests. Context is reset in `finally`.
6. JWKS uses a shared asynchronous client, one refresh lock, a 600-second TTL, 30-second
   refresh cooldown and 3-second total network refresh deadline. Documents are bounded
   at 256 KiB. Valid warm keys do not wait for an unrelated refresh. Failed refreshes
   never extend TTL. Removed keys cease to work after a successful refresh; after TTL
   expiry unavailable keys yield dependency failure. Random kids share one cooldown
   without per-kid memory growth. Cancellation releases the refresh lock.
7. Local disablement applies to newly checked requests, including established MCP
   sessions; already committed or in-flight Runtime transactions keep their existing
   semantics. Auth logout/refresh revocation is distinct from JWT expiry and local
   admission revocation. No unsupported introspection promise.

## Verification and rollout

The Goal A01–A22 matrix is normative for full completion. Offline signed-token tests,
ASGI tests, real PostgreSQL, external TLS, registration and real user consent remain
separate evidence classes. P1–P3 may proceed without certificates or user tokens.
Source snapshots and execution evidence live in Lab, never the installed package.
The first enabled scopes are read-only; write/capture require their direct gates.
Governance and destructive tools stay disabled. No shared service changes during
local verification; public rollout requires the Remote Access Gate and P4–P6 evidence.

Rollback stops the candidate edge and restores its exact package/configuration only.
Keep old OAuth databases, memory, receipts and audit. Do not downgrade to anonymous
HTTP, reuse revoked secrets, or roll back user writes. No database migration needed.

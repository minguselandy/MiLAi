# ADR-049: Login creates access to a private memory namespace

Status: ACCEPTED FOR IMPLEMENTATION by the user's explicit requirement: every logged-in
user can use MiLAi and save their own memory. Supersedes ADR-048's one-owner admission
restriction for deployments explicitly configured in `authenticated_private` mode.

The issuer and exact resource audience remain mandatory. After cryptographic JWT
verification, Runtime-facing project scope is derived from the deployment namespace,
issuer and stable subject, never from client_id, token bytes, request arguments or
self-asserted JWT project/tenant claims. Principal and operation identity bind that
private project. No database account or canonical claim is created on login.

All enabled paths use this request-owned scope: resolve/exact retrieval, Evidence
capture, Working State at every scope, source qualification and continuation. A shared
MCP instance must not mutate its global policy while serving a user. Context remains
request-local, including asynchronous and threadpool work. Existing `milai` and legacy
principal data are not adopted by any newly logged-in user.

The root-owned policy selects the mode and permits a bounded disabled-subject list for
local revocation. `explicit_owners` remains compatible for existing deployments. A
private deployment does not need owner records. Effective tools remain the intersection
of actual token scopes and enabled ordinary memory capabilities; governance/destructive
tools remain closed. Login alone is not authorization for a destructive operation.

This uses existing Runtime project isolation and version/CAS machinery; no schema or
canonical-authority change is planned. Release requires two distinct subjects on the
same endpoint to retain separate State and Evidence, reject cross-user IDs/references/
continuations, remain isolated concurrently and after restart, and preserve legacy tests.
Any missing Runtime isolation must be repaired and directly tested before public rollout.

Public user access is enabled only after the scoped implementation is tested. The user
has already authorized this behavior; a per-user manual approval step is not required.
Real Auth login/refresh/revocation evidence remains separate from signed-fixture tests.
Schema remains 0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE.

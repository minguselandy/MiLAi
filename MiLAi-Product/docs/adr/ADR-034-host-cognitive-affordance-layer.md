# ADR-034: Host Cognitive Affordance Layer

> Status: `ACCEPTED FOR LOCAL CANDIDATE`  
> Date: 2026-09-04  
> Schema: `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`

## Context

Codex already performs semantic task decomposition, hypothesis management, sufficiency judgment
and residual-query formulation. Reimplementing those capabilities as hidden Runtime classifiers or
Reader state machines would duplicate the Host, add model dependencies and blur the boundary
between observations, governed truth and a model's fallible working interpretation.

Long-running coding work still needs a persistent, cross-session place for that interpretation.
It cannot be Evidence, Canonical State, Context, or Product-11's mechanical
`RetrievalContinuationState`.

## Decision

Add a fourth, explicitly non-authoritative object family:

```text
HostCognitiveState authority = HOST_WORKING
```

One stable `state_id` identifies a lineage. Every full replacement creates a unique
`state_version_id`, increments `version`, and points to the preceding version. Semantic versions and
their exact Evidence references are append-only; a small head row moves only after exact version
CAS. This resolves the draft plan's ambiguous use of `state_id` for both a stable handle and a
version identity.

The Runtime stores arbitrary JSON and validates only deterministic boundaries: JSON/size, tenant,
actor, project, scope identity, TTL, CAS, idempotency and reserved exact Evidence pointers. It does
not interpret goals, requirements, hypotheses, decisions, completeness or Evidence entailment.

## Scope and principal binding

The public MCP tool accepts only `SESSION | TASK | PROJECT`. It cannot accept a project or scope
reference. The 7337 service injects:

- the one project in `MILAI_AGENT_SCOPE_JSON`;
- a digest of the authenticated Codex principal and bound scope;
- `MILAI_CODEX_TASK_REF` / `MILAI_CODEX_SESSION_REF`, when configured;
- deterministic one-endpoint defaults otherwise.

PROJECT uses the bound project directly. SESSION Evidence pointers additionally require exact
`source_session_id`; TASK and PROJECT may aggregate Evidence across sessions but still require the
same readable project permission.

## Lifecycle and writes

Scope-owned TTLs are 24 hours (SESSION), 30 days (TASK), and 365 days (PROJECT). Expired content is
not returned. A later `expected_version=0` create retires an expired active head and starts a new
lineage. Manual archive/delete tools are deliberately not introduced in this minimal surface.

`milai_working_state_update` requires an `operation_id`. Same operation and payload replay the
original result; reuse with different semantics returns `OPERATION_CONFLICT`. Existing lineages
require exact `expected_version`; mismatch returns `STALE_WORKING_STATE` with the current version.

## Evidence references and revocation

The reserved keys `evidence_id` and `evidence_refs` carry exact UUID identities wherever they occur
inside payload JSON. At write time each reference must be currently readable, unreclaimed and in
scope. Its semantic relation is always `HOST_ASSERTED`, never verified grounding. Later revocation
does not rewrite history; `get` omits no still-valid working payload but returns an exact stale/
unreadable warning for the reference.

The warning-only disclosure decision above is superseded by
[ADR-041](ADR-041-working-state-disclosure-on-stale-references.md): currently unreadable declared
references withhold the entire opaque payload on GET and replay while retaining immutable history.

## Automatic audit

Working-state access and version appends emit automatic audit records by default. This is an
allowed observability side effect and is not a Host-state or Canonical-state mutation. Audit
metadata contains identity/digests and counts, never payload content. The audit role receives
metadata columns but cannot read `payload_json`.

## Invariants

- Outer authority is always `HOST_WORKING` and cannot be raised by payload content.
- No working-state operation calls or writes a canonical procedure/table.
- Recall never modifies working state; working-state tools never claim retrieval exhaustion.
- Host semantic assertions cannot become Claims without Evidence → Proposal → Review.
- Product-11 frontier/cursor/snapshot state is not stored in this object.
- Version history and Evidence-reference history are immutable.
- Scope, permission and revocation fail closed.

## Compatibility and rollback

This adds migration 0050, two internal REST routes, two Python-client methods and two tools to
`codex-full`. Other MCP profiles remain unchanged. Normal deployment rollback disables the two
tools and retains append-only Host working history. Because schema 0.1.x is experimental, an
explicit Alembic downgrade is supported but destructive: it drops Host working state and its
idempotency records while retaining operational audit events. A verified pre-0050 backup is
therefore required before a physical downgrade that may contain working state.

The empirical HC-4 usability claim remains separate: code and persistence do not by themselves
prove that Codex uses this affordance beneficially across real tasks.

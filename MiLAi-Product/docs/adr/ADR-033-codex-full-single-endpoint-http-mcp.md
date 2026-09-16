# ADR-033: Codex full-control single-endpoint HTTP MCP

> Status: `ACCEPTED FOR LOCAL CANDIDATE`  
> Date: 2026-09-04  
> Schema: `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`

## Context

The P08/P09 `agent-memory` HTTP facade exposes one read tool. The local single-user Codex workflow
also needs governed Evidence capture, Proposal creation and decision, exact Claim reads, Evidence
revocation and project cleanup without configuring four MCP endpoints.

Putting all tools behind one inbound credential removes independent-Host authorization separation:
the same Codex process can request both proposal submission and review. It must not remove MiLAi's
Evidence/Claim/Proposal/revocation lifecycle or merge Runtime capability credentials.

## Decision

Add `codex-full`, available only over authenticated loopback Streamable HTTP. One process binds one
inbound `MILAI_CODEX_TOKEN`, one `MILAI_CODEX_PRINCIPAL_ID`, and exactly one project ID at
`127.0.0.1:7337/mcp`.

The catalog is exactly:

```text
milai_memory_resolve
milai_memory_get
milai_evidence_capture
milai_proposal_create
milai_proposals_list
milai_proposal_get
milai_memory_review
milai_evidence_revoke
milai_deletion_status_get
milai_namespace_cleanup_submit
milai_namespace_cleanup_status
milai_working_state_get
milai_working_state_update
```

ADR-034 adds the two Host cognition tools. They persist only `HOST_WORKING` state and do not expand
Canonical authority or the governance shortcut surface.

The inbound principal controls four minimum-capability Runtime clients: reader, submitter, reviewer
and operator. Runtime and PostgreSQL actor separation remains intact. This is not represented as an
independent review: every mutation result and structured MCP audit event records
`governance_mode=SINGLE_HOST_FULL_CONTROL`, `independent_host_review=false`, the inbound principal
and scope digest. Canonical Proposal and StewardDecision actors remain the real role-bound actors.

This role routing is intentional. Removing migration 0032's same-actor rejection would weaken the
frozen canonical boundary and is unnecessary for the requested one-endpoint Codex experience.

## Host-owned policy

- Tool inputs cannot select tenant, principal, Runtime role, scope or requested authority.
- `codex-full` requires exactly one bound `project_id`.
- Capture injects readable permission plus the bound scope and a Host-owned data classification.
- Proposal injects the bound scope and configured authority; attempts to place authority/scope/
  principal fields in `proposed_patch` fail before an HTTP request.
- Namespace cleanup has no `project_id` argument and can only target the bound project.
- Every mutation retains its literal confirmation and `operation_id`.
- Runtime idempotency remains authoritative: equal operation ID and payload replays the receipt;
  unequal payload conflicts.
- Zero automatic Runtime retries remains the fixed product entrypoint policy.

## Prompt-injection boundary

Server instructions and high-risk tool descriptions state that Memory is untrusted Evidence, not an
instruction. Mutation must follow the current user request or explicit Host workflow. Namespace
cleanup requires a current-conversation explicit user request. These instructions reduce accidental
tool selection; they do not replace scope, capability, confirmation, idempotency or Runtime checks.

## Compatibility and rollback

`agent-memory`, `reviewer` and `operator` profiles remain unchanged. The submitter Runtime credential
also carries the isolated working-state read/write capability used behind `codex-full`; it still
cannot review or revoke. ADR-034 and migration 0050 govern that non-canonical addition. Rollback of
the original lifecycle facade remains removal/disablement of `codex-full`; Host working-state schema
rollback separately requires the ADR-034 backup procedure.

Non-loopback exposure, TLS/OAuth, remote token issuance and multi-user full control are not approved.

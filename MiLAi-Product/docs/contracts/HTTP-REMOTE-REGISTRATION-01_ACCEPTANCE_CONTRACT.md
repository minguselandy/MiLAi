# HTTP-REMOTE-REGISTRATION-01 Acceptance Contract

> Status: superseded by HTTP-STANDARD-MCP-01  
> Schema: `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`

## Client surface

The complete new-user client artifact is exactly one generic object:

```json
{
  "mcpServers": {
    "milai": {
      "type": "remote",
      "url": "http://36.140.33.19:7968/mcp",
      "headers": {
        "Authorization": "Bearer <server-issued-per-user-token>",
        "x-agent-id": "<pre-bound-agent-id>"
      }
    }
  }
}
```

No local MiLAi package, process, environment variable or MiLAi approval is required. Client-owned
third-party-service confirmation is outside MiLAi and may not be bypassed.

## Required gates

```text
server-issued Token unique per user                         PASS
clear Token absent from registry and audit                  PASS
exact Token + x-agent-id first connection activates         PASS
second connection is idempotently ACTIVE                    PASS
missing/mismatched x-agent-id for a registered Token         401
unknown/revoked Token                                        401
one identity cannot reuse another identity's MCP session     FAIL_CLOSED
tool execution receives authenticated dynamic principal      PASS
Working State binding differs across Host principals         PASS
issue/register/revoke audit written automatically             PASS
registry/lock/audit owner-only                               PASS
existing static principal compatibility                      PASS
tool catalog remains exactly 13                              PASS
Memory/Canonical/Runtime schema changed                       0
```

## Authority limits

- `x-agent-id` is not authority and cannot authenticate without its unique Bearer Token.
- The model cannot provide principal, tenant, project, scope, role or authority as a tool argument.
- Registration does not mutate Evidence, Claim, OpenIssue, Working State or retrieval state.
- All registered principals on one endpoint share its fixed tenant/project. This contract does not
  claim user data isolation.
- Registration is server-issued onboarding, not an unauthenticated public signup endpoint.

## Operational contract

Credential states are `PENDING → ACTIVE → REVOKED`. Rotation explicitly revokes the prior live
credential before issuing a new pending one. Revoking an MCP credential blocks future MCP access
but does not delete Memory.

The registry is an MCP edge-authentication file protected by process filesystem controls. It stores
only random Token digests. The adjacent append-only JSONL audit contains event/principal/status
metadata and no credential material.

Plain HTTP remains an acknowledged deployment risk. Passing this contract does not claim secure
operation over an untrusted network without HTTPS/VPN/network restriction.

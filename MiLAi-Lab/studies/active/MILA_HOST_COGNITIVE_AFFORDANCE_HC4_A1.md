# HC-4 A1 guided cognitive-affordance adoption

Date frozen: `2026-09-04T18:01:27+08:00`  
Execution window: `2026-09-04T18:14:00+08:00` to `2026-09-04T19:32:24+08:00`  
Terminal: `HC4_A1_GUIDED_ADOPTION_NEGATIVE`

## Claim and treatment

HC4-A0 had already shown 0/8 natural Working State use under passive affordance text. A1 tested
whether bounded, non-mandatory task-semantic guidance was sufficient to activate Codex's own
Working State policy. It did not test whether persistence works; HC-0 through HC-3 had already
proved the substrate.

Only these model-visible strings changed from A0:

- the `codex-full` server instruction explains that persistent non-canonical TASK State may help
  resume long-running work and preserve material goals, decisions, failures, blockers and next
  actions;
- the existing GET/UPDATE descriptions explain the same natural use cases;
- the instruction says not to update every turn or use the feature for trivial tasks, and leaves
  the choice to Codex.

Runtime, PostgreSQL, migration 0050, State schema, tool names/count/schemas, scope, RLS, CAS, TTL,
audit, Canonical, retrieval and automatic Host orchestration remained unchanged. The in-memory MCP
process presented the same 13-tool catalog to all samples.

## Genuine third chain

Four new `codex exec --ephemeral` processes continued the independently authorized public-IP
HTTPS/OAuth deployment-readiness work. They shared only the server-owned TASK ref
`hc4-a1-public-ip-https-oauth`; no process resumed a Codex conversation or received the prior
transcript. Prompts did not mention HC-4, State, tool names, fields or invocation timing.

| Run | Real outcome | Events | Commands complete / failed | File changes | Working State GET / UPDATE |
| --- | --- | ---: | ---: | ---: | ---: |
| A1-G1 | Read-only edge/NAT/OAuth blocker audit | 104 | 38 / 5 | 0 | 0 / 0 |
| A1-G2 | HTTPS fail-closed validation, readiness CLI and docs; 101 MCP tests | 104 | 25 / 10 | 9 | 0 / 0 |
| A1-G3 | Independent OAuth protocol/security correction; 105 MCP tests | 242 | 96 / 7 | 8 | 0 / 0 |
| A1-G4 | Clean paired-wheel install and deployment-owner handoff | 107 | 37 / 6 | 3 | 0 / 0 |
| **Total** | **4 sessions / 1 chain** | **557** | **196 / 28** | **20** | **0 / 0** |

Host usage totaled 33,857,435 input, 32,958,336 cached input, 149,225 output and 77,894 reasoning
tokens. These are descriptive trace totals, not an effect metric.

## Result and cross-check

```text
EligibleTaskWorkingStateUseRate       0 / 4 = 0.0
successful natural updates            0
ACTIVE TASK State                     0
ResumeStateReadRate                   NOT_DEFINED
MaterialStateUpdateRate               NOT_DEFINED
HC4-C2 usefulness                     NOT_EVALUABLE
```

All JSONL streams contain zero MCP tool-call events. The MCP journal independently shows the four
initialize/list/stream/close lifecycles. PostgreSQL reports zero chain-specific State heads,
versions and Evidence refs, zero update idempotency records in the execution window and no access
event for the chain scope-ref digest.

All seven architecture counters remained zero, with the narrow interpretation imposed by zero
State use: no Working-State-to-Canonical mutation, authority escalation, cross-tenant/principal/
project leak, revoked-reference acceptance or recall-side State mutation was observed.

Under the preregistered rule, four valid A1 sessions with zero calls stop prompt escalation and park
the generic self-maintained feature as manual/explicit. An automatic session-start prefetch or
session-end update policy would be a separate Host-managed experiment and cannot inherit a
`Codex self-maintained cognition` claim.

## Engineering outcomes kept separate

The tasks were materially real: they added a fail-closed HTTPS readiness gate and found/fixed
OAuth revocation, RFC 8707 resource, metadata, normalization, readiness, packaging and service
isolation defects. Those are Product engineering outcomes, not evidence of cognitive-state
adoption. Public OAuth remains blocked by trusted HTTPS gateway/DNS/certificate ownership.

The complete Product-side record is
[`MILA_HOST_COGNITIVE_AFFORDANCE_HC4_A1_EXECUTION_AUDIT_20260904_193542.md`](../../../MiLAi-Product/docs/goals/MILA_HOST_COGNITIVE_AFFORDANCE_HC4_A1_EXECUTION_AUDIT_20260904_193542.md).

## Raw identities

Raw output remains ignored under `artifacts/hc4-host-cognitive-a1/`:

| Run | JSONL SHA-256 |
| --- | --- |
| A1-G1 | `cfe093d05d20d979d94b57accd2c48023799f66fe2fa20340411b4f7ae1fad9d` |
| A1-G2 | `a6b6ef3986f332c9e8dd2867536378f6225cf718c0e3db24b139b9a96324b8bf` |
| A1-G3 | `0966cf3151b19e5d9ee0a2b411424e51ba35f70bde21d6af439fd12d4354506b` |
| A1-G4 | `97066cda99913dda0740bc33dcbc063170011afecccad82400caef243d5f214c` |

The chain TASK-ref override was removed after execution; the public service returned to
`MILAI_CODEX_TASK_REF=milai-product` and passed readiness.
